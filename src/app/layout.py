"""
src.app.layout — Three-column page layout.

Column responsibilities
-----------------------
Left (2/5 width)
    Investigation input (question entry + submit).
    Final answer / risk assessment card.

Center (2/5 width)
    Planner output (mode, entities, steps).
    Execution step results.

Right (1/5 width)
    Trace event viewer (trace ID, stats, warnings/errors).
    Replay / audit panel.

Progressive rendering
---------------------
When the user submits a question, the orchestrator runs in a background
thread.  The thread emits progress events (plan_ready, entity_resolved,
step_starting, step_complete, done) into a queue.Queue.

On each Streamlit rerun, ``render_layout`` calls ``state.drain_run_queue``
which reads all pending events and updates the ``live_*`` session-state keys.
The render functions read from those live keys so the UI updates as data
arrives, without waiting for the full run to complete.

Polling: while the background thread is alive, the layout sleeps 350 ms and
calls ``st.rerun()`` to pick up the next batch of events.
"""

from __future__ import annotations

import queue as _queue
import threading
import time

import streamlit as st

import src.app.state as state
from src.app.app_logger import get_app_logger, log_event
from src.app.components import (
    render_app_header,
    render_execution_steps,
    render_final_answer,
    render_investigation_input,
    render_planner_output,
    render_replay_mode_banner,
    render_replay_panel,
    render_status_banner,
    render_trace_viewer,
)
from src.app.factory import AppComponents, create_app_components
from src.app.styles import inject_styles

_log = get_app_logger()

# Phase → status-banner message
_PHASE_MESSAGES: dict[str, str] = {
    "planning":  "Planning investigation…",
    "resolving": "Resolving entities…",
    "executing": "Executing steps…",
}


def _start_investigation(components: AppComponents, question: str) -> None:
    """Reset live state, start the orchestrator in a background thread, and
    seed the run queue so the UI picks up progress events on each rerun.
    """
    state.reset_live_state()
    state.clear_replay_state()   # dismiss replay view when a new run starts

    q: _queue.Queue = _queue.Queue()
    st.session_state["run_queue"] = q

    log_event("investigation_started", question=question[:120])

    def on_progress(event: str, data: dict) -> None:
        q.put({"event": event, "data": data})

    def thread_func() -> None:
        try:
            result = components.orchestrator.run(question, on_progress=on_progress)
            q.put({"event": "done", "data": {"result": result}})
        except Exception as exc:  # noqa: BLE001
            _log.error("Investigation thread error: %s", exc)
            q.put({"event": "error", "data": {"error": str(exc)}})

    thread = threading.Thread(target=thread_func, daemon=True)
    thread.start()
    st.session_state["run_thread"] = thread


def _update_status_from_live_phase() -> None:
    """Keep the status banner in sync with the current live phase."""
    phase = state.get_live_phase()
    if phase in _PHASE_MESSAGES:
        state.set_status(running=True, message=_PHASE_MESSAGES[phase])
    elif phase == "done":
        state.clear_status()


def _maybe_rerun() -> None:
    """Schedule a rerun if the investigation is still in progress.

    Also handles the "done" transition: logs completion, resets phase to idle.
    """
    phase = state.get_live_phase()

    if phase == "done":
        result = state.get_result()
        if result is not None:
            log_event(
                "investigation_completed",
                success=result.success,
                trace_id=result.trace_id,
                mode=result.mode,
                steps=len(result.step_results),
            )
        state.set_live_phase("idle")
        state.clear_status()
        # No extra rerun needed — result is already rendered on this pass.
        return

    if phase not in _PHASE_MESSAGES:
        return  # idle or unknown — nothing to poll

    thread = st.session_state.get("run_thread")
    if thread and thread.is_alive():
        time.sleep(0.35)
        st.rerun()
    else:
        # Thread exited before putting "done" in the queue — drain remainder.
        state.drain_run_queue()
        if state.get_live_phase() not in ("done", "idle"):
            state.set_live_phase("done")
        st.rerun()


def render_layout() -> None:
    """Render the full page.

    Entry point called by ``app.py``.  Call order:
      1. inject_styles         — global CSS (idempotent across reruns)
      2. state.init            — seed session_state defaults on first load
      3. log startup           — once per browser session
      4. create_app_components — cached across reruns via @st.cache_resource
      5. drain_run_queue       — apply progress events to live state
      6. update status banner  — reflect current phase
      7. render columns        — widgets run here and may set trigger flags
      8. handle _trigger_replay / _trigger_run — consumed AFTER widgets render
      9. _maybe_rerun          — poll while thread alive; handle completion

    Triggers must be consumed AFTER rendering so that the widget that sets
    them (e.g. the submit button) has already been evaluated on this rerun.
    """
    inject_styles()
    state.init()

    if not st.session_state.get("_app_started"):
        log_event("app_start")
        st.session_state["_app_started"] = True

    components = create_app_components()

    # ── Drain progress queue (updates live_* state) ────────────────────
    state.drain_run_queue()

    # ── Keep status banner message in sync with live phase ─────────────
    _update_status_from_live_phase()

    # ── Render page ────────────────────────────────────────────────────
    render_app_header()
    render_status_banner()
    render_replay_mode_banner()

    col_left, col_center, col_right = st.columns([2, 2, 1])

    with col_left:
        render_investigation_input(components)
        st.divider()
        render_final_answer(components)

    with col_center:
        render_planner_output(components)
        st.divider()
        render_execution_steps(components)

    with col_right:
        render_trace_viewer(components)
        st.divider()
        render_replay_panel(components)

    # ── Handle triggers AFTER all widgets are rendered ─────────────────
    # Triggers are set by widgets during this rerun; checking them here
    # ensures they are consumed on the same rerun that set them.

    if st.session_state.pop("_trigger_replay", False):
        replay_id = state.get_replay_trace_id()
        if replay_id:
            log_event("replay_started", trace_id=replay_id)
            state.set_replay_status("loading")
            try:
                replay_data = components.trace_repo.load_trace(replay_id)
                state.set_replay_data(replay_data)
                state.set_replay_status("loaded")
                log_event(
                    "replay_completed",
                    trace_id=replay_id,
                    mode=replay_data.get("mode"),
                    event_count=len(replay_data.get("events") or []),
                )
            except KeyError:
                state.set_replay_status("error")
                state.set_replay_error(
                    f"Trace '{replay_id}' was not found in the database."
                )
                log_event("replay_failed", trace_id=replay_id, error="not_found")
            except Exception as exc:
                _log.error("Replay failed for trace %s: %s", replay_id, exc)
                state.set_replay_status("error")
                state.set_replay_error(f"Failed to load trace: {exc}")
                log_event("replay_failed", trace_id=replay_id, error=str(exc))
            st.rerun()

    if st.session_state.pop("_clear_replay", False):
        state.clear_replay_state()
        st.rerun()

    if st.session_state.pop("_trigger_run", False):
        question = state.get_question()
        if question:
            _start_investigation(components, question)
            st.rerun()  # immediately show "Planning…" state

    # ── Poll / handle completion ───────────────────────────────────────
    _maybe_rerun()
