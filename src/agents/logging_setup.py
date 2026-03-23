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


_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(
    log_file: str | None = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,   # 10 MB per file
    backup_count: int = 5,
) -> None:
    """
    Configure the root logger with a console handler and, optionally,
    a rotating file handler.

    Args:
        log_file:     Path to the log file.  Pass None for console-only output
                      (useful in Jupyter / development).
        level:        Minimum log level captured by all handlers.
        max_bytes:    Rotate the file when it reaches this size.
        backup_count: Number of rotated files to keep.
    """
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid adding duplicate handlers if called more than once.
    if root.handlers:
        return

    # Console handler — always present.
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler — only when a path is given.
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        logging.getLogger(__name__).info(
            "File logging active: %s (level=%s)", log_file, logging.getLevelName(level)
        )
