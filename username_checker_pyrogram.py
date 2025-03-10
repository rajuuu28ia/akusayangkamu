import asyncio
import logging
import time
import aiohttp
import re
from pyrogram import Client
from pyrogram.errors import (
    FloodWait, 
    BadRequest, 
    UsernameInvalid, 
    UsernameOccupied,
    UsernameNotOccupied
)
from config import RESERVED_WORDS

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UsernameChecker")

class UsernameChecker:
    def __init__(self, session_string=None):
        """
        Initialize username checker with Pyrogram
        
        Args:
            session_string (str): Session string for authentication, or None for limited mode
        """
        self.session_string = session_string
        self.client = None  # Will be initialized only if session_string is provided
        self.last_check_time = 0
        self.min_delay = 1.5  # Minimum delay between checks in seconds
        self.cache = {}  # Cache for username availability results
        self.cache_timeout = 900  # Cache timeout in seconds (15 minutes)
        self.running = False
        self.rate_limit_hit = False
        self.ready = False
        self.limited_mode = session_string is None
        
        if self.limited_mode:
            logger.info("Username checker initialized in limited mode (no user session)")
        else:
            logger.info("Username checker initialized with user session")
        
    async def start(self):
        """Start the Pyrogram client"""
        # In limited mode, we don't need to start a client
        if self.limited_mode:
            self.running = True
            self.ready = True
            logger.info("Username checker running in limited mode (no client)")
            return
            
        # Only start if we have a session and client isn't already running
        if not self.running and not self.limited_mode:
            if self.client:
                try:
                    await self.client.start()
                    self.running = True
                    self.ready = True
                    logger.info("Pyrogram client started")
                except Exception as e:
                    logger.error(f"Failed to start Pyrogram client: {str(e)}")
                    # If client fails to start, switch to limited mode
                    self.limited_mode = True
                    self.running = True
                    self.ready = True
                    logger.info("Switched to limited mode due to client start failure")
            else:
                # No client, switch to limited mode
                self.limited_mode = True
                self.running = True
                self.ready = True
                logger.info("No client available, running in limited mode")
            
    async def stop(self):
        """Stop the Pyrogram client"""
        # Only try to stop if not in limited mode and client is running
        if self.running and not self.limited_mode and self.client:
            try:
                await self.client.stop()
            except Exception as e:
                logger.error(f"Error stopping client: {str(e)}")
                
        # Always mark as stopped regardless of client state
        self.running = False
        self.ready = False
        logger.info("Username checker stopped")
            
    async def is_ready(self):
        """Check if client is ready"""
        return self.ready and self.running

    def _enforce_delay(self):
        """Enforce minimum delay between API calls to avoid rate limits"""
        current_time = time.time()
        time_since_last_check = current_time - self.last_check_time
        
        if time_since_last_check < self.min_delay:
            delay_needed = self.min_delay - time_since_last_check
            time.sleep(delay_needed)
            
        self.last_check_time = time.time()
        
    async def _handle_flood_wait(self, flood_wait_seconds):
        """Handle FloodWait error by adjusting delay and waiting"""
        logger.warning(f"FloodWait encountered: {flood_wait_seconds}s")
        self.rate_limit_hit = True
        self.min_delay = max(self.min_delay, flood_wait_seconds / 5)
        await asyncio.sleep(flood_wait_seconds + 0.5)
        self.rate_limit_hit = False
        
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
        """
        Check if username follows Telegram's format rules
        """
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
        """
        Check if a username is available using Pyrogram
        
        Args:
            username (str): Username to check
            
        Returns:
            dict: Result containing availability status and type
        """
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
            
        # If we're in limited mode, return a valid-but-unknown result
        if self.limited_mode:
            result = {
                "username": username,
                "available": False,  # Assume unavailable in limited mode
                "valid": True,
                "type": "unknown",
                "message": "Bot in limited mode, unable to check with Telegram API"
            }
            self._cache_result(username, result)
            return result
        
        # Enforce rate limiting delay
        self._enforce_delay()
        
        result = {
            "username": username,
            "available": False,
            "valid": True,
            "type": "unknown",
            "message": ""
        }
        
        # Skip API check if no client or in limited mode
        if not self.client:
            result["message"] = "No client available for checking"
            self._cache_result(username, result)
            return result
        
        try:
            # Try to get username info
            chat = await self.client.get_chat(username)
            
            # Username exists, determine the type
            if chat.type == "private":
                result["type"] = "user"
                if chat.is_premium:
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
            
        except BadRequest as e:
            # Handle bad request errors
            if "username is invalid" in str(e).lower():
                result["valid"] = False
                result["type"] = "invalid"
                result["message"] = "Username is invalid"
            else:
                result["valid"] = False
                result["type"] = "error"
                result["message"] = f"Error: {str(e)}"
                
        except Exception as e:
            # Handle other errors
            logger.error(f"Error checking username {username}: {str(e)}")
            result["valid"] = False
            result["type"] = "error"
            result["message"] = f"Error: {str(e)}"
            
        # Cache the result
        self._cache_result(username, result)
        return result

    async def check_usernames_batch(self, usernames, max_concurrency=3):
        """
        Check availability for multiple usernames with rate limiting
        
        Args:
            usernames (list): List of usernames to check
            max_concurrency (int): Maximum number of concurrent checks
            
        Returns:
            dict: Results for each username
        """
        # If in limited mode, return a simplified batch result
        if self.limited_mode:
            results = {}
            for username in usernames:
                results[username] = {
                    "username": username,
                    "available": False,  # Assume unavailable in limited mode
                    "valid": self._is_valid_username(username),
                    "type": "unknown" if self._is_valid_username(username) else "invalid_format",
                    "message": "Bot in limited mode, unable to check with Telegram API"
                }
            return results
        
        # Regular batch processing with API
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
        
    async def verify_with_fragment_api(self, username):
        """
        Secondary verification using Fragment API to verify banned usernames
        
        Args:
            username (str): Username to check
            
        Returns:
            bool or None: True if available, False if taken, None if can't determine
        """
        url = f"https://fragment.com/username/{username}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                        
                    text = await response.text()
                    
                    # Check banned pattern
                    if "unavailable to register" in text.lower():
                        return False
                        
                    # Check available pattern 
                    if "available for registration" in text.lower():
                        return True
                        
                    return None
                    
            except Exception as e:
                logger.error(f"Error checking Fragment API for {username}: {str(e)}")
                return None