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
logger = logging.getLogger("SessionGenerator")

# Load environment variables
load_dotenv()

# Get API credentials
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "dummy_session_generator"  # Just for temporary use

async def generate_session():
    """
    Generate a Pyrogram session string
    This will interactively prompt for phone number and verification code
    """
    if not API_ID or not API_HASH:
        logger.error("API_ID and API_HASH must be set in the .env file")
        return None
        
    try:
        print("\n====== Pyrogram Session String Generator ======")
        print("This will create a new session string for your account.")
        print("You'll need to enter your phone number and verification code.")
        print("=================================================\n")
        
        # Create a temporary client
        client = Client(
            SESSION_NAME,
            api_id=API_ID,
            api_hash=API_HASH,
            in_memory=True
        )
        
        # Start the client
        await client.start()
        
        # Get current user
        me = await client.get_me()
        print(f"\n✅ Sukses masuk sebagai: {me.first_name} (ID: {me.id})")
        
        # Export session string
        session_string = await client.export_session_string()
        
        # Save to file
        with open("session.txt", "w") as f:
            f.write(session_string)
            
        print("\n✅ Session string berhasil dihasilkan!")
        print("✅ Session string disimpan ke session.txt")
        print("\n📋 Session String:")
        print("==========================================")
        print(session_string)
        print("==========================================")
        print("\n⚠️ PENTING: Simpan session string ini dengan aman!")
        print("🔒 Jangan bagikan session string ini dengan siapapun!")
        
        # Stop client
        await client.stop()
        
        return session_string
        
    except Exception as e:
        logger.error(f"Failed to create session: {str(e)}")
        print(f"\n❌ Error: {str(e)}")
        return None

if __name__ == "__main__":
    # Run the async function
    result = asyncio.run(generate_session())
    
    if result:
        # Update .env file
        try:
            env_file = ".env"
            with open(env_file, "r") as f:
                lines = f.readlines()
            
            with open(env_file, "w") as f:
                for line in lines:
                    if line.startswith("TELEGRAM_SESSION_STRING="):
                        f.write(f"TELEGRAM_SESSION_STRING={result}\n")
                    else:
                        f.write(line)
            
            print("\n✅ File .env berhasil diperbarui dengan session string baru!")
        except Exception as e:
            print(f"\n❌ Gagal memperbarui file .env: {str(e)}")
            print("⚠️ Silakan perbarui TELEGRAM_SESSION_STRING di file .env secara manual.")
    else:
        print("\n❌ Gagal menghasilkan session string.")
        print("⚠️ Pastikan API_ID dan API_HASH sudah diatur dengan benar di file .env.")