import logging.handlers
import sys
import asyncio
import os
import re
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from username_generator import UsernameGenerator
from username_checker import TelegramUsernameChecker
from username_store import UsernameStore
from flask import Flask
from threading import Thread

# Update logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            'bot.log',
            maxBytes=10000000,
            backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

# Configure base settings
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

# Channel information
INVITE_LINK = "xo6vdaZALL9jN2Zl"
CHANNEL_ID = "-1002443114227"
CHANNEL_LINK = f"https://t.me/+{INVITE_LINK}"

SUBSCRIBE_MESSAGE = (
    "⚠️ <b>Perhatian!</b> ⚠️\n\n"
    "Untuk menggunakan bot ini, Anda harus join channel kami terlebih dahulu:\n"
    f"🔗 {CHANNEL_LINK}\n\n"
    "📝 Setelah join, silakan coba command kembali."
)

# Initialize bot and dispatcher
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# User locks to prevent spam
user_locks = {}

# Username store
username_store = UsernameStore()

# Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    """Endpoint untuk UptimeRobot"""
    return "Bot is alive!"

def run_flask():
    """Run Flask in a separate thread"""
    app.run(host='0.0.0.0', port=5000)

async def batch_check_usernames(checker: TelegramUsernameChecker, usernames: list, batch_size=3) -> dict:
    """Check a batch of usernames concurrently with improved monitoring and timeout"""
    results = {}
    total_batches = (len(usernames) + batch_size - 1) // batch_size
    current_batch = 0
    batch_start_time = time.time()

    try:
        # Add timeout for entire batch operation
        async with asyncio.timeout(300):  # 5 minute total timeout
            for i in range(0, len(usernames), batch_size):
                current_batch += 1
                batch = usernames[i:i + batch_size]
                logger.info(f"Processing batch {current_batch}/{total_batches} with {len(batch)} usernames")

                # Process current batch with timeout
                try:
                    async with asyncio.timeout(60):  # 60 second timeout per batch
                        batch_results = await checker.batch_check(batch)

                        # Process results
                        for username, is_available in zip(batch, batch_results):
                            if is_available is not None:  # Skip errors
                                results[username] = is_available

                        # Log progress
                        found_count = sum(1 for r in results.values() if r)
                        logger.info(f"Batch {current_batch}/{total_batches} completed. Found {found_count} available usernames so far")

                except asyncio.TimeoutError:
                    logger.error(f"Timeout processing batch {current_batch}")
                    continue  # Skip to next batch

    except asyncio.TimeoutError:
        logger.error("Global timeout in batch processing")

    total_time = time.time() - batch_start_time
    found_count = sum(1 for r in results.values() if r)
    logger.info(f"All batches completed in {total_time:.2f}s. Found {found_count} available usernames")

    return results

