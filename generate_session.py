import os
import asyncio
from pyrogram import Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API credentials from environment
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

async def main():
    """Generate session string using Pyrogram"""
    print("📱 Memulai proses pembuatan session string...")
    
    # Create a new client
    async with Client(
        "my_account",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True
    ) as app:
        # Get the session string
        session_string = await app.export_session_string()
        
        # Save to file
        with open("session.txt", "w") as file:
            file.write(session_string)
        
        print("\n✅ Session berhasil dibuat!")
        print("💾 Session string berhasil disimpan ke session.txt")
        print("\n🔑 Session String:")
        print("──────────────────────")
        print(session_string)
        print("──────────────────────")
        print("\n⚠️ PENTING: Jangan bagikan session string ini kepada siapapun!")
        print("🔒 Session string ini memberikan akses penuh ke akun Telegram Anda.")

if __name__ == "__main__":
    # Run the async function
    asyncio.run(main())