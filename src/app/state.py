"""
src.app.state — Session state accessors.

All reads and writes to st.session_state go through this module so that
key names are defined in exactly one place and callers use typed helpers
instead of raw string keys.

Keys
----
question            Current investigation question entered by the user.
orchestrator_result OrchestratorResult from the last completed run, or None.
trace_id            Neo4j trace_id of the current/last investigation.
replay_trace_id     trace_id entered by the user for replay/audit view.
execution_status    Dict with running/message/step describing live progress.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import streamlit as st

if TYPE_CHECKING:
    from src.orchestration.orchestrator import OrchestratorResult

# ---------------------------------------------------------------------------
# Private key constants
# ---------------------------------------------------------------------------

_KEY_QUESTION = "question"
_KEY_RESULT = "orchestrator_result"
_KEY_TRACE_ID = "trace_id"
_KEY_REPLAY_TRACE_ID = "replay_trace_id"
_KEY_STATUS = "execution_status"

_DEFAULTS: dict[str, Any] = {
    _KEY_QUESTION: "",
    _KEY_RESULT: None,
    _KEY_TRACE_ID: None,
    _KEY_REPLAY_TRACE_ID: None,
    _KEY_STATUS: {"running": False, "message": "", "step": None},
}


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init() -> None:
    """Seed session_state with default values on the first page load.

    Safe to call on every rerun — already-set keys are left untouched.
    """
    for key, default in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


# ---------------------------------------------------------------------------
# question
# ---------------------------------------------------------------------------


def get_question() -> str:
    """Return the current investigation question."""
    return st.session_state.get(_KEY_QUESTION, "")


def set_question(value: str) -> None:
    """Store the investigation question."""
    st.session_state[_KEY_QUESTION] = value


# ---------------------------------------------------------------------------
# orchestrator_result
# ---------------------------------------------------------------------------


def get_result() -> "OrchestratorResult | None":
    """Return the most recent OrchestratorResult, or None."""
    return st.session_state.get(_KEY_RESULT)


def set_result(result: "OrchestratorResult | None") -> None:
    """Store an OrchestratorResult (pass None to clear)."""
    st.session_state[_KEY_RESULT] = result


# ---------------------------------------------------------------------------
# trace_id
# ---------------------------------------------------------------------------


def get_trace_id() -> str | None:
    """Return the trace_id of the current investigation."""
    return st.session_state.get(_KEY_TRACE_ID)


def set_trace_id(trace_id: str | None) -> None:
    """Store a trace_id (pass None to clear)."""
    st.session_state[_KEY_TRACE_ID] = trace_id


# ---------------------------------------------------------------------------
# replay_trace_id
# ---------------------------------------------------------------------------


def get_replay_trace_id() -> str | None:
    """Return the trace_id the user has entered for replay/audit."""
    return st.session_state.get(_KEY_REPLAY_TRACE_ID)


def set_replay_trace_id(trace_id: str | None) -> None:
    """Store a replay trace_id (pass None to clear)."""
    st.session_state[_KEY_REPLAY_TRACE_ID] = trace_id


# ---------------------------------------------------------------------------
# execution_status
# ---------------------------------------------------------------------------


def get_status() -> dict[str, Any]:
    """Return the current execution status dict.

    Shape: ``{"running": bool, "message": str, "step": str | None}``
    """
    return st.session_state.get(_KEY_STATUS, _DEFAULTS[_KEY_STATUS])


def set_status(*, running: bool, message: str = "", step: str | None = None) -> None:
    """Update execution status in one call."""
    st.session_state[_KEY_STATUS] = {
        "running": running,
        "message": message,
        "step": step,
    }


def clear_status() -> None:
    """Reset execution status to the idle default."""
    set_status(running=False, message="", step=None)
