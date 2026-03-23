"""
src.app.components — Individual UI component renderers.

Design philosophy
-----------------
All user-facing text uses business-friendly language drawn from the
``_TASK_LABELS`` and ``_TASK_REASONING`` mapping dictionaries.  Technical
strings (task keys, agent keys, tool names) are shown only inside the
"View Technical Details" expander so analysts never see raw identifiers.

Risk signals (HIGH / MEDIUM / LOW) are colour-coded from the live
``findings`` data — nothing is invented or assumed.

Sections
--------
App header
    render_app_header        Full-width title / subtitle.

Left column
    render_investigation_input   Free-text question entry + submit button.
    render_final_answer          Risk headline card + entity resolution tags.

Center column
    render_planner_output        Plan summary: mode, entity, step list.
    render_execution_steps       Per-step cards with reasoning, risk, tools.

Right column
    render_trace_viewer          Decision Trace inspector (ID, stats, issues).
    render_replay_panel          Trace replay input + loaded state.

Shared
    render_status_banner         Live execution banner.
"""

from __future__ import annotations

import html as _html
from typing import TYPE_CHECKING, Any

import streamlit as st

import src.app.state as state

if TYPE_CHECKING:
    from src.app.factory import AppComponents


# ---------------------------------------------------------------------------
# Business-language mapping dictionaries
# ---------------------------------------------------------------------------

_TASK_LABELS: dict[str, str] = {
    "entity_lookup":                 "Identify the company",
    "company_profile":               "Retrieve company profile",
    "expand_ownership":              "Map ownership structure",
    "shared_address_check":          "Check address risk",
    "sic_context":                   "Analyse industry context",
    "ownership_complexity_check":    "Assess ownership complexity",
    "control_signal_check":          "Check control signals",
    "address_risk_check":            "Evaluate address risk",
    "industry_context_check":        "Evaluate industry context",
    "summarize_risk_for_company":    "Assess risk signals",
    "retrieve_trace":                "Retrieve decision trace",
    "find_traces_by_entity":         "Find company traces",
    "summarize_trace":               "Summarise investigation",
    "retrieve_and_summarize_trace":  "Review past investigation",
    "retrieve_latest_for_entity":    "Find latest investigation",
}

_TASK_REASONING: dict[str, str] = {
    "entity_lookup": (
        "We first confirmed the correct legal entity so that every subsequent "
        "step runs against the right company record."
    ),
    "company_profile": (
        "We retrieved the company's registered details — including its address "
        "and industry classification — to build a baseline profile."
    ),
    "expand_ownership": (
        "We mapped the full ownership chain to understand who controls the "
        "company, how many layers exist, and whether individual beneficial "
        "owners can be identified."
    ),
    "shared_address_check": (
        "We checked whether multiple companies share the same registered "
        "address — a common indicator of shell structures and formation-agent abuse."
    ),
    "sic_context": (
        "We examined the company's industry classification and its peer group "
        "to provide broader sector context."
    ),
    "ownership_complexity_check": (
        "We analysed the depth and structure of the ownership chain to flag "
        "complexity that may obscure beneficial ownership from regulators."
    ),
    "control_signal_check": (
        "We identified control mechanisms beyond simple share ownership — such "
        "as rights to appoint directors — that may indicate undisclosed influence."
    ),
    "address_risk_check": (
        "We assessed the registered address for co-location patterns "
        "associated with disposable shell companies."
    ),
    "industry_context_check": (
        "We evaluated the company's industry sector against known high-scrutiny "
        "classifications such as holding companies and dormant entities."
    ),
    "summarize_risk_for_company": (
        "We combined all risk signals — ownership complexity, control types, "
        "address risk, and industry context — to produce an overall risk assessment."
    ),
    "retrieve_trace": (
        "We retrieved the original investigation record to support audit review "
        "and replay."
    ),
    "find_traces_by_entity": (
        "We searched for all previous investigations involving this company "
        "to support continuity of review."
    ),
    "summarize_trace": (
        "We produced a narrative summary of the selected investigation for "
        "audit and compliance purposes."
    ),
    "retrieve_and_summarize_trace": (
        "We retrieved and summarised the full investigation record to provide "
        "a complete audit trail."
    ),
    "retrieve_latest_for_entity": (
        "We located the most recent investigation for this company to inform "
        "the current review."
    ),
}

