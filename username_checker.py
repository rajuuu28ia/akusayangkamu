import os
import logging
import logging.handlers
import aiohttp
import asyncio
import re
import json
import time
from dotenv import load_dotenv
from lxml import html

# Load environment variables
load_dotenv()

# Set up detailed logging with rotation
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

handler = logging.handlers.RotatingFileHandler(
    'username_checker.log',
    maxBytes=2*1024*1024,  # 2MB max file size
    backupCount=1,  # Keep only 1 backup
    encoding='utf-8'
)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Constants
PREMIUM_USER = 'This account is already subscribed to Telegram Premium.'
CHANNEL = 'Please enter a username assigned to a user.'
NOT_FOUND = 'No Telegram users found.'

# Get Telegram API Credentials from .env
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not all([API_ID, API_HASH]):
    logger.error("❌ Missing required API credentials in .env file!")
    exit(1)
else:
    logger.info("✅ API credentials loaded successfully")


class TelegramUsernameChecker:
    def __init__(self):
        """Initialize checker with improved rate limiting"""
        self.session = aiohttp.ClientSession()
        self.rate_semaphore = asyncio.Semaphore(40)
        self.request_times = []
        self.max_requests_per_window = 25  # Maximum requests per time window
        self.time_window = 30  # Time window in seconds
        self.base_delay = 0.5  # Reduced base delay

        # Adaptive delay calculation
        self._last_request_time = time.time()
        self._request_count = 0
        self._window_start = time.time()

        # Cleanup old logs on initialization
        self._cleanup_old_logs()

    def _cleanup_old_logs(self):
        """Clean up old log files"""
        try:
            log_files = [f for f in os.listdir('.') if f.startswith('username_checker.log')]
            if len(log_files) > 2:  # Keep only current and one backup
                for old_log in sorted(log_files, key=os.path.getctime)[:-2]:
                    try:
                        os.remove(old_log)
                        logger.info(f"Removed old log file: {old_log}")
                    except Exception as e:
                        logger.error(f"Error removing log {old_log}: {e}")
        except Exception as e:
            logger.error(f"Error during log cleanup: {e}")

    async def _calculate_adaptive_delay(self):
        """Calculate adaptive delay based on recent request patterns"""
        current_time = time.time()

        # Clean old request times
        self.request_times = [t for t in self.request_times if current_time - t < self.time_window]

        # Add current request
        self.request_times.append(current_time)

        if len(self.request_times) >= self.max_requests_per_window:
            # Calculate required delay to stay within rate limits
            oldest_request = self.request_times[0]
            time_diff = current_time - oldest_request
            if time_diff < self.time_window:
                return (self.time_window - time_diff) / self.max_requests_per_window + 0.2 #Simplified randomness

        return self.base_delay

    async def check_fragment_api(self, username: str, retries=3):
        """Check username availability"""
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$', username):
            logger.info(f'@{username} invalid format')
            return None

        async with self.rate_semaphore:
            delay = await self._calculate_adaptive_delay()
            await asyncio.sleep(delay)
            for attempt in range(retries):
                try:
                    async with self.session.get('https://fragment.com') as response:
                        if response.status != 200:
                            logger.warning(f'Fragment API status {response.status}, attempt {attempt + 1}')
                            await asyncio.sleep(delay * (attempt + 1))
                            continue

                        text = await response.text()
                        tree = html.fromstring(text)
                        scripts = tree.xpath('//script/text()')
                        pattern = re.compile(r'ajInit\((\{.*?})\);', re.DOTALL)

                        for script in scripts:
                            match = pattern.search(script)
                            if match:
                                data = json.loads(match.group(1))
                                api_url = f'https://fragment.com{data.get("apiUrl")}'
                                return await self._check_username_availability(api_url, username)

                except asyncio.TimeoutError:
                    logger.warning(f"Timeout on attempt {attempt + 1} for @{username}")
                except Exception as e:
                    logger.error(f"Error checking @{username}: {e}")

                if attempt < retries - 1:
                    await asyncio.sleep(delay * (attempt + 1))

            return None

    async def _check_username_availability(self, api_url: str, username: str):
        """Internal method to check username availability"""
        search_auctions = {'type': 'usernames', 'query': username, 'method': 'searchAuctions'}

        try:
            async with self.session.post(api_url, data=search_auctions) as response:
                if response.status != 200:
                    return None

                response_data = await response.json()
                if 'html' not in response_data:
                    return None

                tree = html.fromstring(response_data['html'])
                username_data = tree.xpath('//div[contains(@class, "tm-value")]')[:3]

                if len(username_data) < 3:
                    return None

                status = username_data[2].text_content()
                price = username_data[1].text_content()

                if price.isdigit():
                    return None

                if status == 'Unavailable':
                    return await self._verify_unavailable(username)

                return None

        except Exception as e:
            logger.error(f"Error processing response for @{username}: {e}")
            return None

    async def _verify_unavailable(self, username: str):
        """Verify if username is truly unavailable"""
        try:
            async with self.session.get(f'https://t.me/{username}') as response:
                if response.status in [403, 404, 410]:
                    return True
                text = await response.text()
                return "If you have Telegram, you can contact" not in text
        except Exception as e:
            logger.error(f"Error verifying @{username}: {e}")
            return False

    async def close(self):
        """Cleanup resources"""
        if not self.session.closed:
            await self.session.close()

async def batch_check_usernames(usernames: list, batch_size: int = 10) -> dict:
    """Process usernames in optimized batches"""
    checker = TelegramUsernameChecker()
    results = {}
    total_usernames = len(usernames)

    try:
        for i in range(0, total_usernames, batch_size):
            batch = usernames[i:i + batch_size]
            tasks = [checker.check_fragment_api(username) for username in batch]

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for username, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Error in batch for @{username}: {result}")
                    continue
                if result is not None:
                    results[username] = result

            # Adaptive delay between batches
            if i + batch_size < total_usernames:
                delay = 0.5 + (len(batch) / 20)  # Base delay + adjustment for batch size
                await asyncio.sleep(delay)

    except Exception as e:
        logger.error(f"Batch processing error: {e}")
    finally:
        await checker.close()

    return results

async def main():
    usernames = ["test1", "test2", "test3", "test4", "test5"]
    results = await batch_check_usernames(usernames, batch_size=5)
    for username, available in results.items():
        status = "available" if available else "unavailable"
        logger.info(f"Username @{username} is {status}")

if __name__ == "__main__":
    asyncio.run(main())