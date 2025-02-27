import asyncio
import os
import re
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from username_generator import UsernameGenerator
from username_checker import check_telegram_username, TelegramUsernameChecker
from username_store import UsernameStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get token from environment variable with fallback
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
CHANNEL_ID = "-100xo6vdaZALL9jN2Zl"  # Perlu ditambahkan "-100" untuk channel private
CHANNEL_LINK = "https://t.me/+xo6vdaZALL9jN2Zl"

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# User locks to prevent spam
user_locks = {}

# Username store
username_store = UsernameStore()

# Generation methods mapping
METHODS = {
    "ganhur": UsernameGenerator.ganhur,
    "canon": UsernameGenerator.canon,
    "sop": UsernameGenerator.sop,
    "scanon": UsernameGenerator.scanon,
    "switch": UsernameGenerator.switch,
    "kurkuf": UsernameGenerator.kurkuf
}

async def check_subscription(user_id: int) -> bool:
    """Check if user is subscribed to the channel"""
    try:
        logger.info(f"Checking subscription for user {user_id}")
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        is_member = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        logger.info(f"User {user_id} subscription status: {member.status}, is_member: {is_member}")
        return is_member
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id}: {str(e)}")
        return False

async def generate_and_check(base_name: str, method: str) -> list:
    """Generate usernames and check their availability"""
    generator_func = METHODS[method]
    all_usernames = generator_func(base_name)
    results = []

    # Filter out previously generated usernames
    usernames = [
        username for username in all_usernames 
        if not username_store.is_generated(base_name, username)
    ]

    # Rate limiting - process in smaller batches
    batch_size = 5
    for i in range(0, len(usernames), batch_size):
        batch = usernames[i:i + batch_size]

        # Create a single checker instance for the batch
        checker = TelegramUsernameChecker()
        try:
            for username in batch:
                result = await checker.check_fragment_api(username.lower())
                # Store generated username
                username_store.add_username(base_name, username)
                # Don't need to append status since logger.critical already shows it
                if result is not None:
                    results.append(username)

            # Add delay between batches - increased to 3 seconds
            if i + batch_size < len(usernames):
                await asyncio.sleep(3)
        finally:
            await checker.session.close()

    return results

@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    help_text = """
🤖 Bot Generator Username Telegram

⚠️ Untuk menggunakan bot ini:
1️⃣ Join channel kami terlebih dahulu:
   {channel_link}
2️⃣ Setelah join, gunakan command berikut:

/ganhur [username] - Substitusi huruf acak
/canon [username] - Tukar huruf i/l
/sop [username] - Tambah karakter acak
/scanon [username] - Tambah 's'
/switch [username] - Tukar karakter bersebelahan
/kurkuf [username] - Hapus karakter acak

Contoh: /ganhur username

⚠️ Note: 
- Username yang sudah di-generate akan disimpan dan tidak akan muncul lagi dalam 1 jam ke depan
- Bot akan menghapus data username yang tersimpan setelah 1 jam
""".format(channel_link=CHANNEL_LINK)
    await message.reply(help_text)

@dp.message(Command("ganhur", "canon", "sop", "scanon", "switch", "kurkuf"))
async def handle_generation(message: Message):
    user_id = message.from_user.id

    # Check channel subscription
    if not await check_subscription(user_id):
        await message.reply(
            "⚠️ Untuk menggunakan bot ini, Anda harus join channel kami terlebih dahulu:\n"
            f"{CHANNEL_LINK}\n\n"
            "Setelah join, silakan coba command kembali."
        )
        return

    # Check if user is locked
    if user_id in user_locks:
        await message.reply("⏳ Tunggu proses sebelumnya selesai dulu!")
        return

    # Parse command
    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Gunakan format: /command username")
        return

    command = args[0][1:]  # Remove the '/' prefix
    base_name = args[1].lower()

    # Validate username
    if len(base_name) < 5:
        await message.reply("⚠️ Username terlalu pendek! Minimal 5 karakter.")
        return
    elif len(base_name) > 32:
        await message.reply("⚠️ Username terlalu panjang! Maksimal 32 karakter.")
        return
    elif not re.match(r'^[a-zA-Z0-9_]+$', base_name):
        await message.reply("⚠️ Username hanya boleh mengandung huruf, angka, dan underscore.")
        return

    # Lock user
    user_locks[user_id] = True

    try:
        # Send warning message
        warning_msg = await message.reply(
            "⚠️ <b>Peringatan</b>\n"
            "- Username yang sudah di-generate akan disimpan\n"
            "- Username tersimpan tidak akan muncul lagi dalam hasil generate\n"
            "- Data username akan dihapus otomatis setelah 1 jam\n\n"
            f"🔄 Generating '{command}' dari '{base_name}'...\n"
            "⏳ Mohon tunggu, sedang mengecek ketersediaan username..."
        )

        # Generate and check usernames - the logger will automatically display results
        available_usernames = await generate_and_check(base_name, command)

        if available_usernames:
            await warning_msg.edit_text(
                "✅ Generasi username selesai!\n\n"
                "Username yang mungkin tersedia:\n" +
                "\n".join(f"@{username}" for username in available_usernames)
            )
        else:
            await warning_msg.edit_text(
                "✅ Generasi username selesai!\n"
                "❌ Tidak ditemukan username yang tersedia."
            )

    except Exception as e:
        await message.reply(f"❌ Terjadi kesalahan: {str(e)}")

    finally:
        # Always unlock user
        if user_id in user_locks:
            del user_locks[user_id]

async def main():
    # Start username cleanup task
    asyncio.create_task(username_store.start_cleanup_task())

    print("✅ Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())