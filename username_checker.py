import aiohttp
import asyncio
import logging
import re
import json
import os
import time
from lxml import html
from typing import Optional, Dict, Set

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

        # Get API credentials
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")

    async def is_banned(self, username: str) -> bool:
        """
        Multi-layer verification system for banned usernames
        """
        if username in self._banned_cache:
            logger.info(f"@{username} found in banned cache")
            return True

        try:
            async with self.session.get(f'https://t.me/{username}', allow_redirects=False) as response:
                if response.status in [403, 404, 410]:
                    self._banned_cache.add(username)
                    return True

                # Check headers for ban indicators
                headers = response.headers
                if any([
                    headers.get('X-Robot-Tag') == 'banned',
                    headers.get('X-Account-Status') == 'suspended',
                    headers.get('Location', '').endswith('/404'),
                    headers.get('X-Frame-Options') == 'DENY'
                ]):
                    self._banned_cache.add(username)
                    return True

                # Check content for ban indicators
                content = await response.text()
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
                    r"(?i)this account (no longer exists|has been deleted)"
                ]

                if any(re.search(pattern, content.lower()) for pattern in banned_patterns):
                    self._banned_cache.add(username)
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking banned status for {username}: {e}")
            return True  # Assume banned if error occurs

    async def check_fragment_api(self, username: str, retries=3) -> Optional[bool]:
        """Check username availability with Fragment API"""
        if await self.is_banned(username):
            logger.info(f'@{username} is banned.')
            return None

        try:
            async with self.session.get('https://fragment.com') as response:
                text = await response.text()
                tree = html.fromstring(text)
                scripts = tree.xpath('//script/text()')
                pattern = re.compile(r'ajInit(\{.*?});', re.DOTALL)
                script = next((script for script in scripts if pattern.search(script)), None)

                if not script:
                    logger.error(f'@{username} API URL not found')
                    return None

                api_url = f'https://fragment.com{json.loads(pattern.search(script).group(1)).get("apiUrl")}'
                search_auctions = {'type': 'usernames', 'query': username, 'method': 'searchAuctions'}

                async with self.session.post(api_url, data=search_auctions) as response:
                    if response.status == 429:  # Rate limit hit
                        if retries > 0:
                            await asyncio.sleep(self.base_delay * (4 - retries))
                            return await self.check_fragment_api(username, retries - 1)
                        return None

                    response_data = await response.json()
                    if not isinstance(response_data, dict) or not response_data.get('html'):
                        return await self.check_fragment_api(username, retries - 1)

                    tree = html.fromstring(response_data.get('html'))
                    username_data = tree.xpath('//div[contains(@class, "tm-value")]')[:3]

                    if len(username_data) < 3:
                        return None

                    username_tag = username_data[0].text_content()
                    status = username_data[2].text_content()
                    price = username_data[1].text_content()

                    if username_tag[1:] != username:
                        return None

                    if price.isdigit():
                        logger.info(f'@{username} is for sale: {price}💎')
                        return None

                    if status == 'Unavailable':
                        logger.critical(f'✅ @{username} is Available ✅')
                        return True

                    return None

        except asyncio.TimeoutError:
            logger.error(f"Timeout checking @{username}")
            return await self.check_fragment_api(username, retries - 1) if retries > 0 else None
        except Exception as e:
            logger.error(f"Error checking @{username}: {e}")
            return None

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

    username = "testusername"  # Ganti dengan username yang ingin diuji
    is_available = await checker.check_fragment_api(username)

    if is_available:
        logger.info(f"✅ Username @{username} is available!")
    else:
        logger.info(f"❌ Username @{username} is not available or banned.")

    await checker.close()


if __name__ == "__main__":
    asyncio.run(main())