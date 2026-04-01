"""
src.app.layout — Two-tab page layout.

Tab 1 — Investigate
    Three-column layout: AI Assistant | Context Graph | Decision Insights.
    A "How this was analysed" expander at the bottom exposes the investigation
    plan, step-by-step execution cards, and the decision trace ID.

Tab 2 — Replay / Audit
    Three-column layout: Risk Assessment | Investigation Activity | Trace Metadata.
    Focused on reviewing a prior investigation by trace ID.

Progressive rendering
---------------------
When the user submits a question, the orchestrator runs in a background
thread.  The thread emits progress events into a queue.Queue.

Polling is handled by ``_polling_fragment`` — a Streamlit fragment that
re-runs every 250 ms on its own scope (no full-page rebuild).  When it
drains new events from the queue it calls ``st.rerun()`` to trigger a
full-page rebuild so the columns pick up the updated live_* state.
This means a full rebuild only happens when there is actually new data,
instead of unconditionally every 350 ms.

Note on tab rendering
---------------------
Streamlit evaluates *all* tab contents on every rerun (not just the active
tab), so trigger flags set by widgets inside either tab are always visible
to the post-render trigger-handling block below.
"""

from __future__ import annotations

import os
import queue as _queue
import threading

import streamlit as st

import src.app.state as state
from src.app.app_logger import get_app_logger, log_event
from src.app.auth import authenticate, dev_bypass_user, is_dev_bypass_enabled
from src.app.components import (
    render_app_header,
    render_investigate_tab,
    render_replay_tab,
    render_status_banner,
)
from src.app.factory import AppComponents, create_app_components
from src.app.policy import get_policy_for_user
from src.app.styles import inject_styles

_log = get_app_logger()


def _start_investigation(
    components: AppComponents,
    question: str,
    allowed_tools: "frozenset[str] | None" = None,
) -> None:
    """Reset live state, start the orchestrator in a background thread, and
    seed the run queue so the UI picks up progress events on each rerun.

    Creates an ``entity_confirm_queue`` so the orchestrator thread can block
    on entity selection when multiple candidates are returned.  Any prior
    confirmation queue is signalled with ``None`` first to unblock stale threads.

    Args:
        allowed_tools: Optional MCP tool allowlist from the current user's
                       RolePolicy.  Passed through to ``Orchestrator.run()``
                       so disallowed tool steps are skipped safely.
    """
    # Unblock any previously blocking orchestrator thread
    old_cq: "_queue.Queue | None" = st.session_state.get("entity_confirm_queue")
    if old_cq is not None:
        try:
            old_cq.put_nowait(None)
        except Exception:  # noqa: BLE001
            pass

    state.reset_live_state()
    state.reset_replay_state()   # dismiss replay view when a new run starts

    q: _queue.Queue = _queue.Queue()
    confirm_q: _queue.Queue = _queue.Queue()
    st.session_state["run_queue"]            = q
    st.session_state["entity_confirm_queue"] = confirm_q

    log_event("investigation_started", question=question[:120])

    def on_progress(event: str, data: dict) -> None:
        q.put({"event": event, "data": data})

    def thread_func() -> None:
        try:
            result = components.orchestrator.run(
                question,
                on_progress=on_progress,
                confirmation_queue=confirm_q,
                allowed_tools=allowed_tools,
            )
            q.put({"event": "done", "data": {"result": result}})
        except Exception as exc:  # noqa: BLE001
            _log.error("Investigation thread error: %s", exc)
            q.put({"event": "error", "data": {"error": str(exc)}})

    thread = threading.Thread(target=thread_func, daemon=True)
    thread.start()
    st.session_state["run_thread"] = thread



@st.fragment(run_every=0.25)
def _polling_fragment() -> None:
    """Fragment-scoped poller — runs every 250 ms without rebuilding the page.

    Drains the run queue and triggers a full rerun only when new events
    arrive.  When the investigation is idle the fragment exits silently,
    so the page is never rebuilt unnecessarily.
    """
    phase = state.get_live_phase()

    # Nothing to poll when idle.
    if phase == "idle":
        return

    # "done" transition: log completion, flip to idle, trigger one final
    # full rebuild so the results columns render with the finished state.
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
        st.rerun()
        return

    # Active investigation — drain queue.
    count, _done = state.drain_run_queue()

    thread = st.session_state.get("run_thread")

    if count > 0:
        # New events arrived — full rebuild so columns reflect new state.
        st.rerun()
    elif thread and not thread.is_alive():
        # Thread exited without sending "done" — force finalization.
        if state.get_live_phase() not in ("done", "idle"):
            state.set_live_phase("done")
        st.rerun()
    # Otherwise: queue empty, thread still alive — fragment exits silently.
    # No full rebuild; next fragment tick in 250 ms.


