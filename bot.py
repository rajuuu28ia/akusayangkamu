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
bot = Client(
    "username_bot",
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    bot_token=BOT_TOKEN
)

# Username checker class
class UsernameChecker:
    def __init__(self, session_string):
        self.client = Client(
            "username_checker_session",
            api_id=TELEGRAM_API_ID,
            api_hash=TELEGRAM_API_HASH,
            session_string=session_string
        )
        self.last_check_time = 0
        self.min_delay = RATE_LIMIT_DELAY
        self.cache = {}
        self.cache_timeout = 900  # 15 minutes
        self.running = False
        
    async def start(self):
        if not self.running:
            await self.client.start()
            self.running = True
            logger.info("Username checker client started")
            
    async def stop(self):
        if self.running:
            await self.client.stop()
            self.running = False
            logger.info("Username checker client stopped")
    
    def _enforce_delay(self):
        """Enforce minimum delay between requests"""
        current_time = time.time()
        time_since_last_check = current_time - self.last_check_time
        
        if time_since_last_check < self.min_delay:
            delay_needed = self.min_delay - time_since_last_check
            time.sleep(delay_needed)
            
        self.last_check_time = time.time()
        
    async def _handle_flood_wait(self, seconds):
        """Handle FloodWait by adjusting delay and waiting"""
        logger.warning(f"FloodWait: {seconds}s")
        self.min_delay = max(self.min_delay, seconds / 5)
        await asyncio.sleep(seconds + 0.5)
        
    def _is_cached(self, username):
        """Check if username is in cache and not expired"""
        if username in self.cache:
            cache_time, result = self.cache[username]
            if time.time() - cache_time < self.cache_timeout:
                return True, result
        return False, None
        
    def _cache_result(self, username, result):
        """Cache username availability result"""
        self.cache[username] = (time.time(), result)
        
    def _is_valid_username(self, username):
        """Verify if username follows Telegram format rules"""
        # Telegram username rules
        if not 5 <= len(username) <= 32:
            return False
        
        # Must start with a letter, contain only letters, numbers and underscores
        if not re.match(r'^[a-zA-Z][\w\d_]*$', username):
            return False
            
        # Cannot contain consecutive underscores
        if '__' in username:
            return False
            
        # Cannot end with an underscore
        if username.endswith('_'):
            return False
            
        # Check against reserved words
        if username.lower() in RESERVED_WORDS:
            return False
            
        return True
        
    async def check_username(self, username):
        """Check username availability"""
        # Pre-validate username format
        if not self._is_valid_username(username):
            return {
                "username": username,
                "available": False,
                "valid": False,
                "type": "invalid_format",
                "message": "Invalid username format"
            }
        
        # Check cache first
        is_cached, cached_result = self._is_cached(username)
        if is_cached:
            return cached_result
        
        # Enforce rate limiting delay
        self._enforce_delay()
        
        result = {
            "username": username,
            "available": False,
            "valid": True,
            "type": "unknown",
            "message": ""
        }
        
        try:
            # Try to get username info
            chat = await self.client.get_chat(username)
            
            # Username exists, determine the type
            if chat.type == "private":
                result["type"] = "user"
                if getattr(chat, "is_premium", False):
                    result["type"] = "premium_user"
            elif chat.type == "bot":
                result["type"] = "bot"
            elif chat.type == "channel":
                result["type"] = "channel"
            elif chat.type in ["group", "supergroup"]:
                result["type"] = "group"
            
            result["message"] = f"Username taken by {result['type']}"
            
        except UsernameNotOccupied:
            # Username is available
            result["available"] = True
            result["type"] = "available"
            result["message"] = "Username is available"
            
        except UsernameInvalid:
            # Username is invalid (might be banned or reserved)
            result["valid"] = False
            result["type"] = "banned_or_reserved"
            result["message"] = "Username is invalid, banned, or reserved"
            
        except UsernameOccupied:
            # Username is taken
            result["type"] = "occupied"
            result["message"] = "Username is taken"
            
        except FloodWait as e:
            # Handle rate limiting
            await self._handle_flood_wait(e.value)
            # Retry the check after waiting
            return await self.check_username(username)
            
        except Exception as e:
            # Handle other errors
            logger.error(f"Error checking username {username}: {str(e)}")
            result["valid"] = False
            result["type"] = "error"
            result["message"] = f"Error: {str(e)}"
            
        # Cache the result
        self._cache_result(username, result)
        return result
    
    async def verify_with_fragment_api(self, username):
        """Verify username with Fragment API (for banned detection)"""
        import aiohttp
        
        url = f"https://fragment.com/username/{username}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                        
                    text = await response.text()
                    
                    if "unavailable to register" in text.lower():
                        return False
                    if "available for registration" in text.lower():
                        return True
                    return None
                    
            except Exception as e:
                logger.error(f"Error checking Fragment API: {str(e)}")
                return None
                
    async def check_usernames_batch(self, usernames, max_concurrency=3):
        """Check multiple usernames with rate limiting"""
        results = {}
        sem = asyncio.Semaphore(max_concurrency)
        
        async def check_with_semaphore(username):
            async with sem:
                return await self.check_username(username)
        
        tasks = [check_with_semaphore(username) for username in usernames]
        results_list = await asyncio.gather(*tasks)
        
        for result in results_list:
            results[result["username"]] = result
            
        return results

