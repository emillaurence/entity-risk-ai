"""
src.app.app_logger — Lightweight file logger for the Streamlit app.

Usage
-----
    from src.app.app_logger import get_app_logger

    log = get_app_logger()
    log.info("Investigation submitted: %.80s", question)

Log file location: ``<repo-root>/logs/app.log``

The directory is created automatically on first use.  The file is opened in
append mode so successive app restarts accumulate a running history.  Rotate
manually or add a TimedRotatingFileHandler if volume grows.
"""

from __future__ import annotations

import logging
from pathlib import Path

# Resolve relative to this file: src/app/app_logger.py → repo root
_REPO_ROOT = Path(__file__).parent.parent.parent
_LOG_DIR = _REPO_ROOT / "logs"
_LOG_FILE = _LOG_DIR / "app.log"

_FMT = "%(asctime)s  %(levelname)-8s  %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def get_app_logger() -> logging.Logger:
    """Return (or lazily create) the singleton app logger.

    The file handler is added only once even if ``get_app_logger`` is called
    multiple times across Streamlit reruns.
    """
    logger = logging.getLogger("entity_risk_app")

    if not logger.handlers:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_LOG_FILE, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        # Prevent propagation to root logger (avoids double-printing in Jupyter)
        logger.propagate = False

    return logger
