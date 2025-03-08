import logging.handlers
import sys

# Update logging configuration at the start of the file
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
from username_checker import check_telegram_username, TelegramUsernameChecker
from username_store import UsernameStore
from flask import Flask
from threading import Thread

# Replace the TOKEN section with environment variable approach
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    TOKEN = "7894481490:AAEPaAkWj9hnGU5xVHbtU4SzmBB2NWNUZPU"


# Channel information
INVITE_LINK = "xo6vdaZALL9jN2Zl"
CHANNEL_ID = "-1002443114227"  # Fixed numeric format for private channel
CHANNEL_LINK = f"https://t.me/+{INVITE_LINK}"

# Message when user is not subscribed
SUBSCRIBE_MESSAGE = (
    "⚠️ <b>Perhatian!</b> ⚠️\n\n"
    "Untuk menggunakan bot ini, Anda harus join channel kami terlebih dahulu:\n"
    f"🔗 {CHANNEL_LINK}\n\n"
    "📝 Setelah join, silakan coba command kembali."
)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# User locks to prevent spam
user_locks = {}

# Username store
username_store = UsernameStore()

# Flask app untuk keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    """Endpoint untuk UptimeRobot"""
    return "Bot is alive!"

def run_flask():
    """Run Flask in a separate thread"""
    app.run(host='0.0.0.0', port=5000)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Send a message when the command /start is issued."""
    welcome_msg = (
        "🤖 <b>Selamat datang di Bot Generator Username Telegram!</b>\n\n"
        "📋 <b>Cara Penggunaan:</b>\n"
        f"1️⃣ Join channel kami:\n   🔗 {CHANNEL_LINK}\n\n"
        "2️⃣ Gunakan command:\n"
        "   📝 <code>/allusn [username]</code> - Generate semua variasi username\n\n"
        "📱 <b>Contoh:</b>\n"
        "   <code>/allusn username</code>\n\n"
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

async def batch_check_usernames(checker: TelegramUsernameChecker, usernames: list, batch_size=5) -> dict:
    """Check a batch of usernames concurrently with improved monitoring and timeout"""
    results = {}
    tasks = []
    total_batches = (len(usernames) + batch_size - 1) // batch_size
    current_batch = 0

    logger.info(f"Starting batch check for {len(usernames)} usernames in {total_batches} batches")
    batch_start_time = time.time()

    try:
        # Add timeout for entire batch operation
        async with asyncio.timeout(120):  # 2 minute total timeout
            for i in range(0, len(usernames), batch_size):
                current_batch += 1
                batch = usernames[i:i + batch_size]
                logger.info(f"Processing batch {current_batch}/{total_batches} with {len(batch)} usernames")

                # Create tasks for each username in batch
                for username in batch:
                    task = asyncio.create_task(checker.check_fragment_api(username.lower()))
                    tasks.append((username, task))

                # Wait for current batch to complete with timeout
                try:
                    async with asyncio.timeout(30):  # 30 second timeout per batch
                        batch_results = []
                        for username, task in tasks:
                            try:
                                result = await task
                                if result is not None:
                                    results[username] = result
                                    batch_results.append(username)
                            except Exception as e:
                                logger.error(f"Error checking username {username}: {str(e)}")

                        tasks = []  # Clear tasks for next batch

                        # Log batch completion
                        logger.info(f"Batch {current_batch}/{total_batches} completed. Found {len(batch_results)} available usernames")

                        # Small delay between batches to avoid rate limits
                        if i + batch_size < len(usernames):
                            delay = 0.5  # Reduced delay between batches
                            logger.info(f"Waiting {delay}s before next batch...")
                            await asyncio.sleep(delay)

                except asyncio.TimeoutError:
                    logger.error(f"Timeout processing batch {current_batch}")
                    # Cancel remaining tasks in current batch
                    for _, task in tasks:
                        task.cancel()
                    tasks = []
                    continue  # Move to next batch

    except asyncio.TimeoutError:
        logger.error("Global timeout in batch processing")
    finally:
        # Cancel any remaining tasks
        for _, task in tasks:
            task.cancel()

        total_time = time.time() - batch_start_time
        logger.info(f"All batches completed in {total_time:.2f}s. Found {len(results)} available usernames")
        return results

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
            # Check availability in batches
            results = await batch_check_usernames(checker, all_variants)

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

async def main():
    # Start username cleanup task
    asyncio.create_task(username_store.start_cleanup_task())

    # Start Flask in a separate thread
    Thread(target=run_flask, daemon=True).start()
    logger.info("✅ Flask server is running...")

    logger.info("✅ Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())