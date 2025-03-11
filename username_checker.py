import aiohttp
import asyncio
import logging
import logging.handlers
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

# Set up detailed logging with rotation
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Rotating file handler with size limit
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

# Telegram API Credentials
API_ID = "28320430"
API_HASH = "2a15fdaf244a9f3ec4af7ce0501f9db8"

class TelegramUsernameChecker:
    def __init__(self):
        """Initialize checker with improved rate limiting for 40 concurrent users"""
        self.session = aiohttp.ClientSession()
        self.rate_semaphore = asyncio.Semaphore(40)  # Increased to 40 concurrent users
        self.request_times = []
        self.max_requests_per_window = 25  # Maximum requests per time window
        self.time_window = 30  # Time window in seconds
        self.base_delay = 0.5  # Reduced base delay

        # Adaptive delay calculation
        self._last_request_time = time.time()
        self._request_count = 0
        self._window_start = time.time()

        # API credentials
        self.api_id = API_ID
        self.api_hash = API_HASH

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
                return (self.time_window - time_diff) / self.max_requests_per_window + random.uniform(0.1, 0.3)

        return self.base_delay

    async def check_fragment_api(self, username: str, retries=3) -> Optional[bool]:
        """Enhanced check with improved rate limiting and retries"""
        async with self.rate_semaphore:
            delay = await self._calculate_adaptive_delay()
            await asyncio.sleep(delay)

            for attempt in range(retries):
                try:
                    # Basic validation
                    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$', username):
                        logger.info(f'@{username} invalid format')
                        return None

                    async with self.session.get('https://fragment.com') as response:
                        if response.status != 200:
                            logger.warning(f'Fragment API status {response.status}, attempt {attempt + 1}')
                            await asyncio.sleep(delay * (attempt + 1))
                            continue

                        text = await response.text()
                        api_url = self._extract_api_url(text)
                        if not api_url:
                            continue

                        result = await self._check_username_availability(api_url, username)
                        if result is not None:
                            return result

                except asyncio.TimeoutError:
                    logger.warning(f"Timeout on attempt {attempt + 1} for @{username}")
                except Exception as e:
                    logger.error(f"Error checking @{username}: {e}")

                if attempt < retries - 1:
                    await asyncio.sleep(delay * (attempt + 1))

            return None

    def _extract_api_url(self, text: str) -> Optional[str]:
        """Extract API URL from Fragment page"""
        try:
            tree = html.fromstring(text)
            scripts = tree.xpath('//script/text()')
            pattern = re.compile(r'ajInit\((\{.*?})\);', re.DOTALL)

            for script in scripts:
                match = pattern.search(script)
                if match:
                    data = json.loads(match.group(1))
                    return f'https://fragment.com{data.get("apiUrl")}'

            return None
        except Exception as e:
            logger.error(f"Error extracting API URL: {e}")
            return None

    async def _check_username_availability(self, api_url: str, username: str) -> Optional[bool]:
        """Check username availability with enhanced error handling"""
        search_auctions = {'type': 'usernames', 'query': username, 'method': 'searchAuctions'}

        async with self.session.post(api_url, data=search_auctions) as response:
            if response.status == 429:  # Rate limit
                return None

            try:
                response_data = await response.json()
                if not isinstance(response_data, dict) or 'html' not in response_data:
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

    async def _verify_unavailable(self, username: str) -> bool:
        """Verify unavailable status with t.me check"""
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