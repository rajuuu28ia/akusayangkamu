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
    def __init__(self, rate_limit=15, time_window=60):
        self.rate_limit = rate_limit  # Reduced rate limit to be more conservative
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
                logger.warning(f"Rate limit reached, waiting {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)

            self.requests.append(now)

class TelegramUsernameChecker:
    def __init__(self):
        self.session = None
        self.rate_limiter = RateLimiter()
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes
        self._backoff_factor = 2  # Increased backoff factor
        self._max_retries = 3  # Reduced max retries
        self._base_delay = 1  # Base delay in seconds

        # Get API credentials from environment
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")

        if not all([self.api_id, self.api_hash]):
            logger.warning("Telegram API credentials not found. Some features may be limited.")

    async def _init_session(self):
        """Initialize session with improved connection handling"""
        if self.session is None:
            connector = aiohttp.TCPConnector(
                limit=5,  # Reduced connection pool limit
                ttl_dns_cache=300,  # Cache DNS results
                force_close=False,  # Keep connections alive
                enable_cleanup_closed=True
            )
            timeout = aiohttp.ClientTimeout(
                total=15,  # Reduced total timeout
                connect=5,
                sock_read=10
            )
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'TelegramBot/1.0',
                    'Accept': 'application/json, text/html',
                    'Connection': 'keep-alive'
                }
            )

    async def close(self):
        """Properly close the session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def _make_request(self, method: str, url: str, **kwargs):
        """Make HTTP request with improved error handling and retries"""
        await self._init_session()

        for retry in range(self._max_retries):
            try:
                await self.rate_limiter.acquire()

                # Add timeout to request if not provided
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = 10

                async with self.session.request(method, url, **kwargs) as response:
                    if response.status == 429:  # Rate limited
                        retry_after = int(response.headers.get('Retry-After', self._base_delay * (2 ** retry)))
                        logger.warning(f"Rate limited. Waiting {retry_after}s before retry...")
                        await asyncio.sleep(retry_after)
                        continue

                    response.raise_for_status()
                    return response

            except aiohttp.ClientError as e:
                wait_time = self._base_delay * (self._backoff_factor ** retry)
                logger.warning(f"Connection error on try {retry + 1}/{self._max_retries}: {str(e)}")

                if retry < self._max_retries - 1:
                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                logger.error(f"Max retries reached for {url}")
                return None

            except asyncio.TimeoutError:
                wait_time = self._base_delay * (self._backoff_factor ** retry)
                logger.warning(f"Timeout on try {retry + 1}/{self._max_retries}")

                if retry < self._max_retries - 1:
                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                logger.error(f"Request timeout after {self._max_retries} retries")
                return None

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
            for _ in range(2):  # Try twice to get API URL
                response = await self._make_request('GET', 'https://fragment.com')
                if response:
                    text = await response.text()
                    tree = html.fromstring(text)
                    scripts = tree.xpath('//script/text()')
                    pattern = re.compile(r'ajInit\((\{.*?})\);', re.DOTALL)
                    script = next((script for script in scripts if pattern.search(script)), None)

                    if script:
                        api_url = f'https://fragment.com{json.loads(pattern.search(script).group(1)).get("apiUrl")}'
                        break

                await asyncio.sleep(1)

            if not api_url:
                logger.error(f"Failed to get API URL for @{username}")
                return False

            # Check username
            params = {
                'query': username,
                'method': 'searchAuctions',
                'type': 'usernames'
            }

            response = await self._make_request('POST', api_url, data=params)
            if not response:
                return False

            data = await response.json()

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

    async def batch_check(self, usernames: list, batch_size: int = 4) -> list:
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

                # Delay between batches
                if i + batch_size < len(usernames):
                    await asyncio.sleep(2)  # Increased delay between batches

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