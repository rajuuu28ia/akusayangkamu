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
        """Initialize checker with improved caching and rate limiting"""
        self.session = aiohttp.ClientSession()
        self.rate_semaphore = asyncio.Semaphore(5)
        self.last_request_time = 0
        self.base_delay = 1

        # Cache for results
        self._username_cache: Dict[str, tuple] = {}  # (result, timestamp)
        self._banned_cache: Set[str] = set()
        self._last_check_time = time.time()
        self._check_count = 0
        self._cache_ttl = 3600  # 1 hour cache

        # Get API credentials
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")

    async def _is_banned_by_status(self, username: str) -> bool:
        """Check if username is banned by HTTP status"""
        try:
            async with self.session.get(f'https://t.me/{username}', allow_redirects=False) as response:
                # Check specific status codes
                if response.status in [403, 404]:
                    return True

                # Check headers
                headers = response.headers
                if any([
                    headers.get('X-Robot-Tag') == 'banned',
                    headers.get('X-Account-Status') == 'suspended',
                    headers.get('Location', '').endswith('/404')
                ]):
                    return True

                return False
        except Exception as e:
            logger.error(f"Error checking status for {username}: {e}")
            return False

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

    async def is_username_banned(self, username: str) -> bool:
        """
        Multi-layer verification for banned usernames
        Returns True if username is banned
        """
        # Check cache first
        if username in self._banned_cache:
            return True

        try:
            # Layer 1: Status Code Check
            if await self._is_banned_by_status(username):
                self._banned_cache.add(username)
                return True

            # Layer 2: Content Check    
            if await self._is_banned_by_content(username):
                self._banned_cache.add(username)
                return True

            # Layer 3: API Check
            if await self._is_banned_by_api(username):
                self._banned_cache.add(username)
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking banned status for {username}: {e}")
            return False

    async def check_fragment_api(self, username: str, count=6) -> Optional[bool]:
        """Check username availability using Fragment API with improved banned detection"""
        # First check if username is banned
        if await self.is_username_banned(username):
            logger.error(f'@{username} ❌ Account Banned')
            return None

        try:
            async with asyncio.timeout(30):
                current_time = time.time()
                time_since_last = current_time - self._last_check_time
                self._check_count += 1
                logger.info(f"Starting check #{self._check_count} for @{username} (Time since last check: {time_since_last:.2f}s)")
                self._last_check_time = current_time

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

                        if status == 'Unavailable':
                            # Final check for availability
                            if await self.is_username_banned(username):
                                logger.error(f'@{username} ❌ Banned account detected')
                                return None

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

    async def get_api_url(self):
        """Get Fragment API URL with improved caching"""
        async with GLOBAL_SEMAPHORE:
            async with self.rate_semaphore:
                headers = {
                    'X-Api-Id': self.api_id,
                    'X-Api-Hash': self.api_hash
                }
                async with self.session.get('https://fragment.com', headers=headers) as response:
                    text = await response.text()
                    tree = html.fromstring(text)
                    scripts = tree.xpath('//script/text()')
                    pattern = re.compile(r'ajInit\((\{.*?})\);', re.DOTALL)
                    script = next((script for script in scripts if pattern.search(script)), None)
                    if script:
                        api_url = f'https://fragment.com{json.loads(pattern.search(script).group(1)).get("apiUrl")}'
                        return api_url
        return None

    async def get_user(self, username, api_url, count=6):
        """Check user status via Fragment API with improved error handling"""
        async with GLOBAL_SEMAPHORE:
            async with self.rate_semaphore:
                headers = {
                    'X-Api-Id': self.api_id,
                    'X-Api-Hash': self.api_hash
                }
                search_recipient_params = {'query': username, 'months': 3, 'method': 'searchPremiumGiftRecipient'}
                try:
                    async with self.session.post(api_url, data=search_recipient_params, headers=headers) as response:
                        if response.status == 429:
                            delay = self.base_delay * (2 ** (6 - count))
                            logger.warning(f"Rate limited. Waiting {delay} seconds before retry...")
                            await asyncio.sleep(delay)
                            return await self.get_user(username, api_url, count - 1)

                        data = await response.json()
                        error = data.get('error')
                        return error
                except Exception as e:
                    logger.error(f"Error checking user {username}: {str(e)}")
                    if count > 1:
                        await asyncio.sleep(self.base_delay)
                        return await self.get_user(username, api_url, count - 1)
                    return None

    async def get_telegram_web_user(self, username):
        """Check username via Telegram web with improved caching"""
        cached_result = await self._get_cached_result(username)
        if cached_result is not None:
            return cached_result

        async with GLOBAL_SEMAPHORE:
            async with self.rate_semaphore:
                headers = {
                    'X-Api-Id': self.api_id,
                    'X-Api-Hash': self.api_hash
                }
                try:
                    async with self.session.get(f'https://t.me/{username}', headers=headers) as response:
                        if response.status == 429:
                            delay = self.base_delay * 2
                            logger.warning(f"Rate limited by Telegram. Waiting {delay} seconds...")
                            await asyncio.sleep(delay)
                            return await self.get_telegram_web_user(username)

                        text = await response.text()
                        result = f"You can contact @{username} right away." in text
                        self._cache_result(username, result)
                        return result
                except Exception as e:
                    logger.error(f"Error checking web user {username}: {str(e)}")
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

    async def close(self):
        """Close the aiohttp session"""
        if not self.session.closed:
            await self.session.close()

async def check_telegram_username(username: str) -> bool:
    """Check if a Telegram username is available"""
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

# Global rate limit semaphore - increased for more concurrent requests
GLOBAL_SEMAPHORE = asyncio.Semaphore(30)  # Maximum 30 concurrent requests total