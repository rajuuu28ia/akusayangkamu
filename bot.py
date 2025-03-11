import logging.handlers
import sys
import os
import glob
import asyncio
from datetime import datetime, timedelta

# Enhanced logging setup with more detailed output
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            'bot.log',
            maxBytes=1000000,  # 1MB
            backupCount=1,
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)

# Set debug level for specific modules
logging.getLogger('username_checker').setLevel(logging.DEBUG)
logging.getLogger('telethon').setLevel(logging.INFO)

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

# Replace TOKEN section with proper environment variable handling
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN not found in environment variables!")
    sys.exit(1)  # Exit if no token provided

# Debug log for secrets (without showing actual values)
logger.info("Checking environment variables:")
logger.info(f"TELEGRAM_API_ID present: {bool(os.getenv('TELEGRAM_API_ID'))}")
logger.info(f"TELEGRAM_API_HASH present: {bool(os.getenv('TELEGRAM_API_HASH'))}")
logger.info(f"TELEGRAM_BOT_TOKEN present: {bool(TOKEN)}")

# Update channel information
INVITE_LINK = "zr6kLxcG7TQ5NGU9"
CHANNEL_ID = "-1002443114227"  # Fixed numeric format for private channel
CHANNEL_LINK = f"https://t.me/+{INVITE_LINK}"

# Message when user is not subscribed
SUBSCRIBE_MESSAGE = (
    "⚠️ <b>Perhatian!</b> ⚠️\n\n"
    "Untuk menggunakan bot ini, Anda harus join channel kami terlebih dahulu:\n"
    f"🔗 {CHANNEL_LINK}\n\n"
    "📝 Setelah join, silakan coba command kembali."
)

# Initialize bot with parse_mode
logger.info("Initializing Telegram bot...")
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# User locks to prevent spam
user_locks = {}

# Username store
username_store = UsernameStore()

# Flask app untuk keep-alive dengan port dinamis
app = Flask(__name__)

@app.route('/')
def home():
    """Endpoint untuk UptimeRobot"""
    return "Bot is alive!"

