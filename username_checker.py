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

    async def is_banned(self, username: str) -> bool:
        """
        Enhanced multi-layer verification system for banned usernames
        with improved pattern matching and caching
        """
        # Check cache first
        if username in self._banned_cache:
            logger.info(f"@{username} found in banned cache")
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
        """Check username availability with Fragment API"""
        # First check if username is banned
        if await self.is_banned(username):
            logger.info(f'@{username} is banned or restricted.')
            return None

        # Add to banned cache if username contains suspicious patterns
        suspicious_patterns = [
            r'.*support.*', r'.*admin.*', r'.*help.*', r'.*service.*',
            r'.*official.*', r'.*team.*', r'.*staff.*', r'.*mod.*'
        ]
        if any(re.match(pattern, username.lower()) for pattern in suspicious_patterns):
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
                                        # Additional check for banned or taken
                                        if await self.is_banned(username):
                                            logger.info(f'@{username} is banned (final t.me check)')
                                            return None

                                        logger.info(f'✅ @{username} is Available ✅')
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