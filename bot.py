import asyncio
import logging
import os
import re
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get token from environment variable with fallback
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

# Channel information
INVITE_LINK = "xo6vdaZALL9jN2Zl"
CHANNEL_ID = "-1002443114227"  # Fixed numeric format for private channel
CHANNEL_LINK = f"https://t.me/+{INVITE_LINK}"

# Message when user is not subscribed
SUBSCRIBE_MESSAGE = (
    "⚠️ Untuk menggunakan bot ini, Anda harus join channel kami terlebih dahulu:\n"
    f"{CHANNEL_LINK}\n\n"
    "Setelah join, silakan coba command kembali."
)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# User locks to prevent spam
user_locks = {}

# Username store
username_store = UsernameStore()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Send a message when the command /start is issued."""
    welcome_msg = (
        "👋 Selamat datang di Bot Generator Username Telegram!\n\n"
        "⚠️ Untuk menggunakan bot ini:\n"
        f"1️⃣ Join channel kami terlebih dahulu:\n   {CHANNEL_LINK}\n\n"
        "2️⃣ Setelah join, gunakan command berikut:\n"
        "/gen [username] - Generate variasi username\n\n"
        "Contoh: /gen username\n\n"
        "⚠️ Note:\n"
        "- Username yang sudah di-generate akan disimpan\n"
        "- Data username akan dihapus otomatis setelah 5 menit\n"
        "- Harap simpan hasil generate di chat pribadi Anda"
    )
    await message.reply(welcome_msg)

@dp.message(Command("help"))
async def help_command(message: Message):
    """Send a message when the command /help is issued."""
    await cmd_start(message)

async def generate_all_variants(base_name: str) -> list:
    """Generate username variants using all available methods"""
    all_usernames = set()  # Using set to avoid duplicates

    # Generate using all methods
    all_usernames.update(UsernameGenerator.ganhur(base_name))  # Random letter substitution
    all_usernames.update(UsernameGenerator.canon(base_name))   # i/l swap
    all_usernames.update(UsernameGenerator.sop(base_name))     # Add random character
    all_usernames.update(UsernameGenerator.scanon(base_name))  # Add 's'
    all_usernames.update(UsernameGenerator.switch(base_name))  # Swap adjacent
    all_usernames.update(UsernameGenerator.kurkuf(base_name))  # Remove random

    # Convert back to list and filter out already generated usernames
    return [
        username for username in all_usernames 
        if not username_store.is_generated(base_name, username)
    ]

@dp.message(Command("gen"))
async def handle_gen(message: Message):
    user_id = message.from_user.id

    # Check channel subscription
    if not await check_subscription(user_id):
        logger.warning(f"User {user_id} tried to use bot without joining channel")
        await message.reply(SUBSCRIBE_MESSAGE)
        return

    logger.info(f"User {user_id} verified as channel member, processing command: {message.text}")

    # Check if user is locked
    if user_id in user_locks:
        await message.reply("⚠️ Tunggu proses sebelumnya selesai dulu!")
        return

    # Parse command
    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Gunakan format: /gen username")
        return

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
            "- Data username akan dihapus otomatis setelah 5 menit\n"
            "- Harap simpan hasil generate di chat pribadi Anda\n\n"
            f"🔄 Generating variasi untuk '{base_name}'...\n"
            "⏳ Mohon tunggu, sedang mengecek ketersediaan username..."
        )

        # Generate usernames using all methods and check availability
        all_variants = await generate_all_variants(base_name)
        available_usernames = []

        # Check availability in batches
        batch_size = 5
        for i in range(0, len(all_variants), batch_size):
            batch = all_variants[i:i + batch_size]

            # Create a single checker instance for the batch
            checker = TelegramUsernameChecker()
            try:
                for username in batch:
                    result = await checker.check_fragment_api(username.lower())
                    # Store generated username
                    username_store.add_username(base_name, username)
                    if result is not None:
                        available_usernames.append(username)

                # Add delay between batches
                if i + batch_size < len(all_variants):
                    await asyncio.sleep(3)
            finally:
                await checker.session.close()

        if available_usernames:
            await warning_msg.edit_text(
                "✅ Generasi username selesai!\n\n"
                "Username yang mungkin tersedia:\n" +
                "\n".join(f"@{username}" for username in available_usernames) +
                "\n\n⚠️ PENTING: Harap simpan username ini dalam chat pribadi Anda!\n"
                "Bot akan menghapus data ini dalam 5 menit."
            )
        else:
            await warning_msg.edit_text(
                "✅ Generasi username selesai!\n"
                "❌ Tidak ditemukan username yang tersedia.\n\n"
                "⚠️ Data pencarian ini akan dihapus dalam 5 menit."
            )

        # Mark generation as complete after showing results
        username_store.mark_generation_complete(base_name)
        logger.info(f"Generation complete for base name '{base_name}', data will be cleaned up in 5 minutes")

    except Exception as e:
        await message.reply(f"❌ Terjadi kesalahan: {str(e)}")

    finally:
        # Always unlock user
        if user_id in user_locks:
            del user_locks[user_id]

async def check_subscription(user_id: int) -> bool:
    """Check if user is subscribed to the channel"""
    try:
        logger.info(f"Checking subscription for user {user_id} in channel {CHANNEL_ID}")
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        is_member = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        logger.info(f"User {user_id} subscription status: {member.status}, is_member: {is_member}")
        return is_member
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id}: {str(e)}")
        # Try alternative method using invite link
        try:
            chat = await bot.get_chat(CHANNEL_ID)
            logger.info(f"Successfully got chat info: {chat.title}")
            member = await bot.get_chat_member(chat_id=chat.id, user_id=user_id)
            is_member = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
            logger.info(f"Alternative check - User {user_id} status: {member.status}, is_member: {is_member}")
            return is_member
        except Exception as e2:
            logger.error(f"Alternative check failed: {str(e2)}")
            return False

async def main():
    # Start username cleanup task
    asyncio.create_task(username_store.start_cleanup_task())

    logger.info("✅ Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())