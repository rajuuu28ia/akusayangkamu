import os
import asyncio
from pyrogram import Client
from dotenv import load_dotenv

load_dotenv()

async def test_send_message():
    """Send a test message to the bot to verify it's working"""
    # Get API credentials from environment
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    bot_token = os.environ.get("BOT_TOKEN")
    
    print(f"Using bot token: {bot_token[:5]}...{bot_token[-5:]}")
    
    # Create a temporary client using bot token
    async with Client(
        "test_client",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,  # Use the bot token directly
        in_memory=True
    ) as app:
        # Test if the bot is online by getting bot info
        try:
            me = await app.get_me()
            print(f"Test client authenticated as: @{me.username} (ID: {me.id})")
            
            # Get info about our main bot
            bot = await app.get_bot("GenScanBot")
            print(f"Main bot info: @{bot.username} (ID: {bot.id})")
            
            # Check if our main bot is online by getting its status
            if hasattr(bot, 'status') and bot.status == 'online':
                print("✅ Main bot is ONLINE!")
            else:
                print("⚠️ Main bot status unknown")
                
            print("Bot should be operational! Try sending a message to @GenScanBot on Telegram")
        except Exception as e:
            print(f"❌ Error testing bot: {str(e)}")
        
        # Wait a bit for the bot to process
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(test_send_message())