_AGENT_LABELS: dict[str, str] = {
    "graph-agent": "Graph Agent",
    "risk-agent":  "Risk Agent",
    "trace-agent": "Trace Agent",
}

_AGENT_ICONS: dict[str, str] = {
    "graph-agent": "🔗",
    "risk-agent":  "⚠️",
    "trace-agent": "🗂️",
}

# Risk level design tokens — (text_colour, bg_colour, border_colour)
_RISK_COLORS: dict[str, tuple[str, str, str]] = {
    "HIGH":    ("#B91C1C", "#FEF2F2", "#FECACA"),
    "MEDIUM":  ("#92400E", "#FFFBEB", "#FDE68A"),
    "LOW":     ("#14532D", "#F0FDF4", "#BBF7D0"),
    "UNKNOWN": ("#374151", "#F9FAFB", "#E5E7EB"),
}

_RISK_ORDER: dict[str, int] = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}

# Headline copy shown in the Final Answer card
_RISK_HEADLINE: dict[str, tuple[str, str]] = {
    # risk_level → (headline_text, emoji)
    "HIGH":    ("High Risk Identified",           "⚠️"),
    "MEDIUM":  ("Moderate Risk Identified",       "⚡"),
    "LOW":     ("Low Risk — Standard Profile",    "✅"),
    "UNKNOWN": ("Risk Assessment Incomplete",     "❓"),
}

# Tasks that produce a risk_level in their findings
_RISK_TASKS = frozenset({
    "ownership_complexity_check",
    "control_signal_check",
    "address_risk_check",
    "industry_context_check",
})

# Status design tokens
_STATUS_ACCENT: dict[str, str] = {
    "success": "#16A34A",
    "failed":  "#DC2626",
    "skipped": "#9CA3AF",
    "running": "#D97706",
    "pending": "#3B82F6",
}

_STATUS_BG: dict[str, str] = {
    "success": "#F0FDF4",
    "failed":  "#FEF2F2",
    "skipped": "#F9FAFB",
    "running": "#FFFBEB",
    "pending": "#EFF6FF",
}

_STATUS_LABEL: dict[str, str] = {
    "success": "🟢 Complete",
    "failed":  "🔴 Failed",
    "skipped": "⚪ Skipped",
    "running": "🟡 Running",
    "pending": "🔵 Pending",
}


# ---------------------------------------------------------------------------
# Low-level HTML helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """HTML-escape text (< > & only; leaves quotes intact for div content)."""
    return _html.escape(str(text), quote=False)


def _pill(text: str, bg: str, color: str, border: str = "transparent") -> str:
    """Return a single inline HTML pill/chip span."""
    return (
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'border:1px solid {border};border-radius:12px;padding:2px 10px;'
        f'font-size:0.78em;font-weight:500;font-family:monospace;margin:2px 4px 2px 0">'
        f'{_esc(text)}</span>'
    )


def _risk_badge(risk_level: str) -> str:
    """Return a coloured HTML badge for a risk level string."""
    key = risk_level.upper() if risk_level else "UNKNOWN"
    tc, bg, border = _RISK_COLORS.get(key, _RISK_COLORS["UNKNOWN"])
    emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(key, "⚪")
    return (
        f'<span style="background:{bg};color:{tc};border:1px solid {border};'
        f'border-radius:6px;padding:3px 11px;font-size:0.82em;font-weight:700;'
        f'display:inline-block">{emoji} {_esc(risk_level)}</span>'
    )


def _tool_pills(tools: list[str]) -> str:
    """Return an HTML row of monospace tool-name pills."""
    if not tools:
        return ""
    pills = "".join(_pill(t, "#EFF6FF", "#1D4ED8", "#BFDBFE") for t in tools)
    return (
        '<div style="margin:6px 0 4px 0">'
        '<span style="font-size:0.7em;color:#6B7280;font-weight:700;'
        'text-transform:uppercase;letter-spacing:0.05em">Tools&nbsp;&nbsp;</span>'
        f'{pills}</div>'
    )


def _label_row(text: str) -> None:
    """Render an uppercase micro-label (section separator inside cards)."""
    st.markdown(
        f'<div style="font-size:0.68em;font-weight:700;color:#9CA3AF;'
        f'text-transform:uppercase;letter-spacing:0.06em;margin:10px 0 4px 0">'
        f'{_esc(text)}</div>',
        unsafe_allow_html=True,
    )


