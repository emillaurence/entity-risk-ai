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
import re as _re
from datetime import datetime as _datetime
from types import SimpleNamespace as _NS
from typing import TYPE_CHECKING, Any

import streamlit as st

import src.app.state as state

if TYPE_CHECKING:
    from src.app.factory import AppComponents


# ---------------------------------------------------------------------------
# Business-language mapping dictionaries
# ---------------------------------------------------------------------------

_TASK_LABELS: dict[str, str] = {
    "entity_lookup":                 "Confirm company identity",
    "company_profile":               "Retrieve company profile",
    "expand_ownership":              "Analyse ownership structure",
    "shared_address_check":          "Assess address risk",
    "sic_context":                   "Assess industry context",
    "ownership_complexity_check":    "Assess ownership complexity",
    "control_signal_check":          "Analyse control signals",
    "address_risk_check":            "Assess address risk",
    "industry_context_check":        "Assess industry context",
    "summarize_risk_for_company":    "Assess risk signals",
    "retrieve_trace":                "Retrieve decision trace",
    "find_traces_by_entity":         "Find company traces",
    "summarize_trace":               "Summarise investigation",
    "retrieve_and_summarize_trace":  "Review past investigation",
    "retrieve_latest_for_entity":    "Find latest investigation",
}

_TASK_REASONING: dict[str, str] = {
    "entity_lookup": (
        "We confirmed the correct legal entity so that every subsequent "
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

_EVENT_TYPE_LABELS: dict[str, str] = {
    "plan_created":           "Investigation plan generated",
    "step_started":           "Analysis step started",
    "step_completed":         "Analysis step completed",
    "step_failed":            "Analysis step failed",
    "tool_called":            "Data lookup started",
    "tool_returned":          "Data retrieved",
    "agent_reasoning":        "Entity resolution",
    "investigation_complete": "Investigation complete",
}

_EVENT_TYPE_ICONS: dict[str, str] = {
    "plan_created":           "📋",
    "step_started":           "▶",
    "step_completed":         "✅",
    "step_failed":            "🔴",
    "tool_called":            "🔧",
    "tool_returned":          "📦",
    "agent_reasoning":        "🔎",
    "investigation_complete": "🏁",
}

# Business-friendly mode display names
_MODE_DISPLAY: dict[str, str] = {
    "investigate": "Ownership & Risk Analysis",
    "trace":       "Audit Review",
}

# Tooltip copy for audit timeline event types
_EVENT_TYPE_TOOLTIPS: dict[str, str] = {
    "plan_created": (
        "The system generated a structured investigation plan "
        "based on the original question."
    ),
    "step_started": "An analysis step began executing.",
    "step_completed": "An analysis step completed successfully.",
    "step_failed": "An analysis step encountered an error.",
    "tool_called": (
        "A data lookup was initiated against the registry "
        "or risk database."
    ),
    "tool_returned": (
        "Data was retrieved and passed to the analysis engine."
    ),
    "agent_reasoning": (
        "The system matched the provided company name to the most "
        "relevant legal entity in the registry."
    ),
    "investigation_complete": (
        "All planned analysis steps have concluded and "
        "a final assessment was produced."
    ),
}

# Context-aware labels for tool_returned events (keyed by tool_name)
_TOOL_RETURNED_LABELS: dict[str, str] = {
    "entity_lookup":                 "Company identity confirmed",
    "company_profile":               "Company data retrieved",
    "expand_ownership":              "Ownership data analysed",
    "shared_address_check":          "Address risk assessed",
    "sic_context":                   "Industry context assessed",
    "ownership_complexity_check":    "Ownership complexity assessed",
    "control_signal_check":          "Control signals assessed",
    "address_risk_check":            "Address risk evaluated",
    "industry_context_check":        "Industry context assessed",
    "summarize_risk_for_company":    "Risk signals evaluated",
}

# Recommendations keyed by risk level — shown under the headline in assessment cards
_RISK_RECOMMENDATIONS: dict[str, str] = {
    "HIGH":   "Recommendation: Enhanced due diligence required.",
    "MEDIUM": "Recommendation: Additional review advised.",
    "LOW":    "Recommendation: Standard monitoring applies.",
}

# Fallback plan description per investigation mode
_MODE_PLAN_FALLBACK: dict[str, str] = {
    "investigate": (
        "This investigation analysed ownership structure and key risk signals "
        "to assess overall exposure."
    ),
    "trace": (
        "This review examined a prior investigation record for audit and "
        "compliance purposes."
    ),
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
        'text-transform:uppercase;letter-spacing:0.05em">Tools used&nbsp;&nbsp;</span>'
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


def _first_sentences(text: str, n: int = 1) -> str:
    """Return the first n sentences from text.

    Splits on ``.`` / ``!`` / ``?`` punctuation.  Falls back to the full
    text if fewer than n sentence boundaries are found.
    """
    if not text:
        return ""
    s = text.strip()
    count = 0
    for i, ch in enumerate(s):
        if ch in ".!?":
            count += 1
            if count >= n:
                return s[: i + 1].strip()
    return s


def _display_question(query: str) -> str:
    """Return a display-friendly question string.

    If the query already reads as a question or investigation request,
    return it as-is.  Otherwise prefix with 'Investigate' so the label
    is always complete and scannable.
    """
    if not query:
        return ""
    q = query.strip()
    markers = ("?", "who ", "what ", " is ", " are ", " does ",
               "investigate", "find", "check", "assess", "review")
    if any(m in q.lower() for m in markers):
        return q
    return f"Investigate {q}"


def _clean_event_text(text: str) -> str:
    """Strip technical/debug fragments from event summaries.

    Removes:
    - Token counts:  "| tokens in=96 out=43"
    - AI task lines: "AI summary generated for task '...' ..."
    """
    if not text:
        return text
    # Strip "| tokens in=N out=N" anywhere in the string
    cleaned = _re.sub(r"\|\s*tokens\s+in=\d+\s+out=\d+", "", text, flags=_re.IGNORECASE)
    # Remove lines that are purely "AI summary generated for task '...' ..."
    cleaned = _re.sub(
        r"^AI summary generated for task '[^']*'[^\n]*\n?",
        "",
        cleaned,
        flags=_re.IGNORECASE | _re.MULTILINE,
    )
    return cleaned.strip()


def _get_summarize_findings(result: Any) -> dict | None:
    """Return findings from the summarize_risk_for_company step, or None."""
    for sr in result.step_results or []:
        if sr.task == "summarize_risk_for_company" and sr.success and sr.findings:
            return sr.findings
    return None


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


def _render_assessment_card(
    headline_text: str,
    headline_emoji: str,
    risk_level: "str | None",
    summary: str,
    tc: str,
    bg: str,
    border: str,
) -> None:
    """Render the main risk assessment card — identical HTML in both investigate and replay modes.

    ``summary`` is truncated to 2 sentences for the inline display; the full
    text is shown in the "Full Assessment" expander rendered by the caller.
    """
    subheadline_html = (
        f'<div style="font-size:0.78em;font-weight:600;color:{tc};'
        f'opacity:0.85;margin:3px 0 6px 0">'
        f'Overall Risk Level: {_esc(risk_level.title())}</div>'
        if risk_level else ""
    )
    recommendation = _RISK_RECOMMENDATIONS.get(risk_level or "")
    rec_html = (
        f'<div style="font-size:0.82em;font-weight:600;color:{tc};'
        f'margin:2px 0 10px 0">{_esc(recommendation)}</div>'
        if recommendation else ""
    )
    short_summary = _first_sentences(summary, 2)
    summary_section = (
        f'<div style="font-size:0.66em;font-weight:700;color:{tc};opacity:0.7;'
        f'text-transform:uppercase;letter-spacing:0.06em;margin:12px 0 4px 0">'
        f'Summary</div>'
        f'<div style="color:#374151;font-size:0.87em;line-height:1.65">'
        f'{_esc(short_summary)}</div>'
        if short_summary else ""
    )
    st.markdown(
        f'<div style="background:{bg};border:1px solid {border};'
        f'border-left:5px solid {tc};border-radius:8px;'
        f'padding:16px 20px;margin:4px 0 12px 0">'
        f'<div style="font-size:1.05em;font-weight:800;color:{tc};'
        f'line-height:1.2;margin-bottom:2px">'
        f'{headline_emoji} &nbsp;{_esc(headline_text)}</div>'
        f'{subheadline_html}'
        f'{rec_html}'
        f'{summary_section}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_risk_drivers_grid(dims: "dict[str, str]") -> None:
    """Render the 4-signal horizontal risk grid — shared by investigate and replay modes.

    ``dims`` must have keys ``ownership``, ``control``, ``address``,
    ``industry`` mapping to ``'HIGH'``, ``'MEDIUM'``, ``'LOW'``, or
    ``'UNKNOWN'``.  Missing keys fall back to ``'UNKNOWN'``.

    This is the single canonical component for risk-driver display.
    Both investigate mode (via ``_render_risk_breakdown``) and replay mode
    (via ``render_final_answer``) call this function so the layout, spacing,
    colours, font sizes, and border radius are always identical.
    """
    checks = [
        ("ownership", "Ownership"),
        ("control",   "Control"),
        ("address",   "Address"),
        ("industry",  "Industry"),
    ]
    cols = st.columns(4)
    for col, (dim_key, label) in zip(cols, checks):
        risk = dims.get(dim_key) or "UNKNOWN"
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


def _render_risk_breakdown(findings: dict) -> None:
    """Render the 4-signal risk grid for a ``summarize_risk_for_company`` step.

    Converts the structured findings dict to the normalised ``dims`` format
    and delegates to ``_render_risk_drivers_grid``.
    """
    task_to_dim = [
        ("ownership_complexity_check", "ownership"),
        ("control_signal_check",       "control"),
        ("address_risk_check",         "address"),
        ("industry_context_check",     "industry"),
    ]
    dims: dict[str, str] = {}
    for task_key, dim_key in task_to_dim:
        data = findings.get(task_key)
        dims[dim_key] = (
            data.get("risk_level", "UNKNOWN") if isinstance(data, dict) else "UNKNOWN"
        )
    _render_risk_drivers_grid(dims)


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
        '<div style="padding:1.2rem 0 1.1rem 0;border-bottom:1px solid #E5E7EB;'
        'margin-bottom:1.4rem">'
        '<div style="font-size:1.55rem;font-weight:800;color:#111827;'
        'letter-spacing:-0.02em;line-height:1.3">'
        'Entity Risk AI'
        '</div>'
        '<div style="font-size:0.875rem;color:#6B7280;margin-top:5px;'
        'font-weight:400;line-height:1.5">'
        'Investigate ownership, risk, and traceable decisions'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_replay_mode_banner() -> None:
    """Show a prominent banner when the app is in replay / audit mode.

    Call this immediately after ``render_status_banner()`` in the layout.
    Hidden when replay is not active.
    """
    if state.get_replay_status() != "loaded" or state.get_live_phase() != "idle":
        return
    replay_data = state.get_replay_data()
    if not replay_data:
        return

    query      = replay_data.get("query", "")
    mode       = replay_data.get("mode", "")
    ended_at   = replay_data.get("ended_at") or ""
    mode_text  = _MODE_DISPLAY.get(mode, mode.title() if mode else "Investigation")
    # Show only first part of entity name to keep banner compact
    entity_esc = _esc(query[:55] + "…" if len(query) > 55 else query)

    # Completion time — time only (short) for banner; full timestamp in right panel
    ended_time = ""
    if ended_at:
        try:
            dt_utc   = _datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone()
            hour     = str(int(dt_local.strftime("%I")))
            minute   = dt_local.strftime("%M")
            ampm     = dt_local.strftime("%p")
            ended_time = f"{hour}:{minute} {ampm}"
        except Exception:
            ended_time = ""

    completed_html = (
        f'&nbsp;&nbsp;·&nbsp;&nbsp;'
        f'<span style="color:#6B7280">Completed</span>&nbsp;{_esc(ended_time)}'
        if ended_time else ""
    )

    st.markdown(
        f'<div style="background:#EFF6FF;border:1px solid #BFDBFE;'
        f'border-left:5px solid #3B82F6;border-radius:8px;'
        f'padding:8px 14px;margin-bottom:12px">'
        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
        f'  <span style="font-size:0.90em;font-weight:800;color:#1D4ED8">'
        f'    📼 Replay Mode</span>'
        f'  <span style="font-size:0.80em;color:#1E3A8A">'
        f'    — Viewing a previous investigation (read-only)</span>'
        f'  <span style="font-size:0.74em;background:#DBEAFE;color:#1D4ED8;'
        f'    border-radius:10px;padding:1px 8px;font-weight:600">'
        f'    {_esc(mode_text)}</span>'
        f'</div>'
        f'<div style="margin-top:3px;font-size:0.79em;color:#374151">'
        f'  <span style="color:#6B7280">Entity:</span>&nbsp;{entity_esc}'
        f'  {completed_html}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Left column
# ---------------------------------------------------------------------------


def render_investigation_input(components: "AppComponents") -> None:
    """Free-text investigation question and submit button.

    In replay mode: shows a read-only card with the original question
    above the standard input form so reviewers immediately know what
    was asked in the investigation they are viewing.
    """
    _section_header("🔍 Investigation", "Ask a question about any UK company")

    # ── Replay mode: show original question ────────────────────────────
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()
    if replay_status == "loaded" and replay_data and state.get_live_phase() == "idle":
        raw_q = replay_data.get("query", "")
        if raw_q:
            display_q = _display_question(raw_q)
            st.markdown(
                f'<div style="background:#EFF6FF;border:1px solid #BFDBFE;'
                f'border-left:4px solid #3B82F6;border-radius:6px;'
                f'padding:10px 14px;margin-bottom:14px">'
                f'<div style="font-size:0.66em;font-weight:700;color:#3B82F6;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:5px">'
                f'Original Question</div>'
                f'<div style="font-size:0.87em;color:#1E3A8A;line-height:1.55;'
                f'font-style:italic">&ldquo;{_esc(display_q)}&rdquo;</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

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
        state.reset_all_run_state()   # clears all stale state; components rendered
                                       # after this point on the same pass see clean state
        st.session_state["_trigger_run"] = True
        st.rerun()  # abort this pass immediately so PASS B renders with fully clean state


_KEY_RISK_DRIVERS_LABEL = (
    '<div style="font-size:0.72em;font-weight:700;color:#6B7280;'
    'text-transform:uppercase;letter-spacing:0.06em;'
    'margin:10px 0 6px 0">Key Risk Drivers</div>'
)


def render_final_answer(components: "AppComponents") -> None:
    """Risk headline card with colour-coded risk level and entity resolution tags.

    Card anatomy — identical in investigate mode and replay/trace mode
    ------------------------------------------------------------------
    1. Section title:    📊 Risk Assessment
    2. Assessment card:  headline · overall risk · recommendation · summary
    3. Key Risk Drivers: horizontal 4-column grid (UNKNOWN when data absent)
    4. Full Assessment:  expander with complete text
    5. Entities:         resolution pills (investigate mode only)
    """
    _section_header("📊 Risk Assessment")

    live_phase = state.get_live_phase()

    # Investigation is actively running — always show placeholder, regardless of any
    # stale result or replay data that might still be in session_state.
    if live_phase in ("planning", "resolving", "executing"):
        st.markdown(
            '<div style="background:#F9FAFB;border:1px solid #E5E7EB;'
            'border-left:4px solid #D1D5DB;border-radius:8px;'
            'padding:16px 20px;margin:4px 0 12px 0;'
            'color:#9CA3AF;font-size:0.87em">'
            '⏳ &nbsp;Assessment will appear when the investigation completes.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Replay mode ─────────────────────────────────────────────────────
    if state.get_replay_status() == "loaded" and live_phase == "idle":
        replay_data = state.get_replay_data() or {}
        summary  = replay_data.get("final_summary") or ""
        ended_at = replay_data.get("ended_at") or ""

        if not summary:
            st.markdown(
                '<div style="color:#9CA3AF;font-size:0.85em;padding:10px 0">'
                'No summary was recorded for this investigation.'
                '</div>',
                unsafe_allow_html=True,
            )
            return

        risk_level = _risk_from_summary(summary)
        if risk_level:
            tc, bg, border = _RISK_COLORS[risk_level]
            headline_text, headline_emoji = _RISK_HEADLINE.get(
                risk_level, ("Assessment Complete", "✅")
            )
        else:
            tc, bg, border = _RISK_COLORS["UNKNOWN"]
            headline_text, headline_emoji = "Past Investigation Summary", "📋"

        if ended_at:
            st.markdown(
                f'<div style="font-size:0.72em;color:#6B7280;margin-bottom:4px">'
                f'Completed: {_esc(_fmt_ts(ended_at))}</div>',
                unsafe_allow_html=True,
            )

        # 2. Assessment card
        _render_assessment_card(headline_text, headline_emoji, risk_level, summary, tc, bg, border)

        # 3. Key Risk Drivers — only when at least one dimension is known
        replay_dims = _extract_replay_risk_dimensions(replay_data)
        if any(v != "UNKNOWN" for v in replay_dims.values()):
            st.markdown(_KEY_RISK_DRIVERS_LABEL, unsafe_allow_html=True)
            _render_risk_drivers_grid(replay_dims)

        # 4. Full Assessment expander
        with st.expander("Full Assessment", expanded=False):
            st.markdown(
                f'<div style="font-size:0.87em;color:#1F2937;line-height:1.7">'
                f'{_esc(summary)}</div>',
                unsafe_allow_html=True,
            )

        return

    # ── Investigate mode ─────────────────────────────────────────────────
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
            risk_level = None
    else:
        headline_text, headline_emoji = "Investigation Failed", "🔴"
        tc, bg, border = "#B91C1C", "#FEF2F2", "#FECACA"
        risk_level = None

    # 2. Assessment card
    _render_assessment_card(headline_text, headline_emoji, risk_level, answer, tc, bg, border)

    # 3. Key Risk Drivers — only when at least one dimension is known
    summarize_findings = _get_summarize_findings(result)
    if summarize_findings:
        task_to_dim = [
            ("ownership_complexity_check", "ownership"),
            ("control_signal_check",       "control"),
            ("address_risk_check",         "address"),
            ("industry_context_check",     "industry"),
        ]
        live_dims = {
            dim: (summarize_findings.get(task) or {}).get("risk_level", "UNKNOWN")
            if isinstance(summarize_findings.get(task), dict) else "UNKNOWN"
            for task, dim in task_to_dim
        }
        if any(v != "UNKNOWN" for v in live_dims.values()):
            st.markdown(_KEY_RISK_DRIVERS_LABEL, unsafe_allow_html=True)
            _render_risk_drivers_grid(live_dims)

    # 4. Full Assessment expander
    with st.expander("Full Assessment", expanded=False):
        st.markdown(
            f'<div style="font-size:0.87em;color:#1F2937;line-height:1.7">'
            f'{_esc(answer)}</div>',
            unsafe_allow_html=True,
        )

    # 5. Errors (failure mode only)
    if not result.success and result.errors:
        for e in result.errors:
            st.error(e)

    # Warnings
    if result.warnings:
        with st.expander(f"⚠️ {len(result.warnings)} warning(s)", expanded=False):
            for w in result.warnings:
                st.warning(w)

    # 5. Resolved entity tags
    if result.resolved_entities:
        pills_html = ""
        for name, data in result.resolved_entities.items():
            if data is None:
                pills_html += _pill(f"❌ {name} — not found", "#FEF2F2", "#B91C1C", "#FECACA")
            else:
                canonical  = data.get("canonical_name", name)
                exact      = data.get("exact_match", True)
                company_no = data.get("company_number", "")
                qualifier  = "exact match" if exact else "closest match"
                display    = canonical
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
# Replay display helpers
# ---------------------------------------------------------------------------


def _fmt_ts(ts: str) -> str:
    """Format a UTC ISO timestamp as the server's local time.

    Output example: "23 Mar 2026, 9:27 PM"
    Uses the server's local timezone (standard for server-side Streamlit apps).
    """
    if not ts:
        return "—"
    try:
        dt_utc   = _datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone()          # convert to server local tz
        hour     = str(int(dt_local.strftime("%I")))  # strip leading zero
        minute   = dt_local.strftime("%M")
        ampm     = dt_local.strftime("%p")
        day      = str(int(dt_local.strftime("%d")))  # strip leading zero
        mon_year = dt_local.strftime("%b %Y")
        return f"{day} {mon_year}, {hour}:{minute} {ampm}"
    except Exception:
        return ts[:19]


def _risk_from_summary(summary: str) -> str | None:
    """Scan free-text summary for the highest risk level mentioned.

    Returns 'HIGH', 'MEDIUM', 'LOW', or None.
    """
    text = (summary or "").upper()
    for lvl in ("HIGH", "MEDIUM", "LOW"):
        if (
            f" {lvl} " in text
            or f" {lvl}." in text
            or f" {lvl}," in text
            or text.endswith(lvl)
            or text.startswith(lvl)
        ):
            return lvl
    return None


def _render_replay_plan(replay_data: dict) -> None:
    """Render plan metadata extracted from a replay trace.

    Parses the human-readable plan_created event to extract the investigation
    focus (reason) and strips all technical identifiers (mode=, step counts).
    """
    events     = replay_data.get("events") or []
    mode       = replay_data.get("mode", "")
    query      = replay_data.get("query", "—")
    started_at = replay_data.get("started_at") or ""

    # Extract the reason from the PLAN_CREATED event message.
    # Message format: "Plan: mode=investigate, 5 step(s), reason: <text>"
    plan_reason = ""
    for ev in events:
        if ev.get("event_type") == "plan_created":
            raw = ev.get("input_summary", "") or ""
            m = _re.search(r"reason:\s*(.+)$", raw, _re.IGNORECASE | _re.DOTALL)
            if m:
                plan_reason = m.group(1).strip()
            break

    mode_display = _MODE_DISPLAY.get(mode, mode.title() if mode else "—")
    short_query  = query[:38] + "…" if len(query) > 38 else query

    with st.container(border=True):
        col_type, col_entity = st.columns([1, 2])
        col_type.metric("Type", mode_display)
        col_entity.metric("Entity", short_query)

        if started_at:
            st.markdown(
                f'<div style="font-size:0.75em;color:#6B7280;margin:4px 0 8px 0">'
                f'Investigation run: {_esc(_fmt_ts(started_at))}</div>',
                unsafe_allow_html=True,
            )

        focus_text = plan_reason or _MODE_PLAN_FALLBACK.get(mode, "")
        if focus_text:
            st.markdown(
                f'<div style="font-size:0.66em;font-weight:700;color:#9CA3AF;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin:10px 0 4px 0">'
                f'Investigation focus</div>'
                f'<div style="font-size:0.84em;'
                f'border-left:3px solid #BFDBFE;padding:5px 0 5px 10px;'
                f'margin:0 0 8px 0;line-height:1.55;color:#1E3A8A">'
                f'{_esc(focus_text)}</div>',
                unsafe_allow_html=True,
            )


def _render_replay_event_timeline(events: list) -> None:
    """Render a list of trace events as a compact audit timeline.

    Each event row has a browser tooltip (title attribute) describing
    what the event type means in business terms.
    """
    if not events:
        st.caption("No activity was recorded for this investigation.")
        return

    # Group steps with subtle visual separators between analysis steps
    _prev_etype = ""
    for ev in events:
        etype       = ev.get("event_type", "")

        # Subtle separator before each new analysis step
        if etype == "step_started" and _prev_etype not in ("", "plan_created"):
            st.markdown(
                '<div style="height:1px;background:#E5E7EB;margin:8px 0 6px 0"></div>',
                unsafe_allow_html=True,
            )
        _prev_etype = etype

        agent_name  = ev.get("agent_name", "")
        tool_name   = ev.get("tool_name", "")
        in_summary  = _clean_event_text(ev.get("input_summary",  "") or "")
        out_summary = _clean_event_text(ev.get("output_summary", "") or "")
        ev_num      = ev.get("event_number", "")

        icon    = _EVENT_TYPE_ICONS.get(etype, "·")
        # Use context-aware label for tool_returned/tool_called events
        if etype == "tool_returned" and tool_name:
            label = _TOOL_RETURNED_LABELS.get(tool_name, "Data retrieved")
        elif etype == "tool_called" and tool_name:
            label = _TASK_LABELS.get(tool_name, tool_name.replace("_", " ").title())
        else:
            label = _EVENT_TYPE_LABELS.get(etype, etype.replace("_", " ").title())
        tooltip = _EVENT_TYPE_TOOLTIPS.get(etype, "")

        if etype == "step_failed":
            accent = "#DC2626"
        elif etype in ("step_completed", "investigation_complete"):
            accent = "#16A34A"
        elif etype == "tool_returned":
            accent = "#16A34A"
        elif etype in ("tool_called", "agent_reasoning"):
            accent = "#6B7280"
        else:
            accent = "#3B82F6"

        agent_chip = ""
        if agent_name:
            agent_label = _AGENT_LABELS.get(agent_name, agent_name)
            agent_chip = (
                f'<span style="font-size:0.72em;background:#F3F4F6;color:#374151;'
                f'border-radius:8px;padding:1px 8px;white-space:nowrap;margin-left:6px">'
                f'{_esc(_AGENT_ICONS.get(agent_name, "·"))} {_esc(agent_label)}</span>'
            )
        tool_chip = ""
        if tool_name:
            # Show business-friendly tool label where available
            tool_display = _TASK_LABELS.get(tool_name, tool_name.replace("_", " ").title())
            tool_chip = (
                f'<span style="font-size:0.72em;background:#EFF6FF;color:#1D4ED8;'
                f'border:1px solid #BFDBFE;border-radius:8px;padding:1px 8px;'
                f'white-space:nowrap;margin-left:6px">{_esc(tool_display)}</span>'
            )

        # Suppress overly technical output text for tool_returned events;
        # the label "Data retrieved" already conveys the outcome.
        show_out = etype not in ("tool_returned", "tool_called")
        out_text = (out_summary[:80] + "…") if len(out_summary) > 80 else out_summary

        # Only show input summary for meaningful event types
        show_in = etype not in ("tool_called", "tool_returned")
        summary_text = (in_summary[:120] + "…") if len(in_summary) > 120 else in_summary

        out_html = (
            f'<div style="font-size:0.78em;color:#16A34A;margin-top:2px;'
            f'font-style:italic">{_esc(out_text)}</div>'
            if (out_text and show_out) else ""
        )
        summary_html = (
            f'<div style="font-size:0.80em;color:#6B7280;margin-top:3px;'
            f'line-height:1.45">{_esc(summary_text)}</div>'
            if (summary_text and show_in) else ""
        )

        title_attr = f' title="{_esc(tooltip)}"' if tooltip else ""

        st.markdown(
            f'<div{title_attr} style="border-left:3px solid {accent};'
            f'padding:6px 0 6px 12px;margin:4px 0;background:#FAFAFA;'
            f'border-radius:0 6px 6px 0;cursor:default">'
            f'  <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
            f'    <span style="font-size:0.68em;color:#9CA3AF;font-weight:700;'
            f'      background:#F3F4F6;border-radius:3px;padding:1px 5px">#{ev_num}</span>'
            f'    <span style="font-size:0.76em;font-weight:600;color:#374151">'
            f'      {icon} {_esc(label)}</span>'
            f'    {agent_chip}{tool_chip}'
            f'  </div>'
            f'  {summary_html}{out_html}'
            f'</div>',
            unsafe_allow_html=True,
        )


def _extract_replay_risk_dimensions(replay_data: dict) -> dict[str, str]:
    """Extract per-dimension risk levels from replay event output summaries.

    Scans ``tool_returned`` events for the four risk-task tool names and
    parses the highest risk word found in the output_summary text.

    Returns a dict with keys ``ownership``, ``control``, ``address``,
    ``industry`` — each value is ``'HIGH'``, ``'MEDIUM'``, ``'LOW'``, or
    ``'UNKNOWN'``.
    """
    _DIM_TASKS: dict[str, str] = {
        "ownership_complexity_check": "ownership",
        "control_signal_check":       "control",
        "address_risk_check":         "address",
        "industry_context_check":     "industry",
    }
    dims = {v: "UNKNOWN" for v in _DIM_TASKS.values()}

    for ev in (replay_data.get("events") or []):
        if ev.get("event_type") != "tool_returned":
            continue
        tool_name = ev.get("tool_name", "")
        if tool_name not in _DIM_TASKS:
            continue
        dim = _DIM_TASKS[tool_name]
        if dims[dim] != "UNKNOWN":
            continue  # already resolved from an earlier event
        out = (ev.get("output_summary") or "").upper()
        for lvl in ("HIGH", "MEDIUM", "LOW"):
            if (
                f" {lvl} " in out
                or f" {lvl}." in out
                or f" {lvl}," in out
                or out.endswith(lvl)
                or out.startswith(lvl)
                or f":{lvl}" in out
                or f": {lvl}" in out
            ):
                dims[dim] = lvl
                break

    return dims


def _render_replay_trace_metadata(replay_data: dict) -> None:
    """Render trace metadata for a replayed investigation."""
    trace_id   = replay_data.get("trace_id", "")
    mode       = replay_data.get("mode", "")
    query      = replay_data.get("query", "")
    events     = replay_data.get("events") or []
    started_at = replay_data.get("started_at") or ""
    ended_at   = replay_data.get("ended_at") or ""

    # Trace ID block
    st.markdown(
        '<div style="background:#F3F4F6;border-radius:6px;'
        'padding:10px 12px;margin:6px 0 12px 0">'
        '<div style="font-size:0.66em;color:#6B7280;text-transform:uppercase;'
        'letter-spacing:0.06em;font-weight:700;margin-bottom:4px">Trace ID</div>'
        f'<code style="font-size:0.76em;color:#374151;word-break:break-all">'
        f'{_esc(trace_id)}</code></div>',
        unsafe_allow_html=True,
    )

    mode_display = _MODE_DISPLAY.get(mode, mode.title() if mode else "—")
    c1, c2 = st.columns(2)
    c1.metric("Investigation Type", mode_display)
    c2.metric("Activity Events", len(events))

    st.markdown(
        f'<div style="font-size:0.80em;color:#374151;margin:8px 0 4px 0">'
        f'<span style="color:#6B7280">Entity:</span> {_esc(query)}</div>'
        f'<div style="font-size:0.78em;color:#6B7280">'
        f'Started: {_esc(_fmt_ts(started_at))}<br>'
        f'Completed: {_esc(_fmt_ts(ended_at))}</div>',
        unsafe_allow_html=True,
    )



# ---------------------------------------------------------------------------
# Center column
# ---------------------------------------------------------------------------


def render_planner_output(components: "AppComponents") -> None:
    """Investigation plan: mode, entity, reason, and a clean step list."""
    _section_header("📋 Investigation Plan")

    # ── Replay mode ─────────────────────────────────────────────────────
    if state.get_replay_status() == "loaded" and state.get_live_phase() == "idle":
        _render_replay_plan(state.get_replay_data() or {})
        return

    result     = state.get_result()
    live_plan  = state.get_live_plan()
    live_phase = state.get_live_phase()

    plan: dict[str, Any] | None = None
    if result is not None and result.planner_output:
        plan = result.planner_output
    elif live_plan is not None:
        plan = live_plan

    if plan is None:
        if live_phase == "planning":
            st.markdown(
                '<div style="color:#9CA3AF;font-size:0.85em;padding:8px 0">'
                '⏳ &nbsp;Generating investigation plan…</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("The investigation plan will appear here after a run.")
        return

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
    """Ordered step cards — live during execution, full view after completion.

    During a run: shows completed steps as they finish, with a "Running"
    card for the currently active step, and a progress bar.

    After completion: shows all steps from the authoritative OrchestratorResult.
    """
    # ── Replay mode ─────────────────────────────────────────────────────
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()
    if replay_status == "loaded" and replay_data and state.get_live_phase() == "idle":
        _section_header(
            "🗂️ Investigation Activity",
            "Step-by-step record of what was done during this investigation",
        )
        _render_replay_event_timeline(replay_data.get("events") or [])
        return

    _section_header("🔍 Investigation Steps", "How the analysis was performed")

    result     = state.get_result()
    live_phase = state.get_live_phase()
    live_steps = state.get_live_steps()      # list[dict] — completed so far
    live_cur   = state.get_live_current_step()

    # ── Completed run ──────────────────────────────────────────────────
    if result is not None:
        if not result.step_results:
            st.caption("No steps were executed.")
            return
        for i, step in enumerate(result.step_results, start=1):
            _render_step_card(i, step)
        return

    # ── No run yet ─────────────────────────────────────────────────────
    if live_phase in ("idle", None):
        st.caption("Step results will appear here after a run.")
        return

    # ── Run in progress ────────────────────────────────────────────────
    n_done  = len(live_steps)
    n_total = len((state.get_live_plan() or {}).get("plan") or [])

    # Progress indicator
    if n_total:
        progress_val  = n_done / n_total
        progress_text = f"Step {n_done} of {n_total}"
        st.progress(progress_val, text=progress_text)
    elif live_phase in ("planning", "resolving"):
        st.progress(0.0, text="Preparing…")

    # Completed steps
    for i, step_dict in enumerate(live_steps, start=1):
        _render_step_card(i, _NS(**step_dict))

    # Currently running step
    if live_cur:
        running = _NS(
            step_id       = live_cur.get("step_id", ""),
            agent         = live_cur.get("agent", ""),
            task          = live_cur.get("task", ""),
            status        = "running",
            success       = False,
            summary       = "",
            findings      = {},
            tools_executed= [],
            error         = None,
            skipped       = False,
            skip_reason   = None,
        )
        _render_step_card(n_done + 1, running)
    elif live_phase == "planning":
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:12px 0">'
            '⏳ &nbsp;Generating investigation plan…</div>',
            unsafe_allow_html=True,
        )
    elif live_phase == "resolving":
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:12px 0">'
            '⏳ &nbsp;Resolving company entities…</div>',
            unsafe_allow_html=True,
        )


def _render_step_card(index: int, step: Any) -> None:
    """Render a single execution step as a compact colour-accented bordered card.

    Main view (always visible)
    --------------------------
    [3 px status-colour accent bar]
    ┌─ bordered container ─────────────────────────────────┐
    │  #N  Business task name  [icon Agent]  🟢 Complete   │
    │  One-sentence summary                                 │
    │  Tools  [tool_a] [tool_b]    Risk  🔴 HIGH           │
    └───────────────────────────────────────────────────────┘

    Expander (Details)
    ------------------
    Why this step matters (reasoning)
    Error block (if failed)
    Risk breakdown grid (summarize step only)
    Full summary (if truncated above)
    Findings JSON + Raw step JSON
    """
    status        = step.status
    task_key      = step.task  or ""
    agent_key     = step.agent or ""
    task_display  = _task_label(task_key)
    agent_display = _agent_display(agent_key)
    reasoning     = _TASK_REASONING.get(task_key, "")
    findings: dict = step.findings or {}
    summary: str   = step.summary or ""

    _accent_bar(status)

    with st.container(border=True):
        # ── Header row ─────────────────────────────────────────────────
        st.markdown(
            _step_header_html(index, task_display, agent_display, status),
            unsafe_allow_html=True,
        )

        # ── Main body — compact ────────────────────────────────────────
        if status == "running":
            st.markdown(
                '<div style="color:#D97706;font-size:0.82em;padding:4px 0">'
                '⏳ &nbsp;Running…</div>',
                unsafe_allow_html=True,
            )
        elif status == "skipped":
            st.markdown(
                f'<div style="color:#9CA3AF;font-size:0.80em;font-style:italic;'
                f'padding:2px 0 4px 0">'
                f'{_esc(step.skip_reason or "Step was not executed.")}</div>',
                unsafe_allow_html=True,
            )
        else:
            # One-sentence summary visible in main view
            short = _first_sentences(summary, 1)
            if short:
                st.markdown(
                    f'<div style="color:#374151;font-size:0.87em;line-height:1.55;'
                    f'padding:4px 0 4px 0">{_esc(short)}</div>',
                    unsafe_allow_html=True,
                )

            # Tools + inline risk badge on the same row
            tools: list[str] = step.tools_executed or []
            risk_inline_html = ""
            if task_key in _RISK_TASKS and findings:
                data = findings.get(task_key)
                risk = data.get("risk_level") if isinstance(data, dict) else None
                if risk:
                    risk_inline_html = (
                        f'<span style="margin-left:10px;font-size:0.68em;'
                        f'color:#6B7280;font-weight:700;text-transform:uppercase;'
                        f'letter-spacing:0.05em">Risk&nbsp;&nbsp;</span>'
                        f'{_risk_badge(risk)}'
                    )

            if tools or risk_inline_html:
                st.markdown(
                    f'<div style="display:flex;align-items:center;flex-wrap:wrap;'
                    f'gap:4px;margin:4px 0 2px 0">'
                    f'{_tool_pills(tools) if tools else ""}'
                    f'{risk_inline_html}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ── Details expander ───────────────────────────────────────────
        with st.expander("Details", expanded=False):
            # Why this step matters
            if reasoning:
                st.markdown(
                    f'<div style="border-left:3px solid #E5E7EB;padding:3px 0 3px 10px;'
                    f'color:#6B7280;font-size:0.80em;font-style:italic;'
                    f'margin:4px 0 8px 0;line-height:1.55">'
                    f'{_esc(reasoning)}</div>',
                    unsafe_allow_html=True,
                )

            if status == "failed" and step.error:
                st.error(f"Error: {step.error}")

            # Risk breakdown grid (summarize step)
            if task_key == "summarize_risk_for_company" and findings:
                _label_row("Risk Breakdown")
                _render_risk_breakdown(findings)

            # Full summary if it was truncated
            short = _first_sentences(summary, 1)
            if summary and summary.strip() != short.strip():
                _label_row("Full Summary")
                st.markdown(
                    f'<div style="font-size:0.85em;color:#374151;line-height:1.65">'
                    f'{_esc(summary)}</div>',
                    unsafe_allow_html=True,
                )

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
    # ── Replay mode ─────────────────────────────────────────────────────
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()
    if replay_status == "loaded" and replay_data and state.get_live_phase() == "idle":
        _section_header("🗂️ Replayed Trace", "Original investigation audit record")
        _render_replay_trace_metadata(replay_data)
        return

    _section_header("🗂️ Decision Trace", "Audit log for this investigation")

    trace_id      = state.get_trace_id()
    live_trace_id = state.get_live_trace_id()
    live_phase    = state.get_live_phase()
    result        = state.get_result()

    display_trace_id = trace_id or live_trace_id

    if display_trace_id is None:
        if live_phase == "planning":
            st.markdown(
                '<div style="color:#9CA3AF;font-size:0.82em;padding:8px 0">'
                '⏳ &nbsp;Initialising trace…</div>',
                unsafe_allow_html=True,
            )
        else:
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
        f'{_esc(display_trace_id)}</code></div>',
        unsafe_allow_html=True,
    )

    # During execution: show recording status and exit
    if live_phase in ("planning", "resolving", "executing") and result is None:
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.80em;font-style:italic;'
            'padding:2px 0 8px 0">Recording investigation trace…</div>',
            unsafe_allow_html=True,
        )
        return

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
    _section_header("🔄 Replay / Audit", "Replay a previous investigation using its trace ID")

    replay_status = state.get_replay_status()
    replay_error  = state.get_replay_error()
    replay_data   = state.get_replay_data()

    with st.container(border=True):
        replay_id = st.text_input(
            label="Trace ID",
            label_visibility="collapsed",
            value=state.get_replay_trace_id() or "",
            placeholder="Enter a trace ID to replay…",
            key="_input_replay_trace_id",
        )
        load = st.button(
            "Load Trace",
            use_container_width=True,
            disabled=(replay_status == "loading"),
        )
        if load and replay_id.strip():
            state.set_replay_trace_id(replay_id.strip())
            st.session_state["_trigger_replay"] = True

        # ── Status states ───────────────────────────────────────────────
        if replay_status == "loading":
            st.markdown(
                '<div style="color:#D97706;font-size:0.82em;padding:6px 0">'
                '⏳ &nbsp;Loading trace…</div>',
                unsafe_allow_html=True,
            )

        elif replay_status == "error" and replay_error:
            st.markdown(
                f'<div style="background:#FEF2F2;border:1px solid #FECACA;'
                f'border-left:3px solid #DC2626;border-radius:6px;'
                f'padding:10px 14px;margin-top:10px">'
                f'<div style="font-size:0.72em;font-weight:700;color:#DC2626;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">'
                f'Failed to load</div>'
                f'<div style="font-size:0.82em;color:#7F1D1D">{_esc(replay_error)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        elif replay_status == "loaded" and replay_data:
            trace_id     = replay_data.get("trace_id", "")
            mode         = replay_data.get("mode", "")
            n_events     = len(replay_data.get("events") or [])
            short_id     = (trace_id[:16] + "…") if len(trace_id) > 16 else trace_id
            mode_display = _MODE_DISPLAY.get(mode, mode.title() if mode else "—")
            st.markdown(
                f'<div style="background:#F0FDF4;border:1px solid #BBF7D0;'
                f'border-left:3px solid #16A34A;border-radius:6px;'
                f'padding:10px 14px;margin-top:10px">'
                f'<div style="font-size:0.82em;font-weight:700;color:#15803D;'
                f'margin-bottom:5px">✓ Investigation loaded successfully</div>'
                f'<code style="font-size:0.76em;color:#166534;word-break:break-all">'
                f'{_esc(short_id)}</code>'
                f'<div style="font-size:0.78em;color:#6B7280;margin-top:6px">'
                f'{_esc(mode_display)} &nbsp;·&nbsp; {n_events} activity event(s)</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("Clear Replay", use_container_width=True, type="secondary"):
                st.session_state["_clear_replay"] = True


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
