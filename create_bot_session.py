import os
import asyncio
import logging
from pyrogram import Client
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BotSessionGenerator")

# Load environment variables
load_dotenv()

# Get API credentials
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_NAME = "bot_session_generator"  # Just for temporary use

async def generate_bot_session():
    """
    Generate a Pyrogram session string for a bot
    This doesn't require interactive input
    """
    if not API_ID or not API_HASH or not BOT_TOKEN:
        logger.error("API_ID, API_HASH, and BOT_TOKEN must be set in the .env file")
        return None
        
    try:
        print("\n====== Pyrogram Bot Session String Generator ======")
        print("This will create a new session string for your bot.")
        print("=================================================\n")
        
        # Create a temporary client for the bot
        client = Client(
            SESSION_NAME,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True
        )
        
        # Start the client
        await client.start()
        
        # Get bot info
        me = await client.get_me()
        print(f"\n✅ Sukses masuk sebagai: @{me.username} (ID: {me.id})")
        
        # Export session string
        session_string = await client.export_session_string()
        
        # Save to file
        with open("bot_session.txt", "w") as f:
            f.write(session_string)
            
        print("\n✅ Session string bot berhasil dihasilkan!")
        print("✅ Session string disimpan ke bot_session.txt")
        print("\n📋 Session String Bot:")
        print("==========================================")
        print(session_string)
        print("==========================================")
        
        # Stop client
        await client.stop()
        
        return session_string
        
    except Exception as e:
        logger.error(f"Failed to create bot session: {str(e)}")
        print(f"\n❌ Error: {str(e)}")
        return None

if __name__ == "__main__":
    # Run the async function
    result = asyncio.run(generate_bot_session())
    
    if result:
        print("\n✅ Bot session string berhasil dibuat!")
    else:
        print("\n❌ Gagal menghasilkan bot session string.")
        print("⚠️ Pastikan API_ID, API_HASH dan BOT_TOKEN sudah diatur dengan benar di file .env.")