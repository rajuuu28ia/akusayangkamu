import asyncio
import os
import logging
from pyrogram import Client
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DummySessionGenerator")

# Load environment variables
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("DUMMY_SESSION", "dummy_session")

async def generate_session():
    """
    Generate a Pyrogram session for the dummy account
    This will create a new session file for future use
    """
    if not API_ID or not API_HASH:
        logger.error("API_ID and API_HASH must be set in the .env file")
        return False
        
    try:
        logger.info(f"Creating Pyrogram session: {SESSION_NAME}")
        async with Client(SESSION_NAME, API_ID, API_HASH) as app:
            me = await app.get_me()
            logger.info(f"Session created successfully for {me.first_name} ({me.id})")
            return True
    except Exception as e:
        logger.error(f"Failed to create session: {str(e)}")
        return False

if __name__ == "__main__":
    # Run the async function
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(generate_session())
    
    if result:
        print("Session generated successfully!")
    else:
        print("Failed to generate session.")