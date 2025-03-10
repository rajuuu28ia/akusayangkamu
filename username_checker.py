import aiohttp
import asyncio
import logging
import re
import json
import os
import time
import math
import random
from lxml import html
from typing import Optional, Dict, Set, Union
from config import RESERVED_WORDS
from telethon import TelegramClient, functions, errors
from telethon.sessions import StringSession
from datetime import datetime, timedelta

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

        # Caching for checked usernames
        self._username_cache: Dict[str, tuple] = {}  # (result, timestamp)
        self._cache_ttl = 3600  # 1 hour cache

        logger.info("✅ TelegramUsernameChecker initialized successfully")

    async def verify_with_dummy_account(self, client: TelegramClient, username: str, akun_ke: int) -> bool:
        """
        Verifikasi username dengan hanya membaca status tanpa mencoba set username
        dengan sistem delay dan rotasi untuk menghindari rate limit
        """
        try:
            # Tambah delay awal yang lebih adaptif untuk menghindari rate limit
            delay = random.uniform(3, 5)  # Delay yang lebih tinggi dan bervariasi
            logger.debug(f"Menerapkan delay {delay:.2f}s sebelum verifikasi akun #{akun_ke}")
            await asyncio.sleep(delay)

            # Method 1: Check username availability
            try:
                result = await client(functions.account.CheckUsernameRequest(username=username))
                if not result:
                    logger.warning(f"❌ Akun #{akun_ke}: @{username} not available (check method)")
                    return False
                logger.info(f"✅ Akun #{akun_ke}: @{username} available (check method)")

            except errors.UsernameInvalidError:
                logger.warning(f"❌ Akun #{akun_ke}: @{username} format tidak valid") 
                return False
            except errors.FloodWaitError as e:
                logger.error(f"⚠️ Akun #{akun_ke} terkena rate limit: harus menunggu {e.seconds} detik")
                # Simpan waktu tunggu untuk masing-masing akun
                setattr(self, f'_rate_limit_until_{akun_ke}', datetime.now() + timedelta(seconds=e.seconds))
                return None
            except Exception as e:
                logger.error(f"Method 1 error on account #{akun_ke}: {e}")
                return None

            # Method 2: Resolve username
            try:
                resolve_result = await client(functions.contacts.ResolveUsernameRequest(username=username))
                if resolve_result.users or resolve_result.chats:
                    logger.warning(f"❌ Akun #{akun_ke}: @{username} sudah digunakan (resolve method)")
                    return False
                logger.info(f"✅ Akun #{akun_ke}: @{username} tidak ditemukan (resolve method)")

            except errors.UsernameNotOccupiedError:
                # Username tidak ada = bagus
                logger.info(f"✅ Akun #{akun_ke}: @{username} not occupied (resolve method)")
            except errors.FloodWaitError as e:
                logger.error(f"⚠️ Akun #{akun_ke} terkena rate limit: harus menunggu {e.seconds} detik")
                setattr(self, f'_rate_limit_until_{akun_ke}', datetime.now() + timedelta(seconds=e.seconds))
                return None
            except Exception as e:
                logger.error(f"Method 2 error on account #{akun_ke}: {e}")
                return False

            # Method 3: Get entity check
            try:
                entity = await client.get_entity(username)
                if entity:
                    logger.warning(f"❌ Akun #{akun_ke}: @{username} sudah ada entitynya")
                    return False
            except errors.UsernameNotOccupiedError:
                # Username tidak ada = bagus
                logger.info(f"✅ Akun #{akun_ke}: @{username} tidak ada entity")
            except Exception as e:
                logger.error(f"Method 3 error on account #{akun_ke}: {e}")
                # Tidak return False di sini karena error bisa berarti username tidak ada

            # Jika sampai di sini berarti semua check passed
            logger.info(f"✅ Akun #{akun_ke}: @{username} PASSED all verification methods")
            return True

        except Exception as e:
            logger.error(f"Error saat verifikasi dengan akun #{akun_ke}: {e}")
            return None

    async def check_username_with_telethon(self, username: str) -> Optional[bool]:
        """
        Gunakan Telethon API untuk memeriksa ketersediaan username
        tanpa menggunakan session string (anonymous mode only)
        """
        logger.debug(f"Starting anonymous Telethon check for username: {username}")

        try:
            # Get credentials from environment
            api_id = int(os.environ.get("TELEGRAM_API_ID", "26383001"))
            api_hash = os.environ.get("TELEGRAM_API_HASH", "eadffb03a33d6a2751ad9e69cbd95f2d")

            logger.debug("Credentials loaded, using anonymous check only")
            
            # Tambah delay untuk anonymous check
            adaptive_delay = random.uniform(2, 5)  # Delay yang sesuai untuk anonymous check
            logger.info(f"Menunggu {adaptive_delay:.2f}s sebelum anonymous check untuk menghindari rate limit global")
            await asyncio.sleep(adaptive_delay)
            
            # Menggunakan anonymous check
            logger.info("Menggunakan anonymous check tanpa session string")

            client = TelegramClient(StringSession(), api_id, api_hash)

            try:
                await client.connect()
                result = await client(functions.account.CheckUsernameRequest(username=username))
                status = "TERSEDIA ✅" if result else "TIDAK TERSEDIA ❌"
                logger.info(f"Anonymous check: @{username} {status}")
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

    async def check_fragment_api(self, username: str, retries=3) -> Optional[bool]:
        """Check username availability with enhanced banned verification"""

        # Second validation layer - pola terlarang tambahan (Removed strict banned patterns)
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
            logger.info(f'@{username} contains suspicious pattern')
            return None

        for attempt in range(retries):
            try:
                async with self.rate_semaphore: #Added rate limiting here
                    await asyncio.sleep(random.uniform(1, 3)) #Added random delay
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


                            # Check if username is for sale
                            if price.isdigit():
                                logger.info(f'@{username} is for sale: {price}💎')
                                return None

                            # Final availability check
                            if status == 'Unavailable':
                                # Verify with t.me
                                try:
                                    await asyncio.sleep(random.uniform(1, 2)) #Added random delay
                                    async with self.session.get(f'https://t.me/{username}') as resp:
                                        if resp.status in [403, 404, 410]:
                                            logger.info(f'@{username} not accessible on t.me')
                                            return None

                                        content = await resp.text()
                                        if "If you have Telegram, you can contact" not in content:

                                            # Final verification yang lebih terfokus - hanya periksa hal paling penting
                                            unavailable_indicators = [
                                                "This username is used by a channel",
                                                "This username is used by a group"
                                            ]

                                            if any(indicator in content for indicator in unavailable_indicators):
                                                logger.info(f'@{username} appears to be used by a channel or group')
                                                return None


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