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

# Global rate limit semaphore - increased for more concurrent requests
GLOBAL_SEMAPHORE = asyncio.Semaphore(30)  # Maximum 30 concurrent requests total

class TelegramUsernameChecker:
    def __init__(self):
        self.session = aiohttp.ClientSession()
        self.rate_semaphore = asyncio.Semaphore(5)  # Increased from 3 to 5
        self.last_request_time = 0
        self.base_delay = 1  # Reduced delay from 3 to 1 second
        self._cache = {}  # Simple cache for username results
        self._cache_ttl = 300  # Cache TTL in seconds (5 minutes)
        self._last_check_time = time.time()
        self._check_count = 0

        # Get API credentials
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")

        if not all([self.api_id, self.api_hash]):
            logger.warning("Telegram API credentials not found. Some features may be limited.")

    async def _get_cached_result(self, username: str) -> bool:
        """Get cached result if available and not expired"""
        if username in self._cache:
            result, timestamp = self._cache[username]
            if timestamp + self._cache_ttl > time.time():
                return result
            del self._cache[username]
        return None

    def _cache_result(self, username: str, result: bool) -> None:
        """Cache username check result"""
        self._cache[username] = (result, time.time())

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

    async def check_fragment_api(self, username, count=6):
        """Check username availability using Fragment API with improved timeout"""
        try:
            # Add timeout for entire operation
            async with asyncio.timeout(30):  # 30 second total timeout
                current_time = time.time()
                time_since_last = current_time - self._last_check_time
                self._check_count += 1
                logger.info(f"Starting check #{self._check_count} for @{username} (Time since last check: {time_since_last:.2f}s)")
                self._last_check_time = current_time

                # Check banned status first with high accuracy
                try:
                    async with self.session.get(f'https://t.me/{username}') as response:
                        page_text = await response.text()

                        # Multiple indicators untuk status banned
                        banned_indicators = [
                            "This account has been banned",
                            "was banned by Telegram",
                            "banned for violating",
                            "account has been deleted",
                            "account is no longer available",
                            "account has been terminated",
                            "This account has been restricted",
                            "This account has been terminated",
                            "has been banned",
                            "was banned by the Telegram team"
                        ]

                        # Check multiple indicators dengan retry
                        for retry in range(3):  # Increase retries to 3
                            # Check semua indicators
                            is_banned = any(indicator.lower() in page_text.lower() for indicator in banned_indicators)

                            if is_banned:
                                # Double check dengan request kedua
                                await asyncio.sleep(1)  # Brief delay before second check
                                async with self.session.get(f'https://t.me/{username}') as second_response:
                                    second_text = await second_response.text()
                                    second_check = any(indicator.lower() in second_text.lower() for indicator in banned_indicators)

                                    if second_check:  # Konfirmasi banned status
                                        logger.error(f'@{username} 🚫 Username telah dibanned (Confirmed)')
                                        return None

                                    # If second check fails, wait and try one more time
                                    await asyncio.sleep(1)
                                    async with self.session.get(f'https://t.me/{username}') as third_response:
                                        third_text = await third_response.text()
                                        third_check = any(indicator.lower() in third_text.lower() for indicator in banned_indicators)

                                        if third_check:  # Final confirmation
                                            logger.error(f'@{username} 🚫 Username telah dibanned (Triple Confirmed)')
                                            return None

                            if retry < 2:  # Don't sleep on last iteration
                                await asyncio.sleep(1)  # Delay before next retry

                except Exception as e:
                    logger.error(f"Error checking banned status for {username}: {str(e)}")
                    # Jika ada error dalam pengecekan, assume username tidak tersedia
                    return None

                # Only proceed if not banned
                cached_result = await self._get_cached_result(username)
                if cached_result is not None:
                    logger.info(f"Cache hit for @{username}: {cached_result}")
                    return cached_result

                if count == 0:
                    logger.error(f"Max retries reached for @{username}")
                    return None

                async with GLOBAL_SEMAPHORE:
                    async with self.rate_semaphore:
                        # Add timeout for API URL fetch
                        async with asyncio.timeout(10):  # 10 second timeout for API URL
                            api_url = await self.get_api_url()
                            if not api_url:
                                logger.error(f'@{username} 💔 API URL not found')
                                return None

                        headers = {
                            'X-Api-Id': self.api_id,
                            'X-Api-Hash': self.api_hash
                        }
                        search_auctions = {'type': 'usernames', 'query': username, 'method': 'searchAuctions'}

                        try:
                            # Add timeout for API request
                            async with asyncio.timeout(10):  # 10 second timeout for API request
                                async with self.session.post(api_url, data=search_auctions, headers=headers) as response:
                                    if response.status == 429:
                                        delay = self.base_delay * (2 ** (6 - count))
                                        logger.warning(f"Rate limited. Waiting {delay} seconds before retry...")
                                        await asyncio.sleep(delay)
                                        return await self.check_fragment_api(username, count - 1)

                                    response_data = await response.json()

                            if not isinstance(response_data, dict):
                                logger.debug(f'@{username} 💔 Response is not a dict (too many requests. retrying {count} ...)')
                                await asyncio.sleep(self.base_delay)
                                return await self.check_fragment_api(username, count - 1)

                            if not response_data.get('html'):
                                logger.debug(f'@{username} 💔 Request to fragment API failed. Retrying {count} ...')
                                await asyncio.sleep(self.base_delay)
                                return await self.check_fragment_api(username, count - 1)

                            tree = html.fromstring(response_data.get('html'))
                            xpath_expression = '//div[contains(@class, "tm-value")]'
                            username_data = tree.xpath(xpath_expression)[:3]

                            if len(username_data) < 3:
                                logger.error(f'@{username} 💔 Not enough username data')
                                return None

                            username_tag = username_data[0].text_content()
                            status = username_data[2].text_content()
                            price = username_data[1].text_content()

                            if username_tag[1:] != username:
                                logger.error(f'@{username} 💔 Username not found in response')
                                return None

                            if price.isdigit():
                                logger.error(f'@{username} 💸 {status} on fragment for {price}💎')
                                return None

                            user_info = await self.get_user(username, api_url)

                            if not user_info:
                                logger.critical(f'{username_tag} 👤 User')
                                return None
                            elif PREMIUM_USER in user_info:
                                logger.error(f'{username_tag} 👑 Premium User')
                                return None
                            elif CHANNEL in user_info:
                                logger.error(f'{username_tag} 📢 Channel')
                                return None

                            if user_info == NOT_FOUND and status == 'Unavailable':
                                entity = await self.get_telegram_web_user(username)
                                if not entity:
                                    logger.critical(f'✅ {username_tag} Maybe Free or Reserved ✅')
                                    self._cache_result(username, True)
                                    return True
                                logger.critical(f'🔒 {username_tag} Premium User with privacy settings 🔒')
                                return None
                            elif 'Bad request' in user_info:
                                logger.error(f'{username_tag} 💔 Bad request')
                                return None
                            else:
                                logger.error(f'{username_tag} 👀 Unknown api behaviour')
                                logger.debug(f'@{username} | Unknown api behaviour | {user_info} | {status}')
                                return None

                        except asyncio.TimeoutError:
                            logger.error(f"Timeout checking @{username}")
                            if count > 1:
                                await asyncio.sleep(self.base_delay)
                                return await self.check_fragment_api(username, count - 1)
                            return None

        except asyncio.TimeoutError:
            logger.error(f"Global timeout checking @{username}")
            if count > 1:
                logger.info(f"Retrying check for @{username} ({count-1} attempts remaining)")
                await asyncio.sleep(self.base_delay)
                return await self.check_fragment_api(username, count - 1)
            return None
        except Exception as e:
            logger.error(f"Error checking @{username}: {str(e)}")
            if count > 1:
                logger.info(f"Retrying check for @{username} ({count-1} attempts remaining)")
                await asyncio.sleep(self.base_delay)
                return await self.check_fragment_api(username, count - 1)
            return None


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
        await checker.session.close()
        return bool(result)
    except Exception as e:
        logger.error(f"Error in check_telegram_username: {str(e)}")
        await checker.session.close()
        return False