import aiohttp
import asyncio
import logging
import re

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_telegram_username(username: str) -> bool:
    """
    Check if a Telegram username is available
    Returns True if available, False if taken
    """
    # Validate username format first
    if not re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
        logger.warning(f"Invalid username format: {username}")
        return False

    async with aiohttp.ClientSession() as session:
        try:
            # Using Telegram's public bot API endpoint
            url = f"https://t.me/{username}"
            logger.info(f"Checking username availability: {username}")

            async with session.get(url) as response:
                status = response.status
                logger.info(f"Response status for {username}: {status}")

                if status == 404:
                    logger.info(f"Username {username} is available")
                    return True
                elif status == 200:
                    logger.info(f"Username {username} is taken")
                    return False
                else:
                    logger.warning(f"Unexpected status code {status} for {username}")
                    return False

        except aiohttp.ClientError as e:
            logger.error(f"Network error checking {username}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking {username}: {str(e)}")
            return False