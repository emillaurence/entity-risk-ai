"""
src.app.components — Individual UI component renderers.

Design philosophy
-----------------
All user-facing text uses business-friendly language drawn from the
``_TASK_LABELS`` and ``_TASK_REASONING`` mapping dictionaries.  Technical
strings (task keys, agent keys, tool names) are shown only inside
"View Technical Details" / "Details" expanders so analysts never see raw
identifiers.

Risk signals (HIGH / MEDIUM / LOW) are colour-coded from the live
``findings`` data — nothing is invented or assumed.

Public API
----------
Shared
    render_app_header        Full-width title / subtitle.
    render_status_banner     Live execution banner.

Tab entry points (called from layout.py)
    render_investigate_tab   Investigate tab: 3-column layout + analysis expander.
    render_replay_tab        Replay / Audit tab: 3-column layout.

Tab structure
-------------
Investigate tab
    Col 1 — AI Assistant   : question input, risk assessment card, entity chips.
    Col 2 — Context Graph  : ownership graph legend + placeholder / entity panels.
    Col 3 — Decision Insights : reasoning, confidence indicators, risk driver grid.
    Expander — "How this was analysed": plan, step cards, trace ID.

Replay / Audit tab
    Col 1 — Risk Assessment : original question, assessment card, risk drivers, entities.
    Col 2 — Investigation Activity : plan snapshot, event timeline.
    Col 3 — Replayed Trace  : trace metadata, load / clear controls.
"""

from __future__ import annotations

import html as _html
import re as _re
from datetime import datetime as _datetime
from types import SimpleNamespace as _NS
from typing import TYPE_CHECKING, Any

import streamlit as st
import streamlit.components.v1 as _st_components

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

# Headline copy shown in the risk assessment card
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

# Key Risk Drivers label HTML — shared by investigate and replay risk assessments
_KEY_RISK_DRIVERS_LABEL = (
    '<div style="font-size:0.72em;font-weight:700;color:#6B7280;'
    'text-transform:uppercase;letter-spacing:0.06em;'
    'margin:10px 0 6px 0">Key Risk Drivers</div>'
)


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
    """Return the first n sentences from text."""
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
    """Return a display-friendly question string."""
    if not query:
        return ""
    q = query.strip()
    markers = ("?", "who ", "what ", " is ", " are ", " does ",
               "investigate", "find", "check", "assess", "review")
    if any(m in q.lower() for m in markers):
        return q
    return f"Investigate {q}"


def _clean_event_text(text: str) -> str:
    """Strip technical/debug fragments from event summaries."""
    if not text:
        return text
    cleaned = _re.sub(r"\|\s*tokens\s+in=\d+\s+out=\d+", "", text, flags=_re.IGNORECASE)
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
    """Scan step findings for the highest risk level present."""
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

    if not best:
        answer = (result.final_answer or "").strip().upper()
        for lvl in ("HIGH", "MEDIUM", "LOW"):
            if answer.endswith(lvl) or f" {lvl}." in answer or f" {lvl}," in answer:
                best = lvl
                break

    return best


def _risk_from_summary(summary: str) -> str | None:
    """Scan free-text summary for the highest risk level mentioned."""
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


def _extract_replay_risk_dimensions(replay_data: dict) -> dict[str, str]:
    """Extract per-dimension risk levels from replay event output summaries."""
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
            continue
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


# ---------------------------------------------------------------------------
# Shared card renderers — identical HTML in both investigate and replay modes
# ---------------------------------------------------------------------------

