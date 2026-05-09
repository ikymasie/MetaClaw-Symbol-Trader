import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

class BufferedFileHandler(logging.Handler):
    """
    A logging handler that buffers log messages in memory and flushes them 
    to a file every N seconds to reduce IO pressure.
    """
    def __init__(self, filename: str, interval: float = 10.0):
        super().__init__()
        self.filename = filename
        self.interval = interval
        self.buffer: List[str] = []
        self._last_flush = time.time()
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
            
            # If we are in an async loop, we can schedule a flush
            # Otherwise, we wait for the next periodic flush
            try:
                loop = asyncio.get_running_loop()
                if self._flush_task is None or self._flush_task.done():
                    self._flush_task = loop.create_task(self._periodic_flush())
            except RuntimeError:
                # Not in an async loop, will flush on next emit or close if possible
                pass
        except Exception:
            self.handleError(record)

    async def _periodic_flush(self):
        await asyncio.sleep(self.interval)
        await self.flush_async()
        self._flush_task = None

    async def flush_async(self):
        if not self.buffer:
            return
        
        async with self._lock:
            lines_to_write = self.buffer
            self.buffer = []
            
            try:
                with open(self.filename, "a", encoding="utf-8") as f:
                    for line in lines_to_write:
                        f.write(line + "\n")
                self._last_flush = time.time()
            except Exception as e:
                print(f"Failed to flush logs to {self.filename}: {e}")

    def flush(self):
        """Synchronous flush for shutdown or non-async contexts."""
        if not self.buffer:
            return
        
        # Note: This might block if another flush is in progress, 
        # but for logging it's usually acceptable during shutdown.
        lines_to_write = self.buffer
        self.buffer = []
        try:
            with open(self.filename, "a", encoding="utf-8") as f:
                for line in lines_to_write:
                    f.write(line + "\n")
        except Exception as e:
            print(f"Failed to sync-flush logs to {self.filename}: {e}")

    def close(self):
        self.flush()
        if self._flush_task:
            self._flush_task.cancel()
        super().close()

def setup_buffered_logging(filename: str = "logs/fleet.txt", interval: float = 10.0):
    root_logger = logging.getLogger()
    
    # Create the buffered handler
    buffered_handler = BufferedFileHandler(filename, interval)
    buffered_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    ))
    
    # Add to root logger
    root_logger.addHandler(buffered_handler)
    
    # Also keep console logging for visibility
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    ))
    root_logger.addHandler(console_handler)
    
    root_logger.setLevel(logging.INFO)
    return buffered_handler