@dp.message(Command("gen"))
async def handle_gen(message: Message):
    """Handle the /gen command with improved error handling"""
    user_id = message.from_user.id

    # Check channel subscription
    if not await check_subscription(user_id):
        await message.reply(SUBSCRIBE_MESSAGE)
        return

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
    if len(base_name) < 4:
        await message.reply("⚠️ Username terlalu pendek! Minimal 4 karakter.")
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
        # Send initial message
        status_message = await message.reply(
            "⚠️ <b>Informasi Penting</b> ⚠️\n\n"
            "📋 <b>Perhatikan:</b>\n"
            "• Username yang sudah di-generate akan disimpan\n"
            "• Username tersimpan tidak akan muncul lagi\n"
            "• Data akan terhapus otomatis setelah 5 menit\n"
            "• Simpan hasil generate di chat pribadi Anda\n\n"
            f"🔄 <b>Sedang memproses:</b> '{base_name}'\n"
            "⏳ Mohon tunggu, sedang mengecek ketersediaan username..."
        )

        # Generate username variants
        variants = await generate_all_variants(base_name)

        # Create checker instance
        checker = TelegramUsernameChecker()
        try:
            # Process username batches
            results = await batch_check_usernames(checker, variants)

            # Get available usernames
            available_usernames = [username for username, is_available in results.items() if is_available]

            if available_usernames:
                # Format results with improved presentation
                result_msg = (
                    "✅ <b>Generasi Username Selesai!</b>\n\n"
                    "🎯 <b>Username yang mungkin tersedia:</b>\n" +
                    "\n".join(f"• <code>@{username}</code>" for username in available_usernames[:10]) +
                    "\n\n⚠️ <b>PENTING:</b>\n"
                    "• 💾 Harap simpan username ini di chat pribadi\n"
                    "• ⏳ Bot akan menghapus data dalam 5 menit\n"
                    "• 🔄 Gunakan username segera sebelum diambil orang lain"
                )
            else:
                result_msg = (
                    "✅ <b>Generasi Username Selesai</b>\n\n"
                    "❌ Tidak ditemukan username yang tersedia.\n\n"
                    "ℹ️ <b>Saran:</b>\n"
                    "• 🔄 Coba username lain\n"
                    "• 📝 Gunakan kombinasi huruf dan angka yang berbeda"
                )

            await status_message.edit_text(result_msg)
            username_store.mark_generation_complete(base_name)

        finally:
            await checker.close()

    except Exception as e:
        logger.error(f"Error in handle_gen: {str(e)}")
        await message.reply(
            "❌ <b>Terjadi kesalahan</b>\n\n"
            "ℹ️ <b>Saran:</b>\n"
            "• 🔄 Silakan coba lagi dalam beberapa saat\n"
            "• 📝 Jika masih error, coba username lain"
        )

    finally:
        # Always unlock user
        if user_id in user_locks:
            del user_locks[user_id]

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

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Send a message when the command /start is issued."""
    welcome_msg = (
        "🤖 <b>Selamat datang di Bot Generator Username Telegram!</b>\n\n"
        "📋 <b>Cara Penggunaan:</b>\n"
        f"1️⃣ Join channel kami:\n   🔗 {CHANNEL_LINK}\n\n"
        "2️⃣ Gunakan command:\n"
        "   📝 <code>/gen [username]</code> - Generate variasi username\n"
        "   📝 <code>/allusn [username]</code> - Generate all username variations\n\n"
        "📱 <b>Contoh:</b>\n"
        "   <code>/gen username</code>\n\n"
        "⚠️ <b>Penting:</b>\n"
        "• 📋 Username yang sudah di-generate akan disimpan\n"
        "• ⏳ Data username akan dihapus otomatis setelah 5 menit\n"
        "• 💾 Harap simpan hasil generate di chat pribadi Anda"
    )
    await message.reply(welcome_msg)

@dp.message(Command("help"))
async def help_command(message: Message):
    """Send a message when the command /help is issued."""
    await cmd_start(message)


async def check_subscription(user_id: int) -> bool:
    """Check if user is subscribed to the channel with improved error handling"""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception as e:
        logger.error(f"Error checking subscription: {str(e)}")
        try:
            # Fallback method
            chat = await bot.get_chat(CHANNEL_ID)
            member = await bot.get_chat_member(chat_id=chat.id, user_id=user_id)
            return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        except Exception as e2:
            logger.error(f"Fallback subscription check failed: {str(e2)}")
            return False

async def main():
    """Start the bot with improved initialization"""
    try:
        # Start username cleanup task
        asyncio.create_task(username_store.start_cleanup_task())

        # Start Flask in a separate thread
        Thread(target=run_flask, daemon=True).start()
        logger.info("✅ Flask server is running...")

        # Start bot
        logger.info("✅ Bot is starting...")
        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        raise

@dp.message(Command("allusn"))
async def handle_allusn(message: Message):
    user_id = message.from_user.id

    # Check channel subscription
    if not await check_subscription(user_id):
        logger.warning(f"User {user_id} tried to use bot without joining channel")
        await message.reply(SUBSCRIBE_MESSAGE)
        return

    # Check if user is locked
    if user_id in user_locks:
        await message.reply("⚠️ Tunggu proses sebelumnya selesai dulu!")
        return

    # Parse command
    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Gunakan format: /allusn username")
        return

    base_name = args[1].lower()

    # Validate username
    if len(base_name) < 4:  # Changed from 5 to 4
        await message.reply("⚠️ Username terlalu pendek! Minimal 4 karakter.")
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
        # Send processing message
        processing_msg = await message.reply(
            "⚠️ <b>Informasi Penting</b> ⚠️\n\n"
            "📋 <b>Perhatikan:</b>\n"
            "• Username yang sudah di-generate akan disimpan\n"
            "• Username tersimpan tidak akan muncul lagi\n"
            "• Data akan terhapus otomatis setelah 5 menit\n"
            "• Simpan hasil generate di chat pribadi Anda\n\n"
            f"🔄 <b>Sedang memproses:</b> '{base_name}'\n"
            "⏳ Mohon tunggu, sedang mengecek ketersediaan username..."
        )

        # Generate all variations in prioritized order
        all_variants = []
        all_variants.append(base_name)  # OP first
        all_variants.extend(UsernameGenerator.sop(base_name))  # SOP second
        all_variants.extend(UsernameGenerator.canon(base_name))  # Canon/Scanon third
        all_variants.extend(UsernameGenerator.scanon(base_name))
        all_variants.extend(UsernameGenerator.tamhur(base_name))  # Tamhur fourth
        all_variants.extend(UsernameGenerator.ganhur(base_name))  # Ganhur/Switch fifth
        all_variants.extend(UsernameGenerator.switch(base_name))
        all_variants.extend(UsernameGenerator.kurkuf(base_name))  # Kurhuf last

        # Remove duplicates while preserving order
        all_variants = list(dict.fromkeys(all_variants))

        # Initialize result categories
        available_usernames = {
            "op": [],
            "sop": [],
            "canon_scanon": [],
            "tamhur": [],
            "ganhur_switch": [],
            "kurhuf": []
        }

        # Create single checker instance
        checker = TelegramUsernameChecker()
        try:
            # Check availability in optimized batches
            results = await batch_check_usernames(checker, all_variants)

            # Categorize results
            for username, is_available in results.items():
                if not is_available:
                    continue

                if username == base_name:
                    available_usernames["op"].append(username)
                elif username in UsernameGenerator.sop(base_name):
                    available_usernames["sop"].append(username)
                elif username in UsernameGenerator.canon(base_name) or username in UsernameGenerator.scanon(base_name):
                    available_usernames["canon_scanon"].append(username)
                elif username in UsernameGenerator.tamhur(base_name):
                    available_usernames["tamhur"].append(username)
                elif username in UsernameGenerator.ganhur(base_name) or username in UsernameGenerator.switch(base_name):
                    available_usernames["ganhur_switch"].append(username)
                elif username in UsernameGenerator.kurkuf(base_name):
                    available_usernames["kurhuf"].append(username)

            # Format results by category with new priorities
            result_text = "✅ <b>Hasil Generate Username</b>\n\n"
            categories = {
                "op": "👑 <b>On Point</b>",
                "sop": "💫 <b>Semi On Point</b>",
                "canon_scanon": "🔄 <b>Canon & Scanon</b>",
                "tamhur": "💎 <b>Tambah Huruf</b>",
                "ganhur_switch": "📝 <b>Ganti & Switch</b>",
                "kurhuf": "✂️ <b>Kurang Huruf</b>"
            }

            found_any = False
            for category, usernames in available_usernames.items():
                if usernames:
                    found_any = True
                    result_text += f"{categories[category]}:\n"
                    for username in usernames[:3]:  # Limit to 3 per category
                        result_text += f"• <code>@{username}</code>\n"
                    result_text += "\n"

            if found_any:
                result_text += "\n⚠️ <b>PENTING:</b>\n"
                result_text += "• 💾 Simpan username di chat pribadi\n"
                result_text += "• ⏳ Data akan dihapus dalam 5 menit\n"
                result_text += "• 🔄 Gunakan username segera sebelum diambil orang lain"
            else:
                result_text = "❌ <b>Tidak ditemukan username yang tersedia</b>\n\n"
                result_text += "ℹ️ <b>Info:</b>\n"
                result_text += "• ⏳ Data pencarian akan dihapus dalam 5 menit\n"
                result_text += "• 🔄 Silakan coba username lain"

            await processing_msg.edit_text(result_text)
            username_store.mark_generation_complete(base_name)

        finally:
            await checker.close()

    except Exception as e:
        await message.reply(f"❌ Terjadi kesalahan: {str(e)}")

    finally:
        # Always unlock user
        if user_id in user_locks:
            del user_locks[user_id]


if __name__ == "__main__":
    asyncio.run(main())