def _section_header(title: str, subtitle: str = "") -> None:
    """Render a styled section header with optional helper-text subtitle."""
    sub = (
        f'<span style="display:block;font-size:0.78em;color:#6B7280;margin-top:2px">'
        f'{_esc(subtitle)}</span>'
        if subtitle else ""
    )
    st.markdown(
        f'<div style="margin-bottom:10px">'
        f'<span style="font-size:1.05em;font-weight:700;color:#111827">'
        f'{_esc(title)}</span>{sub}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Display-name helpers
# ---------------------------------------------------------------------------

def _task_label(task: str) -> str:
    """Return the business-friendly display name for a task key."""
    return _TASK_LABELS.get(task, task.replace("_", " ").title())


def _agent_display(agent: str) -> str:
    """Return 'icon Display Name' for an agent key."""
    icon  = _AGENT_ICONS.get(agent, "·")
    label = _AGENT_LABELS.get(agent, agent)
    return f"{icon} {label}"


# ---------------------------------------------------------------------------
# Risk extraction helpers
# ---------------------------------------------------------------------------

def _overall_risk_from_result(result: Any) -> str | None:
    """Scan step findings for the highest risk level present.

    Checks ``summarize_risk_for_company`` findings (which bundle all 4
    signals) first, then individual risk task results, then falls back to
    parsing the last word of the final-answer text.

    Returns ``None`` if no risk data is available (e.g. trace-mode queries).
    """
    best: str | None = None

    for sr in (result.step_results or []):
        if not sr.success:
            continue
        if sr.task == "summarize_risk_for_company":
            for task in _RISK_TASKS:
                data = sr.findings.get(task)
                if isinstance(data, dict):
                    lvl = data.get("risk_level", "")
                    if _RISK_ORDER.get(lvl, -1) > _RISK_ORDER.get(best, -1):
                        best = lvl
        elif sr.task in _RISK_TASKS:
            data = sr.findings.get(sr.task)
            if isinstance(data, dict):
                lvl = data.get("risk_level", "")
                if _RISK_ORDER.get(lvl, -1) > _RISK_ORDER.get(best, -1):
                    best = lvl

    # Fallback: the RiskAgent system prompt ends every summary with the risk level
    if not best:
        answer = (result.final_answer or "").strip().upper()
        for lvl in ("HIGH", "MEDIUM", "LOW"):
            if answer.endswith(lvl) or f" {lvl}." in answer or f" {lvl}," in answer:
                best = lvl
                break

    return best


def _render_risk_breakdown(findings: dict) -> None:
    """Render the 4-signal risk grid for a ``summarize_risk_for_company`` step."""
    checks = [
        ("ownership_complexity_check", "Ownership"),
        ("control_signal_check",       "Control"),
        ("address_risk_check",         "Address"),
        ("industry_context_check",     "Industry"),
    ]
    cols = st.columns(4)
    for col, (task_key, label) in zip(cols, checks):
        data = findings.get(task_key)
        risk = (
            data.get("risk_level", "UNKNOWN")
            if isinstance(data, dict)
            else "UNKNOWN"
        )
        tc, bg, border = _RISK_COLORS.get(risk, _RISK_COLORS["UNKNOWN"])
        col.markdown(
            f'<div style="text-align:center;background:{bg};'
            f'border:1px solid {border};border-radius:8px;'
            f'padding:9px 4px;margin:4px 2px">'
            f'<div style="font-size:0.62em;color:#6B7280;text-transform:uppercase;'
            f'letter-spacing:0.05em;font-weight:700;margin-bottom:5px">{label}</div>'
            f'<div style="font-size:0.82em;font-weight:800;color:{tc}">{_esc(risk)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _accent_bar(status: str) -> None:
    """Thin 3 px coloured stripe above each step card — encodes status at a glance."""
    color = _STATUS_ACCENT.get(status, "#D1D5DB")
    st.markdown(
        f'<div style="height:3px;background:{color};border-radius:2px;'
        f'margin-top:14px;margin-bottom:3px"></div>',
        unsafe_allow_html=True,
    )


def _step_header_html(
    index: int,
    task_display: str,
    agent_display: str,
    status: str,
) -> str:
    """Return the HTML for the top row of a step card."""
    badge_bg    = _STATUS_BG.get(status, "#F9FAFB")
    badge_color = _STATUS_ACCENT.get(status, "#6B7280")
    status_text = _STATUS_LABEL.get(status, status)
    return (
        '<div style="display:flex;align-items:center;justify-content:space-between;'
        'padding:2px 0 8px 0;flex-wrap:wrap;gap:6px">'
        '  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        f'    <span style="font-size:0.7em;font-weight:700;color:#6B7280;'
        f'      background:#F3F4F6;border-radius:4px;padding:1px 7px">#{index}</span>'
        f'    <span style="font-weight:600;color:#111827;font-size:0.92em">'
        f'      {_esc(task_display)}</span>'
        f'    <span style="font-size:0.75em;background:#F3F4F6;color:#374151;'
        f'      border-radius:10px;padding:2px 9px;white-space:nowrap">'
        f'      {_esc(agent_display)}</span>'
        f'  </div>'
        f'  <span style="background:{badge_bg};color:{badge_color};'
        f'    border:1px solid {badge_color}33;border-radius:10px;'
        f'    padding:2px 11px;font-size:0.72em;font-weight:600;white-space:nowrap">'
        f'    {_esc(status_text)}</span>'
        '</div>'
    )


# ---------------------------------------------------------------------------
# App header
# ---------------------------------------------------------------------------


def render_app_header() -> None:
    """Full-width app title and subtitle rendered above the column layout."""
    st.markdown(
        '<div style="padding:0.3rem 0 1.4rem 0;border-bottom:1px solid #E5E7EB;'
        'margin-bottom:1.2rem">'
        '<span style="font-size:1.65em;font-weight:800;color:#111827;'
        'letter-spacing:-0.02em">🔍 Entity Risk AI</span>'
        '<span style="display:block;font-size:0.87em;color:#6B7280;margin-top:5px">'
        'Investigate ownership, risk, and traceable decisions'
        '</span>'
        '</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Left column
# ---------------------------------------------------------------------------


def render_investigation_input(components: "AppComponents") -> None:
    """Free-text investigation question and submit button."""
    _section_header("🔍 Investigation", "Ask a question about any UK company")
    question = st.text_area(
        label="Question",
        label_visibility="collapsed",
        value=state.get_question(),
        height=110,
        placeholder=(
            "e.g. Investigate Acme Holdings Ltd for ownership risk\n"
            "e.g. Who controls Redwood Ventures Ltd?"
        ),
        key="_input_question",
    )
    st.caption("Enter a company name or a free-text compliance question.")
    submitted = st.button(
        "Run Investigation", type="primary", use_container_width=True
    )
    if submitted and question.strip():
        state.set_question(question.strip())
        st.session_state["_trigger_run"] = True


def render_final_answer(components: "AppComponents") -> None:
    """Risk headline card with colour-coded risk level and entity resolution tags."""
    _section_header("Assessment")
    result = state.get_result()

    if result is None:
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:10px 0">'
            'The risk assessment will appear here after a run.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    answer = result.final_answer or "Investigation complete — no summary generated."

    if result.success:
        # Determine risk level from findings or final answer text
        risk_level = _overall_risk_from_result(result)
        if risk_level:
            headline_text, headline_emoji = _RISK_HEADLINE.get(
                risk_level, ("Assessment Complete", "✅")
            )
            tc, bg, border = _RISK_COLORS.get(risk_level, _RISK_COLORS["UNKNOWN"])
        else:
            # Non-risk mode (trace query, lookup, etc.)
            headline_text, headline_emoji = "Investigation Complete", "✅"
            tc, bg, border = "#14532D", "#F0FDF4", "#BBF7D0"
    else:
        headline_text, headline_emoji = "Investigation Failed", "🔴"
        tc, bg, border = "#B91C1C", "#FEF2F2", "#FECACA"

    # ── Headline card ──────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:{bg};border:1px solid {border};'
        f'border-left:4px solid {tc};border-radius:8px;'
        f'padding:14px 18px;margin:4px 0 12px 0">'
        f'<div style="font-size:0.8em;font-weight:800;color:{tc};'
        f'text-transform:uppercase;letter-spacing:0.07em;margin-bottom:9px">'
        f'{headline_emoji} &nbsp;{_esc(headline_text)}</div>'
        f'<div style="color:#1F2937;line-height:1.7;font-size:0.88em">'
        f'{_esc(answer)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Errors (failure mode only) ─────────────────────────────────────
    if not result.success and result.errors:
        for e in result.errors:
            st.error(e)

    # ── Warnings ───────────────────────────────────────────────────────
    if result.warnings:
        with st.expander(f"⚠️ {len(result.warnings)} warning(s)", expanded=False):
            for w in result.warnings:
                st.warning(w)

    # ── Resolved entity tags ───────────────────────────────────────────
    if result.resolved_entities:
        pills_html = ""
        for name, data in result.resolved_entities.items():
            if data is None:
                pills_html += _pill(f"❌ {name} — not found", "#FEF2F2", "#B91C1C", "#FECACA")
            else:
                canonical     = data.get("canonical_name", name)
                exact         = data.get("exact_match", True)
                company_no    = data.get("company_number", "")
                qualifier     = "exact match" if exact else "closest match"
                display       = canonical
                if company_no:
                    display += f"  ·  #{company_no}"
                display += f"  ·  {qualifier}"
                pills_html += _pill(f"✅ {display}", "#F0FDF4", "#15803D", "#BBF7D0")

        st.markdown(
            '<div style="margin-top:10px">'
            '<span style="font-size:0.68em;font-weight:700;color:#9CA3AF;'
            'text-transform:uppercase;letter-spacing:0.05em">'
            'Entities&nbsp;&nbsp;</span>'
            f'{pills_html}</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Center column
# ---------------------------------------------------------------------------


def render_planner_output(components: "AppComponents") -> None:
    """Investigation plan: mode, entity, reason, and a clean step list."""
    _section_header("📋 Investigation Plan")
    result = state.get_result()

    if result is None or not result.planner_output:
        st.caption("The investigation plan will appear here after a run.")
        return

    plan: dict[str, Any] = result.planner_output

    with st.container(border=True):
        col_mode, col_entity = st.columns([1, 2])
        col_mode.metric("Mode", plan.get("mode", "—").title())

        entities = plan.get("entities") or []
        entity_str = "  ·  ".join(e["name"] for e in entities) if entities else "—"
        col_entity.metric("Entity", entity_str)

        reason = plan.get("reason", "")
        if reason:
            st.markdown(
                f'<div style="font-size:0.83em;color:#374151;'
                f'border-left:3px solid #E5E7EB;padding:4px 0 4px 10px;'
                f'margin:10px 0 8px 0;line-height:1.55">'
                f'{_esc(reason)}</div>',
                unsafe_allow_html=True,
            )

        steps = plan.get("plan") or []
        if steps:
            _label_row("Steps")
            for i, s in enumerate(steps, start=1):
                agent_key  = s.get("agent", "")
                task_key   = s.get("task",  "")
                task_disp  = _task_label(task_key)
                agent_disp = _agent_display(agent_key)
                # Render as a clean scannable row — no expanding needed
                st.markdown(
                    f'<div style="display:flex;align-items:center;'
                    f'justify-content:space-between;padding:7px 2px;'
                    f'border-bottom:1px solid #F3F4F6">'
                    f'  <div style="display:flex;align-items:center;gap:8px">'
                    f'    <span style="font-size:0.68em;font-weight:700;color:#9CA3AF;'
                    f'      background:#F3F4F6;border-radius:3px;padding:1px 6px">#{i}</span>'
                    f'    <span style="font-size:0.87em;color:#1F2937;font-weight:500">'
                    f'      {_esc(task_disp)}</span>'
                    f'  </div>'
                    f'  <span style="font-size:0.74em;background:#F3F4F6;color:#374151;'
                    f'    border-radius:10px;padding:2px 9px;white-space:nowrap">'
                    f'    {_esc(agent_disp)}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        with st.expander("View technical plan details", expanded=False):
            st.json(plan)


def render_execution_steps(components: "AppComponents") -> None:
    """Ordered step cards, each showing reasoning, tools, risk signals, and summary."""
    _section_header("⚙️ Execution", "Step-by-step agent results")
    result = state.get_result()

    if result is None:
        st.caption("Step results will appear here after a run.")
        return
    if not result.step_results:
        st.caption("No steps were executed.")
        return

    for i, step in enumerate(result.step_results, start=1):
        _render_step_card(i, step)


def _render_step_card(index: int, step: Any) -> None:
    """Render a single execution step as a colour-accented bordered card.

    Card anatomy
    ------------
    [3 px status-colour accent bar]
    ┌─ bordered container ──────────────────────────────────┐
    │  #N  Business task name   [icon Agent]   🟢 Complete  │
    │                                                        │
    │  Why this step matters:                               │
    │  Italic reasoning text…                               │
    │                                                        │
    │  Tools  [tool_1] [tool_2]                             │
    │                                                        │
    │  [4-signal risk grid  — summarize step only]          │
    │  [Single risk badge   — individual risk step]         │
    │                                                        │
    │  Summary text…                                        │
    │  Error block (if failed)                              │
    │  Skip reason (if skipped)                             │
    │                                                        │
    │  ▶ View Technical Details                             │
    └────────────────────────────────────────────────────────┘
    """
    status       = step.status
    task_key     = step.task    or ""
    agent_key    = step.agent   or ""
    task_display  = _task_label(task_key)
    agent_display = _agent_display(agent_key)
    reasoning     = _TASK_REASONING.get(task_key, "")
    findings: dict = step.findings or {}

    _accent_bar(status)

    with st.container(border=True):
        # ── Header row ─────────────────────────────────────────────────
        st.markdown(
            _step_header_html(index, task_display, agent_display, status),
            unsafe_allow_html=True,
        )

        # ── Reasoning ──────────────────────────────────────────────────
        if reasoning:
            st.markdown(
                f'<div style="border-left:3px solid #E5E7EB;padding:3px 0 3px 10px;'
                f'color:#6B7280;font-size:0.81em;font-style:italic;'
                f'margin:4px 0 8px 0;line-height:1.55">'
                f'{_esc(reasoning)}</div>',
                unsafe_allow_html=True,
            )

        # ── Tool pills ─────────────────────────────────────────────────
        tools: list[str] = step.tools_executed or []
        if tools:
            st.markdown(_tool_pills(tools), unsafe_allow_html=True)

        # ── Status-specific body ───────────────────────────────────────
        if status == "skipped":
            skip_text = step.skip_reason or "This step was not executed."
            st.markdown(
                f'<div style="color:#6B7280;font-size:0.82em;font-style:italic;'
                f'padding:4px 0 2px 0">{_esc(skip_text)}</div>',
                unsafe_allow_html=True,
            )
        else:
            # Risk signals
            if task_key == "summarize_risk_for_company" and findings:
                _render_risk_breakdown(findings)

            elif task_key in _RISK_TASKS and findings:
                data = findings.get(task_key)
                risk = data.get("risk_level") if isinstance(data, dict) else None
                if risk:
                    st.markdown(
                        f'<div style="margin:8px 0 4px 0">'
                        f'<span style="font-size:0.7em;color:#6B7280;font-weight:700;'
                        f'text-transform:uppercase;letter-spacing:0.05em">'
                        f'Risk&nbsp;&nbsp;</span>'
                        f'{_risk_badge(risk)}</div>',
                        unsafe_allow_html=True,
                    )

            # Summary
            summary: str = step.summary or ""
            if summary:
                st.markdown(
                    f'<div style="color:#1F2937;font-size:0.87em;line-height:1.65;'
                    f'padding:6px 0 4px 0">{_esc(summary)}</div>',
                    unsafe_allow_html=True,
                )

            if step.error:
                st.error(f"Error: {step.error}")

        # ── Technical details expander ─────────────────────────────────
        with st.expander("View Technical Details", expanded=False):
            if findings:
                _label_row("Findings")
                st.json(findings)
            _label_row("Raw Step")
            raw = (
                step.to_dict()
                if hasattr(step, "to_dict")
                else {
                    "step_id":        step.step_id,
                    "agent":          step.agent,
                    "task":           step.task,
                    "status":         status,
                    "success":        step.success,
                    "summary":        step.summary,
                    "tools_executed": step.tools_executed,
                    "error":          step.error,
                    "skipped":        step.skipped,
                    "skip_reason":    step.skip_reason,
                }
            )
            st.json(raw)


# ---------------------------------------------------------------------------
# Right column
# ---------------------------------------------------------------------------


def render_trace_viewer(components: "AppComponents") -> None:
    """Decision Trace inspector — trace ID, step counts, issues."""
    _section_header("🗂️ Decision Trace", "Audit log for this investigation")
    trace_id = state.get_trace_id()
    result   = state.get_result()

    if trace_id is None:
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.82em;padding:8px 0">'
            'Trace details will appear here after a run.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Trace ID block ─────────────────────────────────────────────────
    st.markdown(
        '<div style="background:#F3F4F6;border-radius:6px;'
        'padding:10px 12px;margin:6px 0 12px 0">'
        '<div style="font-size:0.66em;color:#6B7280;text-transform:uppercase;'
        'letter-spacing:0.06em;font-weight:700;margin-bottom:4px">Trace ID</div>'
        f'<code style="font-size:0.76em;color:#374151;word-break:break-all">'
        f'{_esc(trace_id)}</code></div>',
        unsafe_allow_html=True,
    )

    if result is None:
        return

    # ── Step stats ─────────────────────────────────────────────────────
    steps = result.step_results or []
    if steps:
        n_done    = sum(1 for s in steps if s.status == "success")
        n_failed  = sum(1 for s in steps if s.status == "failed")
        n_skipped = sum(1 for s in steps if s.status == "skipped")
        c1, c2, c3 = st.columns(3)
        c1.metric("Completed", n_done)
        c2.metric("Failed",    n_failed)
        c3.metric("Skipped",   n_skipped)

    # ── Short trace summary ────────────────────────────────────────────
    # Derive a one-line summary from the step outcomes without backend calls
    if steps:
        agents_run = sorted({
            _AGENT_LABELS.get(s.agent, s.agent)
            for s in steps if s.status == "success"
        })
        if agents_run:
            st.markdown(
                f'<div style="font-size:0.8em;color:#374151;margin:8px 0 10px 0;'
                f'line-height:1.5">'
                f'Agents involved: {", ".join(agents_run)}.'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Issues ─────────────────────────────────────────────────────────
    if result.errors:
        with st.expander(f"🔴 {len(result.errors)} error(s)", expanded=True):
            for e in result.errors:
                st.error(e)

    if result.warnings:
        with st.expander(f"⚠️ {len(result.warnings)} warning(s)", expanded=False):
            for w in result.warnings:
                st.warning(w)


def render_replay_panel(components: "AppComponents") -> None:
    """Trace replay — load any past investigation by trace ID."""
    _section_header("🔄 Replay / Audit", "Load a past investigation")

    with st.container(border=True):
        replay_id = st.text_input(
            label="Trace ID",
            label_visibility="collapsed",
            value=state.get_replay_trace_id() or "",
            placeholder="Enter a trace ID to replay…",
            key="_input_replay_trace_id",
        )
        load = st.button("Load Trace", use_container_width=True)
        if load and replay_id.strip():
            state.set_replay_trace_id(replay_id.strip())
            st.session_state["_trigger_replay"] = True

        replay_trace_id = state.get_replay_trace_id()
        if replay_trace_id:
            st.markdown(
                '<div style="background:#F0F9FF;border:1px solid #BAE6FD;'
                'border-left:3px solid #0EA5E9;border-radius:6px;'
                'padding:10px 14px;margin-top:10px">'
                '<div style="font-size:0.66em;font-weight:700;color:#0284C7;'
                'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:5px">'
                'Trace loaded</div>'
                f'<code style="font-size:0.76em;color:#0C4A6E;word-break:break-all">'
                f'{_esc(replay_trace_id)}</code>'
                '<div style="font-size:0.78em;color:#6B7280;margin-top:8px">'
                'Full replay view coming in a future release.</div>'
                '</div>',
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def render_status_banner() -> None:
    """Full-width live status bar.

    Hidden when idle.  Amber while running; falls back to st.error for
    persistent failure messages.
    """
    status = state.get_status()
    if not status.get("running") and not status.get("message"):
        return

    if status.get("running"):
        step = status.get("step")
        msg  = status.get("message") or "Running investigation…"
        text = f"{msg} · step: {step}" if step else msg
        st.markdown(
            f'<div style="background:#FFFBEB;border:1px solid #FDE68A;'
            f'border-radius:8px;padding:11px 16px;margin-bottom:12px;'
            f'color:#92400E;font-size:0.87em;font-weight:500">'
            f'🟡 &nbsp;{_esc(text)}</div>',
            unsafe_allow_html=True,
        )
    elif status.get("message"):
        st.error(status["message"])
