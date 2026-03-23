"""
src.app.components — Individual UI component renderers.

Each function renders one logical section of the page.  Functions are
intentionally stateless: they read from ``src.app.state`` and accept
``AppComponents`` for any backend interaction.  No function writes to
session_state directly — state mutations go through ``src.app.state``.

Sections
--------
Left column
    render_investigation_input   Free-text question entry + submit button.
    render_final_answer          Final answer from the last OrchestratorResult.

Center column
    render_planner_output        Parsed plan (mode, entities, steps).
    render_execution_steps       Per-step results with success/failure status.

Right column
    render_trace_viewer          Structured event log for the current trace.
    render_replay_panel          Trace-ID input + replay trigger.

Shared
    render_status_banner         Live execution status / error banner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

import src.app.state as state

if TYPE_CHECKING:
    from src.app.factory import AppComponents


# ---------------------------------------------------------------------------
# Left column
# ---------------------------------------------------------------------------


def render_investigation_input(components: "AppComponents") -> None:
    """Render the free-text investigation question input and submit button.

    On submit the question is stored in session_state via ``state.set_question``.
    The actual orchestrator call is the responsibility of the layout layer so
    that it can update status and result state in one place.
    """
    st.subheader("Investigation")
    question = st.text_area(
        label="Enter a company name or investigation question",
        value=state.get_question(),
        height=120,
        placeholder="e.g. Investigate Acme Holdings Ltd for ownership risk",
        key="_input_question",
    )
    submitted = st.button("Run investigation", type="primary", use_container_width=True)
    if submitted and question.strip():
        state.set_question(question.strip())
        # Signal to the layout that a run should be triggered.
        st.session_state["_trigger_run"] = True


def render_final_answer(components: "AppComponents") -> None:
    """Render the final answer section from the most recent OrchestratorResult."""
    result = state.get_result()
    st.subheader("Final Answer")
    if result is None:
        st.caption("No investigation has been run yet.")
        return
    if result.success:
        st.success(result.final_answer or "Investigation complete — no answer generated.")
    else:
        errors = "; ".join(result.errors) if result.errors else "Unknown error."
        st.error(f"Investigation failed: {errors}")
    if result.warnings:
        with st.expander("Warnings", expanded=False):
            for w in result.warnings:
                st.warning(w)


# ---------------------------------------------------------------------------
# Center column
# ---------------------------------------------------------------------------


def render_planner_output(components: "AppComponents") -> None:
    """Render the planner's parsed plan from the most recent result."""
    result = state.get_result()
    st.subheader("Plan")
    if result is None or result.planner_output is None:
        st.caption("Planner output will appear here after a run.")
        return

    plan = result.planner_output
    col_mode, col_entity = st.columns(2)
    col_mode.metric("Mode", plan.mode)
    entities = ", ".join(plan.entities) if plan.entities else "—"
    col_entity.metric("Entities", entities)

    if plan.reason:
        st.caption(f"Planner reasoning: {plan.reason}")

    if plan.plan:
        st.markdown("**Steps**")
        for i, step in enumerate(plan.plan, start=1):
            agent = getattr(step, "agent", "—")
            task = getattr(step, "task", "—")
            params = getattr(step, "params", {})
            with st.expander(f"{i}. [{agent}] {task}", expanded=False):
                if params:
                    st.json(params)
                else:
                    st.caption("No parameters.")


def render_execution_steps(components: "AppComponents") -> None:
    """Render per-step execution results from the most recent OrchestratorResult."""
    result = state.get_result()
    st.subheader("Execution")
    if result is None:
        st.caption("Step results will appear here after a run.")
        return
    if not result.step_results:
        st.caption("No steps were executed.")
        return

    for step in result.step_results:
        step_id = getattr(step, "request_id", "—")
        success = getattr(step, "success", False)
        summary = getattr(step, "summary", "") or ""
        entity = getattr(step, "entity_name", "—")
        icon = "✓" if success else "✗"
        label = f"{icon} {entity} — {step_id}"
        with st.expander(label, expanded=not success):
            if summary:
                st.write(summary)
            findings = getattr(step, "findings", {})
            if findings:
                st.json(findings)
            if not success:
                err = getattr(step, "error", None)
                if err:
                    st.error(err)


# ---------------------------------------------------------------------------
# Right column
# ---------------------------------------------------------------------------


def render_trace_viewer(components: "AppComponents") -> None:
    """Render the structured event log for the current trace_id."""
    trace_id = state.get_trace_id()
    st.subheader("Trace")
    if trace_id is None:
        st.caption("Trace events will appear here after a run.")
        return

    st.caption(f"trace_id: `{trace_id}`")

    result = state.get_result()
    if result is None:
        return

    # Surface events from the in-memory trace attached to step results.
    all_events: list = []
    for step in (result.step_results or []):
        trace = getattr(step, "trace", None)
        if trace is not None:
            all_events.extend(getattr(trace, "events", []))

    if not all_events:
        st.caption("No events recorded.")
        return

    for event in all_events:
        event_type = getattr(event, "event_type", None)
        label = event_type.value if hasattr(event_type, "value") else str(event_type)
        message = getattr(event, "message", "")
        timestamp = getattr(event, "timestamp", None)
        ts_str = timestamp.strftime("%H:%M:%S") if timestamp else ""
        with st.expander(f"[{ts_str}] {label}", expanded=False):
            st.write(message)
            payload = getattr(event, "payload", None)
            if payload:
                st.json(payload)


def render_replay_panel(components: "AppComponents") -> None:
    """Render the trace replay panel — look up any past trace by ID."""
    st.subheader("Replay / Audit")
    replay_id = st.text_input(
        label="Enter a trace_id to replay",
        value=state.get_replay_trace_id() or "",
        placeholder="e.g. 3f2a1b...",
        key="_input_replay_trace_id",
    )
    load = st.button("Load trace", use_container_width=True)
    if load and replay_id.strip():
        state.set_replay_trace_id(replay_id.strip())
        st.session_state["_trigger_replay"] = True

    replay_trace_id = state.get_replay_trace_id()
    if replay_trace_id:
        st.caption(f"Loaded trace: `{replay_trace_id}`")
        # Full replay rendering will be implemented in a later phase.
        st.info("Replay view not yet implemented.")


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def render_status_banner() -> None:
    """Render a live status/progress banner at the top of the page.

    Shows nothing when idle; shows a spinner when running; shows an error
    message on failure.
    """
    status = state.get_status()
    if not status.get("running") and not status.get("message"):
        return
    if status.get("running"):
        step = status.get("step")
        msg = status.get("message") or "Running investigation…"
        label = f"{msg} (step: {step})" if step else msg
        st.info(label)
    elif status.get("message"):
        st.error(status["message"])