def _render_assessment_card(
    headline_text: str,
    headline_emoji: str,
    risk_level: "str | None",
    summary: str,
    tc: str,
    bg: str,
    border: str,
) -> None:
    """Render the main risk assessment card."""
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
    """Render the 4-signal horizontal risk grid.

    ``dims`` must have keys ``ownership``, ``control``, ``address``,
    ``industry`` mapping to ``'HIGH'``, ``'MEDIUM'``, ``'LOW'``, or
    ``'UNKNOWN'``.  Missing keys fall back to ``'UNKNOWN'``.

    This is the single canonical renderer for risk-driver display.
    Both investigate and replay modes call this function so layout,
    spacing, colours, and border radius are always identical.
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
    """Render the 4-signal risk grid for a summarize_risk_for_company step."""
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


# ---------------------------------------------------------------------------
# Step card helpers
# ---------------------------------------------------------------------------

def _accent_bar(status: str) -> None:
    """Thin 3 px coloured stripe above each step card."""
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
        st.markdown(
            _step_header_html(index, task_display, agent_display, status),
            unsafe_allow_html=True,
        )

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
            short = _first_sentences(summary, 1)
            if short:
                st.markdown(
                    f'<div style="color:#374151;font-size:0.87em;line-height:1.55;'
                    f'padding:4px 0 4px 0">{_esc(short)}</div>',
                    unsafe_allow_html=True,
                )

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

        with st.expander("Details", expanded=False):
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

            if task_key == "summarize_risk_for_company" and findings:
                _label_row("Risk Breakdown")
                _render_risk_breakdown(findings)

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
# Replay helpers (used by Replay / Audit tab)
# ---------------------------------------------------------------------------

def _fmt_ts(ts: str) -> str:
    """Format a UTC ISO timestamp as the server's local time.

    Output example: "23 Mar 2026, 9:27 PM"
    """
    if not ts:
        return "—"
    try:
        dt_utc   = _datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone()
        hour     = str(int(dt_local.strftime("%I")))
        minute   = dt_local.strftime("%M")
        ampm     = dt_local.strftime("%p")
        day      = str(int(dt_local.strftime("%d")))
        mon_year = dt_local.strftime("%b %Y")
        return f"{day} {mon_year}, {hour}:{minute} {ampm}"
    except Exception:
        return ts[:19]


def _render_replay_plan(replay_data: dict) -> None:
    """Render plan metadata extracted from a replay trace."""
    events     = replay_data.get("events") or []
    mode       = replay_data.get("mode", "")
    query      = replay_data.get("query", "—")
    started_at = replay_data.get("started_at") or ""

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
    """Render a list of trace events as a compact audit timeline."""
    if not events:
        st.caption("No activity was recorded for this investigation.")
        return

    _prev_etype = ""
    for ev in events:
        etype       = ev.get("event_type", "")

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
            tool_display = _TASK_LABELS.get(tool_name, tool_name.replace("_", " ").title())
            tool_chip = (
                f'<span style="font-size:0.72em;background:#EFF6FF;color:#1D4ED8;'
                f'border:1px solid #BFDBFE;border-radius:8px;padding:1px 8px;'
                f'white-space:nowrap;margin-left:6px">{_esc(tool_display)}</span>'
            )

        show_out = etype not in ("tool_returned", "tool_called")
        out_text = (out_summary[:80] + "…") if len(out_summary) > 80 else out_summary

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


def _render_replay_trace_metadata(replay_data: dict) -> None:
    """Render trace metadata for a replayed investigation."""
    trace_id   = replay_data.get("trace_id", "")
    mode       = replay_data.get("mode", "")
    query      = replay_data.get("query", "")
    events     = replay_data.get("events") or []
    started_at = replay_data.get("started_at") or ""
    ended_at   = replay_data.get("ended_at") or ""

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
# Shared public components
# ---------------------------------------------------------------------------


def render_app_header() -> None:
    """Full-width app title and subtitle rendered above the tab layout."""
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


def render_status_banner() -> None:
    """Full-width error banner rendered above the tabs.

    Hidden when idle or running.  Only surfaces persistent failure messages
    (e.g. investigation thread crash).  Progress during a run is shown by
    ``_render_progress_section`` inside the Investigate tab instead.
    """
    status = state.get_status()
    msg = status.get("message", "")
    if not msg or status.get("running"):
        return
    st.error(msg)


# ===========================================================================
# INVESTIGATE TAB — progressive rendering helpers
# ===========================================================================

# Ordered list of risk-dimension tasks used across progressive rendering helpers
_RISK_DIM_TASKS: list[tuple[str, str, str]] = [
    ("ownership_complexity_check", "ownership", "Ownership"),
    ("control_signal_check",       "control",   "Control"),
    ("address_risk_check",         "address",   "Address"),
    ("industry_context_check",     "industry",  "Industry"),
]


def _extract_live_risk_dims() -> dict[str, str]:
    """Extract per-dimension risk levels from live completed steps.

    Returns dims dict suitable for ``_render_risk_drivers_grid``.
    Only reflects steps that have already completed during this run.
    """
    dims = {dim: "UNKNOWN" for _, dim, _ in _RISK_DIM_TASKS}
    for step_dict in state.get_live_steps():
        task = step_dict.get("task", "")
        for task_key, dim, _ in _RISK_DIM_TASKS:
            if task == task_key:
                findings = step_dict.get("findings") or {}
                data = findings.get(task)
                if isinstance(data, dict):
                    lvl = data.get("risk_level", "UNKNOWN")
                    if lvl != "UNKNOWN":
                        dims[dim] = lvl
    return dims


def _render_resolved_entity_banner(entities: dict) -> None:
    """Render a prominent 'Identified Entity' banner for each resolved entity.

    Called as soon as ``live_entities`` is populated so the user knows
    which company is being investigated before results arrive.
    """
    for name, data in entities.items():
        if data is None:
            st.markdown(
                f'<div style="background:#FEF2F2;border:1px solid #FECACA;'
                f'border-left:4px solid #DC2626;border-radius:6px;'
                f'padding:10px 14px;margin:8px 0">'
                f'<div style="font-size:0.66em;font-weight:700;color:#DC2626;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:3px">'
                f'Entity not found</div>'
                f'<div style="font-size:0.87em;color:#7F1D1D;font-weight:500">'
                f'❌ {_esc(name)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            canonical  = data.get("canonical_name", name)
            company_no = data.get("company_number", "")
            no_str     = f" (No. {company_no})" if company_no else ""
            st.markdown(
                f'<div style="background:#F0FDF4;border:1px solid #BBF7D0;'
                f'border-left:4px solid #16A34A;border-radius:6px;'
                f'padding:10px 14px;margin:8px 0">'
                f'<div style="font-size:0.66em;font-weight:700;color:#16A34A;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:3px">'
                f'Identified Entity</div>'
                f'<div style="font-size:0.92em;color:#14532D;font-weight:700">'
                f'✔ {_esc(canonical)}{_esc(no_str)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_live_step_checklist() -> None:
    """Render a live step-by-step checklist for the Context Graph panel.

    Shows ✔ (done) / 🔄 (running) / ⏳ (pending) for each planned step.
    Updates on every rerun as live_steps and live_current_step change.
    """
    live_plan  = state.get_live_plan()
    live_steps = state.get_live_steps()
    live_cur   = state.get_live_current_step()

    plan_steps    = (live_plan or {}).get("plan") or []
    completed_set = {s.get("task") for s in live_steps}
    current_task  = (live_cur or {}).get("task") if live_cur else None

    rows_html = ""
    for s in plan_steps:
        task  = s.get("task", "")
        label = _TASK_LABELS.get(task, task.replace("_", " ").title())
        if task in completed_set:
            icon  = "✔"
            color = "#16A34A"
            weight = "500"
        elif task == current_task:
            icon  = "🔄"
            color = "#D97706"
            weight = "600"
        else:
            icon  = "⏳"
            color = "#9CA3AF"
            weight = "400"
        rows_html += (
            f'<div style="display:flex;align-items:center;gap:8px;'
            f'padding:5px 0;border-bottom:1px solid #F3F4F6">'
            f'<span style="font-size:0.85em;width:18px;text-align:center">{icon}</span>'
            f'<span style="font-size:0.83em;color:{color};font-weight:{weight}">'
            f'{_esc(label)}</span>'
            f'</div>'
        )

    if rows_html:
        st.markdown(
            f'<div style="background:#FAFAFA;border:1px solid #E5E7EB;'
            f'border-radius:8px;padding:10px 14px;margin:4px 0">'
            f'{rows_html}'
            f'</div>',
            unsafe_allow_html=True,
        )


# ===========================================================================
# INVESTIGATE TAB
# ===========================================================================


def _render_progress_section() -> None:
    """Compact progress bar shown at the top of the Investigate tab during a run.

    Hidden when idle or done.  Reads live_phase and step counters directly
    so it reflects the latest state on each full-page rerun.
    """
    phase = state.get_live_phase()
    if phase not in ("planning", "resolving", "executing"):
        return

    num   = state.get_live_step_num()
    total = state.get_live_step_total()
    label = state.get_live_step_label()

    if phase == "planning":
        pct  = 0.03
        text = "Planning investigation…"
    elif phase == "resolving":
        pct  = 0.06
        text = "Identifying company…"
    else:  # executing
        if num and total:
            pct  = num / total
            text = f"Step {num} of {total} — {label}"
        elif label:
            pct  = 0.10
            text = label
        else:
            pct  = 0.10
            text = "Running investigation…"

    st.progress(pct, text=text)
    st.markdown(
        '<div style="margin-bottom:6px"></div>',
        unsafe_allow_html=True,
    )


def render_investigate_tab(components: "AppComponents") -> None:
    """Render the Investigate tab.

    Layout
    ------
    [Progress bar]  (only during active investigation)
    [Col 1 — AI Assistant]  [Col 2 — Context Graph]  [Col 3 — Decision Insights]
                                                       └─ "How this decision was made"
                                                          (collapsed expander at bottom)
    """
    _render_progress_section()

    # Compute once per render pass; passed into the two columns that need it
    # so _extract_live_risk_dims() is not called twice on the same rerun.
    live_dims = _extract_live_risk_dims()

    col1, col2, col3 = st.columns([2, 2, 2])

    with col1:
        _render_input_column(components, live_dims)

    with col2:
        _render_graph_column()

    with col3:
        _render_insights_column(live_dims)


def _render_input_column(components: "AppComponents", live_dims: dict) -> None:
    """Col 1 of the Investigate tab: question input + resolved entity + risk assessment."""
    _section_header("🔍 AI Assistant", "Ask a question about any UK company")

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
    submitted = st.button("Run Investigation", type="primary", use_container_width=True)
    if submitted and question.strip():
        state.set_question(question.strip())
        state.reset_all_run_state()
        st.session_state["_trigger_run"] = True
        st.rerun()

    # Show resolved entity banner as soon as it is available (before result)
    live_entities = state.get_live_entities()
    if live_entities:
        _render_resolved_entity_banner(live_entities)

    st.divider()
    _render_live_risk_assessment(live_dims)


def _render_live_risk_assessment(live_dims: dict) -> None:
    """Risk Assessment for the Investigate tab — staged progressive rendering.

    Stages
    ------
    1. planning / resolving  → spinner placeholder
    2. executing, no signals → "Calculating risk profile…" + partial grid if any dims known
    3. executing, dims known → partial risk driver grid with live values
    4. done / result ready   → full assessment card + full grid + entity chips
    """
    _section_header("📊 Risk Assessment")

    live_phase = state.get_live_phase()
    result     = state.get_result()

    # ── Stage 1: planning or resolving ──────────────────────────────────
    if live_phase in ("planning", "resolving"):
        st.markdown(
            '<div style="background:#F9FAFB;border:1px solid #E5E7EB;'
            'border-left:4px solid #D1D5DB;border-radius:8px;'
            'padding:16px 20px;margin:4px 0 12px 0;'
            'color:#9CA3AF;font-size:0.87em">'
            '⏳ &nbsp;Starting analysis…'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Stage 2 / 3: executing — show partial risk grid progressively ────
    if live_phase == "executing" and result is None:
        has_signals = any(v != "UNKNOWN" for v in live_dims.values())

        st.markdown(
            '<div style="background:#FFFBEB;border:1px solid #FDE68A;'
            'border-left:4px solid #D97706;border-radius:8px;'
            'padding:14px 20px;margin:4px 0 12px 0;'
            'color:#92400E;font-size:0.87em">'
            '⏳ &nbsp;Calculating risk profile…'
            '</div>',
            unsafe_allow_html=True,
        )
        if has_signals:
            _label_row("Risk Signals (in progress)")
            _render_risk_drivers_grid(live_dims)
        return

    # ── Stage 4: idle with no result (initial state) ─────────────────────
    if result is None:
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:10px 0">'
            'The risk assessment will appear here after a run.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Stage 4: full result ready ────────────────────────────────────────
    answer = result.final_answer or "Investigation complete — no summary generated."

    if result.success:
        risk_level = _overall_risk_from_result(result)
        if risk_level:
            headline_text, headline_emoji = _RISK_HEADLINE.get(
                risk_level, ("Assessment Complete", "✅")
            )
            tc, bg, border = _RISK_COLORS.get(risk_level, _RISK_COLORS["UNKNOWN"])
        else:
            headline_text, headline_emoji = "Investigation Complete", "✅"
            tc, bg, border = "#14532D", "#F0FDF4", "#BBF7D0"
            risk_level = None
    else:
        headline_text, headline_emoji = "Investigation Failed", "🔴"
        tc, bg, border = "#B91C1C", "#FEF2F2", "#FECACA"
        risk_level = None

    _render_assessment_card(headline_text, headline_emoji, risk_level, answer, tc, bg, border)

    # Trace ID — muted inline row with working copy button (execCommand works in sandboxed iframe)
    trace_id = result.trace_id
    if trace_id:
        _st_components.html(
            f"""
            <div style="display:flex;align-items:center;gap:6px;padding:4px 0 8px 2px;
                        font-size:11.5px;color:#9CA3AF;font-family:monospace">
              <span style="font-family:sans-serif;font-weight:600;letter-spacing:.04em;font-size:10px">TRACE ID</span>
              <span id="tid" style="user-select:all;word-break:break-all">{_esc(trace_id)}</span>
              <button id="cpybtn"
                style="background:none;border:1px solid #D1D5DB;border-radius:4px;
                       cursor:pointer;padding:1px 7px;font-size:12px;color:#6B7280;
                       line-height:1.5;flex-shrink:0"
                title="Copy trace ID">⎘</button>
            </div>
            <script>
              document.getElementById('cpybtn').addEventListener('click', function() {{
                var el = document.getElementById('tid');
                var range = document.createRange();
                range.selectNode(el);
                window.getSelection().removeAllRanges();
                window.getSelection().addRange(range);
                document.execCommand('copy');
                window.getSelection().removeAllRanges();
                this.textContent = '✓';
                setTimeout(function(btn){{ btn.textContent = '⎘'; }}, 1500, this);
              }});
            </script>
            """,
            height=36,
        )

    with st.expander("Full Assessment", expanded=False):
        st.markdown(
            f'<div style="font-size:0.87em;color:#1F2937;line-height:1.7">'
            f'{_esc(answer)}</div>',
            unsafe_allow_html=True,
        )

    if not result.success and result.errors:
        for e in result.errors:
            st.error(e)

    if result.warnings:
        with st.expander(f"⚠️ {len(result.warnings)} warning(s)", expanded=False):
            for w in result.warnings:
                st.warning(w)

    # Resolved entity chips (final state; live banner shown above during run)
    if result.resolved_entities and not state.get_live_entities():
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
        if pills_html:
            st.markdown(
                '<div style="margin-top:10px">'
                '<span style="font-size:0.68em;font-weight:700;color:#9CA3AF;'
                'text-transform:uppercase;letter-spacing:0.05em">'
                'Entities&nbsp;&nbsp;</span>'
                f'{pills_html}</div>',
                unsafe_allow_html=True,
            )


def _render_graph_column() -> None:
    """Col 2 of the Investigate tab: live step checklist + entity panels when done."""
    _section_header("🕸️ Context Graph", "Entity ownership and relationship map")

    legend_items = [
        ("🔵", "Company"),
        ("🟢", "Beneficial Owner"),
        ("🟡", "Address"),
        ("🔗", "Ownership Link"),
    ]
    legend_html = "".join(
        f'<span style="margin-right:12px;font-size:0.78em;color:#6B7280">'
        f'{icon} {_esc(label)}</span>'
        for icon, label in legend_items
    )
    st.markdown(f'<div style="margin-bottom:12px">{legend_html}</div>', unsafe_allow_html=True)

    live_phase    = state.get_live_phase()
    live_entities = state.get_live_entities()
    live_plan     = state.get_live_plan()
    result        = state.get_result()

    # Planning: nothing useful yet
    if live_phase == "planning":
        st.markdown(
            '<div style="background:#F9FAFB;border:1px solid #E5E7EB;'
            'border-radius:8px;padding:40px 20px;text-align:center;'
            'color:#9CA3AF;font-size:0.85em">'
            '⏳ &nbsp;Generating investigation plan…'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Resolving: show entity lookup in progress
    if live_phase == "resolving" and not live_entities:
        st.markdown(
            '<div style="background:#EFF6FF;border:1px solid #BFDBFE;'
            'border-radius:8px;padding:16px 20px;margin:4px 0">'
            '<span style="font-size:0.87em;color:#1D4ED8">'
            '🔄 &nbsp;Looking up company in registry…</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Show entity banner once resolved
    if live_entities:
        for name, data in live_entities.items():
            canonical  = (data or {}).get("canonical_name", name)
            company_no = (data or {}).get("company_number", "")
            no_str     = f" (No. {company_no})" if company_no else ""
            status_html = (
                f'<div style="font-size:0.85em;color:#14532D;font-weight:600;'
                f'margin-bottom:8px">✔ {_esc(canonical)}{_esc(no_str)}</div>'
                if data else
                f'<div style="font-size:0.85em;color:#B91C1C;margin-bottom:8px">'
                f'❌ {_esc(name)} — not found</div>'
            )
            st.markdown(status_html, unsafe_allow_html=True)

    # Show live step checklist while executing
    if live_phase == "executing" and live_plan:
        _render_live_step_checklist()
        return

    # Done: show entity detail panels
    if result is not None and result.resolved_entities:
        _label_row("Entity Details")
        for name, data in result.resolved_entities.items():
            if data is None:
                continue
            with st.container(border=True):
                canonical  = data.get("canonical_name", name)
                company_no = data.get("company_number", "")
                exact      = data.get("exact_match", True)
                st.markdown(
                    f'<div style="font-weight:600;color:#111827;font-size:0.92em;'
                    f'margin-bottom:4px">🔵 {_esc(canonical)}</div>',
                    unsafe_allow_html=True,
                )
                meta = []
                if company_no:
                    meta.append(f"No. {company_no}")
                meta.append("exact match" if exact else "closest match")
                st.caption("  ·  ".join(meta))
        return

    if live_phase == "idle" and result is None:
        st.markdown(
            '<div style="background:#F9FAFB;border:1px solid #E5E7EB;'
            'border-radius:8px;padding:40px 20px;text-align:center;'
            'color:#9CA3AF;font-size:0.85em">'
            '🕸️ &nbsp;Entity graph will appear here after an investigation.'
            '</div>',
            unsafe_allow_html=True,
        )


def _render_insights_column(live_dims: dict) -> None:
    """Col 3 of the Investigate tab: progressive risk signals + final reasoning.

    During execution: shows which risk dimensions are resolved and which are pending.
    After completion: shows reasoning, confidence, and the complete risk driver grid.
    Always ends with a collapsed "How this decision was made" expander when data exists.
    """
    _section_header("💡 Decision Insights", "Reasoning and risk factor breakdown")

    live_phase = state.get_live_phase()
    result     = state.get_result()
    live_plan  = state.get_live_plan()
    plan       = (result.planner_output if result is not None else None) or live_plan

    # ── Idle, no data ──────────────────────────────────────────────────
    if live_phase == "idle" and result is None:
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:10px 0">'
            'Decision insights will appear here after a run.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Show investigation type as soon as plan is known ─────────────────
    if plan:
        mode         = plan.get("mode", "")
        mode_display = _MODE_DISPLAY.get(mode, mode.title() if mode else "")
        if mode_display:
            st.markdown(
                f'<div style="font-size:0.72em;font-weight:700;color:#6B7280;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">'
                f'Investigation Type</div>'
                f'<div style="font-size:0.88em;color:#1F2937;font-weight:600;'
                f'margin-bottom:10px">{_esc(mode_display)}</div>',
                unsafe_allow_html=True,
            )

    # ── Progressive risk signals while executing ──────────────────────
    if live_phase in ("planning", "resolving", "executing") and result is None:
        live_steps    = state.get_live_steps()
        live_cur      = state.get_live_current_step()
        current_task  = (live_cur or {}).get("task") if live_cur else None
        completed_set = {s.get("task") for s in live_steps}

        _label_row("Risk Signals")

        signal_rows = ""
        for task_key, dim, label in _RISK_DIM_TASKS:
            risk = live_dims.get(dim, "UNKNOWN")
            if task_key in completed_set:
                tc, bg, border = _RISK_COLORS.get(risk, _RISK_COLORS["UNKNOWN"])
                icon    = "✔"
                c_icon  = "#16A34A"
                badge   = (
                    f'<span style="background:{bg};color:{tc};border:1px solid {border};'
                    f'border-radius:4px;padding:1px 8px;font-size:0.76em;font-weight:700">'
                    f'{_esc(risk)}</span>'
                )
            elif task_key == current_task:
                icon    = "🔄"
                c_icon  = "#D97706"
                badge   = (
                    '<span style="color:#D97706;font-size:0.76em;font-style:italic">'
                    'Computing…</span>'
                )
            else:
                icon    = "⏳"
                c_icon  = "#9CA3AF"
                badge   = (
                    '<span style="color:#9CA3AF;font-size:0.76em">Pending</span>'
                )
            signal_rows += (
                f'<div style="display:flex;align-items:center;justify-content:space-between;'
                f'padding:6px 0;border-bottom:1px solid #F3F4F6">'
                f'<span style="font-size:0.83em;color:{c_icon}">{icon} {_esc(label)}</span>'
                f'{badge}'
                f'</div>'
            )

        if signal_rows:
            st.markdown(
                f'<div style="background:#FAFAFA;border:1px solid #E5E7EB;'
                f'border-radius:8px;padding:10px 14px;margin:4px 0">'
                f'{signal_rows}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Full result ────────────────────────────────────────────────────
    elif result is not None:
        # Reasoning summary
        if plan:
            reason = plan.get("reason", "")
            if reason:
                _label_row("Reasoning Summary")
                st.markdown(
                    f'<div style="font-size:0.84em;color:#374151;'
                    f'border-left:3px solid #BFDBFE;padding:5px 0 5px 10px;'
                    f'margin:0 0 12px 0;line-height:1.55">'
                    f'{_esc(reason)}</div>',
                    unsafe_allow_html=True,
                )

        # Confidence indicators
        steps      = result.step_results or []
        n_done     = sum(1 for s in steps if s.status == "success")
        n_total    = len(steps)
        agents_run = sorted({
            _AGENT_LABELS.get(s.agent, s.agent)
            for s in steps if s.status == "success"
        })

        _label_row("Confidence Indicators")
        c1, c2 = st.columns(2)
        c1.metric("Steps Completed", f"{n_done}/{n_total}")
        c2.metric("Outcome", "✓ Success" if result.success else "✗ Failed")

        if agents_run:
            st.markdown(
                f'<div style="font-size:0.78em;color:#374151;margin:6px 0 12px 0">'
                f'<span style="color:#6B7280">Agents:</span> '
                f'{_esc(", ".join(agents_run))}</div>',
                unsafe_allow_html=True,
            )

        # Complete risk driver grid
        summarize_findings = _get_summarize_findings(result)
        if summarize_findings:
            dims = {
                dim: (summarize_findings.get(task) or {}).get("risk_level", "UNKNOWN")
                if isinstance(summarize_findings.get(task), dict) else "UNKNOWN"
                for task, dim, _ in _RISK_DIM_TASKS
            }
            if any(v != "UNKNOWN" for v in dims.values()):
                _label_row("Key Risk Drivers")
                _render_risk_drivers_grid(dims)

        if result.warnings:
            with st.expander(f"⚠️ {len(result.warnings)} warning(s)", expanded=False):
                for w in result.warnings:
                    st.warning(w)

    # ── How this decision was made ─────────────────────────────────────
    # Shown whenever plan or result data is available; always collapsed.
    if result is not None or live_plan is not None:
        st.markdown(
            '<div style="margin-top:14px"></div>',
            unsafe_allow_html=True,
        )
        with st.expander("🔍 How this decision was made", expanded=False):
            _render_analysis_expander()


def _render_analysis_expander() -> None:
    """Content for the 'How this decision was made' expander.

    Shows investigation plan, step-by-step execution cards, and trace ID.
    Rendered at the bottom of the Decision Insights column, always collapsed.
    """
    result     = state.get_result()
    live_plan  = state.get_live_plan()
    live_phase = state.get_live_phase()

    if result is None and live_plan is None and live_phase == "idle":
        st.caption("Run an investigation to see the analysis details here.")
        return

    # ── Investigation Plan ──────────────────────────────────────────────
    plan = (result.planner_output if result is not None else None) or live_plan
    if plan is not None:
        _section_header("📋 Investigation Plan")
        with st.container(border=True):
            col_mode, col_entity = st.columns([1, 2])
            col_mode.metric("Mode", plan.get("mode", "—").title())

            entities   = plan.get("entities") or []
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
                    task_disp  = _task_label(s.get("task", ""))
                    agent_disp = _agent_display(s.get("agent", ""))
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

        st.divider()

    # ── Execution Steps ─────────────────────────────────────────────────
    _section_header("🔍 Investigation Steps", "How the analysis was performed")

    live_steps = state.get_live_steps()
    live_cur   = state.get_live_current_step()

    if result is not None:
        if not result.step_results:
            st.caption("No steps were executed.")
        else:
            for i, step in enumerate(result.step_results, start=1):
                _render_step_card(i, step)
    elif live_phase in ("planning", "resolving"):
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:12px 0">'
            '⏳ &nbsp;Steps will appear as they complete…</div>',
            unsafe_allow_html=True,
        )
    else:
        n_total = len((live_plan or {}).get("plan") or [])
        n_done  = len(live_steps)
        if n_total:
            st.progress(n_done / n_total, text=f"Step {n_done} of {n_total}")

        for i, step_dict in enumerate(live_steps, start=1):
            _render_step_card(i, _NS(**step_dict))

        if live_cur:
            running = _NS(
                step_id        = live_cur.get("step_id", ""),
                agent          = live_cur.get("agent", ""),
                task           = live_cur.get("task", ""),
                status         = "running",
                success        = False,
                summary        = "",
                findings       = {},
                tools_executed = [],
                error          = None,
                skipped        = False,
                skip_reason    = None,
            )
            _render_step_card(n_done + 1, running)

    # ── Decision Trace ──────────────────────────────────────────────────
    trace_id = state.get_trace_id() or state.get_live_trace_id()
    if trace_id:
        st.divider()
        _section_header("🗂️ Decision Trace")
        st.markdown(
            '<div style="background:#F3F4F6;border-radius:6px;'
            'padding:10px 12px;margin:6px 0 10px 0">'
            '<div style="font-size:0.66em;color:#6B7280;text-transform:uppercase;'
            'letter-spacing:0.06em;font-weight:700;margin-bottom:4px">Trace ID</div>'
            f'<code style="font-size:0.76em;color:#374151;word-break:break-all">'
            f'{_esc(trace_id)}</code></div>',
            unsafe_allow_html=True,
        )
        if result is not None:
            steps = result.step_results or []
            if steps:
                n_ok      = sum(1 for s in steps if s.status == "success")
                n_failed  = sum(1 for s in steps if s.status == "failed")
                n_skipped = sum(1 for s in steps if s.status == "skipped")
                c1, c2, c3 = st.columns(3)
                c1.metric("Completed", n_ok)
                c2.metric("Failed",    n_failed)
                c3.metric("Skipped",   n_skipped)


# ===========================================================================
# REPLAY / AUDIT TAB
# ===========================================================================


def render_replay_tab(components: "AppComponents") -> None:
    """Render the Replay / Audit tab.

    Layout
    ------
    [Col 1 — Risk Assessment]  [Col 2 — Investigation Activity]  [Col 3 — Replayed Trace]
    """
    col1, col2, col3 = st.columns([2, 3, 2])

    with col1:
        _render_replay_assessment_column()

    with col2:
        _render_replay_activity_column()

    with col3:
        _render_replay_metadata_column(components)


def _render_replay_assessment_column() -> None:
    """Col 1 of the Replay tab: original question + risk assessment + risk drivers."""
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()

    _section_header("📊 Risk Assessment")

    if replay_status == "idle":
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:10px 0">'
            'Load a past investigation using the trace ID panel on the right.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    if replay_status == "loading":
        st.markdown(
            '<div style="color:#D97706;font-size:0.85em;padding:10px 0">'
            '⏳ &nbsp;Loading investigation…</div>',
            unsafe_allow_html=True,
        )
        return

    if replay_status == "error":
        error = state.get_replay_error()
        if error:
            st.error(error)
        return

    if not replay_data:
        return

    # Original question — prefer full question text (new traces); fall back
    # to entity name (legacy traces that predate the question field).
    question_raw = replay_data.get("question") or replay_data.get("query", "")
    if question_raw:
        display_q = _display_question(question_raw)
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

    # 2. Assessment card
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

    _render_assessment_card(headline_text, headline_emoji, risk_level, summary, tc, bg, border)

    # 3. Key Risk Drivers
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


def _render_replay_activity_column() -> None:
    """Col 2 of the Replay tab: investigation plan snapshot + event timeline."""
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()

    _section_header("📋 Investigation Plan")

    if replay_status != "loaded" or not replay_data:
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:10px 0">'
            'Load a trace to view the investigation plan and activity timeline.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    _render_replay_plan(replay_data)

    st.divider()

    _section_header(
        "🗂️ Investigation Activity",
        "Step-by-step record of what was done during this investigation",
    )
    _render_replay_event_timeline(replay_data.get("events") or [])


def _render_replay_metadata_column(components: "AppComponents") -> None:
    """Col 3 of the Replay tab: trace ID input, load/clear controls, trace metadata."""
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()
    replay_error  = state.get_replay_error()

    _section_header("🗂️ Replayed Trace", "Load a previous investigation by trace ID")

    # Load controls (always shown)
    with st.container(border=True):
        replay_id = st.text_input(
            label="Trace ID",
            label_visibility="collapsed",
            value=state.get_replay_trace_id() or "",
            placeholder="Enter a trace ID to replay…",
            key="_input_replay_trace_id",
        )
        load_clicked = st.button(
            "Load Trace",
            use_container_width=True,
            disabled=(replay_status == "loading"),
        )
        if load_clicked and replay_id.strip():
            state.set_replay_trace_id(replay_id.strip())
            st.session_state["_trigger_replay"] = True

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
                f'margin-bottom:5px">✓ Investigation loaded</div>'
                f'<code style="font-size:0.76em;color:#166534;word-break:break-all">'
                f'{_esc(short_id)}</code>'
                f'<div style="font-size:0.78em;color:#6B7280;margin-top:6px">'
                f'{_esc(mode_display)} &nbsp;·&nbsp; {n_events} activity event(s)</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("Clear Replay", use_container_width=True, type="secondary"):
                st.session_state["_clear_replay"] = True

    # Trace metadata (shown below controls when loaded)
    if replay_status == "loaded" and replay_data:
        st.divider()
        _render_replay_trace_metadata(replay_data)
