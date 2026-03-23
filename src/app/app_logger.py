"""
src.app.app_logger — Application-level logger and event helper.

Calling get_app_logger() initialises file logging for the whole process using
the standard format defined in src.agents.logging_setup.  All backend loggers
(src.*, agent.*) propagate to root and therefore write to the same file.

Log file: <repo-root>/logs/app.log

Format:
    2026-03-23 14:42:27 [INFO] entity_risk_app: investigation_completed ...

Usage:
    from src.app.app_logger import get_app_logger, log_event

    log = get_app_logger()
    log.info("Something happened")

    log_event("investigation_completed", success=True, trace_id="abc", steps=6)
    # → 2026-03-23 14:42:27 [INFO] entity_risk_app: investigation_completed success=True trace_id='abc' steps=6
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.agents.logging_setup import configure_logging

_REPO_ROOT = Path(__file__).parent.parent.parent
_LOG_FILE  = str(_REPO_ROOT / "logs" / "app.log")

_log = logging.getLogger("entity_risk_app")


def get_app_logger() -> logging.Logger:
    """Initialise file logging (idempotent) and return the app logger.

    Safe to call on every Streamlit rerun — configure_logging() ensures
    handlers are added only once.
    """
    configure_logging(log_file=_LOG_FILE)
    return _log


def log_event(event: str, **kwargs: Any) -> None:
    """Log a named application event as a structured one-liner.

    Keyword arguments are appended as ``key=repr(value)`` pairs.
    None values are omitted.

    Example::

        log_event("investigation_completed", success=True, steps=6, duration_ms=4521)
        # → 2026-03-23 14:42:27 [INFO] entity_risk_app: investigation_completed success=True steps=6 duration_ms=4521
    """
    parts = [f"{k}={v!r}" for k, v in kwargs.items() if v is not None]
    msg = event + (" " + " ".join(parts) if parts else "")
    _log.info(msg)
