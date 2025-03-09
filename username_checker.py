import aiohttp
import asyncio
import logging
import re
import json
import os
import time
import math
from lxml import html
from typing import Optional, Dict, Set
from config import RESERVED_WORDS

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        
        # Immediately ban very short usernames (likely premium or reserved)
        if len(username) <= 5:
            logger.info(f"@{username} is too short (<=5 chars) - likely premium/reserved")
            self._banned_cache.add(username)
            return True
            
        # Check against RESERVED_WORDS list from config.py with exact match
        if username_lower in RESERVED_WORDS:
            logger.info(f"@{username} is in RESERVED_WORDS list")
            self._banned_cache.add(username)
            return True
            
        # --- LEVEL 2: SUBSTRING AND SIMILARITY CHECKS ---
            
        # Check if username contains any reserved word as a substring
        for reserved in RESERVED_WORDS:
            # Direct match or close substring
            if reserved in username_lower or username_lower in reserved:
                logger.info(f"@{username} contains or is contained in reserved word: {reserved}")
                self._banned_cache.add(username)
                return True
                
            # Hanya berlaku untuk reserved words yang sangat sensitif
            sensitive_reserved = ['admin', 'telegram', 'support', 'help', 'official', 'mod', 'staff']
            if reserved in sensitive_reserved:
                # Check for transposition only for sensitive words (e.g. 'admin' -> 'amdin')
                if len(reserved) >= 4 and len(username) >= 4:
                    # Hitung exact substring
                    if reserved in username_lower:
                        logger.info(f"@{username} contains sensitive word: {reserved}")
                        self._banned_cache.add(username)
                        return True
                    
                    # Levenshtein distance check - hanya untuk kata sensitif
                    if self._levenshtein_distance(reserved, username_lower) <= 1:  # Sangat mirip
                        logger.info(f"@{username} has edit distance <= 1 from sensitive word: {reserved}")
                        self._banned_cache.add(username)
                        return True
        
        # --- LEVEL 3: PATTERN MATCHING (Sangat Minimal) ---
            
        # Pola yang sangat MINIMAL untuk username terlarang
        banned_patterns = [
            # Hanya Numeric (angka saja)
            r'^[0-9]+$',
            
            # Hanya untuk Telegram officials yang SANGAT jelas
            r'^(telegram|admin)$',  # Hanya username yang persis sama dengan kata-kata ini
            
            # Username dengan special characters yang dilarang Telegram
            r'^[_.].*|.*[_.]$'  # Hanya username yang dimulai atau diakhiri dengan _ atau .
        ]
        
        for pattern in banned_patterns:
            if re.search(pattern, username, re.IGNORECASE):
                logger.info(f"@{username} matches banned pattern: {pattern}")
                self._banned_cache.add(username)
                return True
        
        # --- LEVEL 4: STATISTICAL CHECKS (KURANGI KEKETATAN) ---
                
        # Check for repetitive characters (level normal)
        char_counts = {}
        for char in username_lower:
            if char in char_counts:
                char_counts[char] += 1
            else:
                char_counts[char] = 1
                
        for char, count in char_counts.items():
            # Hanya periksa digit berulang untuk username yang dicurigai
            if count >= 3 and char in '0123456789' and len(username) <= 6:  # Three+ digit hanya untuk username pendek
                logger.info(f"@{username} has {count} instances of digit '{char}' in short username")
                self._banned_cache.add(username)
                return True
                
            # Karakter berulang yang sangat berlebihan (4+ kali)
            if count >= 4:  # Empat atau lebih karakter yang sama (kurangi keketatan)
                logger.info(f"@{username} has excessive {count} instances of '{char}'")
                self._banned_cache.add(username)
                return True
                
        # Character distribution check - only for extreme cases
        unique_chars = len(char_counts)
        if unique_chars <= 2 and len(username) > 6:  # Hanya 2 karakter unik pada username panjang
            logger.info(f"@{username} has extremely limited character distribution - only {unique_chars} unique chars")
            self._banned_cache.add(username)
            return True
            
        # Entropy check - hanya untuk kasus ekstrem
        entropy = self._calculate_entropy(username_lower)
        if entropy < 2.0 and len(username) > 6:  # Entropi sangat rendah pada username panjang
            logger.info(f"@{username} has extremely low entropy ({entropy})")
            self._banned_cache.add(username)
            return True

        try:
            async with self.session.get(f'https://t.me/{username}', allow_redirects=False) as response:
                # Quick check based on status codes
                if response.status in [403, 404, 410]:
                    self._banned_cache.add(username)
                    logger.info(f"@{username} banned (status code: {response.status})")
                    return True

                # Get text content for detailed analysis
                content = await response.text()
                content_lower = content.lower()

                # Enhanced banned patterns with more specific matches
                banned_patterns = [
                    r"(?i)this account (has been|was) (banned|terminated|suspended)",
                    r"(?i)(banned|terminated) for (spam|scam|abuse|violating)",
                    r"(?i)account (deleted|terminated|no longer available)",
                    r"(?i)violating telegram('s)? terms of service",
                    r"(?i)this account (is not accessible|has been restricted)",
                    r"(?i)permanently (removed|suspended|banned)",
                    r"(?i)account (suspended|blocked|removed)",
                    r"(?i)was banned by (telegram|the telegram team)",
                    r"(?i)this username (cannot|can't) be displayed",
                    r"(?i)this account (no longer exists|has been deleted)",
                    r"(?i)this account is no longer available",
                    r"(?i)this username has been banned",
                    r"(?i)username is not available for use",
                    r"(?i)username cannot be used due to security reasons",
                    r"(?i)username has been restricted",
                ]

                # Check for specific HTML elements that indicate banned status
                banned_indicators = [
                    'tgme_page_status_text',
                    'account_banned',
                    'username_banned',
                    'account_deleted',
                    'account_restricted'
                ]

                # Check HTML structure for banned indicators
                tree = html.fromstring(content)
                for indicator in banned_indicators:
                    elements = tree.xpath(f"//*[contains(@class, '{indicator}')]")
                    if elements:
                        self._banned_cache.add(username)
                        logger.info(f"@{username} banned (found indicator: {indicator})")
                        return True

                # Check content against banned patterns
                if any(re.search(pattern, content_lower) for pattern in banned_patterns):
                    self._banned_cache.add(username)
                    logger.info(f"@{username} banned (matched pattern)")
                    return True

                # Additional checks for specific Telegram error messages
                error_messages = [
                    "Sorry, this username is no longer available.",
                    "Sorry, this username is invalid.",
                    "Sorry, this username is taken by existing account.",
                    "Sorry, too many attempts."
                ]

                if any(msg.lower() in content_lower for msg in error_messages):
                    self._banned_cache.add(username)
                    logger.info(f"@{username} banned (error message)")
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking banned status for {username}: {e}")
            return True  # Assume banned on error to be safe

    async def check_fragment_api(self, username: str, retries=3) -> Optional[bool]:
        """Check username availability with Fragment API - Enhanced with stricter filtering"""
        # First check if username is banned
        if await self.is_banned(username):
            logger.info(f'@{username} is banned or restricted.')
            return None

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
                                        
                                        # Additional negative check - if it's really available, these shouldn't be there
                                        unavailable_indicators = [
                                            "This username is used by a channel",
                                            "This username is used by a group", 
                                            "This account is already taken",
                                            "This username is already taken",
                                            "Get Telegram"
                                        ]
                                        
                                        if any(indicator in content for indicator in unavailable_indicators):
                                            logger.info(f'@{username} appears to be taken despite availability check')
                                            return None

                                        # Perform one last HEAD request to verify status
                                        try:
                                            async with self.session.head(f'https://t.me/{username}', allow_redirects=False) as head_resp:
                                                if head_resp.status != 200:
                                                    logger.info(f'@{username} HEAD request returned {head_resp.status}')
                                                    return None
                                        except Exception as e:
                                            logger.error(f"Error in final HEAD check for @{username}: {e}")
                                            return None

                                        # Ultimate PARANOIA checks - the most extreme filtering possible
                                        
                                        # Final verification yang lebih terfokus - hanya periksa hal paling penting
                                        
                                        # Fragment API validation untuk username premium
                                        try:
                                            async with self.session.get(f'https://fragment.com/username/{username}') as frag_resp:
                                                frag_content = await frag_resp.text()
                                                
                                                # Hanya indikator kritis - jual beli username
                                                sale_indicators = [
                                                    "for sale", "buy now", "place bid", "auction", "current price"
                                                ]
                                                
                                                if any(indicator in frag_content.lower() for indicator in sale_indicators):
                                                    logger.info(f'@{username} appears to be for sale in final check')
                                                    return None
                                                    
                                        except Exception as e:
                                            logger.error(f"Error in final Fragment check for @{username}: {str(e)}")
                                            # Tidak gagal pada error, hanya log
                                        
                                        # Verifikasi dasar dengan user agent berbeda
                                        try:
                                            mobile_headers = {
                                                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15'
                                            }
                                            
                                            async with self.session.get(f'https://t.me/{username}', 
                                                                        headers=mobile_headers, 
                                                                        allow_redirects=True) as mobile_resp:
                                                
                                                # Hanya cek error status
                                                if mobile_resp.status >= 400:
                                                    logger.info(f'@{username} failed with error status {mobile_resp.status}')
                                                    return None
                                                
                                        except Exception as e:
                                            logger.error(f"Error in final check for @{username}: {str(e)}")
                                            # Tidak gagal pada error, hanya log
                                        
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