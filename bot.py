import os
import asyncio
import logging
import time
import re
import threading
from flask import Flask, request
from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    CallbackQuery
)
from pyrogram.errors import (
    FloodWait,
    UserDeactivated,
    UserIsBlocked,
    PeerIdInvalid,
    UsernameInvalid,
    UsernameOccupied,
    UsernameNotOccupied
)

# Import helper modules
from username_generator import UsernameGenerator
from username_rules import (
    HURUF_RATA, 
    HURUF_TIDAK_RATA, 
    HURUF_VOKAL,
    UsernameTypes, 
    NameFormat
)
from config import RESERVED_WORDS

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Bot credentials
TELEGRAM_API_ID = os.getenv("API_ID") or os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("API_HASH") or os.getenv("TELEGRAM_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
SESSION_STRING = os.getenv("DUMMY_SESSION") or os.getenv("TELEGRAM_SESSION_STRING")
SESSION_STRING_2 = os.getenv("TELEGRAM_SESSION_STRING_2")

# Log environment variables (only presence, not values)
logger.info("Checking environment variables:")
logger.info(f"TELEGRAM_API_ID present: {bool(TELEGRAM_API_ID)}")
logger.info(f"TELEGRAM_API_HASH present: {bool(TELEGRAM_API_HASH)}")
logger.info(f"TELEGRAM_SESSION_STRING present: {bool(SESSION_STRING)}")
logger.info(f"TELEGRAM_SESSION_STRING_2 present: {bool(SESSION_STRING_2)}")

# User tracking
active_users = set()
user_locks = {}
user_tasks = {}
user_generations = {}

# Constants
MAX_USERS = 40
MAX_GENERATIONS_PER_USER = 30
COMMAND_COOLDOWN = 3  # seconds
RATE_LIMIT_DELAY = 1.5  # seconds

# Create Flask app for webhook server (optional but useful for uptime)
app = Flask("bot")

@app.route('/')
def home():
    """Endpoint for UptimeRobot"""
    return "Username Generator Bot is running!"

def run_flask():
    """Run Flask in a separate thread with dynamic port"""
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Initialize Telegram bot
logger.info("Initializing Telegram bot...")
# Use in-memory session instead of file-based session to avoid session reuse issues
bot = Client(
    ":memory:",  # Use in-memory session to avoid session file issues
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    bot_token=BOT_TOKEN,
    workers=8,  # Increase number of workers for better performance
    parse_mode="markdown",  # Default parse mode for messages
    ipv6=False  # Disable IPv6 to avoid connectivity issues
)

# Username checker class - Simplified version that works without user session
# Import the actual checker
from username_checker_pyrogram import UsernameChecker

# Initialize checker to None first
checker = None
            
# Create username checker instance in limited mode (no username checking)
logger.info("Initializing bot in limited mode without full username checker")
# Create a limited checker instance with no session string dependency
checker = UsernameChecker(None)  # Will operate in limited mode

# This will allow users to generate username variations but won't verify if they're available with Telegram API

# Create username checker instance in limited mode (no username checking)
logger.info("Initializing bot in limited mode without full username checker")
# Create a limited checker instance with no session string dependency
checker = UsernameChecker(None)  # Will operate in limited mode

# This will allow users to generate username variations but won't verify if they're available with Telegram API

# Add debug handler for ALL incoming messages
# We set group=1 to make it run after command handlers (which have group=0 by default)
@bot.on_message(filters.all, group=1)
async def debug_all_messages(client, message):
    """Log all incoming messages for debugging purposes"""
    try:
        user_info = f"{message.from_user.id} ({message.from_user.first_name})" if message.from_user else "Unknown"
        msg_text = message.text or message.caption or "No text" 
        logger.info(f"RECEIVED MESSAGE FROM {user_info}: {msg_text}")
        
        # Don't process further if it's a command (let command handlers work)
        if message.text and message.text.startswith('/'):
            logger.info(f"Message is a command, handled by command handlers")
            return
            
        # Auto-reply with help for non-command messages
        if message.from_user:
            logger.info(f"Sending help reply for non-command message")
            await message.reply(
                "👋 Selamat datang di bot Generator Username!\n\n"
                "Gunakan perintah /start untuk memulai atau /help untuk melihat daftar perintah."
            )
    except Exception as e:
        logger.error(f"Error in debug message handler: {str(e)}")

# User management functions
def can_add_user(user_id):
    """Check if a new user can be added"""
    return len(active_users) < MAX_USERS or user_id in active_users

def add_user(user_id):
    """Add a user to active users"""
    if len(active_users) < MAX_USERS or user_id in active_users:
        active_users.add(user_id)
        return True
    return False

def remove_user(user_id):
    """Remove a user from active users"""
    if user_id in active_users:
        active_users.remove(user_id)
        if user_id in user_generations:
            del user_generations[user_id]
        if user_id in user_locks:
            del user_locks[user_id]
        if user_id in user_tasks:
            del user_tasks[user_id]

def can_generate(user_id):
    """Check if user can generate more usernames"""
    return user_generations.get(user_id, 0) < MAX_GENERATIONS_PER_USER

def increment_generation(user_id):
    """Increment generation count for a user"""
    user_generations[user_id] = user_generations.get(user_id, 0) + 1
    return user_generations[user_id]

def get_remaining_generations(user_id):
    """Get remaining generations for a user"""
    return MAX_GENERATIONS_PER_USER - user_generations.get(user_id, 0)

def acquire_lock(user_id):
    """Try to acquire a command lock for a user"""
    current_time = time.time()
    
    if user_id in user_locks:
        lock_time, locked = user_locks[user_id]
        if locked and (current_time - lock_time) < COMMAND_COOLDOWN:
            return False
            
    user_locks[user_id] = (current_time, True)
    return True

def release_lock(user_id):
    """Release a command lock for a user"""
    if user_id in user_locks:
        user_locks[user_id] = (user_locks[user_id][0], False)

# Helper function to create status message
def format_status_emoji(status):
    """Convert status to emoji for better visualization"""
    if status == "available":
        return "✅ AVAILABLE"
    elif status == "banned_or_reserved":
        return "🚫 BANNED/RESERVED"
    elif status == "premium_user":
        return "👑 TAKEN (Premium User)"
    elif status == "user":
        return "👤 TAKEN (User)"
    elif status == "bot":
        return "🤖 TAKEN (Bot)"
    elif status == "channel":
        return "📢 TAKEN (Channel)"
    elif status == "group":
        return "👥 TAKEN (Group)"
    elif status == "invalid_format":
        return "❌ INVALID FORMAT"
    else:
        return "❓ UNKNOWN"

def format_username_result(result):
    """Format username check result for display"""
    username = result["username"]
    status = result["type"]
    emoji_status = format_status_emoji(status)
    
    return f"{emoji_status}: @{username}"

async def check_generated_usernames(base_name, generator_method, user_id, message_id):
    """
    Generate and check usernames based on method
    """
    try:
        # Generate usernames
        if generator_method == UsernameGenerator.tamhur:
            generated_usernames = generator_method(base_name, "BOTH")
        else:
            generated_usernames = generator_method(base_name)
        
        # Remove duplicates and limit to 30
        generated_usernames = list(set(generated_usernames))[:30]
        
        # Count as a generation
        increment_generation(user_id)
        
        # Update progress message
        await bot.edit_message_text(
            user_id,
            message_id,
            f"⏳ Checking {len(generated_usernames)} usernames...\n"
            f"(0/{len(generated_usernames)} checked)"
        )
        
        # Check if we're in limited mode
        if checker.limited_mode:
            # Show generated usernames without checking
            usernames_text = "\n".join([f"@{username}" for username in generated_usernames])
            result_text = (
                f"🔍 **Hasil Generasi Username**\n\n"
                f"🎯 Username Dasar: **@{base_name}**\n"
                f"🧮 Dihasilkan: **{len(generated_usernames)}** username\n\n"
                f"⚠️ **PERHATIAN:** Bot dalam mode terbatas, username tidak dapat diperiksa ketersediaannya.\n\n"
                f"**Username yang Dihasilkan:**\n{usernames_text}"
            )
            await bot.edit_message_text(user_id, message_id, result_text)
            return
        
        # Check in batches to avoid rate limits
        available_usernames = []
        unavailable_count = 0
        batch_size = 5
        
        for i in range(0, len(generated_usernames), batch_size):
            batch = generated_usernames[i:i+batch_size]
            results = await checker.check_usernames_batch(batch, max_concurrency=2)
            
            for username, result in results.items():
                if result["available"]:
                    available_usernames.append(username)
                else:
                    unavailable_count += 1
            
            # Update progress
            checked_count = i + len(batch)
            remaining = len(generated_usernames) - checked_count
            await bot.edit_message_text(
                user_id,
                message_id,
                f"⏳ Checking usernames...\n"
                f"({checked_count}/{len(generated_usernames)} checked, {len(available_usernames)} available)"
            )
            
            # Slight delay to avoid flood limits
            await asyncio.sleep(1)
        
        # Final report
        if available_usernames:
            available_text = "\n".join([f"✅ @{username}" for username in available_usernames])
            result_text = (
                f"🔍 **Hasil Pengecekan Username**\n\n"
                f"🎯 Username Dasar: **@{base_name}**\n"
                f"🧮 Dihasilkan: **{len(generated_usernames)}** username\n"
                f"✅ Tersedia: **{len(available_usernames)}** username\n"
                f"❌ Tidak Tersedia: **{unavailable_count}** username\n\n"
                f"**Username Tersedia:**\n{available_text}"
            )
        else:
            result_text = (
                f"🔍 **Hasil Pengecekan Username**\n\n"
                f"🎯 Username Dasar: **@{base_name}**\n"
                f"🧮 Dihasilkan: **{len(generated_usernames)}** username\n"
                f"❌ Tidak ada username yang tersedia dari {len(generated_usernames)} yang dihasilkan"
            )
        
        # Send final report
        await bot.edit_message_text(user_id, message_id, result_text)
        
    except Exception as e:
        logger.error(f"Error in check_generated_usernames: {str(e)}")
        await bot.edit_message_text(
            user_id,
            message_id,
            f"❌ Error saat melakukan pengecekan username:\n{str(e)}"
        )
    finally:
        # Clean up
        if user_id in user_tasks:
            del user_tasks[user_id]
        release_lock(user_id)

async def check_specific_username(username, user_id, message_id):
    """
    Check a specific username
    """
    try:
        # Count as a generation
        increment_generation(user_id)
        
        # Update progress message
        await bot.edit_message_text(
            user_id,
            message_id,
            f"⏳ Checking @{username}..."
        )
        
        # Check if we're in limited mode
        if checker.limited_mode:
            # If we're in limited mode, inform user
            await bot.edit_message_text(
                user_id,
                message_id,
                "❌ Maaf, fitur pengecekan username sedang tidak tersedia. "
                "Bot dalam mode terbatas. Silakan hubungi admin bot."
            )
            return
            
        # Check the username
        result = await checker.check_username(username)
        
        # Format the result
        formatted_result = format_username_result(result)
        
        # Send result
        await bot.edit_message_text(
            user_id,
            message_id,
            f"🔍 **Hasil Pengecekan Username**\n\n{formatted_result}"
        )
        
    except Exception as e:
        logger.error(f"Error in check_specific_username: {str(e)}")
        await bot.edit_message_text(
            user_id,
            message_id,
            f"❌ Error saat melakukan pengecekan username:\n{str(e)}"
        )
    finally:
        # Clean up
        if user_id in user_tasks:
            del user_tasks[user_id]
        release_lock(user_id)

@bot.on_message(filters.command("start"))
async def start_command(client, message: Message):
    """Handle /start command"""
    # Log message for debugging
    logger.info(f"Received /start command from user: {message.from_user.id} ({message.from_user.first_name})")
    
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # Add user to active users
    if not can_add_user(user_id):
        logger.info(f"User {user_id} rejected due to capacity limit")
        await message.reply(
            "❌ Bot sedang dalam kapasitas penuh. Silakan coba lagi nanti."
        )
        return
        
    add_user(user_id)
    logger.info(f"User {user_id} added to active users")
    
    # Welcome message
    welcome_text = (
        f"👋 Halo {user_name}!\n\n"
        f"Selamat datang di Bot Cek Username Telegram\n\n"
        f"🔍 Bot ini dapat membantu Anda memeriksa ketersediaan username Telegram "
        f"dan menghasilkan variasi username berdasarkan berbagai metode.\n\n"
        f"Gunakan /help untuk melihat daftar perintah yang tersedia.\n\n"
        f"Sisa generasi Anda: {get_remaining_generations(user_id)}/{MAX_GENERATIONS_PER_USER}"
    )
    
    logger.info(f"Sending welcome message to user {user_id}")
    await message.reply(welcome_text)

@bot.on_message(filters.command("help"))
async def help_command(client, message: Message):
    """Handle /help command"""
    user_id = message.from_user.id
    
    # Check if user is active
    if user_id not in active_users:
        add_user(user_id)
    
    # Get bot status
    bot_mode = "🟢 Penuh (dengan pengecekan username)" if checker else "🟠 Terbatas (hanya generasi username)"
    
    help_text = (
        "🔍 **Perintah yang tersedia:**\n\n"
        "• /start - Memulai bot\n"
        "• /help - Menampilkan pesan bantuan ini\n"
        "• /check username - Memeriksa satu username tertentu\n"
        "• /generate username - Menampilkan menu generator username\n"
        "• /stats - Menampilkan statistik penggunaan bot\n"
        "• /cancel - Membatalkan operasi yang sedang berjalan\n\n"
        "**Format Username:**\n"
        f"• Huruf Rata: {HURUF_RATA}\n"
        f"• Huruf Tidak Rata: {HURUF_TIDAK_RATA}\n"
        f"• Huruf Vokal: {HURUF_VOKAL}\n\n"
        "**Jenis Generator:**\n"
        "• OP (On Point) - Tanpa modifikasi\n"
        "• SOP (Semi On Point) - Menggandakan huruf (mis. jjaem, jaeemmin)\n"
        "• Canon - Tukar i/L (mis. jaemin → jaeml̇n)\n"
        "• Scanon - Tambah huruf 's' di akhir (mis. jaemins)\n"
        "• Tamhur - Tambah satu huruf di mana saja\n"
        "• Ganhur - Ganti satu huruf dengan huruf sejenis\n"
        "• Switch - Tukar posisi dua huruf bersebelahan\n"
        "• Kurhuf - Kurangi satu huruf\n\n"
        f"**Status Bot:** {bot_mode}\n"
        f"Sisa generasi Anda: {get_remaining_generations(user_id)}/{MAX_GENERATIONS_PER_USER}"
    )
    
    # Add note if bot is in limited mode
    if not checker:
        help_text += (
            "\n\n⚠️ **PERHATIAN:** Bot sedang beroperasi dalam mode terbatas. "
            "Fitur pengecekan ketersediaan username tidak tersedia. Bot hanya dapat "
            "menampilkan variasi username tanpa memeriksa ketersediaannya."
        )
    
    await message.reply(help_text)

@bot.on_message(filters.command("stats"))
async def stats_command(client, message: Message):
    """Handle /stats command"""
    user_id = message.from_user.id
    
    # Get stats
    remaining = get_remaining_generations(user_id)
    
    # Get bot status
    bot_mode = "🟢 Penuh (dengan pengecekan username)" if checker else "🟠 Terbatas (hanya generasi username)"
    
    stats_text = (
        "📊 **Statistik Bot**\n\n"
        f"👤 Pengguna aktif: {len(active_users)}/{MAX_USERS}\n"
        f"🔄 Sisa generasi Anda: {remaining}/{MAX_GENERATIONS_PER_USER}\n"
        f"🤖 Status bot: {bot_mode}\n"
        f"⏱️ Batas waktu perintah: {COMMAND_COOLDOWN} detik\n"
        f"⏳ Rate limit: {RATE_LIMIT_DELAY} detik per permintaan\n"
    )
    
    # Add note if bot is in limited mode
    if not checker:
        stats_text += (
            "\n⚠️ **PERHATIAN:** Bot sedang beroperasi dalam mode terbatas. "
            "Fitur pengecekan ketersediaan username tidak tersedia."
        )
    
    await message.reply(stats_text)

@bot.on_message(filters.command("check"))
async def check_command(client, message: Message):
    """Handle /check command"""
    user_id = message.from_user.id
    
    # Check if user is active
    if user_id not in active_users:
        add_user(user_id)
    
    # Check if user is rate limited
    if not acquire_lock(user_id):
        await message.reply(
            "⏳ Mohon tunggu sebentar sebelum mengirim perintah lagi."
        )
        return
    
    # Check if user already has an active task
    if user_id in user_tasks:
        await message.reply(
            "❌ Anda sudah memiliki operasi yang sedang berjalan. "
            "Gunakan /cancel untuk membatalkan operasi tersebut."
        )
        release_lock(user_id)
        return
    
    # Check if arguments are provided
    if len(message.command) < 2:
        await message.reply(
            "❌ Silakan masukkan username yang ingin diperiksa.\n"
            "Contoh: /check jaemin"
        )
        release_lock(user_id)
        return
    
    # Get username from command
    username = message.command[1].lower().replace("@", "")
    
    # Check if user still has generations left
    if not can_generate(user_id):
        await message.reply(
            "❌ Anda telah mencapai batas maksimum generasi. "
            "Silakan coba lagi nanti."
        )
        release_lock(user_id)
        return
    
    # Send initial message
    initial_message = await message.reply(f"⏳ Memulai pengecekan untuk @{username}...")
    
    # Start check task
    task = asyncio.create_task(
        check_specific_username(username, user_id, initial_message.id)
    )
    user_tasks[user_id] = task

@bot.on_message(filters.command("generate"))
async def generate_command(client, message: Message):
    """Handle /generate command"""
    user_id = message.from_user.id
    
    # Check if user is active
    if user_id not in active_users:
        add_user(user_id)
    
    # Check if user is rate limited
    if not acquire_lock(user_id):
        await message.reply(
            "⏳ Mohon tunggu sebentar sebelum mengirim perintah lagi."
        )
        return
    
    # Check if user already has an active task
    if user_id in user_tasks:
        await message.reply(
            "❌ Anda sudah memiliki operasi yang sedang berjalan. "
            "Gunakan /cancel untuk membatalkan operasi tersebut."
        )
        release_lock(user_id)
        return
    
    # Check if arguments are provided
    if len(message.command) < 2:
        await message.reply(
            "❌ Silakan masukkan username yang ingin digenerate.\n"
            "Contoh: /generate jaemin"
        )
        release_lock(user_id)
        return
    
    # Get username from command
    username = message.command[1].lower().replace("@", "")
    
    # Check if user still has generations left
    if not can_generate(user_id):
        await message.reply(
            "❌ Anda telah mencapai batas maksimum generasi. "
            "Silakan coba lagi nanti."
        )
        release_lock(user_id)
        return
    
    # Create generator selection menu
    keyboard = [
        [
            InlineKeyboardButton("OP", callback_data=f"gen_op_{username}"),
            InlineKeyboardButton("SOP", callback_data=f"gen_sop_{username}"),
        ],
        [
            InlineKeyboardButton("Canon", callback_data=f"gen_canon_{username}"),
            InlineKeyboardButton("Scanon", callback_data=f"gen_scanon_{username}"),
        ],
        [
            InlineKeyboardButton("Tamhur", callback_data=f"gen_tamhur_{username}"),
            InlineKeyboardButton("Ganhur", callback_data=f"gen_ganhur_{username}"),
        ],
        [
            InlineKeyboardButton("Switch", callback_data=f"gen_switch_{username}"),
            InlineKeyboardButton("Kurhuf", callback_data=f"gen_kurhuf_{username}"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="gen_cancel"),
        ]
    ]
    
    await message.reply(
        f"🔍 Pilih metode generate untuk username @{username}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    release_lock(user_id)

@bot.on_message(filters.command("cancel"))
async def cancel_command(client, message: Message):
    """Handle /cancel command"""
    user_id = message.from_user.id
    
    # Check if user has an active task
    if user_id in user_tasks:
        user_tasks[user_id].cancel()
        del user_tasks[user_id]
        release_lock(user_id)
        await message.reply("✅ Operasi dibatalkan.")
    else:
        await message.reply("❌ Tidak ada operasi yang sedang berjalan.")

@bot.on_callback_query(filters.regex(r"^gen_"))
async def handle_generator_callback(client, callback_query: CallbackQuery):
    """Handle generator callback queries"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    # Check if cancel was clicked
    if data == "gen_cancel":
        await callback_query.message.edit_text("❌ Generator dibatalkan.")
        return
    
    # Extract method and username
    parts = data.split("_")
    if len(parts) < 3:
        await callback_query.answer("❌ Format callback tidak valid.", show_alert=True)
        return
    
    method = parts[1]
    username = parts[2]
    
    # Check if user still has generations left
    if not can_generate(user_id):
        await callback_query.answer(
            "❌ Anda telah mencapai batas maksimum generasi.",
            show_alert=True
        )
        await callback_query.message.edit_text(
            "❌ Anda telah mencapai batas maksimum generasi. "
            "Silakan coba lagi nanti."
        )
        return
    
    # Check if user is rate limited
    if not acquire_lock(user_id):
        await callback_query.answer(
            "⏳ Mohon tunggu sebentar sebelum mengirim perintah lagi.",
            show_alert=True
        )
        return
    
    # Check if user already has an active task
    if user_id in user_tasks:
        await callback_query.answer(
            "❌ Anda sudah memiliki operasi yang sedang berjalan.",
            show_alert=True
        )
        release_lock(user_id)
        return
    
    # Update message to processing state
    await callback_query.message.edit_text(f"⏳ Memproses {method} untuk @{username}...")
    
    # Select generator method
    if method == "op":
        # OP just checks the username as is
        task = asyncio.create_task(
            check_specific_username(username, user_id, callback_query.message.id)
        )
    elif method == "sop":
        task = asyncio.create_task(
            check_generated_usernames(username, UsernameGenerator.sop, user_id, callback_query.message.id)
        )
    elif method == "canon":
        task = asyncio.create_task(
            check_generated_usernames(username, UsernameGenerator.canon, user_id, callback_query.message.id)
        )
    elif method == "scanon":
        task = asyncio.create_task(
            check_generated_usernames(username, UsernameGenerator.scanon, user_id, callback_query.message.id)
        )
    elif method == "tamhur":
        task = asyncio.create_task(
            check_generated_usernames(username, UsernameGenerator.tamhur, user_id, callback_query.message.id)
        )
    elif method == "ganhur":
        task = asyncio.create_task(
            check_generated_usernames(username, UsernameGenerator.ganhur, user_id, callback_query.message.id)
        )
    elif method == "switch":
        task = asyncio.create_task(
            check_generated_usernames(username, UsernameGenerator.switch, user_id, callback_query.message.id)
        )
    elif method == "kurhuf":
        task = asyncio.create_task(
            check_generated_usernames(username, UsernameGenerator.kurkuf, user_id, callback_query.message.id)
        )
    else:
        await callback_query.message.edit_text("❌ Metode tidak valid.")
        release_lock(user_id)
        return
    
    user_tasks[user_id] = task
    await callback_query.answer()

async def setup_bot():
    """Setup bot for polling mode - this explicitly enables polling"""
    try:
        # Client is already initialized in main(), so we skip initialization here
        
        # Log status for verification
        me = await bot.get_me()
        logger.info(f"Bot setup complete: @{me.username} (ID: {me.id})")
        logger.info(f"Bot is running in polling mode, ready to receive commands")
    except Exception as e:
        logger.error(f"Error in bot setup: {str(e)}")

async def main():
    """Main function to start the bot"""
    global checker
    
    try:
        # Start Flask server in background (just for uptime monitoring)
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        logger.info("✅ Flask server is running...")
        
        # Force set checker to be available in limited mode (no need for session)
        logger.info("📝 Operating bot in limited mode - username generation only, no availability checks")
        
        # Start the bot with polling mode explicitly enabled
        # No webhook will be used - pure polling mode
        await bot.start()
        logger.info("✅ Bot is running...")
        
        # Setup bot for polling mode
        await setup_bot()
        
        # Logging to indicate bot is ready to receive commands
        logger.info("🤖 Bot is ready to receive commands!")
        
        # Manual loop instead of idle to make bot more resilient
        while True:
            try:
                # Keep the bot running by waiting 
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                # Handle cancellation gracefully
                logger.info("Bot loop cancelled, shutting down...")
                break
        
    except Exception as e:
        logger.error(f"Error in main function: {str(e)}")
    finally:
        # Stop the bot when idle is interrupted
        try:
            await bot.stop()
        except Exception as e:
            logger.error(f"Error stopping bot: {str(e)}")
        
        # Stop checker client if it was started
        if checker and checker.running:
            try:
                await checker.stop()
            except Exception as e:
                logger.error(f"Error stopping checker: {str(e)}")

if __name__ == "__main__":
    # Run the bot with improved error handling
    try:
        # Create new event loop to avoid potential issues with existing loops
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run main function
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error running bot: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        try:
            # Clean up tasks
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()
                
            # Let cancelled tasks complete
            if tasks:
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                
            # Close the loop
            if not loop.is_closed():
                loop.close()
                
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")
        
        logger.info("Bot shutdown complete")