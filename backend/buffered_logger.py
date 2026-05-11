import asyncio
import logging
import os
import time
from typing import List, Optional

# Phase 3 §8.1 — Structured JSON logging.
# python-json-logger is added in requirements.txt; if unavailable (e.g. in
# minimal dev environments) we fall back to the plain text formatter so the
# backend still starts.
try:
    from pythonjsonlogger import jsonlogger  # type: ignore
    _JSON_LOGGER_AVAILABLE = True
except Exception:
    jsonlogger = None  # type: ignore
    _JSON_LOGGER_AVAILABLE = False

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
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._write_to_file, lines_to_write)
                self._last_flush = time.time()
            except Exception as e:
                print(f"Failed to flush logs to {self.filename}: {e}")

    def _write_to_file(self, lines: List[str]):
        """Synchronous helper to write lines to file."""
        with open(self.filename, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

    def flush(self):
        """Synchronous flush for shutdown or non-async contexts."""
        if not self.buffer:
            return
        
        # Note: This might block if another flush is in progress, 
        # but for logging it's usually acceptable during shutdown.
        lines_to_write = self.buffer
        self.buffer = []
        try:
            self._write_to_file(lines_to_write)
        except Exception as e:
            print(f"Failed to sync-flush logs to {self.filename}: {e}")

    def close(self):
        self.flush()
        if self._flush_task:
            self._flush_task.cancel()
        super().close()

def _make_formatter(json_mode: bool) -> logging.Formatter:
    """
    Build the log formatter.

    Phase 3 §8.1 — When `python-json-logger` is available, emit structured
    JSON lines so log aggregators can index `extra={}` payloads (event,
    bot_id, agent, quorum_score, etc.). The base fields are:
      - asctime, levelname, name, message
      - Every key passed via `logger.info("msg", extra={...})` is merged
        as a top-level JSON key.

    Falls back to the existing plain-text formatter when the lib is missing,
    so dev environments without the dependency still start cleanly.
    """
    if json_mode and _JSON_LOGGER_AVAILABLE:
        # `%(asctime)s %(levelname)s %(name)s %(message)s` tells JsonFormatter
        # which standard fields to surface as top-level keys.
        return jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
            json_ensure_ascii=False,
        )
    return logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def setup_buffered_logging(filename: str = "logs/fleet.txt", interval: float = 10.0):
    """
    Initialise the root logger with a buffered file handler + console handler.

    JSON mode is enabled by default when `python-json-logger` is installed.
    Set the environment variable `TRADECLAW_LOG_JSON=0` to force plain-text
    output (useful for local debugging where humans tail the log directly).
    """
    json_mode = os.getenv("TRADECLAW_LOG_JSON", "1") != "0"

    root_logger = logging.getLogger()

    # Create the buffered handler
    buffered_handler = BufferedFileHandler(filename, interval)
    buffered_handler.setFormatter(_make_formatter(json_mode))

    # Add to root logger
    root_logger.addHandler(buffered_handler)

    # Console — always human-readable plain text. JSON to file, text to stdout.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    )
    root_logger.addHandler(console_handler)

    root_logger.setLevel(logging.INFO)

    if json_mode and not _JSON_LOGGER_AVAILABLE:
        root_logger.warning(
            "TRADECLAW_LOG_JSON=1 but python-json-logger is not installed; "
            "falling back to plain-text logs. Run: pip install python-json-logger"
        )

    return buffered_handler
