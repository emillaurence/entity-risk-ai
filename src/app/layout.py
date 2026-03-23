"""
src.app.layout — Three-column page layout.

Column responsibilities
-----------------------
Left (2/5 width)
    Investigation input (question entry + submit).
    Final answer from the last orchestrator run.

Center (2/5 width)
    Planner output (mode, entities, steps).
    Execution step results.

Right (1/5 width)
    Trace event viewer for the current trace.
    Replay / audit panel for loading past traces.

The layout layer is the only place that calls the orchestrator.  Component
functions are kept free of side-effects; the layout orchestrates state
transitions after a user action.
"""

from __future__ import annotations

import streamlit as st

import src.app.state as state
from src.app.components import (
    render_execution_steps,
    render_final_answer,
    render_investigation_input,
    render_planner_output,
    render_replay_panel,
    render_status_banner,
    render_trace_viewer,
)
from src.app.factory import AppComponents, create_app_components


def _run_investigation(components: AppComponents, question: str) -> None:
    """Execute the orchestrator and update session state with the result.

    Called by ``render_layout`` when ``_trigger_run`` is set in session_state.
    Updates ``state.execution_status``, ``state.orchestrator_result``, and
    ``state.trace_id`` in sequence.
    """
    state.set_status(running=True, message="Starting investigation…")
    try:
        result = components.orchestrator.run(question)
        state.set_result(result)
        state.set_trace_id(result.trace_id)
        state.clear_status()
    except Exception as exc:  # noqa: BLE001
        state.set_result(None)
        state.set_status(running=False, message=f"Error: {exc}")


def render_layout() -> None:
    """Render the full page: initialise state, wire components, draw columns.

    Entry point called by ``app.py``.  Keeps ``app.py`` free of any
    Streamlit widget logic.
    """
    # Initialise session_state defaults on first load.
    state.init()

    # Load (or retrieve cached) system components.
    components = create_app_components()

    # Status banner spans full width above the columns.
    render_status_banner()

    # Three-column layout: left=2, center=2, right=1.
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

    # Handle run trigger set by render_investigation_input.
    if st.session_state.pop("_trigger_run", False):
        question = state.get_question()
        if question:
            _run_investigation(components, question)
            st.rerun()
