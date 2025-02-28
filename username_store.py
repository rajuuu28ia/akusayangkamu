import time
from typing import Dict, Set, Tuple
import asyncio
import logging

logger = logging.getLogger(__name__)

class UsernameStore:
    def __init__(self):
        self._store: Dict[str, Set[Tuple[str, float]]] = {}  # base_name -> set of (generated_name, timestamp)
        self._cleanup_task = None
        self._completed_generations: Set[str] = set()  # Track completed base_names

    def add_username(self, base_name: str, generated_name: str) -> None:
        """Add a generated username with current timestamp"""
        if base_name not in self._store:
            self._store[base_name] = set()
        self._store[base_name].add((generated_name, time.time()))
        logger.info(f"Stored generated username '{generated_name}' for base name '{base_name}'")

    def mark_generation_complete(self, base_name: str) -> None:
        """Mark a base_name's generation as complete"""
        self._completed_generations.add(base_name)
        logger.info(f"Marked generation complete for base name '{base_name}'")

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
        """Remove entries that are complete and older than 5 minutes"""
        current_time = time.time()
        five_minutes_ago = current_time - 300  # 5 minutes in seconds

        total_removed = 0
        for base_name in list(self._store.keys()):
            # Count entries before cleanup
            before_count = len(self._store[base_name])

            # If generation is complete, check time
            if base_name in self._completed_generations:
                # Get the most recent timestamp for this base_name
                latest_timestamp = max(ts for _, ts in self._store[base_name])

                # If the most recent generation was more than 5 minutes ago
                if latest_timestamp <= five_minutes_ago:
                    del self._store[base_name]
                    self._completed_generations.remove(base_name)
                    logger.info(f"Removed all entries for completed base name '{base_name}' ({before_count} usernames)")
                    total_removed += before_count
                    continue

            # For incomplete generations or those within 5 minutes
            current_entries = {
                (name, ts) for name, ts in self._store[base_name]
                if ts > five_minutes_ago
            }

            if current_entries:
                self._store[base_name] = current_entries
                removed_count = before_count - len(current_entries)
                if removed_count > 0:
                    logger.info(f"Removed {removed_count} old usernames for base name '{base_name}'")
                    total_removed += removed_count
            else:
                del self._store[base_name]
                if base_name in self._completed_generations:
                    self._completed_generations.remove(base_name)
                logger.info(f"Removed all entries for base name '{base_name}' ({before_count} usernames)")
                total_removed += before_count

        if total_removed > 0:
            logger.info(f"Cleaned up {total_removed} old username entries")

    async def start_cleanup_task(self):
        """Start periodic cleanup task"""
        while True:
            self.cleanup_old_entries()
            await asyncio.sleep(60)  # Run cleanup every minute