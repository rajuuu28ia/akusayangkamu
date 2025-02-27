
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import sys
import os

# Add the telegram-username-grabber directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'telegram-username-grabber'))
from main import TelegramUsernameChecker

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get the token from environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

async def start(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text('Hi! I can check Telegram usernames for you. Send me a username to check.')

async def help_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text('Send me a username (without @) to check if it\'s available or taken.')

async def check_username(update: Update, context: CallbackContext) -> None:
    """Check the username and send the result."""
    username = update.message.text.strip()
    
    # Remove @ if present
    if username.startswith('@'):
        username = username[1:]
    
    await update.message.reply_text(f"Checking username: @{username}...")
    
    # Create a checker instance
    checker = TelegramUsernameChecker(file_path=None, verbose=True)
    
    # Setup logging to capture output
    import io
    import logging
    from contextlib import redirect_stderr
    
    # Create a custom handler that writes to a string buffer
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(message)s'))
    
    # Add the handler to the logger
    logger = logging.getLogger(__name__)
    logger.addHandler(handler)
    
    # Check the username
    try:
        result = checker.check(username)
        
        # Get the captured output
        log_output = log_buffer.getvalue().strip()
        
        # Send the result
        if log_output:
            await update.message.reply_text(log_output)
        else:
            status = "Available" if result else "Not available or has issues"
            await update.message.reply_text(f"Result for @{username}: {status}")
    except Exception as e:
        await update.message.reply_text(f"Error checking username: {str(e)}")
    finally:
        # Clean up
        logger.removeHandler(handler)


async def check_usernames_list(update: Update, context: CallbackContext) -> None:
    if not context.args:
        await update.message.reply_text("Please provide a URL to a file with usernames. Usage: /checklist [URL]")
        return

    file_url = context.args[0]
    checker = TelegramUsernameChecker(file_path=file_url, verbose=True)

    if checker.load():
        await update.message.reply_text("Usernames loaded successfully. Starting checks...")
        
        usernames = list(checker.usernames)[:30]  # Batasi hingga 30 username
        batch_size = 10  # Cek 10 username per batch

        results = await checker.batch_check(usernames, batch_size=batch_size)

        result_messages = [f"@{username} {'✅ Available' if res else '🚫 Taken'}" for username, res in zip(usernames, results)]
        await update.message.reply_text("\n".join(result_messages))

    else:
        await update.message.reply_text("Failed to load usernames.")
update: Update, context: CallbackContext) -> None:
    """Check a list of usernames from a file URL."""
    if not context.args:
        await update.message.reply_text("Please provide a URL to a file with usernames. Usage: /checklist [URL]")
        return
    
    file_url = context.args[0]
    await update.message.reply_text(f"Checking usernames from: {file_url}...")
    
    # Create a checker instance
    checker = TelegramUsernameChecker(file_path=file_url, verbose=True)
    
    # Load and check usernames
    if checker.load():
        await update.message.reply_text("Usernames loaded successfully. Starting checks...")
        
        # Process only a limited number to avoid timeouts
        limited_usernames = list(checker.usernames)[:10]  # Limit to 10 usernames
        
        # Setup logging to capture output
        import io
        import logging
        
        # Create a custom handler that writes to a string buffer
        log_buffer = io.StringIO()
        handler = logging.StreamHandler(log_buffer)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('%(message)s'))
        
        # Add the handler to the logger
        logger = logging.getLogger(__name__)
        logger.addHandler(handler)
        
        try:
            for username in limited_usernames:
                # Reset buffer before each check
                log_buffer.truncate(0)
                log_buffer.seek(0)
                
                # Check the username
                checker.check(username)
                
                # Get the captured output
                log_output = log_buffer.getvalue().strip()
                
                # Send the result
                if log_output:
                    await update.message.reply_text(log_output)
            
            await update.message.reply_text("Finished checking usernames.")
        except Exception as e:
            await update.message.reply_text(f"Error checking usernames: {str(e)}")
        finally:
            # Clean up
            logger.removeHandler(handler)
    else:
        await update.message.reply_text("Failed to load usernames from the provided URL.")

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("checklist", check_usernames_list))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_username))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == "__main__":
    main()
