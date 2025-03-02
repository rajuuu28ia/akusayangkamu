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
    def __init__(self, rate_limit=10, time_window=60):
        self.rate_limit = rate_limit  # Further reduced rate limit
        self.time_window = time_window
        self.requests = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.time()
            # Remove old requests
            self.requests = [req_time for req_time in self.requests 
                           if now - req_time <= self.time_window]

            if len(self.requests) >= self.rate_limit:
                oldest_request = self.requests[0]
                sleep_time = max(0, self.time_window - (now - oldest_request))
                logger.warning(f"Rate limit reached, waiting {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)

            self.requests.append(now)

class TelegramUsernameChecker:
    def __init__(self):
        self._session = None
        self.rate_limiter = RateLimiter()
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes
        self._base_delay = 2  # Increased base delay
        self._max_retries = 3
        self._session_timeout = aiohttp.ClientTimeout(
            total=30,
            connect=10,
            sock_read=15
        )
        self._session_connector = aiohttp.TCPConnector(
            limit=5,  # Reduced connection limit
            force_close=True,  # Force close to prevent stale connections
            enable_cleanup_closed=True
        )

    @property
    async def session(self):
        """Lazy session initialization with proper error handling"""
        if self._session is None or self._session.closed:
            if self._session:
                await self._session.close()

            self._session = aiohttp.ClientSession(
                timeout=self._session_timeout,
                connector=self._session_connector,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/json',
                    'Connection': 'close'  # Don't keep connections alive
                }
            )
        return self._session

    async def close(self):
        """Properly close the session"""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _make_request(self, method: str, url: str, **kwargs):
        """Make HTTP request with improved error handling and retries"""
        session = await self.session

        for retry in range(self._max_retries):
            try:
                await self.rate_limiter.acquire()

                # Add delay before retry
                if retry > 0:
                    delay = self._base_delay * (2 ** retry)
                    logger.info(f"Retry {retry + 1}/{self._max_retries}, waiting {delay}s...")
                    await asyncio.sleep(delay)

                async with session.request(method, url, **kwargs) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 5))
                        logger.warning(f"Rate limited. Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        continue

                    # Handle other status codes
                    if response.status >= 400:
                        logger.warning(f"Request failed with status {response.status}")
                        if retry < self._max_retries - 1:
                            continue
                        return None

                    return response

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Request error on try {retry + 1}: {str(e)}")
                if retry == self._max_retries - 1:
                    logger.error(f"Max retries reached for {url}")
                    return None
                await asyncio.sleep(self._base_delay * (2 ** retry))

                # Recreate session on connection errors
                await self.close()
                continue

        return None

    def _get_cache(self, username: str):
        """Get cached result if not expired"""
        if username in self._cache:
            result, timestamp = self._cache[username]
            if time.time() - timestamp <= self._cache_ttl:
                logger.debug(f"Cache hit for @{username}")
                return result
            del self._cache[username]
        return None

    def _set_cache(self, username: str, result: bool):
        """Cache username check result"""
        self._cache[username] = (result, time.time())

    async def check_username(self, username: str) -> bool:
        """Check if a Telegram username is available"""
        # Input validation
        if not re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
            logger.warning(f"Invalid username format: {username}")
            return False

        if username.lower() in RESERVED_WORDS:
            logger.warning(f"Reserved username: {username}")
            return False

        # Check cache
        cached_result = self._get_cache(username)
        if cached_result is not None:
            return cached_result

        try:
            # Get Fragment API URL
            api_url = None
            for _ in range(2):
                response = await self._make_request('GET', 'https://fragment.com')
                if not response:
                    logger.warning("Failed to get Fragment homepage")
                    await asyncio.sleep(2)
                    continue

                text = await response.text()
                tree = html.fromstring(text)
                scripts = tree.xpath('//script/text()')
                pattern = re.compile(r'ajInit\((\{.*?})\);', re.DOTALL)
                script = next((s for s in scripts if pattern.search(s)), None)

                if script:
                    match = pattern.search(script)
                    if match:
                        try:
                            api_url = f'https://fragment.com{json.loads(match.group(1)).get("apiUrl")}'
                            break
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse API URL")
                            continue

                await asyncio.sleep(2)

            if not api_url:
                logger.error(f"Could not get API URL for @{username}")
                return False

            # Check username availability
            params = {
                'query': username,
                'method': 'searchAuctions',
                'type': 'usernames'
            }

            response = await self._make_request('POST', api_url, data=params)
            if not response:
                return False

            try:
                data = await response.json()
            except json.JSONDecodeError:
                logger.error("Failed to parse API response")
                return False

            if not isinstance(data, dict) or not data.get('html'):
                logger.warning(f"Invalid response format for @{username}")
                return False

            tree = html.fromstring(data['html'])
            values = tree.xpath('//div[contains(@class, "tm-value")]/text()')

            if len(values) < 3:
                logger.warning(f"Insufficient data for @{username}")
                return False

            username_tag, price, status = values[:3]

            if price.isdigit():
                logger.info(f"@{username} is for sale: {price}💎")
                self._set_cache(username, False)
                return False

            if status == 'Unavailable':
                # Double check with web
                web_response = await self._make_request('GET', f'https://t.me/{username}')
                if web_response:
                    text = await web_response.text()
                    if f"You can contact @{username} right away." not in text:
                        logger.info(f"✅ @{username} might be available")
                        self._set_cache(username, True)
                        return True

            logger.info(f"❌ @{username} is taken or unavailable")
            self._set_cache(username, False)
            return False

        except Exception as e:
            logger.error(f"Error checking @{username}: {str(e)}")
            return False

        finally:
            # Ensure connection is closed
            await self.close()

    async def batch_check(self, usernames: list, batch_size: int = 3) -> list:
        """Check multiple usernames concurrently in batches"""
        results = []
        total_batches = (len(usernames) + batch_size - 1) // batch_size
        current_batch = 0

        for i in range(0, len(usernames), batch_size):
            current_batch += 1
            batch = usernames[i:i + batch_size]
            logger.info(f"Processing batch {current_batch}/{total_batches}")

            try:
                # Process current batch
                tasks = [self.check_username(username) for username in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                for username, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        logger.error(f"Error checking @{username}: {result}")
                        results.append(False)
                    else:
                        results.append(result)

                # Longer delay between batches
                if i + batch_size < len(usernames):
                    await asyncio.sleep(3)  # Increased delay between batches

            except Exception as e:
                logger.error(f"Batch {current_batch} failed: {str(e)}")
                results.extend([False] * len(batch))

        return results

async def check_usernames(usernames: list) -> list:
    """Helper function to check multiple usernames"""
    checker = TelegramUsernameChecker()
    try:
        return await checker.batch_check(usernames)
    finally:
        await checker.close()