def _render_login() -> None:
    """Render the pre-app login gate.

    Shows a username / password form.  On success, calls ``state.login()``
    and triggers a full rerun so ``render_layout`` picks up the auth state.

    A dev bypass button is shown when ``DEV_BYPASS_AUTH=true`` is set.
    """
    _, col, _ = st.columns([1, 1, 1])
    with col:
        st.markdown("## Entity Risk Investigation")
        st.markdown("Sign in to continue.")

        error = state.get_auth_error()
        if error:
            st.error(error)

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="e.g. jr_analyst")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            user = authenticate(username.strip(), password)
            if user:
                state.login(user)
                st.rerun()
            else:
                state.set_auth_error("Invalid username or password.")
                st.rerun()

        if is_dev_bypass_enabled():
            st.divider()
            st.caption("Dev bypass enabled (`DEV_BYPASS_AUTH=true`)")
            if st.button("Enter as dev user (bypass)", use_container_width=True):
                state.login(dev_bypass_user())
                state.set_auth_dev_bypass(True)
                st.rerun()


def render_layout() -> None:
    """Render the full page.

    Entry point called by ``app.py``.  Call order:
      1. inject_styles         — global CSS (idempotent across reruns)
      2. state.init            — seed session_state defaults on first load
      3. auth gate             — returns early if not authenticated
      4. log startup           — once per browser session
      5. create_app_components — cached across reruns via @st.cache_resource
      6. render header + error banner — above the tabs
      7. render two tabs        — Investigate | Replay / Audit
         (progress bar rendered inside the Investigate tab)
      8. handle triggers        — consumed AFTER widgets render
      9. _polling_fragment      — fragment-scoped poller; triggers full reruns
                                  only when new events arrive
    """
    inject_styles()
    state.init()

    # ── Auth gate ────────────────────────────────────────────────────────
    if not state.is_authenticated():
        _render_login()
        return

    if not st.session_state.get("_app_started"):
        log_event("app_start")
        st.session_state["_app_started"] = True

    # ── Sidebar ─────────────────────────────────────────────────────────
    remote_url_configured = bool(os.getenv("REMOTE_MCP_URL"))
    with st.sidebar:
        st.markdown("### Settings")
        mcp_mode = st.radio(
            "Tool backend",
            options=["local", "remote"],
            format_func=lambda x: "Local (in-process)" if x == "local" else "Remote MCP Server",
            index=0,
            key="mcp_mode",
            help=(
                "Switch between the in-process tool layer and the hosted "
                "Railway MCP server. Set REMOTE_MCP_URL in .env to enable."
            ),
            disabled=not remote_url_configured,
        )
        if not remote_url_configured:
            st.caption("Set REMOTE_MCP_URL in .env to enable remote mode.")

        st.divider()
        user = state.get_authenticated_user()
        if user:
            st.caption(f"Signed in as **{user.user_id}**")
            st.caption(f"Role: `{user.role}`")
        if st.button("Sign out", key="btn_logout", use_container_width=True):
            state.logout()
            st.rerun()

    components = create_app_components(use_remote_mcp=(mcp_mode == "remote"))

    # ── Derive policy for current user ─────────────────────────────────
    _policy = get_policy_for_user(user) if user else None

    # ── Render page ────────────────────────────────────────────────────
    render_app_header()
    render_status_banner()  # error-only; hidden when idle

    # Build tab list based on what the current role can access.
    # Jr analysts see Investigate only; Sr analysts see both tabs.
    _tab_labels = ["🔍 Investigate"]
    _show_replay = _policy is not None and _policy.can_replay
    if _show_replay:
        _tab_labels.append("📼 Replay / Audit")

    _tabs = st.tabs(_tab_labels)
    tab_investigate = _tabs[0]
    tab_replay = _tabs[1] if _show_replay else None

    with tab_investigate:
        render_investigate_tab(components)

    if tab_replay is not None:
        with tab_replay:
            render_replay_tab(components)

    # ── Handle triggers AFTER all widgets are rendered ─────────────────
    # Triggers are set by widgets during this rerun; checking them here
    # ensures they are consumed on the same rerun that set them.
    # Both tabs are always evaluated by Streamlit on every rerun, so
    # triggers from either tab are reliably visible here.

    if st.session_state.pop("_trigger_replay", False):
        # Hard block: enforce replay access even if the session key was set
        # through a crafted path (e.g. direct URL param manipulation).
        if not _show_replay:
            _log.warning(
                "Replay attempt blocked for role '%s'",
                user.role if user else "unknown",
            )
            state.reset_replay_state()
        else:
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
        state.reset_replay_state()
        st.rerun()

    if st.session_state.pop("_trigger_run", False):
        question = state.get_question()
        if question:
            _allowed = _policy.allowed_mcp_tools if _policy is not None else None
            _start_investigation(components, question, allowed_tools=_allowed)
            st.rerun()  # immediately show "Planning…" state

    # ── Fragment-scoped poller ─────────────────────────────────────────
    # Runs every 250 ms; triggers a full rerun only when new events arrive.
    _polling_fragment()
