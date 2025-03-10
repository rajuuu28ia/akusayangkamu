from pyrogram import Client

# Masukkan API ID dan API Hash kamu
API_ID = 28320430  # Ganti dengan API ID kamu
API_HASH = "2a15fdaf244a9f3ec4af7ce0501f9db8"  # Ganti dengan API Hash kamu

# Buat session kedua
client = Client("session2", api_id=API_ID, api_hash=API_HASH)

async def main():
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

# Jalankan proses
client.run(main())