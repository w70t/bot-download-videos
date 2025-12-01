# -*- coding: utf-8 -*-
"""
Download Queue Manager
======================
Manages per-user download queues with rate limiting and concurrent processing.

Features:
- Per-user queue: Each user has their own sequential queue
- Rate limiting: 10-second cooldown between requests
- Concurrent processing: Multiple users can download simultaneously
- Async/await: Non-blocking queue processing
"""

import asyncio
import time
import logging
from typing import Dict, Set, Optional, Callable, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    """Represents a single download task in the queue"""
    url: str
    message: Any  # Pyrogram Message object
    user_id: int
    callback_query: Optional[Any] = None
    quality: str = "best"


class DownloadQueueManager:
    """
    Manages download queues for all users with rate limiting.
    
    Each user has their own asyncio.Queue to ensure sequential processing
    of their downloads while allowing concurrent downloads across users.
    """
    
    def __init__(self, cooldown_seconds: int = 10):
        """
        Initialize the queue manager.
        
        Args:
            cooldown_seconds: Minimum seconds between requests from same user
        """
        self.cooldown_seconds = cooldown_seconds
        
        # Per-user queues: {user_id: asyncio.Queue}
        self.user_queues: Dict[int, asyncio.Queue] = {}
        
        # Track last request time: {user_id: timestamp}
        self.user_last_request: Dict[int, float] = {}
        
        # Track users currently being processed: {user_id}
        self.processing_users: Set[int] = set()
        
        # Track queue processor tasks: {user_id: Task}
        self.processor_tasks: Dict[int, asyncio.Task] = {}
        
        logger.info("✅ Queue Manager initialized with %d second cooldown", cooldown_seconds)
    
    def is_rate_limited(self, user_id: int) -> tuple[bool, float]:
        """
        Check if user is currently rate limited.
        
        Args:
            user_id: User's Telegram ID
            
        Returns:
            (is_limited, seconds_remaining)
        """
        if user_id not in self.user_last_request:
            return False, 0.0
        
        elapsed = time.time() - self.user_last_request[user_id]
        remaining = self.cooldown_seconds - elapsed
        
        if remaining > 0:
            return True, remaining
        
        return False, 0.0
    
    def mark_request(self, user_id: int):
        """
        Mark that user made a request (for rate limiting during quality selection).
        
        This updates the last request time without adding to queue, allowing
        rate limiting to work even during the quality selection phase.
        
        Args:
            user_id: User's Telegram ID
        """
        self.user_last_request[user_id] = time.time()
        logger.info(f"⏱️ Marked request time for user {user_id} for rate limiting")
    
    def get_queue_size(self, user_id: int) -> int:
        """
        Get the number of pending downloads for a user.
        
        Args:
            user_id: User's Telegram ID
            
        Returns:
            Number of items in user's queue
        """
        if user_id not in self.user_queues:
            return 0
        return self.user_queues[user_id].qsize()
    
    def is_processing(self, user_id: int) -> bool:
        """
        Check if user currently has an active download.
        
        Args:
            user_id: User's Telegram ID
            
        Returns:
            True if user is currently downloading
        """
        return user_id in self.processing_users
    
    async def add_to_queue(
        self, 
        user_id: int, 
        task: DownloadTask,
        process_func: Callable
    ) -> int:
        """
        Add a download task to user's queue and start processing if needed.
        
        Args:
            user_id: User's Telegram ID
            task: DownloadTask to add
            process_func: Async function to call for processing downloads
            
        Returns:
            Position in queue (1-based)
        """
        # Create queue if doesn't exist
        if user_id not in self.user_queues:
            self.user_queues[user_id] = asyncio.Queue()
        
        # Add to queue
        await self.user_queues[user_id].put(task)
        queue_size = self.user_queues[user_id].qsize()
        
        # Update last request time
        self.user_last_request[user_id] = time.time()
        
        logger.info(f"📋 Added task to user {user_id} queue (position: {queue_size})")
        
        # Start processor if not already running
        if user_id not in self.processor_tasks or self.processor_tasks[user_id].done():
            self.processor_tasks[user_id] = asyncio.create_task(
                self._process_user_queue(user_id, process_func)
            )
            logger.info(f"🚀 Started queue processor for user {user_id}")
        
        return queue_size
    
    async def _process_user_queue(self, user_id: int, process_func: Callable):
        """
        Process all downloads in a user's queue sequentially.
        
        Args:
            user_id: User's Telegram ID
            process_func: Async function to process downloads
        """
        logger.info(f"⚙️ Queue processor started for user {user_id}")
        
        try:
            while True:
                # Get next task from queue (wait if empty)
                try:
                    task = await asyncio.wait_for(
                        self.user_queues[user_id].get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    # Queue is empty, check if we should stop
                    if self.user_queues[user_id].empty():
                        break
                    continue
                
                # Mark user as processing
                self.processing_users.add(user_id)
                
                logger.info(f"▶️ Processing download for user {user_id}: {task.url[:50]}...")
                
                try:
                    # Process the download
                    await process_func(task)
                    logger.info(f"✅ Completed download for user {user_id}")
                    
                except Exception as e:
                    logger.error(f"❌ Error processing download for user {user_id}: {e}", exc_info=True)
                
                finally:
                    # Mark task as done
                    self.user_queues[user_id].task_done()
                    
                    # Remove from processing if queue is empty
                    if self.user_queues[user_id].empty():
                        self.processing_users.discard(user_id)
                
        except Exception as e:
            logger.error(f"❌ Queue processor error for user {user_id}: {e}", exc_info=True)
        
        finally:
            # Cleanup
            self.processing_users.discard(user_id)
            logger.info(f"⏹️ Queue processor stopped for user {user_id}")
    
    def get_status(self, user_id: int) -> dict:
        """
        Get current queue status for a user.
        
        Args:
            user_id: User's Telegram ID
            
        Returns:
            Dictionary with queue status information
        """
        return {
            'queue_size': self.get_queue_size(user_id),
            'is_processing': self.is_processing(user_id),
            'is_rate_limited': self.is_rate_limited(user_id)[0],
            'seconds_remaining': self.is_rate_limited(user_id)[1]
        }
    
    async def clear_user_queue(self, user_id: int):
        """
        Clear all pending downloads for a user.
        
        Args:
            user_id: User's Telegram ID
        """
        if user_id in self.user_queues:
            while not self.user_queues[user_id].empty():
                try:
                    self.user_queues[user_id].get_nowait()
                    self.user_queues[user_id].task_done()
                except asyncio.QueueEmpty:
                    break
            
            logger.info(f"🗑️ Cleared queue for user {user_id}")
