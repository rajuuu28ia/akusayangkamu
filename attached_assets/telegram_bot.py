import logging
import os
import sys
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import asyncio
import io
from contextlib import redirect_stderr

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from checker.main import TelegramUsernameChecker
from utils.logging_config import setup_logging

logger = setup_logging()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

async def start(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    welcome_msg = (
        "👋 Welcome to the Telegram Username Checker Bot!\n\n"
        "I can help you check if Telegram usernames are available.\n"
        "Commands:\n"
        "- Send any username or multiple usernames (up to 30) to check\n"
        "- /checklist [URL] - Check multiple usernames from a file\n"
        "- /help - Show this help message"
    )
    await update.message.reply_text(welcome_msg)

async def help_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    help_msg = (
        "🔍 How to use this bot:\n\n"
        "1. Check single or multiple usernames:\n"
        "   Send username(s) with or without @ symbol\n"
        "   Example: username1 username2 username3\n"
        "   Maximum 30 usernames at once\n\n"
        "2. Check from file:\n"
        "   Use /checklist with a URL to a text file\n"
        "   Example: /checklist https://example.com/usernames.txt\n\n"
        "The file should contain one username per line"
    )
    await update.message.reply_text(help_msg)

async def check_username(update: Update, context: CallbackContext) -> None:
    """Check single or multiple usernames availability."""
    text = update.message.text.strip()

    # Split text into usernames, handle multiple formats and clean them
    usernames = []
    for name in text.split():
        # Remove @ if present and clean
        cleaned_name = name.lstrip('@').strip()
        if cleaned_name:  # Only add non-empty usernames
            usernames.append(cleaned_name)

    if len(usernames) > 30:
        await update.message.reply_text("⚠️ Maksimal 30 username dalam satu pesan. Akan mengecek 30 username pertama.")
        usernames = usernames[:30]

    # Create a custom handler that writes to a string buffer
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(message)s'))

    # Add the handler to the logger
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        checker = TelegramUsernameChecker(verbose=True)

        for username in usernames:
            # Reset buffer before each check
            log_buffer.truncate(0)
            log_buffer.seek(0)

            try:
                result = await checker.check_username(username)
                # Get the captured output
                log_output = log_buffer.getvalue().strip()
                if log_output:
                    await update.message.reply_text(log_output)

                await asyncio.sleep(2)  # Delay between checks

            except Exception as e:
                logger.error(f"Error checking username {username}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error in batch check: {e}")
        await update.message.reply_text(f"❌ Error checking usernames: {str(e)}")
    finally:
        # Clean up
        root_logger.removeHandler(handler)

async def check_usernames_list(update: Update, context: CallbackContext) -> None:
    """Check multiple usernames from a file URL."""
    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide a URL to a file with usernames.\n"
            "Usage: /checklist [URL]"
        )
        return

    file_url = context.args[0]
    await update.message.reply_text("📥 Loading usernames from file...")

    # Create a custom handler that writes to a string buffer
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(message)s'))

    # Add the handler to the logger
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        checker = TelegramUsernameChecker(file_path=file_url, verbose=True)

        if not checker.load():
            await update.message.reply_text("❌ Failed to load usernames from the URL")
            return

        await update.message.reply_text("✅ Usernames loaded. Starting checks...")

        # Limit number of usernames to check
        usernames = list(checker.usernames)[:30]

        for username in usernames:
            # Reset buffer before each check
            log_buffer.truncate(0)
            log_buffer.seek(0)

            try:
                result = await checker.check_username(username)
                # Get the captured output
                log_output = log_buffer.getvalue().strip()
                if log_output:
                    await update.message.reply_text(log_output)

                await asyncio.sleep(2)  # Delay between checks

            except Exception as e:
                logger.error(f"Error checking username {username}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error in batch check: {e}")
        await update.message.reply_text(f"❌ Error checking usernames: {str(e)}")
    finally:
        # Clean up
        root_logger.removeHandler(handler)

def main() -> None:
    """Start the bot."""
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("checklist", check_usernames_list))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_username))

    logger.info("Bot started")
    application.run_polling()

if __name__ == "__main__":
    main()