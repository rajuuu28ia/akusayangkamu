from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Masukkan API ID & API HASH
API_ID = 23878472
API_HASH = "1cc826615a9cba49bad596370f7823cc"

# Buat client dengan StringSession (bukan SQLite)
client = TelegramClient(StringSession(), API_ID, API_HASH)

async def main():
    await client.start()
    print("✅ Session berhasil dibuat!")

    # Ambil session string
    session_string = client.session.save()

    # Simpan ke file "session.txt"
    with open("session.txt", "w") as file:
        file.write(session_string)

    print("💾 Session string berhasil disimpan ke session.txt")
    print("🔑 Session String:\n", session_string)

with client:
    client.loop.run_until_complete(main())