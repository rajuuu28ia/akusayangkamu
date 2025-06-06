import os
import sys
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

# Ambil API ID dan API HASH sebagai argumen command line
if len(sys.argv) != 3:
    print("Penggunaan: python generate_telethon_session.py <API_ID> <API_HASH>")
    sys.exit(1)

API_ID = sys.argv[1]
API_HASH = sys.argv[2]

async def generate_session_string():
    # Buat client untuk mendapatkan session string
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    
    print("Menghubungkan ke Telegram...")
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Anda perlu login ke akun Telegram.")
        phone = input("Masukkan nomor telepon Anda (format internasional, contoh: +62812345678): ")
        await client.send_code_request(phone)
        code = input("Masukkan kode verifikasi yang dikirim ke Telegram Anda: ")
        await client.sign_in(phone, code)
    
    # Dapatkan session string
    session_string = client.session.save()
    print("\n\nSESSION STRING ANDA (simpan dengan aman, jangan bagikan):")
    print("========================================================")
    print(session_string)
    print("========================================================")
    print("\nGunakan string ini sebagai nilai untuk TELEGRAM_SESSION_STRING di environment variables.")
    
    await client.disconnect()

if __name__ == "__main__":
    # Jalankan fungsi asynchronous
    asyncio.run(generate_session_string())