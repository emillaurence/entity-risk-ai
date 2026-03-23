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

The layout layer is the only place that calls the orchestrator and the app
logger.  Component functions are kept free of side-effects; the layout
orchestrates state transitions after a user action.
"""

from __future__ import annotations

import streamlit as st

import src.app.state as state
from src.app.app_logger import get_app_logger
from src.app.components import (
    render_app_header,
    render_execution_steps,
    render_final_answer,
    render_investigation_input,
    render_planner_output,
    render_replay_panel,
    render_status_banner,
    render_trace_viewer,
)
from src.app.factory import AppComponents, create_app_components
from src.app.styles import inject_styles

# Module-level logger — created once when the module is first imported.
_log = get_app_logger()


def _run_investigation(components: AppComponents, question: str) -> None:
    """Execute the orchestrator and update session state with the result.

    Logs the investigation lifecycle at INFO level.  Any uncaught exception
    from the orchestrator is caught, logged, and surfaced to the UI via the
    status banner (not a hard crash).
    """
    state.set_status(running=True, message="Starting investigation…")
    _log.info("Investigation submitted: %.120s", question)
    try:
        result = components.orchestrator.run(question)
        state.set_result(result)
        state.set_trace_id(result.trace_id)
        state.clear_status()
        _log.info(
            "Investigation completed: success=%s trace_id=%s steps=%d",
            result.success,
            result.trace_id,
            len(result.step_results),
        )
    except Exception as exc:  # noqa: BLE001
        state.set_result(None)
        state.set_status(running=False, message=f"Error: {exc}")
        _log.error("Investigation error: %s", exc)


def render_layout() -> None:
    """Render the full page.

    Entry point called by ``app.py``.  Keeps ``app.py`` free of any
    Streamlit widget logic.  Call order:
      1. inject_styles  — global CSS (idempotent across reruns)
      2. state.init     — seed session_state defaults on first load
      3. log startup    — once per browser session via a session_state flag
      4. create_app_components — cached across reruns via @st.cache_resource
      5. render columns
      6. handle run / replay triggers set by interactive widgets
    """
    inject_styles()
    state.init()

    # Log once per browser session (not once per rerun).
    if not st.session_state.get("_app_started"):
        _log.info("App started")
        st.session_state["_app_started"] = True

    components = create_app_components()

    # App title / subtitle — full width above all columns.
    render_app_header()

    # Live status banner — full width, hidden when idle.
    render_status_banner()

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

    # Handle triggers set by render_investigation_input / render_replay_panel.
    # Use pop so the flag is consumed on the rerun that triggered the action.

    if st.session_state.pop("_trigger_run", False):
        question = state.get_question()
        if question:
            _run_investigation(components, question)
            st.rerun()

    if st.session_state.pop("_trigger_replay", False):
        replay_id = state.get_replay_trace_id()
        if replay_id:
            _log.info("Replay requested: trace_id=%s", replay_id)
            # Full replay rendering is not yet implemented.
            # The request is logged; the panel shows a "loaded" state.
