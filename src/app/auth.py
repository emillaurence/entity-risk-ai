"""
src.app.auth — Phase-1 mock authentication.

``AuthenticatedUser`` holds the session identity.  Mock credentials are
defined in ``_MOCK_USERS`` and validated by ``authenticate()``.

A dev-bypass path (``DEV_BYPASS_AUTH=true``) lets local developers skip the
login form without removing it.  This is never active in production because
the env var defaults to an empty string.

Phase 2 note: replace ``authenticate()`` with a Kong-backed provider;
``AuthenticatedUser.auth_provider`` will change from ``"mock"`` to ``"kong"``.
``metadata`` is reserved for JWT claims / Kong consumer attributes.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


@dataclass
class AuthenticatedUser:
    """Represents a successfully authenticated session user."""

    user_id: str
    role: str                           # "jr_risk_analyst" | "sr_risk_analyst"
    auth_provider: str = "mock"         # future: "kong"
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mock user registry
# ---------------------------------------------------------------------------

_MOCK_USERS: dict[str, dict] = {
    "jr_analyst": {
        "password": "demo123",
        "role": "jr_risk_analyst",
    },
    "sr_analyst": {
        "password": "demo123",
        "role": "sr_risk_analyst",
    },
}


def get_mock_users() -> dict[str, dict]:
    """Return a copy of the mock user registry (passwords included — tests only)."""
    return dict(_MOCK_USERS)


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------


def authenticate(username: str, password: str) -> AuthenticatedUser | None:
    """Return an ``AuthenticatedUser`` if credentials match, else ``None``.

    Both username and password must match exactly (case-sensitive).
    """
    entry = _MOCK_USERS.get(username)
    if entry is None or entry["password"] != password:
        return None
    return AuthenticatedUser(
        user_id=username,
        role=entry["role"],
        auth_provider="mock",
    )


# ---------------------------------------------------------------------------
# Dev bypass
# ---------------------------------------------------------------------------


def is_dev_bypass_enabled() -> bool:
    """Return True when ``DEV_BYPASS_AUTH=true`` (or ``1`` / ``yes``) is set."""
    return os.getenv("DEV_BYPASS_AUTH", "").strip().lower() in ("true", "1", "yes")


def dev_bypass_user() -> AuthenticatedUser:
    """Return a pre-authenticated sr_risk_analyst for local dev bypass."""
    return AuthenticatedUser(
        user_id="dev_bypass",
        role="sr_risk_analyst",
        auth_provider="dev_bypass",
        metadata={"bypass": True},
    )
