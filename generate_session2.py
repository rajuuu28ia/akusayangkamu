
from pyrogram import Client
import asyncio

# Gunakan API ID dan API Hash yang sama dengan generate_session.py
API_ID = 23878472  # Konsisten dengan generate_session.py
API_HASH = "1cc826615a9cba49bad596370f7823cc"  # Konsisten dengan generate_session.py

async def main():
    # Buat client untuk session kedua
    client = Client("session2", api_id=API_ID, api_hash=API_HASH)
    
    await client.start()
    print("✅ Session kedua berhasil dibuat!")

    # Generate session string
    session_string = await client.export_session_string()
    
    # Simpan ke file session2.txt
    with open("session2.txt", "w") as file:
        file.write(session_string)

    print("📂 Session string berhasil disimpan ke session2.txt")
    print("🔑 Session String:\n", session_string)

    await client.stop()

if __name__ == "__main__":
    # Jalankan fungsi asynchronous
    asyncio.run(main())
