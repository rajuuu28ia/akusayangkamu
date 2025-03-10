import asyncio
import os
import logging
from dotenv import load_dotenv
from pyrogram_bot import startup

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("PyrogramMain")

# Load environment variables
load_dotenv()

if __name__ == "__main__":
    # Check for required environment variables
    required_vars = ["API_ID", "API_HASH", "BOT_TOKEN"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set these variables in the .env file")
        exit(1)
    
    # Run the bot
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(startup())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error running bot: {str(e)}")
    finally:
        loop.close()