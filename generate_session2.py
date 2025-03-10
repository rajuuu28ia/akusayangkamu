
import asyncio
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Gunakan API ID dan API Hash yang konsisten
API_ID = 23878472
API_HASH = "1cc826615a9cba49bad596370f7823cc"

async def main():
    # Buat client dengan StringSession
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    
    await client.start()
    
    # Login dengan nomor telepon jika belum login
    if not await client.is_user_authorized():
        phone = input("Masukkan nomor telepon akun dummy (format: +628xxx): ")
        await client.send_code_request(phone)
        code = input("Masukkan kode verifikasi yang dikirim: ")
        await client.sign_in(phone, code)
    
    print("✅ Session kedua berhasil dibuat!")

    # Ambil session string
    session_string = client.session.save()

    # Simpan ke file "session2.txt"
    with open("session2.txt", "w") as file:
        file.write(session_string)

    print("💾 Session string kedua berhasil disimpan ke session2.txt")
    print("🔑 Session String kedua:\n", session_string)
    
    await client.disconnect()

# Jalankan fungsi asynchronous
if __name__ == "__main__":
    asyncio.run(main())
