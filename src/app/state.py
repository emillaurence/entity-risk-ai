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

Auth keys
---------
auth_user           AuthenticatedUser | None — current session user.
auth_authenticated  bool — True once the user has successfully logged in.
auth_error          str | None — last login error message.
auth_dev_bypass     bool — True when the session was opened via dev bypass.

Live / progressive rendering keys
----------------------------------
live_phase          "idle"|"planning"|"resolving"|"executing"|"done"
live_plan           InvestigationPlan dict, or None
live_entities       dict[entity_name, resolution_dict | None]
live_steps          list[dict] — completed steps emitted by step_complete events
live_current_step   dict | None — step currently executing
live_trace_id       str | None
live_step_num       int — 1-based index of the current executing step (0 = none)
live_step_total     int — total planned steps (0 = unknown)
live_step_label     str — business-friendly label of the currently executing step
"""

from __future__ import annotations

import queue as _queue
from typing import TYPE_CHECKING, Any

import streamlit as st

if TYPE_CHECKING:
    from src.app.auth import AuthenticatedUser
    from src.orchestration.orchestrator import OrchestratorResult

# ---------------------------------------------------------------------------
# Private key constants
# ---------------------------------------------------------------------------

# Auth
_KEY_AUTH_USER          = "auth_user"
_KEY_AUTH_AUTHENTICATED = "auth_authenticated"
_KEY_AUTH_ERROR         = "auth_error"
_KEY_AUTH_DEV_BYPASS    = "auth_dev_bypass"

_KEY_QUESTION        = "question"
_KEY_RESULT          = "orchestrator_result"
_KEY_TRACE_ID        = "trace_id"
_KEY_REPLAY_TRACE_ID = "replay_trace_id"
_KEY_STATUS          = "execution_status"
_KEY_STEPS_REVEALED  = "steps_revealed"

# Live / progressive rendering state
_KEY_LIVE_PHASE       = "live_phase"         # "idle"|"planning"|"resolving"|"selecting"|"executing"|"done"
_KEY_LIVE_PLAN        = "live_plan"          # dict | None
_KEY_LIVE_ENTITIES    = "live_entities"      # dict[str, dict | None]
_KEY_LIVE_STEPS       = "live_steps"         # list[dict] — completed steps (as dicts)
_KEY_LIVE_CURRENT     = "live_current_step"  # dict | None — step currently running
_KEY_LIVE_TRACE_ID    = "live_trace_id"      # str | None
_KEY_LIVE_STEP_NUM    = "live_step_num"      # int — 1-based current step, 0 if none
_KEY_LIVE_STEP_TOTAL  = "live_step_total"    # int — total planned steps, 0 if unknown
_KEY_LIVE_STEP_LABEL  = "live_step_label"    # str — business-friendly current step label
_KEY_LIVE_CANDIDATES  = "live_entity_candidates"  # list[dict] — entity candidates awaiting selection
_KEY_LIVE_ENTITY_NAME = "live_entity_name"         # str — original query name being confirmed

# Replay / audit state
_KEY_REPLAY_DATA   = "replay_data"    # dict from trace_repo.load_trace() | None
_KEY_REPLAY_STATUS = "replay_status"  # "idle" | "loading" | "loaded" | "error"
_KEY_REPLAY_ERROR  = "replay_error"   # str | None

_DEFAULTS: dict[str, Any] = {
    _KEY_AUTH_USER:          None,
    _KEY_AUTH_AUTHENTICATED: False,
    _KEY_AUTH_ERROR:         None,
    _KEY_AUTH_DEV_BYPASS:    False,
    _KEY_QUESTION:        "",
    _KEY_RESULT:          None,
    _KEY_TRACE_ID:        None,
    _KEY_REPLAY_TRACE_ID: None,
    _KEY_STATUS:          {"running": False, "message": "", "step": None},
    _KEY_STEPS_REVEALED:  0,
    _KEY_LIVE_PHASE:      "idle",
    _KEY_LIVE_PLAN:       None,
    _KEY_LIVE_ENTITIES:   {},
    _KEY_LIVE_STEPS:      [],
    _KEY_LIVE_CURRENT:    None,
    _KEY_LIVE_TRACE_ID:   None,
    _KEY_LIVE_STEP_NUM:   0,
    _KEY_LIVE_STEP_TOTAL: 0,
    _KEY_LIVE_STEP_LABEL: "",
    _KEY_LIVE_CANDIDATES:  [],
    _KEY_LIVE_ENTITY_NAME: "",
    _KEY_REPLAY_DATA:     None,
    _KEY_REPLAY_STATUS:   "idle",
    _KEY_REPLAY_ERROR:    None,
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
# Auth state
# ---------------------------------------------------------------------------


def is_authenticated() -> bool:
    """Return True when a user is logged in for this session."""
    return bool(st.session_state.get(_KEY_AUTH_AUTHENTICATED, False))


def get_authenticated_user() -> "AuthenticatedUser | None":
    """Return the current AuthenticatedUser, or None."""
    return st.session_state.get(_KEY_AUTH_USER)


def login(user: "AuthenticatedUser") -> None:
    """Store the authenticated user and mark the session as authenticated."""
    st.session_state[_KEY_AUTH_USER]          = user
    st.session_state[_KEY_AUTH_AUTHENTICATED] = True
    st.session_state[_KEY_AUTH_ERROR]         = None


def logout() -> None:
    """Clear auth state, returning the session to the unauthenticated gate."""
    st.session_state[_KEY_AUTH_USER]          = None
    st.session_state[_KEY_AUTH_AUTHENTICATED] = False
    st.session_state[_KEY_AUTH_ERROR]         = None
    st.session_state[_KEY_AUTH_DEV_BYPASS]    = False


def get_auth_error() -> str | None:
    """Return the most recent auth error message, or None."""
    return st.session_state.get(_KEY_AUTH_ERROR)


def set_auth_error(msg: str | None) -> None:
    """Store an auth error message (pass None to clear)."""
    st.session_state[_KEY_AUTH_ERROR] = msg


def set_auth_dev_bypass(value: bool) -> None:
    """Mark (or unmark) the session as opened via the dev bypass."""
    st.session_state[_KEY_AUTH_DEV_BYPASS] = value


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
# Replay result state
# ---------------------------------------------------------------------------


def get_replay_data() -> "dict | None":
    """Return the loaded replay trace data dict, or None."""
    return st.session_state.get(_KEY_REPLAY_DATA)


def set_replay_data(data: "dict | None") -> None:
    """Store the loaded replay trace data."""
    st.session_state[_KEY_REPLAY_DATA] = data


def get_replay_status() -> str:
    """Return the replay status: 'idle' | 'loading' | 'loaded' | 'error'."""
    return st.session_state.get(_KEY_REPLAY_STATUS, "idle")


def set_replay_status(status: str) -> None:
    """Set the replay status."""
    st.session_state[_KEY_REPLAY_STATUS] = status


def get_replay_error() -> "str | None":
    """Return the replay error message, or None."""
    return st.session_state.get(_KEY_REPLAY_ERROR)


def set_replay_error(error: "str | None") -> None:
    """Store a replay error message (pass None to clear)."""
    st.session_state[_KEY_REPLAY_ERROR] = error


def reset_replay_state() -> None:
    """Reset all replay state (call when user clears the replay view or starts a new run)."""
    st.session_state[_KEY_REPLAY_DATA]     = None
    st.session_state[_KEY_REPLAY_STATUS]   = "idle"
    st.session_state[_KEY_REPLAY_ERROR]    = None
    st.session_state[_KEY_REPLAY_TRACE_ID] = None


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


# ---------------------------------------------------------------------------
# steps_revealed  (progressive rendering counter)
# ---------------------------------------------------------------------------


def get_steps_revealed() -> int:
    """Return the number of execution step cards revealed so far."""
    return st.session_state.get(_KEY_STEPS_REVEALED, 0)


def set_steps_revealed(n: int) -> None:
    """Set the number of revealed step cards."""
    st.session_state[_KEY_STEPS_REVEALED] = n


def reset_steps_revealed() -> None:
    """Reset the reveal counter to zero (call at the start of a new run)."""
    st.session_state[_KEY_STEPS_REVEALED] = 0


# ---------------------------------------------------------------------------
# Live / progressive rendering state
# ---------------------------------------------------------------------------


def get_live_phase() -> str:
    return st.session_state.get(_KEY_LIVE_PHASE, "idle")


def set_live_phase(phase: str) -> None:
    st.session_state[_KEY_LIVE_PHASE] = phase


def get_live_plan() -> "dict | None":
    return st.session_state.get(_KEY_LIVE_PLAN)


def get_live_entities() -> dict:
    return st.session_state.get(_KEY_LIVE_ENTITIES, {})


def get_live_steps() -> list:
    return st.session_state.get(_KEY_LIVE_STEPS, [])


def get_live_current_step() -> "dict | None":
    return st.session_state.get(_KEY_LIVE_CURRENT)


def get_live_trace_id() -> "str | None":
    return st.session_state.get(_KEY_LIVE_TRACE_ID)


def get_live_step_num() -> int:
    """Return the 1-based index of the currently executing step (0 = none)."""
    return st.session_state.get(_KEY_LIVE_STEP_NUM, 0)


def get_live_step_total() -> int:
    """Return the total number of planned steps (0 = unknown)."""
    return st.session_state.get(_KEY_LIVE_STEP_TOTAL, 0)


def get_live_step_label() -> str:
    """Return the business-friendly label of the currently executing step."""
    return st.session_state.get(_KEY_LIVE_STEP_LABEL, "")


def get_live_candidates() -> list:
    """Return entity candidates awaiting user selection (empty when not in 'selecting' phase)."""
    return st.session_state.get(_KEY_LIVE_CANDIDATES, [])


def get_live_entity_name() -> str:
    """Return the original query entity name awaiting confirmation."""
    return st.session_state.get(_KEY_LIVE_ENTITY_NAME, "")


def reset_all_run_state() -> None:
    """Clear every piece of state that carries over from a previous run.

    Call this as early as possible — ideally in the button handler — so
    the *same* Streamlit render pass that detects the button press starts
    a clean page.  Combining both helpers here keeps the call site simple.
    """
    reset_live_state()
    reset_replay_state()


def reset_live_state() -> None:
    """Clear all live rendering state (call before starting a new run).

    Resets every key that could carry over stale data from a previous run,
    so the UI renders clean placeholders on the very first rerun after the
    investigation thread starts.
    """
    st.session_state[_KEY_LIVE_PHASE]       = "planning"
    st.session_state[_KEY_LIVE_PLAN]        = None
    st.session_state[_KEY_LIVE_ENTITIES]    = {}
    st.session_state[_KEY_LIVE_STEPS]       = []
    st.session_state[_KEY_LIVE_CURRENT]     = None
    st.session_state[_KEY_LIVE_TRACE_ID]    = None
    st.session_state[_KEY_LIVE_STEP_NUM]    = 0
    st.session_state[_KEY_LIVE_STEP_TOTAL]  = 0
    st.session_state[_KEY_LIVE_STEP_LABEL]  = ""
    st.session_state[_KEY_LIVE_CANDIDATES]  = []
    st.session_state[_KEY_LIVE_ENTITY_NAME] = ""
    # Clear previous result/trace so placeholders show correctly
    st.session_state[_KEY_RESULT]           = None
    st.session_state[_KEY_TRACE_ID]         = None
    # Clear status banner and step counter so no stale indicators remain
    st.session_state[_KEY_STATUS]           = _DEFAULTS[_KEY_STATUS].copy()
    st.session_state[_KEY_STEPS_REVEALED]   = 0


# Business-friendly step labels used in the progress banner.
# Intentionally kept in state.py so layout.py can read them without
# importing from components.py (which would create a circular dependency).
_STEP_LABELS: dict[str, str] = {
    "entity_lookup":                "Identifying company",
    "company_profile":              "Retrieving company profile",
    "expand_ownership":             "Mapping ownership structure",
    "shared_address_check":         "Checking address",
    "sic_context":                  "Analysing industry context",
    "ownership_complexity_check":   "Assessing ownership complexity",
    "control_signal_check":         "Analysing control signals",
    "address_risk_check":           "Assessing address risk",
    "industry_context_check":       "Assessing industry context",
    "summarize_risk_for_company":   "Calculating overall risk",
    "retrieve_trace":               "Retrieving decision trace",
    "find_traces_by_entity":        "Finding company traces",
    "summarize_trace":              "Summarising investigation",
    "retrieve_and_summarize_trace": "Reviewing past investigation",
    "retrieve_latest_for_entity":   "Finding latest investigation",
}


def drain_run_queue() -> tuple[int, bool]:
    """Drain the progress queue and update live state.

    Called on the main Streamlit thread at the start of each render pass.
    The background orchestrator thread writes only to the queue; this
    function applies those events to session_state (main-thread safe).

    Returns (events_drained, is_done) where:
      events_drained — number of events consumed from the queue (0 = nothing new)
      is_done        — True when the run is fully complete (phase set to "done")
    """
    q: "_queue.Queue | None" = st.session_state.get("run_queue")
    if q is None:
        return 0, False

    done = False
    count = 0
    try:
        while True:
            event = q.get_nowait()
            count += 1
            etype = event.get("event")
            data  = event.get("data", {})

            if etype == "plan_ready":
                st.session_state[_KEY_LIVE_PLAN]        = data
                st.session_state[_KEY_LIVE_PHASE]       = "resolving"
                plan_steps = data.get("plan") or []
                st.session_state[_KEY_LIVE_STEP_TOTAL]  = len(plan_steps)

            elif etype == "trace_created":
                st.session_state[_KEY_LIVE_TRACE_ID] = data.get("trace_id")

            elif etype == "entity_candidates":
                st.session_state[_KEY_LIVE_CANDIDATES]  = data.get("candidates", [])
                st.session_state[_KEY_LIVE_ENTITY_NAME] = data.get("name", "")
                st.session_state[_KEY_LIVE_PHASE]       = "selecting"

            elif etype == "entity_resolved":
                entities = dict(st.session_state.get(_KEY_LIVE_ENTITIES) or {})
                entities.update(data)
                st.session_state[_KEY_LIVE_ENTITIES] = entities
                # Only advance phase if we're past the selecting step
                if st.session_state.get(_KEY_LIVE_PHASE) not in ("selecting",):
                    st.session_state[_KEY_LIVE_PHASE] = "executing"

            elif etype == "step_starting":
                st.session_state[_KEY_LIVE_CURRENT] = data
                st.session_state[_KEY_LIVE_PHASE]   = "executing"
                task  = data.get("task", "")
                label = _STEP_LABELS.get(task, task.replace("_", " ").title())
                # Determine 1-based step number from plan order
                plan_steps = (st.session_state.get(_KEY_LIVE_PLAN) or {}).get("plan") or []
                num = next(
                    (i + 1 for i, s in enumerate(plan_steps) if s.get("task") == task),
                    len(st.session_state.get(_KEY_LIVE_STEPS) or []) + 1,
                )
                total = max(
                    len(plan_steps),
                    st.session_state.get(_KEY_LIVE_STEP_TOTAL, 0),
                )
                st.session_state[_KEY_LIVE_STEP_NUM]   = num
                st.session_state[_KEY_LIVE_STEP_TOTAL] = total
                st.session_state[_KEY_LIVE_STEP_LABEL] = label

            elif etype == "step_complete":
                steps = list(st.session_state.get(_KEY_LIVE_STEPS) or [])
                steps.append(data)
                st.session_state[_KEY_LIVE_STEPS]   = steps
                st.session_state[_KEY_LIVE_CURRENT] = None

            elif etype == "done":
                result = data.get("result")
                if result is not None:
                    set_result(result)
                    set_trace_id(result.trace_id)
                st.session_state[_KEY_LIVE_PHASE] = "done"
                done = True

            elif etype == "error":
                set_result(None)
                set_status(running=False, message=f"Error: {data.get('error', 'Unknown error')}")
                st.session_state[_KEY_LIVE_PHASE] = "done"
                done = True

    except _queue.Empty:
        pass

    return count, done
