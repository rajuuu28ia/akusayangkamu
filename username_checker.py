import aiohttp
import asyncio
import logging
import re
import json
import os
import time
from lxml import html
from config import RESERVED_WORDS

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PREMIUM_USER = 'This account is already subscribed to Telegram Premium.'
CHANNEL = 'Please enter a username assigned to a user.'
NOT_FOUND = 'No Telegram users found.'

class RateLimiter:
    def __init__(self, rate_limit=30, time_window=60):
        self.rate_limit = rate_limit  # Maximum requests per time window
        self.time_window = time_window  # Time window in seconds
        self.requests = []  # List to track request timestamps
        self._lock = asyncio.Lock()  # Lock for thread safety

    async def acquire(self):
        async with self._lock:
            now = time.time()
            # Remove old requests outside the time window
            self.requests = [req_time for req_time in self.requests 
                           if now - req_time <= self.time_window]

            if len(self.requests) >= self.rate_limit:
                oldest_request = self.requests[0]
                sleep_time = max(0, self.time_window - (now - oldest_request))
                await asyncio.sleep(sleep_time)

            self.requests.append(now)

class TelegramUsernameChecker:
    def __init__(self):
        self.session = None
        self.rate_limiter = RateLimiter(rate_limit=25, time_window=60)
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes

        # Get API credentials from environment
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")

        if not all([self.api_id, self.api_hash]):
            logger.warning("Telegram API credentials not found. Some features may be limited.")

    async def _init_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    def _get_cache(self, username: str):
        """Get cached result if not expired"""
        if username in self._cache:
            result, timestamp = self._cache[username]
            if time.time() - timestamp <= self._cache_ttl:
                return result
            del self._cache[username]
        return None

    def _set_cache(self, username: str, result: bool):
        """Cache username check result"""
        self._cache[username] = (result, time.time())

    async def get_api_url(self):
        await self._init_session()
        await self.rate_limiter.acquire()

        try:
            async with self.session.get('https://fragment.com') as response:
                if response.status == 429:
                    logger.warning("Rate limited by Fragment API. Waiting...")
                    await asyncio.sleep(5)
                    return await self.get_api_url()

                text = await response.text()
                tree = html.fromstring(text)
                scripts = tree.xpath('//script/text()')
                pattern = re.compile(r'ajInit\((\{.*?})\);', re.DOTALL)
                script = next((script for script in scripts if pattern.search(script)), None)
                if script:
                    api_url = f'https://fragment.com{json.loads(pattern.search(script).group(1)).get("apiUrl")}'
                    return api_url
        except Exception as e:
            logger.error(f"Error getting API URL: {e}")
        return None

    async def check_username(self, username: str) -> bool:
        """Check if a Telegram username is available"""
        # Check format and reserved words
        if not re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
            logger.warning(f"Invalid username format: {username}")
            return False

        if username.lower() in RESERVED_WORDS:
            logger.warning(f"Reserved username: {username}")
            return False

        # Check cache first
        cached_result = self._get_cache(username)
        if cached_result is not None:
            logger.info(f"Cache hit for @{username}")
            return cached_result

        try:
            await self._init_session()
            await self.rate_limiter.acquire()

            api_url = await self.get_api_url()
            if not api_url:
                logger.error(f"Could not get API URL for @{username}")
                return False

            params = {
                'query': username,
                'method': 'searchAuctions',
                'type': 'usernames'
            }

            async with self.session.post(api_url, data=params) as response:
                if response.status == 429:
                    logger.warning(f"Rate limited checking @{username}. Retrying...")
                    await asyncio.sleep(5)
                    return await self.check_username(username)

                data = await response.json()

                if isinstance(data, dict) and data.get('html'):
                    tree = html.fromstring(data['html'])
                    values = tree.xpath('//div[contains(@class, "tm-value")]/text()')

                    if len(values) >= 3:
                        username_tag, price, status = values[:3]

                        if price.isdigit():
                            logger.info(f"@{username} is for sale: {price}💎")
                            return False

                        if status == 'Unavailable':
                            # Double check with web
                            async with self.session.get(f'https://t.me/{username}') as web_response:
                                text = await web_response.text()
                                if f"You can contact @{username} right away." not in text:
                                    logger.info(f"✅ @{username} might be available")
                                    self._set_cache(username, True)
                                    return True

                logger.info(f"❌ @{username} is taken or unavailable")
                self._set_cache(username, False)
                return False

        except Exception as e:
            logger.error(f"Error checking @{username}: {e}")
            return False

    async def batch_check(self, usernames: list, batch_size: int = 5) -> list:
        """Check multiple usernames concurrently in batches"""
        results = []
        for i in range(0, len(usernames), batch_size):
            batch = usernames[i:i + batch_size]
            tasks = [self.check_username(username) for username in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for username, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Error checking @{username}: {result}")
                    results.append(False)
                else:
                    results.append(result)

            # Small delay between batches to prevent overwhelming
            await asyncio.sleep(1)

        return results

async def check_usernames(usernames: list) -> list:
    """Helper function to check multiple usernames"""
    async with TelegramUsernameChecker() as checker:
        return await checker.batch_check(usernames)