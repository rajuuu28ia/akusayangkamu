
import asyncio
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os

# Gunakan API ID dan API HASH yang konsisten
API_ID = 23878472
API_HASH = "1cc826615a9cba49bad596370f7823cc"

async def main():
    # Buat client dengan StringSession
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    
    await client.start()
    
    # Login dengan nomor telepon jika belum login
    if not await client.is_user_authorized():
        phone = input("Please enter your phone (or bot token): ")
        await client.send_code_request(phone)
        code = input("Please enter the code you received: ")
        await client.sign_in(phone, code)
        print(f"Signed in successfully as {(await client.get_me()).first_name}; remember to not break the ToS or you will risk an account ban!")
    
    # Ambil session string
    session_string = client.session.save()

    # Simpan ke file "session2.txt"
    with open("session2.txt", "w") as file:
        file.write(session_string)

    print("✅ Session kedua berhasil dibuat!")
    print("💾 Session string kedua berhasil disimpan ke session2.txt")
    print("🔑 Session String kedua:\n", session_string)
    print("\nPenting: Tambahkan session string ini ke Secrets dengan nama TELEGRAM_SESSION_STRING_2")
    
    await client.disconnect()

# Jalankan fungsi asynchronous
if __name__ == "__main__":
    asyncio.run(main())
