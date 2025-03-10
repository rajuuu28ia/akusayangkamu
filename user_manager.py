import time
import logging
from collections import defaultdict

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UserManager")

class UserManager:
    def __init__(self, max_users=40, max_generations=30, command_cooldown=3):
        """
        Initialize user manager with limits
        
        Args:
            max_users (int): Maximum concurrent users
            max_generations (int): Maximum generations per user
            command_cooldown (int): Cooldown between commands in seconds
        """
        self.active_users = set()  # Set of active user IDs
        self.user_generations = defaultdict(int)  # Count of generations per user
        self.user_locks = {}  # Command locks per user
        self.max_users = max_users
        self.max_generations = max_generations
        self.command_cooldown = command_cooldown
        
    def can_add_user(self, user_id):
        """Check if a new user can be added"""
        return len(self.active_users) < self.max_users or user_id in self.active_users
        
    def add_user(self, user_id):
        """Add a user to active users"""
        if len(self.active_users) < self.max_users or user_id in self.active_users:
            self.active_users.add(user_id)
            logger.info(f"Added user {user_id}, active users: {len(self.active_users)}")
            return True
        return False
        
    def remove_user(self, user_id):
        """Remove a user from active users"""
        if user_id in self.active_users:
            self.active_users.remove(user_id)
            if user_id in self.user_generations:
                del self.user_generations[user_id]
            if user_id in self.user_locks:
                del self.user_locks[user_id]
            logger.info(f"Removed user {user_id}, active users: {len(self.active_users)}")
            
    def can_generate(self, user_id):
        """Check if user can generate more usernames"""
        return self.user_generations.get(user_id, 0) < self.max_generations
        
    def increment_generation(self, user_id):
        """Increment generation count for a user"""
        self.user_generations[user_id] += 1
        return self.user_generations[user_id]
        
    def get_remaining_generations(self, user_id):
        """Get remaining generations for a user"""
        return self.max_generations - self.user_generations.get(user_id, 0)
        
    def reset_generations(self, user_id):
        """Reset generation count for a user"""
        if user_id in self.user_generations:
            self.user_generations[user_id] = 0
            
    def acquire_lock(self, user_id):
        """Try to acquire a command lock for a user"""
        current_time = time.time()
        
        # Check if user is locked and lock hasn't expired
        if user_id in self.user_locks:
            lock_time, locked = self.user_locks[user_id]
            if locked and (current_time - lock_time) < self.command_cooldown:
                # Lock is still active
                return False
                
        # Set or update lock
        self.user_locks[user_id] = (current_time, True)
        return True
        
    def release_lock(self, user_id):
        """Release a command lock for a user"""
        if user_id in self.user_locks:
            self.user_locks[user_id] = (self.user_locks[user_id][0], False)
            
    def get_stats(self):
        """Get current usage statistics"""
        return {
            "active_users": len(self.active_users),
            "max_users": self.max_users,
            "user_generations": dict(self.user_generations)
        }