# Create username checker instance
checker = None
if SESSION_STRING and TELEGRAM_API_ID and TELEGRAM_API_HASH:
    try:
        # Extra validation for session string
        if len(SESSION_STRING) % 4 != 0:
            logger.warning("Session string length is not divisible by 4, possible invalid base64")
            # Try to fix common base64 padding issues
            fixed_session = SESSION_STRING
            while len(fixed_session) % 4 != 0:
                fixed_session += "="
            logger.info("Attempting to use fixed session string")
            checker = UsernameChecker(fixed_session)
        else:
            checker = UsernameChecker(SESSION_STRING)
            
        logger.info("Username checker created with provided session string")
    except Exception as e:
        logger.error(f"Error creating username checker: {str(e)}")
        # Fallback to bot-only mode if session string is invalid
        logger.warning("Bot will run without username checker capability")
else:
    logger.warning("Required credentials for username checker not provided")
    logger.warning("Bot will run without username checker capability")

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
        
        # Check if checker is available
        if checker is None:
            # If no checker available, show generated usernames without checking
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
        
        # Check if checker is available
        if checker is None:
            # If no checker available, inform user
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
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # Add user to active users
    if not can_add_user(user_id):
        await message.reply(
            "❌ Bot sedang dalam kapasitas penuh. Silakan coba lagi nanti."
        )
        return
        
    add_user(user_id)
    
    # Welcome message
    welcome_text = (
        f"👋 Halo {user_name}!\n\n"
        f"Selamat datang di Bot Cek Username Telegram\n\n"
        f"🔍 Bot ini dapat membantu Anda memeriksa ketersediaan username Telegram "
        f"dan menghasilkan variasi username berdasarkan berbagai metode.\n\n"
        f"Gunakan /help untuk melihat daftar perintah yang tersedia.\n\n"
        f"Sisa generasi Anda: {get_remaining_generations(user_id)}/{MAX_GENERATIONS_PER_USER}"
    )
    
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
    """Setup bot for polling mode"""
    try:
        # Pyrogram doesn't have delete_webhook method, so we skip this step
        logger.info("Bot setup complete for polling mode")
    except Exception as e:
        logger.error(f"Error in bot setup: {str(e)}")

async def main():
    """Main function to start the bot"""
    global checker
    
    try:
        # Start Flask server in background
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        logger.info("✅ Flask server is running...")
        
        # Start the bot
        await bot.start()
        logger.info("✅ Bot is running...")
        
        # Setup bot for polling mode
        await setup_bot()
        
        # Try to start checker client if available
        if checker:
            try:
                await checker.start()
                logger.info("Username checker client started successfully")
            except Exception as e:
                logger.error(f"Failed to start username checker: {str(e)}")
                logger.warning("Bot will run without username checker capability")
                checker = None
        
        # Keep the bot running, even without checker
        await idle()
        
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