def run_flask():
    """Run Flask in a separate thread with dynamic port"""
    port = int(os.getenv('PORT', 5000))
    while True:
        try:
            app.run(host='0.0.0.0', port=port)
            break
        except OSError:
            logger.warning(f"Port {port} is in use, trying port {port + 1}")
            port += 1

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

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Send a message when the command /start is issued."""
    # Check channel subscription first
    user_id = message.from_user.id
    is_member = await check_subscription(user_id)
    if not is_member:
        await message.reply(SUBSCRIBE_MESSAGE, parse_mode="HTML")
        return

    welcome_msg = (
        "🤖 <b>Selamat datang di Bot Generator Username Telegram!</b>\n\n"
        "📋 <b>Cara Penggunaan:</b>\n"
        "• Gunakan command:\n"
        "   📝 <code>/allusn [username]</code> - Generate semua variasi username\n\n"
        "📱 <b>Contoh:</b>\n"
        "   <code>/allusn username</code>\n\n"
        "⚠️ <b>Penting:</b>\n"
        "• 📋 Username yang sudah di-generate akan disimpan\n"
        "• ⏳ Data username akan dihapus otomatis setelah 5 menit\n"
        "• 💾 Harap simpan hasil generate di chat pribadi Anda"
    )
    await message.reply(welcome_msg, parse_mode="HTML")

@dp.message(Command("help"))
async def help_command(message: Message):
    """Send a message when the command /help is issued."""
    # Check channel subscription first
    user_id = message.from_user.id
    is_member = await check_subscription(user_id)
    if not is_member:
        await message.reply(SUBSCRIBE_MESSAGE, parse_mode="HTML")
        return

    await cmd_start(message)

async def batch_check_usernames(checker: TelegramUsernameChecker, usernames: list, batch_size=10) -> dict:
    """
    Check a batch of usernames concurrently with optimized load balancing for 40 users
    Uses adaptive batch sizing and session rotation to avoid rate limits
    """
    results = {}
    total_usernames = len(usernames)
    processed = 0

    # Start time for tracking
    batch_start_time = time.time()
    logger.info(f"Starting optimized batch check for {total_usernames} usernames with batch size {batch_size}")

    # Use semaphore to limit concurrent requests (40 concurrent users)
    concurrency_limit = min(40, batch_size * 2)
    batch_size = min(20, batch_size)  # Mengurangi batch size
    semaphore = asyncio.Semaphore(concurrency_limit)

    async def check_username_with_semaphore(username):
        async with semaphore:
            try:
                return username, await checker.check_fragment_api(username.lower())
            except Exception as e:
                logger.error(f"Error in username check {username}: {str(e)}")
                return username, None

    try:
        # Process in optimized batches
        for i in range(0, total_usernames, batch_size):
            batch = usernames[i:i + batch_size]
            processed += len(batch)

            # Create tasks for this batch
            tasks = [check_username_with_semaphore(username) for username in batch]

            # Process batch with timeout
            try:
                async with asyncio.timeout(30):  # 30 second timeout per batch
                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Process results
                    available_in_batch = 0
                    for result in batch_results:
                        if isinstance(result, Exception):
                            logger.warning(f"Task error: {str(result)}")
                            continue

                        username, is_available = result
                        if is_available is not None:
                            results[username] = is_available
                            if is_available:
                                available_in_batch += 1

                    # Progress update
                    progress = (processed / total_usernames) * 100
                    logger.info(f"Progress: {progress:.1f}% - Batch found {available_in_batch} available usernames")

                    # Adaptive delay based on batch size to prevent rate limits
                    if i + batch_size < total_usernames:
                        # Calculate adaptive delay: more usernames = slightly longer delay
                        delay = 0.5 + (batch_size / 50)  # 0.5s base + adjustment
                        await asyncio.sleep(delay)

            except asyncio.TimeoutError:
                logger.error(f"Timeout processing batch starting at username {batch[0]}")
                continue

    except Exception as e:
        logger.error(f"Error in batch processing: {str(e)}")

    finally:
        total_time = time.time() - batch_start_time
        logger.info(f"All batches completed in {total_time:.2f}s. Found {len(results)} available usernames")
        return results

# Modify the cleanup interval and file management
CLEANUP_INTERVAL = 8 * 60  # 8 minutes for file cleanup
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB maximum log size
MAX_LOG_FILES = 2  # Keep only 2 log files (current and backup)

async def cleanup_files():
    """Clean up old files and logs periodically"""
    while True:
        try:
            current_time = time.time()

            # Clean up log files
            log_files = glob.glob('*.log*')
            if len(log_files) > MAX_LOG_FILES:
                for old_log in sorted(log_files, key=os.path.getctime)[:-MAX_LOG_FILES]:
                    try:
                        os.remove(old_log)
                        logger.info(f"Removed old log file: {old_log}")
                    except Exception as e:
                        logger.error(f"Error removing log {old_log}: {e}")

            # Clean up session files older than 8 minutes
            session_files = glob.glob('*.session*') + glob.glob('*.session-journal')
            for session_file in session_files:
                if os.path.getctime(session_file) < current_time - CLEANUP_INTERVAL:
                    try:
                        os.remove(session_file)
                        logger.info(f"Removed old session file: {session_file}")
                    except Exception as e:
                        logger.error(f"Error removing session file {session_file}: {e}")

            # Rotate main log file if too large
            if os.path.exists('bot.log') and os.path.getsize('bot.log') > MAX_LOG_SIZE:
                try:
                    os.rename('bot.log', f'bot.log.{int(time.time())}')
                    logger.info("Rotated main log file")
                except Exception as e:
                    logger.error(f"Error rotating log file: {e}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        await asyncio.sleep(CLEANUP_INTERVAL)


@dp.message(Command("allusn"))
async def handle_allusn(message: Message):
    user_id = message.from_user.id

    # Check channel subscription
    is_member = await check_subscription(user_id)
    if not is_member:
        await message.reply(SUBSCRIBE_MESSAGE, parse_mode="HTML")
        return

    # Lock user
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

        # Determine if it's a mulchar username
        is_mulchar = base_name.lower().startswith(('mc', 'mulchar'))

        # Generate variants based on type
        all_variants = [base_name]  # Start with base name

        # Generate basic variations that are shared between types
        sop_variants = UsernameGenerator.sop(base_name)
        canon_variants = UsernameGenerator.canon(base_name)
        scanon_variants = UsernameGenerator.scanon(base_name)
        tamhur_variants = UsernameGenerator.tamhur(base_name)
        switch_variants = UsernameGenerator.switch(base_name)
        kurkuf_variants = UsernameGenerator.kurkuf(base_name)
        ganhur_variants = UsernameGenerator.ganhur(base_name)

        if is_mulchar:
            # Mulchar: only allowed methods in priority order
            logger.info(f"Generating variations for mulchar: {base_name}")
            all_variants.extend(tamhur_variants)  # Priority 1
            all_variants.extend(switch_variants)  # Priority 2
            all_variants.extend(kurkuf_variants)  # Priority 3
        else:
            # Regular username: all methods
            logger.info(f"Generating variations for regular username: {base_name}")
            all_variants.extend(sop_variants)
            all_variants.extend(canon_variants)
            all_variants.extend(scanon_variants)
            all_variants.extend(tamhur_variants)
            all_variants.extend(ganhur_variants)
            all_variants.extend(switch_variants)
            all_variants.extend(kurkuf_variants)

        # Remove duplicates while preserving order
        all_variants = list(dict.fromkeys(all_variants))

        # Initialize result categories based on type
        if is_mulchar:
            available_usernames = {
                "op": [],
                "tamhur": [],  # Priority for mulchar
                "switch": [],  # Secondary for mulchar
                "kurhuf": []   # Tertiary for mulchar
            }
        else:
            available_usernames = {
                "op": [],
                "sop": [],
                "canon_scanon": [],
                "tamhur": [],
                "ganhur_switch": [],
                "kurhuf": []
            }

        # Create checker instance
        checker = TelegramUsernameChecker()
        try:
            # Optimize batch size based on current load
            active_users = len(user_locks)
            optimal_batch_size = max(5, min(20, 40 // (active_users + 1)))  # Dynamic batch size

            # Check availability in batches
            results = await batch_check_usernames(checker, all_variants, batch_size=optimal_batch_size)

            # Categorize results based on type
            for username, is_available in results.items():
                if not is_available:
                    continue

                if username == base_name:
                    available_usernames["op"].append(username)
                elif is_mulchar:
                    # Mulchar categorization
                    if username in tamhur_variants:
                        available_usernames["tamhur"].append(username)
                    elif username in switch_variants:
                        available_usernames["switch"].append(username)
                    elif username in kurkuf_variants:
                        available_usernames["kurhuf"].append(username)
                else:
                    # Regular username categorization
                    if username in sop_variants:
                        available_usernames["sop"].append(username)
                    elif username in canon_variants or username in scanon_variants:
                        available_usernames["canon_scanon"].append(username)
                    elif username in tamhur_variants:
                        available_usernames["tamhur"].append(username)
                    elif username in ganhur_variants or username in switch_variants:
                        available_usernames["ganhur_switch"].append(username)
                    elif username in kurkuf_variants:
                        available_usernames["kurhuf"].append(username)

            # Format results with appropriate categories
            result_text = "✅ <b>Hasil Generate Username</b>\n\n"

            if is_mulchar:
                result_text += "🎭 <b>Mode: MULCHAR</b> (Metode Khusus)\n\n"
                categories = {
                    "op": "👑 <b>On Point</b>",
                    "tamhur": "💎 <b>Tambah Huruf</b>",
                    "switch": "🔄 <b>Tukar Huruf</b>",
                    "kurhuf": "✂️ <b>Kurang Huruf</b>"
                }
            else:
                result_text += "🎤 <b>Mode: REGULAR</b> (Semua metode)\n\n"
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
                if usernames and category in categories:  # Check if category exists and has usernames
                    found_any = True
                    result_text += f"{categories[category]}:\n"
                    for username in usernames[:3]:  # Limit to 3 per category
                        result_text += f"• @{username}\n"
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
            await checker.session.close()

    except Exception as e:
        await message.reply(f"❌ Terjadi kesalahan: {str(e)}")

    finally:
        # Always unlock user
        if user_id in user_locks:
            del user_locks[user_id]

async def periodic_log_cleanup():
    """Periodically clean up old log files"""
    while True:
        try:
            # Find all log files
            log_files = glob.glob('bot.log*')
            if not log_files:
                await asyncio.sleep(3600)  # Sleep for 1 hour if no logs
                continue

            # Sort by modification time, newest first
            log_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

            # Keep only the most recent log file
            for old_log in log_files[1:]:
                try:
                    os.remove(old_log)
                    logger.info(f"Removed old log file: {old_log}")
                except Exception as e:
                    logger.error(f"Error removing log file {old_log}: {e}")

        except Exception as e:
            logger.error(f"Error during periodic log cleanup: {e}")

        await asyncio.sleep(3600)  # Run every hour

async def main():
    # Start cleanup task
    asyncio.create_task(cleanup_files())

    # Start username cleanup task
    asyncio.create_task(username_store.start_cleanup_task())

    try:
        # Start Flask in a separate thread
        Thread(target=run_flask, daemon=True).start()
        logger.info("✅ Flask server is running...")

        # Initialize bot and start polling with custom settings
        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)

        logger.info("✅ Bot is running...")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        sys.exit(1)

async def on_startup(dispatcher):
    """Startup handler to ensure clean bot startup"""
    try:
        # Delete webhook to ensure clean polling
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted successfully")
    except Exception as e:
        logger.error(f"Error in startup: {e}")
        raise

async def on_shutdown(dispatcher):
    """Shutdown handler to ensure clean bot shutdown"""
    try:
        # Close bot session
        await bot.session.close()
        logger.info("Bot session closed successfully")
    except Exception as e:
        logger.error(f"Error in shutdown: {e}")

if __name__ == "__main__":
    asyncio.run(main())