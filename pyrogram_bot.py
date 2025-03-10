import os
import asyncio
import logging
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
    PeerIdInvalid
)

# Import custom modules
from username_checker_pyrogram import UsernameChecker
from username_generator import UsernameGenerator
from user_manager import UserManager
from username_rules import (
    HURUF_RATA, 
    HURUF_TIDAK_RATA, 
    HURUF_VOKAL,
    UsernameTypes, 
    NameFormat
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("PyrogramBot")

# Load environment variables
load_dotenv()

# Bot configuration
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DUMMY_SESSION = os.getenv("DUMMY_SESSION", "dummy_session")

# Initialize the managers
user_manager = UserManager(max_users=40, max_generations=30, command_cooldown=3)

# Initialize the bot
app = Client("telegram_username_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Initialize the checker
checker = None

# Keep track of ongoing tasks
active_tasks = {}

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
    
    Args:
        base_name (str): Original username
        generator_method (function): Username generation method
        user_id (int): User ID for tracking
        message_id (int): Message ID for updates
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
        user_manager.increment_generation(user_id)
        
        # Update progress message
        await app.edit_message_text(
            user_id,
            message_id,
            f"⏳ Checking {len(generated_usernames)} usernames...\n"
            f"(0/{len(generated_usernames)} checked)"
        )
        
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
            await app.edit_message_text(
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
        await app.edit_message_text(user_id, message_id, result_text)
        
    except Exception as e:
        logger.error(f"Error in check_generated_usernames: {str(e)}")
        await app.edit_message_text(
            user_id,
            message_id,
            f"❌ Error saat melakukan pengecekan username:\n{str(e)}"
        )
    finally:
        # Clean up
        if user_id in active_tasks:
            del active_tasks[user_id]
        user_manager.release_lock(user_id)

async def check_specific_username(username, user_id, message_id):
    """
    Check a specific username
    
    Args:
        username (str): Username to check
        user_id (int): User ID for tracking
        message_id (int): Message ID for updates
    """
    try:
        # Count as a generation
        user_manager.increment_generation(user_id)
        
        # Update progress message
        await app.edit_message_text(
            user_id,
            message_id,
            f"⏳ Checking @{username}..."
        )
        
        # Check the username
        result = await checker.check_username(username)
        
        # Format the result
        formatted_result = format_username_result(result)
        
        # Send result
        await app.edit_message_text(
            user_id,
            message_id,
            f"🔍 **Hasil Pengecekan Username**\n\n{formatted_result}"
        )
        
    except Exception as e:
        logger.error(f"Error in check_specific_username: {str(e)}")
        await app.edit_message_text(
            user_id,
            message_id,
            f"❌ Error saat melakukan pengecekan username:\n{str(e)}"
        )
    finally:
        # Clean up
        if user_id in active_tasks:
            del active_tasks[user_id]
        user_manager.release_lock(user_id)

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    """Handle /start command"""
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # Add user to active users
    if not user_manager.can_add_user(user_id):
        await message.reply(
            "❌ Bot sedang dalam kapasitas penuh. Silakan coba lagi nanti."
        )
        return
        
    user_manager.add_user(user_id)
    
    # Welcome message
    welcome_text = (
        f"👋 Halo {user_name}!\n\n"
        f"Selamat datang di Bot Cek Username Telegram\n\n"
        f"🔍 Bot ini dapat membantu Anda memeriksa ketersediaan username Telegram "
        f"dan menghasilkan variasi username berdasarkan berbagai metode.\n\n"
        f"Gunakan /help untuk melihat daftar perintah yang tersedia.\n\n"
        f"Sisa generasi Anda: {user_manager.get_remaining_generations(user_id)}/{user_manager.max_generations}"
    )
    
    await message.reply(welcome_text)

@app.on_message(filters.command("help"))
async def help_command(client, message: Message):
    """Handle /help command"""
    user_id = message.from_user.id
    
    # Check if user is active
    if user_id not in user_manager.active_users:
        user_manager.add_user(user_id)
    
    help_text = (
        "🔍 **Perintah yang tersedia:**\n\n"
        "• /start - Memulai bot\n"
        "• /help - Menampilkan pesan bantuan ini\n"
        "• /check username - Memeriksa satu username tertentu\n"
        "• /generate username - Menampilkan menu generator username\n"
        "• /stats - Menampilkan statistik penggunaan bot\n"
        "• /cancel - Membatalkan operasi yang sedang berjalan\n\n"
        "**Format Username:**\n"
        "• Huruf Rata: aceimnorsuvwxz\n"
        "• Huruf Tidak Rata: bdfghjklpqty\n"
        "• Huruf Vokal: aiueo\n\n"
        "**Jenis Generator:**\n"
        "• OP (On Point) - Tanpa modifikasi\n"
        "• SOP (Semi On Point) - Menggandakan huruf (mis. jjaem, jaeemmin)\n"
        "• Canon - Tukar i/L (mis. jaemin → jaeml̇n)\n"
        "• Scanon - Tambah huruf 's' di akhir (mis. jaemins)\n"
        "• Tamhur - Tambah satu huruf di mana saja\n"
        "• Ganhur - Ganti satu huruf dengan huruf sejenis\n"
        "• Switch - Tukar posisi dua huruf bersebelahan\n"
        "• Kurhuf - Kurangi satu huruf\n\n"
        f"Sisa generasi Anda: {user_manager.get_remaining_generations(user_id)}/{user_manager.max_generations}"
    )
    
    await message.reply(help_text)

@app.on_message(filters.command("stats"))
async def stats_command(client, message: Message):
    """Handle /stats command"""
    user_id = message.from_user.id
    
    # Get stats
    stats = user_manager.get_stats()
    remaining = user_manager.get_remaining_generations(user_id)
    
    stats_text = (
        "📊 **Statistik Bot**\n\n"
        f"👤 Pengguna aktif: {stats['active_users']}/{stats['max_users']}\n"
        f"🔄 Sisa generasi Anda: {remaining}/{user_manager.max_generations}\n"
    )
    
    await message.reply(stats_text)

@app.on_message(filters.command("check"))
async def check_command(client, message: Message):
    """Handle /check command"""
    user_id = message.from_user.id
    
    # Check if user is active
    if user_id not in user_manager.active_users:
        user_manager.add_user(user_id)
    
    # Check if user is rate limited
    if not user_manager.acquire_lock(user_id):
        await message.reply(
            "⏳ Mohon tunggu sebentar sebelum mengirim perintah lagi."
        )
        return
    
    # Check if user already has an active task
    if user_id in active_tasks:
        await message.reply(
            "❌ Anda sudah memiliki operasi yang sedang berjalan. "
            "Gunakan /cancel untuk membatalkan operasi tersebut."
        )
        user_manager.release_lock(user_id)
        return
    
    # Check if arguments are provided
    if len(message.command) < 2:
        await message.reply(
            "❌ Silakan masukkan username yang ingin diperiksa.\n"
            "Contoh: /check jaemin"
        )
        user_manager.release_lock(user_id)
        return
    
    # Get username from command
    username = message.command[1].lower().replace("@", "")
    
    # Check if user still has generations left
    if not user_manager.can_generate(user_id):
        await message.reply(
            "❌ Anda telah mencapai batas maksimum generasi. "
            "Silakan coba lagi nanti."
        )
        user_manager.release_lock(user_id)
        return
    
    # Send initial message
    initial_message = await message.reply(f"⏳ Memulai pengecekan untuk @{username}...")
    
    # Start check task
    task = asyncio.create_task(
        check_specific_username(username, user_id, initial_message.id)
    )
    active_tasks[user_id] = task

@app.on_message(filters.command("generate"))
async def generate_command(client, message: Message):
    """Handle /generate command"""
    user_id = message.from_user.id
    
    # Check if user is active
    if user_id not in user_manager.active_users:
        user_manager.add_user(user_id)
    
    # Check if user is rate limited
    if not user_manager.acquire_lock(user_id):
        await message.reply(
            "⏳ Mohon tunggu sebentar sebelum mengirim perintah lagi."
        )
        return
    
    # Check if user already has an active task
    if user_id in active_tasks:
        await message.reply(
            "❌ Anda sudah memiliki operasi yang sedang berjalan. "
            "Gunakan /cancel untuk membatalkan operasi tersebut."
        )
        user_manager.release_lock(user_id)
        return
    
    # Check if arguments are provided
    if len(message.command) < 2:
        await message.reply(
            "❌ Silakan masukkan username yang ingin digenerate.\n"
            "Contoh: /generate jaemin"
        )
        user_manager.release_lock(user_id)
        return
    
    # Get username from command
    username = message.command[1].lower().replace("@", "")
    
    # Check if user still has generations left
    if not user_manager.can_generate(user_id):
        await message.reply(
            "❌ Anda telah mencapai batas maksimum generasi. "
            "Silakan coba lagi nanti."
        )
        user_manager.release_lock(user_id)
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
    user_manager.release_lock(user_id)

@app.on_message(filters.command("cancel"))
async def cancel_command(client, message: Message):
    """Handle /cancel command"""
    user_id = message.from_user.id
    
    # Check if user has an active task
    if user_id in active_tasks:
        active_tasks[user_id].cancel()
        del active_tasks[user_id]
        user_manager.release_lock(user_id)
        await message.reply("✅ Operasi dibatalkan.")
    else:
        await message.reply("❌ Tidak ada operasi yang sedang berjalan.")

@app.on_callback_query(filters.regex(r"^gen_"))
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
    if not user_manager.can_generate(user_id):
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
    if not user_manager.acquire_lock(user_id):
        await callback_query.answer(
            "⏳ Mohon tunggu sebentar sebelum mengirim perintah lagi.",
            show_alert=True
        )
        return
    
    # Check if user already has an active task
    if user_id in active_tasks:
        await callback_query.answer(
            "❌ Anda sudah memiliki operasi yang sedang berjalan.",
            show_alert=True
        )
        user_manager.release_lock(user_id)
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
        user_manager.release_lock(user_id)
        return
    
    active_tasks[user_id] = task
    await callback_query.answer()

async def startup():
    """Initialize everything at startup"""
    global checker
    
    try:
        # Initialize username checker with Pyrogram
        checker = UsernameChecker(API_ID, API_HASH, DUMMY_SESSION)
        await checker.start()
        
        # Start the bot
        await app.start()
        logger.info("Bot started. Press Ctrl+C to exit.")
        
        # Wait for idle
        await idle()
    except Exception as e:
        logger.error(f"Error in startup: {str(e)}")
    finally:
        # Cleanup
        if checker:
            await checker.stop()
        await app.stop()

if __name__ == "__main__":
    # Run the startup coroutine
    loop = asyncio.get_event_loop()
    loop.run_until_complete(startup())