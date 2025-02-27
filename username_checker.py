import aiohttp
import asyncio
import logging
import re
import json
from lxml import html
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
        self.session = aiohttp.ClientSession()
        # Limit concurrent requests to 5
        self.rate_semaphore = asyncio.Semaphore(5)
        # Store last request time for rate limiting
        self.last_request_time = 0
        # Initial delay for exponential backoff
        self.base_delay = 2

    async def get_api_url(self):
        """Get Fragment API URL"""
        async with self.rate_semaphore:
            async with self.session.get('https://fragment.com') as response:
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
        """Check user status via Fragment API"""
        async with self.rate_semaphore:
            search_recipient_params = {'query': username, 'months': 3, 'method': 'searchPremiumGiftRecipient'}
            async with self.session.post(api_url, data=search_recipient_params) as response:
                if response.status == 429:
                    delay = self.base_delay * (2 ** (6 - count))  # Exponential backoff
                    logger.warning(f"Rate limited. Waiting {delay} seconds before retry...")
                    await asyncio.sleep(delay)
                    return await self.get_user(username, api_url, count - 1)

                data = await response.json()
                error = data.get('error')
                return error

    async def get_telegram_web_user(self, username):
        """Check username via Telegram web"""
        async with self.rate_semaphore:
            async with self.session.get(f'https://t.me/{username}') as response:
                if response.status == 429:
                    delay = self.base_delay * 2  # Simple backoff for Telegram web
                    logger.warning(f"Rate limited by Telegram. Waiting {delay} seconds...")
                    await asyncio.sleep(delay)
                    return await self.get_telegram_web_user(username)

                text = await response.text()
                return f"You can contact @{username} right away." in text

    async def check_fragment_api(self, username, count=6):
        """Check username availability using Fragment API"""
        if count == 0:
            return

        async with self.rate_semaphore:
            api_url = await self.get_api_url()
            if not api_url:
                logger.error(f'@{username} 💔 API URL not found')
                return

            search_auctions = {'type': 'usernames', 'query': username, 'method': 'searchAuctions'}
            try:
                async with self.session.post(api_url, data=search_auctions) as response:
                    if response.status == 429:
                        delay = self.base_delay * (2 ** (6 - count))  # Exponential backoff
                        logger.warning(f"Rate limited. Waiting {delay} seconds before retry...")
                        await asyncio.sleep(delay)
                        return await self.check_fragment_api(username, count - 1)

                    response_data = await response.json()

                    if not isinstance(response_data, dict):
                        logger.debug(f'@{username} 💔 Response is not a dict (too many requests. retrying {count} ...)')
                        await asyncio.sleep(10)
                        return await self.check_fragment_api(username, count - 1)

                    if not response_data.get('html'):
                        logger.debug(f'@{username} 💔 Request to fragment API failed. Retrying {count} ...')
                        await asyncio.sleep(6)
                        return await self.check_fragment_api(username, count - 1)

                    tree = html.fromstring(response_data.get('html'))
                    xpath_expression = '//div[contains(@class, "tm-value")]'
                    username_data = tree.xpath(xpath_expression)[:3]

                    if len(username_data) < 3:
                        logger.error(f'@{username} 💔 Not enough username data')
                        return

                    username_tag = username_data[0].text_content()
                    status = username_data[2].text_content()
                    price = username_data[1].text_content()

                    if username_tag[1:] != username:
                        logger.error(f'@{username} 💔 Username not found in response')
                        return

                    if price.isdigit():
                        logger.error(f'@{username} 💸 {status} on fragment for {price}💎')
                        return

                    user_info = await self.get_user(username, api_url)

                    if not user_info:
                        logger.critical(f'{username_tag} 👤 User')
                        return
                    elif PREMIUM_USER in user_info:
                        logger.error(f'{username_tag} 👑 Premium User')
                        return
                    elif CHANNEL in user_info:
                        logger.error(f'{username_tag} 📢 Channel')
                        return

                    if user_info == NOT_FOUND and status == 'Unavailable':
                        entity = await self.get_telegram_web_user(username)
                        if not entity:
                            logger.critical(f'✅ {username_tag} Maybe Free or Reserved ✅')
                            return True
                        logger.critical(f'🔒 {username_tag} Premium User with privacy settings 🔒')
                        return
                    elif 'Bad request' in user_info:
                        logger.error(f'{username_tag} 💔 Bad request')
                        return
                    else:
                        logger.error(f'{username_tag} 👀 Unknown api behaviour')
                        logger.debug(f'@{username} | Unknown api behaviour | {user_info} | {status}')

            except Exception as e:
                logger.error(f"Error checking username {username}: {str(e)}")
                if count > 1:  # Retry on error
                    await asyncio.sleep(5)
                    return await self.check_fragment_api(username, count - 1)
                return False

async def check_telegram_username(username: str) -> bool:
    """
    Check if a Telegram username is available
    Returns True if available, False if taken
    """
    # Validate username format first
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