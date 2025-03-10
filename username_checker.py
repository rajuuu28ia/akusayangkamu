import aiohttp
import asyncio
import logging
import re
import json
import os
import time
import math
from lxml import html
from typing import Optional, Dict, Set, Union
from config import RESERVED_WORDS
from telethon import TelegramClient, functions, errors
from telethon.sessions import StringSession

# Set up detailed logging for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Add file handler for username checker specific logs
file_handler = logging.FileHandler('username_checker.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'))
logger.addHandler(file_handler)

# Constants
PREMIUM_USER = 'This account is already subscribed to Telegram Premium.'
CHANNEL = 'Please enter a username assigned to a user.'
NOT_FOUND = 'No Telegram users found.'

class TelegramUsernameChecker:
    def __init__(self):
        """Initialize checker with improved caching and strict verification"""
        self.session = aiohttp.ClientSession()
        self.rate_semaphore = asyncio.Semaphore(5)
        self.base_delay = 1

        # Caching for banned and checked usernames
        self._username_cache: Dict[str, tuple] = {}  # (result, timestamp)
        self._banned_cache: Set[str] = set()
        self._cache_ttl = 3600  # 1 hour cache

        logger.info("✅ TelegramUsernameChecker initialized successfully")

    def _levenshtein_distance(self, s1, s2):
        """Calculate the edit distance between two strings"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def _calculate_entropy(self, text):
        """Calculate Shannon entropy for a string (low values are suspicious)"""
        if not text:
            return 0

        entropy = 0
        text_len = len(text)
        char_counts = {}

        # Count characters
        for char in text:
            if char in char_counts:
                char_counts[char] += 1
            else:
                char_counts[char] = 1

        # Calculate entropy
        for count in char_counts.values():
            prob = count / text_len
            entropy -= prob * math.log2(prob)

        return entropy

    async def is_banned(self, username: str) -> bool:
        """
        ULTIMATE paranoid multi-layer verification system for banned usernames
        with extreme pattern matching and caching - Prefers false positives over false negatives
        """
        username_lower = username.lower()

        # Check cache first
        if username in self._banned_cache:
            logger.info(f"@{username} found in banned cache")
            return True

        # --- LEVEL 1: BASIC CHECKS ---

        # Pre-check validasi ultra ketat
        strict_banned_patterns = [
            r'^[0-9].*',  # Tidak boleh diawali angka
            r'.*[_]{2,}.*',  # Tidak boleh ada underscore berurutan
            r'.*\d{4,}.*',  # Tidak boleh ada 4+ angka berurutan
            r'^(admin|support|help|info|bot|official|staff|mod)\d*$',  # Kata-kata terlarang dengan angka opsional
            r'^[a-zA-Z0-9]{1,2}[0-9]+$',  # 1-2 huruf diikuti hanya angka
            r'.*(_bot|bot_|_admin|admin_|_staff|staff_|_mod|mod_).*',  # Kata terlarang dengan underscore
            r'.*[0-9]{5,}.*',  # Tidak boleh ada 5+ angka berurutan di manapun
            r'^(telegram|tg|gram).*',  # Tidak boleh diawali dengan telegram-related
            r'.*(support|admin|mod|staff|official).*',  # Kata sensitif di manapun
        ]

        logger.info(f"🔍 Checking strict banned patterns for @{username}")
        for pattern in strict_banned_patterns:
            if re.match(pattern, username_lower):
                logger.warning(f"❌ @{username} ditolak oleh pola ultra ketat: {pattern}")
                self._banned_cache.add(username)
                return True

        # Immediately ban very short usernames (likely premium or reserved)
        if len(username) <= 5:
            logger.warning(f"❌ @{username} terlalu pendek (<=5 chars) - kemungkinan premium/reserved")
            self._banned_cache.add(username)
            return True

        # Check against RESERVED_WORDS list from config.py with exact match
        if username_lower in RESERVED_WORDS:
            logger.warning(f"❌ @{username} ada dalam RESERVED_WORDS list")
            self._banned_cache.add(username)
            return True

        # Check if username contains any reserved word as a substring
        for reserved in RESERVED_WORDS:
            if reserved in username_lower or username_lower in reserved:
                logger.warning(f"❌ @{username} mengandung kata reserved: {reserved}")
                self._banned_cache.add(username)
                return True

        try:
            async with self.session.get(f'https://t.me/{username}', allow_redirects=False) as response:
                # Quick check based on status codes
                if response.status in [403, 404, 410]:
                    self._banned_cache.add(username)
                    logger.warning(f"❌ @{username} banned (status code: {response.status})")
                    return True

                # Get text content for detailed analysis
                content = await response.text()
                content_lower = content.lower()

                # Check content against banned patterns
                banned_indicators = [
                    "this account has been banned",
                    "this username has been banned",
                    "username is not available for use",
                    "username cannot be used due to security reasons",
                    "username has been restricted",
                    "this account is no longer available",
                    "account deleted",
                    "account restricted"
                ]

                if any(indicator in content_lower for indicator in banned_indicators):
                    self._banned_cache.add(username)
                    logger.warning(f"❌ @{username} banned (found banned indicator in content)")
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking banned status for {username}: {e}")
            return True  # Assume banned on error to be safe

        return False

    async def check_fragment_api(self, username: str, retries=3) -> Optional[bool]:
        """Check username availability with enhanced banned verification"""
        # First check if username is banned - HARUS CEK INI DULU
        if await self.is_banned(username):
            logger.warning(f'❌ @{username} is banned or restricted')
            return None

        # Second validation layer - pola terlarang tambahan
        strict_banned_patterns = [
            r'^[0-9].*',  # Tidak boleh diawali angka
            r'.*[_]{2,}.*',  # Tidak boleh ada underscore berurutan
            r'.*\d{4,}.*',  # Tidak boleh ada 4+ angka berurutan
            r'^(admin|support|help|info|bot|official|staff|mod)\d*$',  # Kata-kata terlarang dengan angka opsional
            r'^[a-zA-Z0-9]{1,2}[0-9]+$',  # 1-2 huruf diikuti hanya angka
            r'.*(_bot|bot_|_admin|admin_|_staff|staff_|_mod|mod_).*',  # Kata terlarang dengan underscore
            r'.*[0-9]{5,}.*',  # Tidak boleh ada 5+ angka berurutan di manapun
            r'^(telegram|tg|gram).*',  # Tidak boleh diawali dengan telegram-related
            r'.*(support|admin|mod|staff|official).*',  # Kata sensitif di manapun
        ]

        logger.info(f"🔍 Validasi tambahan untuk @{username}")
        for pattern in strict_banned_patterns:
            if re.match(pattern, username.lower()):
                logger.warning(f"❌ @{username} ditolak oleh pola tambahan: {pattern}")
                return None

        # Lanjutkan dengan pengecekan Telethon jika lolos semua validasi
        telethon_result = await self.check_username_with_telethon(username)
        if telethon_result is not None:
            return telethon_result

        # Jika Telethon gagal, gunakan Fragment API sebagai fallback
        logger.info(f"Mencoba Fragment API untuk @{username}")
        return await self._check_fragment_api_internal(username, retries)

    async def _check_fragment_api_internal(self, username: str, retries=3) -> Optional[bool]:
        """Internal method for Fragment API checks"""
        # List of suspicious patterns - HANYA YANG SANGAT KRITIS
        suspicious_patterns = [
            # Official-sounding names (hanya yang sangat sensitif)
            r'^.*admin.*$', r'^.*support.*$', r'^.*telegram.*$', r'^.*official.*$',

            # Brand names (hanya yang paling umum diproteksi)
            r'^.*apple.*$', r'^.*google.*$', r'^.*meta.*$', r'^.*facebook.*$',

            # Explicit content
            r'^.*porn.*$', r'^.*xxx.*$', r'^.*sex.*$',

            # Hanya untuk akun scam yang sangat jelas
            r'^.*spam.*$', r'^.*scam.*$', r'^.*fake.*$'
        ]

        if any(re.search(pattern, username.lower()) for pattern in suspicious_patterns):
            self._banned_cache.add(username)
            logger.info(f'@{username} contains suspicious pattern')
            return None

        for attempt in range(retries):
            try:
                async with self.session.get('https://fragment.com') as response:
                    if response.status != 200:
                        logger.warning(f'Fragment API returned status {response.status}, retrying...')
                        await asyncio.sleep(self.base_delay * (attempt + 1))
                        continue

                    text = await response.text()
                    tree = html.fromstring(text)
                    scripts = tree.xpath('//script/text()')
                    pattern = re.compile(r'ajInit\((\{.*?})\);', re.DOTALL)

                    api_url = None
                    for script in scripts:
                        match = pattern.search(script)
                        if match:
                            try:
                                data = json.loads(match.group(1))
                                api_url = f'https://fragment.com{data.get("apiUrl")}'
                                break
                            except json.JSONDecodeError:
                                continue

                    if not api_url:
                        logger.error(f'@{username} API URL not found, retrying...')
                        await asyncio.sleep(self.base_delay * (attempt + 1))
                        continue

                    # Check Fragment API
                    search_auctions = {'type': 'usernames', 'query': username, 'method': 'searchAuctions'}
                    async with self.session.post(api_url, data=search_auctions) as response:
                        if response.status == 429:  # Rate limit
                            await asyncio.sleep(self.base_delay * (attempt + 1))
                            continue

                        response_data = await response.json()
                        if not isinstance(response_data, dict) or not response_data.get('html'):
                            logger.warning(f'Invalid response data for @{username}, retrying...')
                            continue

                        tree = html.fromstring(response_data.get('html'))
                        username_data = tree.xpath('//div[contains(@class, "tm-value")]')[:3]

                        if len(username_data) < 3:
                            logger.warning(f'Incomplete data for @{username}')
                            return None

                        username_tag = username_data[0].text_content()
                        status = username_data[2].text_content()
                        price = username_data[1].text_content()

                        if username_tag[1:] != username:
                            logger.warning(f'Username mismatch: {username_tag[1:]} != {username}')
                            return None

                        # Additional check for banned status
                        if await self.is_banned(username):
                            logger.info(f'@{username} became banned during check.')
                            return None

                        # Check if username is for sale
                        if price.isdigit():
                            logger.info(f'@{username} is for sale: {price}💎')
                            return None

                        # Final availability check
                        if status == 'Unavailable':
                            # Verify with t.me
                            try:
                                async with self.session.get(f'https://t.me/{username}') as resp:
                                    if resp.status in [403, 404, 410]:
                                        logger.info(f'@{username} not accessible on t.me')
                                        return None

                                    content = await resp.text()
                                    if "If you have Telegram, you can contact" not in content:
                                        # ULTIMATE CHECK - quadruple verification
                                        # First, check standard banned status
                                        if await self.is_banned(username):
                                            logger.info(f'@{username} is banned (final t.me check)')
                                            return None

                                        # Second, ultra-strict check with direct API validation
                                        try:
                                            # HAPUS SEMUA SPECIAL PATTERN TEST - terlalu ketat

                                            # Special HTTP headers check - dengan kriteria sangat minim
                                            custom_headers = {
                                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                                            }

                                            async with self.session.get(f'https://t.me/{username}', headers=custom_headers) as special_check:
                                                special_content = await special_check.text()
                                                # Hanya periksa kata-kata kunci banned yang SANGAT SPESIFIK
                                                if "this account has been banned" in special_content.lower() or \
                                                   "this username has been banned" in special_content.lower():
                                                    logger.info(f'@{username} found to be explicitly banned in special content check')
                                                    self._banned_cache.add(username)
                                                    return None
                                        except Exception as e:
                                            logger.error(f"Error in ultra-strict check for @{username}: {str(e)}")
                                            # If there's any error in this critical check, assume it's banned
                                            return None


                                        # Hapus semua banned indicators yang terlalu umum
                                        # Hapus semua checkings ban yang tidak eksplisit
                                        # Sekarang kita akan menghentikan pemeriksaan indikator ban di sini

                                        # Hanya cek indikator yang sangat spesifik dan pasti
                                        unavailable_indicators = [
                                            "This username is used by a channel",
                                            "This username is used by a group"
                                        ]

                                        if any(indicator in content for indicator in unavailable_indicators):
                                            logger.info(f'@{username} appears to be used by a channel or group')
                                            return None


                                        # Hapus HEAD request check - menyebabkan terlalu banyak false positive

                                        # Ultimate PARANOIA checks - the most extreme filtering possible

                                        # Final verification yang lebih terfokus - hanya periksa hal paling penting

                                        # HAPUS PEMERIKSAAN FRAGMENT API YANG MENYEBABKAN FALSE POSITIVES
                                        # Fragment API terlalu sering mengembalikan halaman yang berisi teks umum yang
                                        # menyebabkan false positive

                                        # Kita akan mengandalkan pemeriksaan dari API Fragment yang dilakukan sebelumnya
                                        # yang lebih akurat (dalam if price.isdigit() check)

                                        # Hapus verifikasi tambahan ini
                                        # Setiap pemeriksaan tambahan meningkatkan false positive
                                        # Jika sampai di sini, assume username tersedia

                                        # PASS - Username telah lulus semua verifikasi wajib
                                        logger.info(f'✅ @{username} is Verified Available ✅')
                                        return True
                                    else:
                                        logger.info(f'@{username} is taken (t.me check)')
                                        return None
                            except Exception as e:
                                logger.error(f"Error checking t.me for @{username}: {e}")
                                return None

                        return None

            except asyncio.TimeoutError:
                logger.error(f"Timeout checking @{username}")
                await asyncio.sleep(self.base_delay * (attempt + 1))
            except Exception as e:
                logger.error(f"Error checking @{username}: {e}")
                await asyncio.sleep(self.base_delay * (attempt + 1))

        return None  # Return None after all retries failed

    async def get_telegram_web_user(self, username: str) -> bool:
        """Check username via Telegram web"""
        try:
            async with self.session.get(f'https://t.me/{username}') as response:
                if response.status in [403, 404]:
                    return False

                text = await response.text()
                return f"You can contact @{username} right away." in text
        except Exception as e:
            logger.error(f"Error checking web user {username}: {e}")
            return False

    async def check_username_with_telethon(self, username: str) -> Optional[bool]:
        """
        Gunakan Telethon API untuk memeriksa ketersediaan username
        dengan validasi ekstra ketat untuk banned username
        """
        logger.debug(f"Starting Telethon check for username: {username}")

        # Pre-check validasi ekstra
        if len(username) <= 3:  # Username terlalu pendek pasti tidak valid
            logger.warning(f"❌ @{username} ditolak: terlalu pendek (<=3 karakter)")
            return False

        # Tambahan pola terlarang yang lebih ketat
        strict_banned_patterns = [
            r'^[0-9].*',  # Tidak boleh diawali angka
            r'.*[_]{2,}.*',  # Tidak boleh ada underscore berurutan
            r'.*\d{4,}.*',  # Tidak boleh ada 4+ angka berurutan
            r'^(admin|support|help|info|bot|official|staff|mod)\d*$',  # Kata-kata terlarang dengan angka opsional
            r'^[a-zA-Z0-9]{1,2}[0-9]+$',  # 1-2 huruf diikuti hanya angka
            r'.*(_bot|bot_|_admin|admin_|_staff|staff_|_mod|mod_).*',  # Kata terlarang dengan underscore
            r'.*[0-9]{5,}.*',  # Tidak boleh ada 5+ angka berurutan di manapun
            r'^(telegram|tg|gram).*',  # Tidak boleh diawali dengan telegram-related
            r'.*(support|admin|mod|staff|official).*',  # Kata sensitif di manapun
        ]

        logger.info(f"🔍 Memeriksa pola terlarang untuk @{username}")
        for pattern in strict_banned_patterns:
            if re.match(pattern, username.lower()):
                logger.warning(f"❌ @{username} ditolak: match pola terlarang '{pattern}'")
                return False

        logger.info(f"✅ @{username} lolos pemeriksaan pola terlarang")

        try:
            # Get credentials from environment
            api_id = int(os.environ.get("TELEGRAM_API_ID", "26383001"))
            api_hash = os.environ.get("TELEGRAM_API_HASH", "eadffb03a33d6a2751ad9e69cbd95f2d")

            logger.debug("Credentials loaded, checking for session strings")

            # Initialize session strings list
            session_strings = []

            # Check main session string
            main_session = os.environ.get("TELEGRAM_SESSION_STRING")
            if main_session:
                if len(main_session) > 50:  # Basic validation
                    session_strings.append(main_session)
                    logger.info("✅ Main session string loaded successfully")
                else:
                    logger.warning("⚠️ Main session string found but invalid length")

            # Check second session string
            second_session = os.environ.get("TELEGRAM_SESSION_STRING_2")
            if second_session:
                if len(second_session) > 50:
                    if second_session not in session_strings:
                        session_strings.append(second_session)
                        logger.info("✅ Second session string loaded successfully")
                else:
                    logger.warning("⚠️ Second session string found but invalid length")

            logger.info(f"Total valid session strings found: {len(session_strings)}")

            # Verifikasi dengan multiple dummy accounts
            is_available = False  # Default false sampai terbukti available
            verification_count = 0  # Hitung berapa akun yang berhasil verifikasi

            # Try using available session strings
            if session_strings:
                for i, current_session in enumerate(session_strings):
                    akun_ke = i + 1
                    logger.debug(f"Attempting to use dummy account #{akun_ke}")

                    client = TelegramClient(
                        StringSession(current_session),
                        api_id,
                        api_hash,
                        device_model=f"Dummy Checker #{akun_ke}",
                        system_version="1.0",
                        app_version="1.0",
                        lang_code="en",
                        system_lang_code="en"
                    )

                    try:
                        logger.debug(f"Connecting dummy account #{akun_ke}")
                        await client.connect()

                        if not await client.is_user_authorized():
                            logger.warning(f"Session #{akun_ke} not authorized, skipping")
                            await client.disconnect()
                            continue

                        logger.info(f"✅ Successfully using dummy account #{akun_ke}")

                        # Multi-method verification
                        methods_passed = 0
                        total_methods = 3

                        # Method 1: Check username availability
                        try:
                            result = await client(functions.account.CheckUsernameRequest(username=username))
                            if result:
                                methods_passed += 1
                                logger.info(f"Method 1 (Check) - Akun #{akun_ke}: @{username} PASSED ✅")
                            else:
                                logger.warning(f"Method 1 (Check) - Akun #{akun_ke}: @{username} FAILED ❌")
                        except errors.UsernameInvalidError:
                            logger.warning(f"Method 1 (Check) - Akun #{akun_ke}: @{username} invalid format")
                        except errors.UsernameNotModifiedError:
                            logger.warning(f"Method 1 (Check) - Akun #{akun_ke}: @{username} not modified")
                        except Exception as e:
                            logger.error(f"Method 1 error on account #{akun_ke}: {e}")

                        # Method 2: Resolve username (lebih ketat)
                        try:
                            resolve_result = await client(functions.contacts.ResolveUsernameRequest(username=username))
                            if not resolve_result:  # Tidak ada user = bagus
                                methods_passed += 1
                                logger.info(f"Method 2 (Resolve) - Akun #{akun_ke}: @{username} PASSED ✅")
                            else:
                                logger.warning(f"Method 2 (Resolve) - Akun #{akun_ke}: @{username} FAILED ❌")
                        except errors.UsernameNotOccupiedError:
                            methods_passed += 1  # Error ini sebenarnya bagus
                            logger.info(f"Method 2 (Resolve) - Akun #{akun_ke}: @{username} PASSED ✅")
                        except errors.UsernameInvalidError:
                            logger.warning(f"Method 2 (Resolve) - Akun #{akun_ke}: @{username} invalid format")
                        except Exception as e:
                            logger.error(f"Method 2 error on account #{akun_ke}: {e}")

                        # Method 3: Get user by username
                        try:
                            user = await client.get_entity(username)
                            if user:
                                logger.warning(f"Method 3 (Get) - Akun #{akun_ke}: @{username} FAILED ❌")
                            else:
                                methods_passed += 1
                                logger.info(f"Method 3 (Get) - Akun #{akun_ke}: @{username} PASSED ✅")
                        except errors.UsernameNotOccupiedError:
                            methods_passed += 1  # Username tidak ada = bagus
                            logger.info(f"Method 3 (Get) - Akun #{akun_ke}: @{username} PASSED ✅")
                        except errors.UsernameInvalidError:
                            logger.warning(f"Method 3 (Get) - Akun #{akun_ke}: @{username} invalid format")
                        except Exception as e:
                            logger.error(f"Method 3 error on account #{akun_ke}: {e}")

                        # Username dianggap tersedia jika lolos minimal 2 dari 3 metode
                        if methods_passed >= 2:
                            verification_count += 1
                            logger.info(f"Akun #{akun_ke} verifikasi BERHASIL ({methods_passed}/{total_methods} metode)")
                        else:
                            logger.warning(f"Akun #{akun_ke} verifikasi GAGAL (hanya {methods_passed}/{total_methods} metode)")

                        await client.disconnect()

                    except errors.FloodWaitError as e:
                        logger.warning(f"Rate limit on account #{akun_ke}: {e.seconds}s wait")
                        if client.is_connected():
                            await client.disconnect()
                        continue
                    except Exception as e:
                        logger.error(f"Error with account #{akun_ke}: {e}")
                        if client.is_connected():
                            await client.disconnect()
                        continue

                # Username dianggap tersedia jika MINIMAL 2 akun memverifikasi
                is_available = verification_count >= 2
                if is_available:
                    logger.info(f"✅ @{username} TERSEDIA (verified by {verification_count} accounts)")
                else:
                    logger.warning(f"❌ @{username} TIDAK TERSEDIA (only verified by {verification_count} accounts)")

                return is_available

            # Fallback to anonymous check jika tidak ada akun yang berhasil
            logger.warning("Semua akun dummy gagal, mencoba anonymous check")
            client = TelegramClient(StringSession(), api_id, api_hash)

            try:
                await client.connect()
                result = await client(functions.account.CheckUsernameRequest(username=username))
                status = "TERSEDIA ✅" if result else "TIDAK TERSEDIA ❌"
                logger.info(f"Anonymous check: @{username} {status}")

                # Tambahan verifikasi untuk anonymous check
                if result:
                    try:
                        entity = await client.get_entity(username)
                        if entity:
                            logger.warning(f"Anonymous check: @{username} ternyata sudah ada user")
                            result = False
                    except errors.UsernameNotOccupiedError:
                        logger.info(f"Anonymous check: @{username} konfirmasi tidak ada user")
                    except:
                        # Error lain berarti ada masalah - anggap tidak tersedia
                        logger.warning(f"Anonymous check: @{username} error saat verifikasi tambahan")
                        result = False

                await client.disconnect()
                return result

            except Exception as e:
                logger.error(f"Anonymous check failed: {e}")
                if client.is_connected():
                    await client.disconnect()
                return None

        except Exception as e:
            logger.error(f"Unexpected error in check_username_with_telethon: {e}")
            return None

    async def close(self):
        """Cleanup resources"""
        if not self.session.closed:
            await self.session.close()

async def main():
    checker = TelegramUsernameChecker()
    username = "testusername"
    is_available = await checker.check_fragment_api(username)

    if is_available:
        logger.info(f"✅ Username @{username} is available!")
    else:
        logger.info(f"❌ Username @{username} is not available or banned.")

    await checker.close()

if __name__ == "__main__":
    asyncio.run(main())