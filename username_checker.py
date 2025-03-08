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
        """Initialize checker with aggressive caching and strict verification"""
        self.session = aiohttp.ClientSession()
        self.rate_semaphore = asyncio.Semaphore(5)
        self.last_request_time = 0
        self.base_delay = 1

        # Enhanced caching
        self._username_cache: Dict[str, tuple] = {}  # (result, timestamp)
        self._banned_cache: Set[str] = set()  # Permanent cache for banned usernames
        self._last_check_time = time.time()
        self._check_count = 0
        self._cache_ttl = 3600  # 1 hour cache

        # Get API credentials
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")

    async def is_banned_by_status(self, username: str) -> bool:
        """Check if username is banned based on HTTP status and headers"""
        try:
            headers = {
                'User-Agent': 'TelegramBot (like TwitterBot/1.0)',
                'Accept': 'application/json'
            }
            async with self.session.get(f'https://t.me/{username}', 
                                      headers=headers, 
                                      allow_redirects=False) as response:
                # Check status codes first
                if response.status in [403, 404, 410]:
                    return True

                # Check headers for ban indicators
                headers = response.headers
                if any([
                    headers.get('X-Robot-Tag') == 'banned',
                    headers.get('X-Account-Status') == 'suspended',
                    headers.get('Location', '').endswith('/404'),
                    headers.get('X-Frame-Options') == 'DENY'  # Often used for banned accounts
                ]):
                    return True

                return False
        except Exception as e:
            logger.error(f"Error checking status for {username}: {e}")
            return False

    async def is_banned_by_content(self, username: str) -> bool:
        """Enhanced check for banned status in page content"""
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
            r"(?i)(account|username) (violated|violating) (terms|guidelines)",
            r"(?i)account (terminated|suspended) due to",
            r"(?i)this account (cannot|can't) be (accessed|reached)"
        ]

        try:
            # First check
            async with self.session.get(f'https://t.me/{username}') as response:
                content = await response.text()

                # Quick check for obvious indicators
                content_lower = content.lower()
                if 'banned' in content_lower or 'terminated' in content_lower:
                    # Double verify with second request after delay
                    await asyncio.sleep(1)
                    async with self.session.get(f'https://t.me/{username}') as second_response:
                        second_content = await second_response.text()

                        # Check patterns in both responses
                        for pattern in banned_patterns:
                            if (re.search(pattern, content_lower) and 
                                re.search(pattern, second_content.lower())):
                                return True

            return False
        except Exception as e:
            logger.error(f"Error checking content for {username}: {e}")
            return False

    async def verify_with_api(self, username: str) -> bool:
        """Verify banned status using Telegram API with multiple endpoints"""
        if not self.api_id or not self.api_hash:
            return False

        headers = {
            'User-Agent': 'TelegramBot (like TwitterBot/1.0)',
            'Accept': 'application/json',
            'api_id': self.api_id,
            'api_hash': self.api_hash
        }

        endpoints = [
            f'https://api.telegram.org/bot{self.api_id}/getChat',
            'https://api.telegram.org/v1/users/getInfo',
            f'https://api.telegram.org/bot{self.api_id}/getChatMember'
        ]

        for endpoint in endpoints:
            try:
                params = {'username': username}
                async with self.session.get(endpoint, params=params, headers=headers) as response:
                    if response.status in [403, 404]:
                        return True

                    data = await response.json()
                    if any([
                        data.get('error_code') in [400, 403],
                        'deleted' in str(data).lower(),
                        'deactivated' in str(data).lower(),
                        'banned' in str(data).lower()
                    ]):
                        return True
            except:
                continue

        return False

    async def is_username_banned(self, username: str) -> bool:
        """
        Multi-layer verification system for banned usernames with aggressive caching
        """
        # Check cache first
        if username in self._banned_cache:
            logger.info(f"@{username} found in banned cache")
            return True

        try:
            # Layer 1: Quick Status Check
            if await self.is_banned_by_status(username):
                logger.info(f"@{username} banned by status check")
                self._banned_cache.add(username)
                return True

            # Layer 2: Content Analysis
            if await self.is_banned_by_content(username):
                logger.info(f"@{username} banned by content check")
                self._banned_cache.add(username)
                return True

            # Layer 3: API Verification
            if await self.verify_with_api(username):
                logger.info(f"@{username} banned by API check")
                self._banned_cache.add(username)
                return True

            # Double verification for important cases
            if username.isalnum() or '_' in username:  # Only for valid-looking usernames
                await asyncio.sleep(1)  # Brief delay before double-check
                status_check = await self.is_banned_by_status(username)
                content_check = await self.is_banned_by_content(username)

                if status_check or content_check:
                    logger.info(f"@{username} banned on double-check")
                    self._banned_cache.add(username)
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking banned status for {username}: {e}")
            # If error occurs, assume banned to be safe
            return True

    async def check_fragment_api(self, username: str, count=6) -> Optional[bool]:
        """Check username availability with strict banned checks first"""
        try:
            # Comprehensive multi-layer banned check before anything else
            is_banned = False

            # Layer 1: Quick ban check via status codes and headers
            try:
                async with self.session.get(f'https://t.me/{username}', 
                                          allow_redirects=False,
                                          timeout=10) as response:
                    if response.status in [403, 404, 410]:
                        logger.error(f'@{username} ❌ Banned (status code: {response.status})')
                        return None

                    headers = response.headers
                    if any([
                        headers.get('X-Robot-Tag') == 'banned',
                        headers.get('X-Account-Status') == 'suspended',
                        headers.get('Location', '').endswith('/404'),
                        headers.get('X-Frame-Options') == 'DENY'
                    ]):
                        logger.error(f'@{username} ❌ Banned (headers indicate banned)')
                        return None

                    content = await response.text()

                    # Check for banned indicators in content
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
                    ]

                    content_lower = content.lower()
                    for pattern in banned_patterns:
                        if re.search(pattern, content_lower):
                            # Double verify with second request
                            await asyncio.sleep(1)
                            async with self.session.get(f'https://t.me/{username}') as second_response:
                                second_content = await second_response.text()
                                if re.search(pattern, second_content.lower()):
                                    logger.error(f'@{username} ❌ Banned (content indicates banned)')
                                    return None

                    # Check for premium indicators that might mask banned status
                    premium_indicators = [
                        "This account is already subscribed to Telegram Premium",
                        "Premium Account",
                        "premium_badge",
                        "tg-premium"
                    ]

                    if any(ind in content for ind in premium_indicators):
                        logger.error(f'@{username} 👑 Premium user (might mask banned status)')
                        return None

            except Exception as e:
                logger.error(f"Error in Layer 1 ban check for {username}: {e}")
                return None

            # Layer 2: Fragment API check
            if count == 0:
                return None

            async with self.session.get('https://fragment.com') as response:
                text = await response.text()
                tree = html.fromstring(text)
                scripts = tree.xpath('//script/text()')
                pattern = re.compile(r'ajInit\((\{.*?})\);', re.DOTALL)
                script = next((script for script in scripts if pattern.search(script)), None)

                if not script:
                    logger.error(f'@{username} 💔 API URL not found')
                    return None

                api_url = f'https://fragment.com{json.loads(pattern.search(script).group(1)).get("apiUrl")}'
                search_auctions = {'type': 'usernames', 'query': username, 'method': 'searchAuctions'}

                async with self.session.post(api_url, data=search_auctions) as response:
                    if response.status == 429:  # Rate limit hit
                        delay = self.base_delay * (2 ** (6 - count))
                        await asyncio.sleep(delay)
                        return await self.check_fragment_api(username, count - 1)

                    response_data = await response.json()

                    if not isinstance(response_data, dict) or not response_data.get('html'):
                        logger.debug(f'@{username} 💔 Invalid API response')
                        await asyncio.sleep(self.base_delay)
                        return await self.check_fragment_api(username, count - 1)

                    tree = html.fromstring(response_data.get('html'))
                    username_data = tree.xpath('//div[contains(@class, "tm-value")]')[:3]

                    if len(username_data) < 3:
                        logger.error(f'@{username} 💔 Not enough username data')
                        return None

                    username_tag = username_data[0].text_content()
                    status = username_data[2].text_content()
                    price = username_data[1].text_content()

                    if username_tag[1:] != username:
                        logger.error(f'@{username} 💔 Username mismatch')
                        return None

                    if price.isdigit():
                        logger.error(f'@{username} 💸 For sale: {price}💎')
                        return None

                    # Final availability verification
                    if status == 'Unavailable':
                        # Triple verification before declaring available
                        for _ in range(3):
                            # Check with delay between attempts
                            await asyncio.sleep(1)
                            async with self.session.get(f'https://t.me/{username}') as verify_response:
                                if verify_response.status in [403, 404, 410]:
                                    logger.error(f'@{username} ❌ Banned (final verification)')
                                    return None

                                content = await verify_response.text()
                                # Check for any banned or premium indicators
                                if any(ind.lower() in content.lower() for ind in banned_patterns + premium_indicators):
                                    logger.error(f'@{username} ❌ Banned/Premium (final verification)')
                                    return None

                        # If passed all verifications, mark as available
                        logger.critical(f'✅ @{username} Available ✅')
                        return True

                    return None

        except asyncio.TimeoutError:
            logger.error(f"Timeout checking @{username}")
            if count > 1:
                await asyncio.sleep(self.base_delay)
                return await self.check_fragment_api(username, count - 1)
            return None
        except Exception as e:
            logger.error(f"Error checking @{username}: {e}")
            return None

    async def get_telegram_web_user(self, username: str) -> bool:
        """Check username via Telegram web with improved verification"""
        try:
            headers = {
                'User-Agent': 'TelegramBot (like TwitterBot/1.0)',
                'Accept': 'application/json'
            }
            async with self.session.get(f'https://t.me/{username}', headers=headers) as response:
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

    async def _is_banned_by_api(self, username: str) -> bool:
        """Verify banned status using Telegram API"""
        try:
            if not self.api_id or not self.api_hash:
                return False

            headers = {
                'User-Agent': 'TelegramBot (like TwitterBot/1.0)',
                'Accept': 'application/json',
                'api_id': self.api_id,
                'api_hash': self.api_hash
            }

            params = {'username': username}

            # Try multiple API endpoints
            endpoints = [
                f'https://api.telegram.org/bot{self.api_id}/getChat',
                'https://api.telegram.org/v1/users/getInfo'
            ]

            for endpoint in endpoints:
                try:
                    async with self.session.get(endpoint, params=params, headers=headers) as response:
                        if response.status in [403, 404]:
                            return True

                        data = await response.json()
                        if data.get('error_code') in [400, 403] or 'deleted' in str(data).lower():
                            return True
                except:
                    continue

            return False

        except Exception as e:
            logger.error(f"API verification error for {username}: {e}")
            return False

    async def _is_banned_by_content(self, username: str) -> bool:
        """Check if username is banned by page content"""
        banned_patterns = [
            # Direct ban indicators
            r"(?i)this account (has been|was) (banned|terminated|suspended)",
            r"(?i)(banned|terminated) for (spam|scam|abuse|violating)",
            r"(?i)account (deleted|terminated|no longer available)",
            r"(?i)violating telegram('s)? terms of service",
            r"(?i)this account (is not accessible|has been restricted)",
            # Additional indicators
            r"(?i)permanently (removed|suspended|banned)",
            r"(?i)account (suspended|blocked|removed)",
            r"(?i)was banned by (telegram|the telegram team)",
            r"(?i)this username (cannot|can't) be displayed"
        ]

        try:
            async with self.session.get(f'https://t.me/{username}') as response:
                content = await response.text()
                content_lower = content.lower()

                # Check each pattern
                for pattern in banned_patterns:
                    if re.search(pattern, content_lower):
                        # Double verify
                        await asyncio.sleep(1)
                        async with self.session.get(f'https://t.me/{username}') as second_response:
                            second_content = await second_response.text()
                            if re.search(pattern, second_content.lower()):
                                return True

                return False
        except Exception as e:
            logger.error(f"Error checking content for {username}: {e}")
            return False


    async def _get_cached_result(self, username: str) -> bool:
        """Get cached result if available and not expired"""
        if username in self._username_cache:
            result, timestamp = self._username_cache[username]
            if timestamp + self._cache_ttl > time.time():
                return result
            del self._username_cache[username]
        return None

    def _cache_result(self, username: str, result: bool) -> None:
        """Cache username check result"""
        self._username_cache[username] = (result, time.time())


# Reusable check function
async def check_telegram_username(username: str) -> bool:
    """Check if a Telegram username is available with strict verification"""
    if not re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
        logger.warning(f"Invalid username format: {username}")
        return False

    if username.lower() in RESERVED_WORDS:
        logger.warning(f"Reserved username: {username}")
        return False

    checker = TelegramUsernameChecker()
    try:
        result = await checker.check_fragment_api(username.lower())
        return bool(result)
    except Exception as e:
        logger.error(f"Error in check_telegram_username: {str(e)}")
        return False
    finally:
        await checker.close()

# Global rate limit semaphore
GLOBAL_SEMAPHORE = asyncio.Semaphore(30)  # Maximum 30 concurrent requests total