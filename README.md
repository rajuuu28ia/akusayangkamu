# Telegram Username Generator Bot

Bot Telegram untuk menghasilkan dan memeriksa variasi username dengan fitur canggih untuk eksplorasi username yang mulus.

## Fitur Utama

- Generate variasi username otomatis
- Cek ketersediaan username secara real-time
- Anti-spam & rate limit protection
- Mendukung hingga 40 pengguna bersamaan
- Sistem pembersihan otomatis untuk menghemat ruang

## Cara Setup

1. Clone repository ini
```bash
git clone https://github.com/rajuuu28ia/akusamakamu.git
cd akusamakamu
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Setup konfigurasi:
   - Copy `config.example.py` ke `config.py`
   - Update nilai-nilai di `config.py` dengan kredensial Anda:
     - Dapatkan `API_ID` dan `API_HASH` dari https://my.telegram.org/apps
     - Dapatkan `BOT_TOKEN` dari @BotFather
     - Set `CHANNEL_ID` dan `INVITE_LINK` untuk channel Anda

4. Jalankan bot:
```bash
python bot.py
```

## Penggunaan

1. Start bot dengan command `/start`
2. Join channel yang diperlukan
3. Gunakan command `/allusn [username]` untuk menghasilkan variasi
4. Hasil akan ditampilkan dan dihapus otomatis setelah 5 menit

## Catatan Penting

- Username yang dihasilkan akan dihapus setelah 5 menit
- Hindari spam untuk mencegah pemblokiran
- Simpan hasil generate yang Anda inginkan segera

## Dependencies

- Python 3.11+
- aiogram
- aiohttp
- flask
- lxml
- python-dotenv
- telethon

## Kontribusi

Silakan buat issue atau pull request jika Anda ingin berkontribusi pada proyek ini.

## License

[MIT License](LICENSE)# akusamakamu
