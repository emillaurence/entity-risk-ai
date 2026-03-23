"""
App-level logging configuration for the investigation system.

Call configure_logging() once at startup (e.g. in your FastAPI lifespan,
CLI entrypoint, or Jupyter setup cell). After that every agent, service, and
tool writes to the same rotating file automatically — no changes to individual
classes needed.

Logger hierarchy used in this project:
    agent.<name>          BaseAgent subclasses (graph-agent, risk-agent, …)
    trace_service         TraceService (if you add logging there later)
    neo4j_repository      Neo4jRepository (if you add logging there later)

All of the above are children of the root logger, so a single handler on the
root captures everything.

Example (FastAPI):
    from contextlib import asynccontextmanager
    from src.agents.logging_setup import configure_logging

    @asynccontextmanager
    async def lifespan(app):
        configure_logging(log_file="logs/app.log")
        yield

Example (CLI / script):
    from src.agents.logging_setup import configure_logging
    configure_logging(log_file="logs/app.log", level=logging.DEBUG)

Example (Jupyter — development only):
    from src.agents.logging_setup import configure_logging
    configure_logging()   # console only, no file
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Module-level guard so a file handler is added only once regardless of how
# many times configure_logging() is called (e.g. from app_logger + factory).
_file_handler_path: str | None = None


def configure_logging(
    log_file: str | None = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,   # 10 MB per file
    backup_count: int = 5,
) -> None:
    """
    Configure the root logger with a console handler and, optionally,
    a rotating file handler.

    Safe to call multiple times — duplicate handlers are never added.

    Args:
        log_file:     Path to the log file.  Pass None for console-only output
                      (useful in Jupyter / development).
        level:        Minimum log level captured by all handlers.
        max_bytes:    Rotate the file when it reaches this size.
        backup_count: Number of rotated files to keep.
    """
    global _file_handler_path

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(level)

    # Add a console handler only if none exists yet.
    has_console = any(
        type(h) is logging.StreamHandler for h in root.handlers
    )
    if not has_console:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    # Add a rotating file handler only once per unique path.
    if log_file and log_file != _file_handler_path:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        _file_handler_path = log_file
        logging.getLogger(__name__).info("Log file: %s", log_file)
