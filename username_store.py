import time
from typing import Dict, Set, Tuple
import asyncio
import logging

logger = logging.getLogger(__name__)

class UsernameStore:
    def __init__(self):
        self._store: Dict[str, Set[Tuple[str, float]]] = {}  # base_name -> set of (generated_name, timestamp)
        self._cleanup_task = None

    def add_username(self, base_name: str, generated_name: str) -> None:
        """Add a generated username with current timestamp"""
        if base_name not in self._store:
            self._store[base_name] = set()
        self._store[base_name].add((generated_name, time.time()))
        logger.info(f"Stored generated username '{generated_name}' for base name '{base_name}'")

    def is_generated(self, base_name: str, username: str) -> bool:
        """Check if username was previously generated from base_name"""
        if base_name not in self._store:
            logger.debug(f"No stored usernames found for base name '{base_name}'")
            return False
        is_found = any(username == gen_name for gen_name, _ in self._store[base_name])
        if is_found:
            logger.info(f"Username '{username}' was previously generated from '{base_name}'")
        return is_found

    def cleanup_old_entries(self) -> None:
        """Remove entries older than 1 hour"""
        current_time = time.time()
        hour_ago = current_time - 3600  # 1 hour in seconds

        total_removed = 0
        for base_name in list(self._store.keys()):
            # Count entries before cleanup
            before_count = len(self._store[base_name])

            # Filter out old entries
            current_entries = {
                (name, ts) for name, ts in self._store[base_name]
                if ts > hour_ago
            }

            if current_entries:
                self._store[base_name] = current_entries
                removed_count = before_count - len(current_entries)
                if removed_count > 0:
                    logger.info(f"Removed {removed_count} old usernames for base name '{base_name}'")
                    total_removed += removed_count
            else:
                del self._store[base_name]
                logger.info(f"Removed all entries for base name '{base_name}' ({before_count} usernames)")
                total_removed += before_count

        logger.info(f"Cleaned up {total_removed} old username entries")

    async def start_cleanup_task(self):
        """Start periodic cleanup task"""
        while True:
            self.cleanup_old_entries()
            await asyncio.sleep(300)  # Run cleanup every 5 minutes