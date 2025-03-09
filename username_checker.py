import aiohttp
import asyncio
import logging
import re
import json
import os
import time
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

    async def is_banned(self, username: str) -> bool:
        """
        Enhanced multi-layer verification system for banned usernames
        with improved pattern matching and caching
        """
        # Check cache first
        if username in self._banned_cache:
            logger.info(f"@{username} found in banned cache")
            return True
            
        # Check against RESERVED_WORDS list from config.py
        if username.lower() in RESERVED_WORDS:
            logger.info(f"@{username} is in RESERVED_WORDS list")
            self._banned_cache.add(username)
            return True
            
        # Check if username contains any reserved word as a substring
        for reserved in RESERVED_WORDS:
            if reserved in username.lower():
                logger.info(f"@{username} contains reserved word '{reserved}'")
                self._banned_cache.add(username)
                return True
            
        # Special check for common banned patterns
        common_banned_patterns = [
            # Very short usernames (typically reserved)
            r'^[a-z]{1,3}$',
            # Numeric-only usernames (typically reserved)
            r'^[0-9]+$',
            # Common prefixes for Telegram officials (reserved)
            r'^(telegram|tg|admin|support|help|info|news|bot|official|service|verify).*',
            # Common suffixes for official accounts
            r'.*(official|support|help|admin|mod|team|staff|service|verify|account)$',
            # Common patterns in phishing/scam attempts
            r'.*(_adm|_support|admin[0-9]|[0-9]admin|_team|_official).*',
            # Usernames with excessive repeating characters (often banned)
            r'.*(.)\1{3,}.*',
            # Username with dot or underscore at start/end (invalid)
            r'^[_.].*|.*[_.]$',
            # Sequential character patterns (often reserved)
            r'^abcd.*|^efgh.*|^ijkl.*|^mnop.*|^qrst.*|^uvwx.*|^wxyz.*|^1234.*',
            # Too many underscores (often used in spam)
            r'.*_{2,}.*'
        ]
        
        if any(re.match(pattern, username.lower()) for pattern in common_banned_patterns):
            logger.info(f"@{username} matches a common banned pattern")
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

        # More comprehensive list of suspicious patterns that are likely banned
        suspicious_patterns = [
            # Official-sounding names (commonly banned)
            r'.*support.*', r'.*admin.*', r'.*help.*', r'.*service.*',
            r'.*official.*', r'.*team.*', r'.*staff.*', r'.*mod.*',
            r'.*contact.*', r'.*care.*', r'.*telegram.*', r'.*assist.*',
            r'.*verify.*', r'.*auth.*', r'.*security.*', r'.*privacy.*',
            
            # Brand names (commonly protected)
            r'.*apple.*', r'.*google.*', r'.*meta.*', r'.*facebook.*',
            r'.*instagram.*', r'.*whatsapp.*', r'.*microsoft.*', r'.*amazon.*',
            r'.*netflix.*', r'.*spotify.*', r'.*paypal.*', r'.*visa.*',
            r'.*youtube.*', r'.*twitter.*', r'.*tiktok.*',
            
            # Support/service-related 
            r'.*helpdesk.*', r'.*customer.*', r'.*service.*', r'.*agent.*',
            r'.*representative.*', r'.*operator.*',
            
            # Premium/financial patterns
            r'.*premium.*', r'.*wallet.*', r'.*crypto.*', r'.*bitcoin.*',
            r'.*payment.*', r'.*finance.*', r'.*bank.*', r'.*money.*',
            
            # Explicit content or harmful related
            r'.*porn.*', r'.*adult.*', r'.*xxx.*', r'.*sex.*',
            r'.*hack.*', r'.*crack.*', r'.*cheat.*', r'.*spam.*',
            
            # Generic names used by scammers
            r'.*real.*', r'.*true.*', r'.*genuine.*', r'.*legit.*',
            r'.*verified.*', r'.*original.*'
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
                                            # Special pattern test for concealed banned usernames
                                            pattern_test = username.lower()
                                            strict_patterns = [
                                                # Check for numerical replacements (common in banned usernames)
                                                r'.*[0o][0o].*', # Double zeros or o's (often in banned)
                                                r'.*[1il][1il].*', # Combinations of 1, i, l (often in banned)
                                                r'.*[0o][1il].*', # Combinations of 0/o with 1/i/l (often in banned)
                                                r'.*[1il][0o].*', # Reverse of above
                                                # Check for mixed case patterns (common in banned)
                                                r'.*[A-Z][A-Z].*', # Two or more uppercase letters
                                                # Check for specific risky character sequences
                                                r'.*admin.*', r'.*mod.*', r'.*staff.*', r'.*team.*', r'.*help.*',
                                                r'.*support.*', r'.*service.*', r'.*official.*', r'.*bot.*',
                                                # Numeric patterns at end
                                                r'.*[0-9][0-9]+$'
                                            ]
                                            
                                            if any(re.search(p, pattern_test) for p in strict_patterns):
                                                logger.info(f'@{username} contains ultra-sensitive pattern - marking as banned')
                                                self._banned_cache.add(username)
                                                return None
                                                
                                            # Special HTTP headers check - some banned usernames show with special headers
                                            custom_headers = {
                                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                                                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                                                'Accept-Language': 'en-US,en;q=0.9',
                                                'Cache-Control': 'no-cache'
                                            }
                                            
                                            async with self.session.get(f'https://t.me/{username}', headers=custom_headers) as special_check:
                                                special_content = await special_check.text()
                                                if any(banned_word in special_content.lower() for banned_word in [
                                                    "unavailable", "banned", "blocked", "removed", "deleted", 
                                                    "terminated", "restricted", "violation", "bot", "telegram"
                                                ]):
                                                    logger.info(f'@{username} found to be banned in special content check')
                                                    self._banned_cache.add(username)
                                                    return None
                                        except Exception as e:
                                            logger.error(f"Error in ultra-strict check for @{username}: {str(e)}")
                                            # If there's any error in this critical check, assume it's banned
                                            return None
                                            
                                        # Final verification to avoid false positives
                                        # Check for specific text patterns that indicate restrictions
                                        banned_indicators = [
                                            "account is not accessible",
                                            "username is not available",
                                            "username cannot be displayed",
                                            "was banned",
                                            "has been banned",
                                            "username banned",
                                            "violating",
                                            "violation",
                                            "terms of service",
                                            "this account",
                                            "for sale",
                                            "purchase this",
                                            "auction",
                                            "premium",
                                            "restricted"
                                        ]
                                        
                                        if any(indicator in content.lower() for indicator in banned_indicators):
                                            logger.info(f'@{username} has banned indicator text in final check')
                                            return None
                                        
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

                                        # Absolute final check - direct Fragment API validation
                                        try:
                                            # Try one more check via different channel
                                            async with self.session.get(f'https://fragment.com/username/{username}') as frag_resp:
                                                frag_content = await frag_resp.text()
                                                
                                                # Check if page contains "Not found" or auction indicators
                                                not_found_indicators = ["not found", "not available", "auction", "tgFragment.showSimilar"]
                                                if any(indicator in frag_content.lower() for indicator in not_found_indicators):
                                                    logger.info(f'@{username} failed final Fragment direct check')
                                                    return None
                                                
                                                # Check if page contains sale indicators
                                                sale_indicators = ["for sale", "buy now", "place bid", "auction", "current price"]
                                                if any(indicator in frag_content.lower() for indicator in sale_indicators):
                                                    logger.info(f'@{username} appears to be for sale in final check')
                                                    return None
                                                    
                                        except Exception as e:
                                            logger.error(f"Error in absolute final check for @{username}: {str(e)}")
                                            # Don't fail here, as this is just an extra safeguard
                                        
                                        # ABSOLUTELY PASS - username has passed ALL verification layers
                                        logger.info(f'✅ @{username} is Fully Verified Available ✅')
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