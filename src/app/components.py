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

import difflib as _difflib
import html as _html
import json as _json
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

# Canonical recommendation strings — never vary
_RISK_RECOMMENDATIONS: dict[str, str] = {
    "HIGH":   "Enhanced due diligence required before onboarding",
    "MEDIUM": "Additional review recommended before proceeding",
    "LOW":    "Standard monitoring applies",
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
    """Return the first n sentences from text.

    A sentence boundary is a '.', '!', or '?' that is either followed by
    whitespace or is the last character — this avoids cutting on dots inside
    company-name suffixes like 'VODAFONE 2.' mid-paragraph.
    """
    if not text:
        return ""
    s = text.strip()
    count = 0
    for i, ch in enumerate(s):
        if ch in ".!?":
            # Require boundary: end-of-string OR followed by whitespace
            if i == len(s) - 1 or s[i + 1].isspace():
                # Skip "2." pattern — digit-terminated company names are not sentence ends
                if ch == "." and i > 0 and s[i - 1].isdigit():
                    continue
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


def _collect_risk_dims(result: Any) -> dict[str, str]:
    """
    Return {dim_key: risk_level} for all four risk dimensions.

    Prefers summarize_risk_for_company (covers all four in one step).
    Falls back to collecting from whichever individual risk tasks ran.
    Dimensions not assessed are marked "NOT RUN"; dimensions assessed
    but with no graph data are marked "UNKNOWN".
    """
    _TASK_TO_DIM = {task: dim for task, dim, _ in _RISK_DIM_TASKS}

    # Prefer the summary step (all four dimensions present)
    summarize_findings = _get_summarize_findings(result)
    if summarize_findings:
        return {
            dim: (summarize_findings.get(task) or {}).get("risk_level", "UNKNOWN")
            if isinstance(summarize_findings.get(task), dict) else "UNKNOWN"
            for task, dim, _ in _RISK_DIM_TASKS
        }

    # Fall back: collect from whichever individual risk tasks ran
    dims = {dim: "NOT RUN" for _, dim, _ in _RISK_DIM_TASKS}
    for sr in result.step_results or []:
        dim = _TASK_TO_DIM.get(sr.task)
        if dim and sr.success and sr.findings:
            data = sr.findings.get(sr.task)
            if isinstance(data, dict):
                dims[dim] = data.get("risk_level", "UNKNOWN")
    return dims


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




def _extract_replay_risk_dimensions(replay_data: dict) -> dict[str, str]:
    """Extract per-dimension risk levels from replay event output summaries."""
    _DIM_TASKS: dict[str, str] = {
        "ownership_complexity_check": "ownership",
        "control_signal_check":       "control",
        "address_risk_check":         "address",
        "industry_context_check":     "industry",
    }
    dims = {v: "NOT RUN" for v in _DIM_TASKS.values()}

    for ev in (replay_data.get("events") or []):
        if ev.get("event_type") != "tool_returned":
            continue
        tool_name = ev.get("tool_name", "")
        if tool_name not in _DIM_TASKS:
            continue
        dim = _DIM_TASKS[tool_name]
        if dims[dim] not in ("NOT RUN", "UNKNOWN"):
            continue
        # Prefer structured data_json (traces after backend update)
        raw_json = ev.get("data_json") or ""
        if raw_json:
            try:
                import json as _json_mod
                data = _json_mod.loads(raw_json)
                lvl = (data.get("risk_level") or "").upper()
                if lvl in ("HIGH", "MEDIUM", "LOW"):
                    dims[dim] = lvl
                    continue
                # Tool ran but had no data
                dims[dim] = "UNKNOWN"
                continue
            except Exception:
                pass
        # Fall back: parse output_summary text (old traces without data_json)
        dims[dim] = "UNKNOWN"  # tool ran, mark as at least assessed
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


_RISK_TASK_NAMES = {
    "ownership_complexity_check",
    "control_signal_check",
    "address_risk_check",
    "industry_context_check",
}


def _extract_replay_all_findings(replay_data: dict) -> dict[str, dict]:
    """Extract full per-task findings dicts from replay trace events.

    Reads data_json from tool_returned events for the 4 risk tasks.
    Returns {task_name: findings_dict}, mirroring _get_all_risk_findings(result).
    """
    out: dict[str, dict] = {}
    for ev in (replay_data.get("events") or []):
        if ev.get("event_type") != "tool_returned":
            continue
        task = ev.get("tool_name", "")
        if task not in _RISK_TASK_NAMES:
            continue
        raw = ev.get("data_json") or ""
        if not raw:
            continue
        try:
            data = _json.loads(raw)
            if isinstance(data, dict):
                out[task] = data
        except Exception:
            pass
    return out


def _extract_replay_graph_insights(events: list) -> dict:
    """Extract graph insight values from replay events.

    Scans the ownership_complexity_check tool_returned event output_summary
    to derive the same three metrics shown in the Investigate tab's
    Context Graph column.

    Returns dict with keys: ownership_depth, beneficial_owner, structure_complexity.
    Values are display strings or "—" when not determinable.
    """
    out = {"ownership_depth": "—", "beneficial_owner": "—", "structure_complexity": "—"}
    for ev in events:
        if ev.get("event_type") != "tool_returned":
            continue
        if ev.get("tool_name") != "ownership_complexity_check":
            continue
        # Try structured data first (available in traces after backend update)
        raw_json = ev.get("data_json", "")
        if raw_json:
            try:
                data = _json.loads(raw_json)
                depth = data.get("max_chain_depth")
                if depth is not None:
                    out["ownership_depth"] = f"{depth} hop{'s' if depth != 1 else ''}"
                has_ubos = data.get("has_individual_ubos")
                if has_ubos is not None:
                    out["beneficial_owner"] = "Yes" if has_ubos else "No"
                risk_lvl = data.get("risk_level", "")
                _cmap = {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}
                if risk_lvl in _cmap:
                    out["structure_complexity"] = _cmap[risk_lvl]
                break
            except Exception:
                pass

        # Fall back to parsing output_summary text (for traces before backend update)
        text = ev.get("output_summary") or ""
        m = _re.search(r"max depth\s+(\d+)", text, _re.IGNORECASE)
        if m:
            out["ownership_depth"] = f"{m.group(1)} hops"
        tl = text.lower()
        # "K individual UBO(s)" — use count directly (matches actual tool output format)
        m2 = _re.search(r"(\d+)\s+individual\s+ubo", tl)
        if m2:
            out["beneficial_owner"] = "Yes" if int(m2.group(1)) > 0 else "No"
        elif "corporate entities" in tl or "corporate-only" in tl or "corporate only" in tl:
            out["beneficial_owner"] = "No"
        tu = text.upper()
        for lvl, label in (("HIGH", "High"), ("MEDIUM", "Medium"), ("LOW", "Low")):
            if f" {lvl}" in tu or f":{lvl}" in tu:
                out["structure_complexity"] = label
                break
        break  # only need the first matching event
    return out


def _name_similarity(searched: str, canonical: str) -> int:
    """Return 0–100 name similarity score using SequenceMatcher ratio."""
    if not searched or not canonical:
        return 0
    return round(
        _difflib.SequenceMatcher(None, searched.lower(), canonical.lower()).ratio() * 100
    )


def _extract_replay_entity(events: list, query: str) -> dict:
    """Extract canonical name, company number, and status from trace events.

    Primary path  — agent_reasoning event 'Resolved <query> → <canonical>':
      1. Try data_json (structured payload).
      2. Fall back to message parsing for canonical name, then supplement
         company_number / status from the entity_lookup output_summary.

    Final fallback — entity_lookup output_summary only.
    """
    def _from_lookup(events: list) -> tuple[str, str]:
        """Return (company_number, status) from entity_lookup output_summary."""
        for ev in events:
            if ev.get("event_type") != "tool_returned":
                continue
            if ev.get("tool_name") != "entity_lookup":
                continue
            text = ev.get("output_summary") or ""
            cn = ""
            m = _re.search(r"number:\s*([A-Z0-9]+)", text, _re.IGNORECASE)
            if m:
                cn = m.group(1)
            st = ""
            m2 = _re.search(r"status:\s*(\w+)", text, _re.IGNORECASE)
            if m2:
                st = m2.group(1).capitalize()
            if cn or st:
                return cn, st
        return "", ""

    for ev in events:
        if ev.get("event_type") != "agent_reasoning":
            continue
        msg = ev.get("input_summary") or ev.get("message") or ""
        if not _re.search(
            rf"Resolved\s+['\"]?{_re.escape(query)}['\"]?", msg, _re.IGNORECASE
        ):
            continue
        # Try structured data_json first (present on newer traces)
        raw = ev.get("data_json") or ""
        if raw:
            try:
                d = _json.loads(raw)
                return {
                    "canonical_name":  d.get("canonical_name") or query,
                    "company_number":  d.get("company_number") or "",
                    "status":          d.get("status") or "",
                    "match_score_pct": d.get("match_score_pct"),
                }
            except Exception:  # noqa: BLE001
                pass
        # data_json absent — parse canonical name from message, supplement rest
        m = _re.search(r"→\s*['\"]?(.+?)['\"]?\s*$", msg)
        canonical = m.group(1).strip() if m else query
        cn, st = _from_lookup(events)
        return {"canonical_name": canonical, "company_number": cn, "status": st}

    # No agent_reasoning event found — use lookup data only
    cn, st = _from_lookup(events)
    return {"canonical_name": query, "company_number": cn, "status": st}


def _extract_replay_company_number(events: list) -> str:
    """Extract company number from the entity_lookup tool_returned event.

    Returns the number string (e.g. "04083193") or "" if not found.
    """
    for ev in events:
        if ev.get("event_type") != "tool_returned":
            continue
        if ev.get("tool_name") != "entity_lookup":
            continue
        text = ev.get("output_summary") or ""
        m = _re.search(r"No\.\s*([A-Z0-9]+)", text, _re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


# Maps individual tool names to the logical plan-step (task, agent) pair
_TOOL_TO_PLAN_STEP: dict[str, tuple[str, str]] = {
    "entity_lookup":               ("entity_lookup",              "graph-agent"),
    "expand_ownership":            ("expand_ownership",           "graph-agent"),
    "ownership_complexity_check":  ("summarize_risk_for_company", "risk-agent"),
    "control_signal_check":        ("summarize_risk_for_company", "risk-agent"),
    "address_risk_check":          ("summarize_risk_for_company", "risk-agent"),
    "industry_context_check":      ("summarize_risk_for_company", "risk-agent"),
}


def _replay_plan_steps(events: list) -> list[dict]:
    """Derive ordered, deduplicated plan steps from replay tool_returned events.

    Maps individual tool calls back to the three logical plan steps so the
    Replay tab can show the same step structure as the Investigate tab.
    Returns list of {task, agent, success} dicts.
    """
    seen: list[tuple] = []
    for ev in events:
        if ev.get("event_type") != "tool_returned":
            continue
        key = _TOOL_TO_PLAN_STEP.get(ev.get("tool_name", ""))
        if key and key not in seen:
            seen.append(key)
    return [{"task": k[0], "agent": k[1], "success": True} for k in seen]


_REPLAY_RISK_TOOLS: frozenset = frozenset({
    "ownership_complexity_check", "control_signal_check",
    "address_risk_check", "industry_context_check",
})
_REPLAY_TOOL_DIM: dict[str, str] = {
    "ownership_complexity_check": "ownership",
    "control_signal_check":       "control",
    "address_risk_check":         "address",
    "industry_context_check":     "industry",
}


def _render_replay_step_cards(events: list) -> None:
    """Render replay audit trail as 3 grouped step cards matching the Investigate tab.

    Groups all tool_returned events into the same 3 logical plan steps used by
    _replay_plan_steps (entity_lookup, expand_ownership, summarize_risk_for_company).
    The "Assess risk signals" card shows a risk driver grid for the 4 sub-checks.
    """
    groups: dict[tuple, list] = {}
    order: list[tuple] = []
    for ev in events:
        if ev.get("event_type") != "tool_returned":
            continue
        key = _TOOL_TO_PLAN_STEP.get(ev.get("tool_name", ""))
        if not key:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(ev)

    if not order:
        st.caption("No steps were recorded for this investigation.")
        return

    for i, key in enumerate(order, 1):
        task_key, agent_key = key
        task_disp  = _task_label(task_key)
        agent_disp = _agent_display(agent_key)
        evs = groups[key]

        summary = next(
            (e.get("output_summary", "").strip() for e in evs
             if e.get("output_summary", "").strip()),
            "",
        )

        _accent_bar("success")
        with st.container(border=True):
            st.markdown(
                _step_header_html(i, task_disp, agent_disp, "success"),
                unsafe_allow_html=True,
            )
            if summary:
                st.markdown(
                    f'<div style="color:#374151;font-size:0.87em;line-height:1.55;'
                    f'padding:4px 0">{_esc(_first_sentences(summary, 1))}</div>',
                    unsafe_allow_html=True,
                )
            # Tools used pills — same as _render_step_card
            tool_names = [e.get("tool_name", "") for e in evs if e.get("tool_name")]
            tools_html = _tool_pills(tool_names)
            if tools_html:
                st.markdown(tools_html, unsafe_allow_html=True)
            # Risk breakdown grid for the "Assess risk signals" grouped step
            risk_evs = [e for e in evs if e.get("tool_name") in _REPLAY_RISK_TOOLS]
            if risk_evs:
                dims: dict[str, str] = {}
                for e in risk_evs:
                    dim = _REPLAY_TOOL_DIM.get(e.get("tool_name", ""))
                    if not dim:
                        continue
                    out_text = (e.get("output_summary") or "").upper()
                    for lvl in ("HIGH", "MEDIUM", "LOW"):
                        if f" {lvl}" in out_text or f":{lvl}" in out_text:
                            dims[dim] = lvl
                            break
                if dims:
                    _label_row("Risk Breakdown")
                    _render_risk_drivers_grid(dims)
            # "View step details" expander — mirrors _render_step_card
            with st.expander("View step details", expanded=False):
                reasoning = _TASK_REASONING.get(task_key, "")
                if reasoning:
                    st.markdown(
                        f'<div style="font-size:0.83em;color:#374151;line-height:1.55;'
                        f'margin-bottom:8px">{_esc(reasoning)}</div>',
                        unsafe_allow_html=True,
                    )
                if summary:
                    _label_row("Full Summary")
                    st.markdown(
                        f'<div style="font-size:0.83em;color:#374151;line-height:1.55">'
                        f'{_esc(summary)}</div>',
                        unsafe_allow_html=True,
                    )
                # Findings from structured data_json (available in new traces)
                for e in evs:
                    raw = e.get("data_json") or ""
                    if raw:
                        try:
                            findings = _json.loads(raw)
                            if findings:
                                _label_row("Findings")
                                st.json(findings)
                                break
                        except Exception:
                            pass


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
    summary_section = (
        f'<div style="font-size:0.66em;font-weight:700;color:{tc};opacity:0.7;'
        f'text-transform:uppercase;letter-spacing:0.06em;margin:12px 0 4px 0">'
        f'Summary</div>'
        f'<div style="color:#374151;font-size:0.87em;line-height:1.65">'
        f'{_esc(summary)}</div>'
        if summary else ""
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


def _render_overall_risk_badge(overall_risk: "str | None") -> None:
    """Render a prominent overall risk verdict badge in the Assessment column."""
    if not overall_risk or overall_risk not in _RISK_COLORS:
        return
    tc, bg, border = _RISK_COLORS[overall_risk]
    st.markdown(
        f'<div style="margin:6px 0 14px 0">'
        f'<div style="font-size:0.66em;font-weight:700;color:#6B7280;'
        f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:5px">'
        f'Overall Risk</div>'
        f'<div style="background:{bg};color:{tc};border:2px solid {border};'
        f'border-radius:8px;padding:6px 18px;font-size:1.0em;font-weight:800;'
        f'display:inline-block;letter-spacing:0.05em">'
        f'{_esc(overall_risk)}</div>'
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

    _section_header("📋 Investigation Plan")
    with st.container(border=True):
        col_mode, col_entity = st.columns([1, 2])
        col_mode.metric("Mode", mode_display)
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
                f'<div style="font-size:0.83em;color:#374151;'
                f'border-left:3px solid #E5E7EB;padding:4px 0 4px 10px;'
                f'margin:10px 0 8px 0;line-height:1.55">'
                f'{_esc(focus_text)}</div>',
                unsafe_allow_html=True,
            )

        plan_steps = _replay_plan_steps(events)
        if plan_steps:
            _label_row("Steps")
            for i, s in enumerate(plan_steps, 1):
                task_disp  = _task_label(s["task"])
                agent_disp = _agent_display(s["agent"])
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
    result = state.get_result()
    overall = _overall_risk_from_result(result) if result else None

    if overall and overall in _RISK_COLORS:
        tc, bg, border = _RISK_COLORS[overall]
        badge_html = (
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<span style="font-size:0.7em;font-weight:700;color:#6B7280;'
            f'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap">'
            f'Overall Risk</span>'
            f'<span style="background:{bg};color:{tc};border:2px solid {border};'
            f'border-radius:8px;padding:5px 16px;font-size:1.15em;font-weight:800;'
            f'letter-spacing:0.05em;white-space:nowrap">'
            f'{_esc(overall)}</span>'
            f'</div>'
        )
    else:
        badge_html = ''

    st.markdown(
        f'<div style="padding:1.2rem 0 1.1rem 0;border-bottom:1px solid #E5E7EB;'
        f'margin-bottom:1.4rem;display:flex;justify-content:space-between;align-items:center">'
        f'<div>'
        f'<div style="font-size:1.55rem;font-weight:800;color:#111827;'
        f'letter-spacing:-0.02em;line-height:1.3">Entity Risk AI</div>'
        f'<div style="font-size:0.875rem;color:#6B7280;margin-top:5px;'
        f'font-weight:400;line-height:1.5">'
        f'Investigate ownership, risk, and traceable decisions</div>'
        f'</div>'
        f'{badge_html}'
        f'</div>',
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
    """Render a structured 'Identified Entity' card for each resolved entity.

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
                f'❌ {_esc(name)} — no match in registry</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            canonical  = data.get("canonical_name", name)
            company_no = data.get("company_number", "")
            status     = data.get("status", "")
            score      = data.get("match_score_pct") if data.get("match_score_pct") is not None else _name_similarity(name, canonical)

            def _meta_row(label: str, value: str, last: bool = False) -> str:
                border = "" if last else "border-bottom:1px solid #D1FAE5;"
                return (
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:4px 0;{border}">'
                    f'<span style="font-size:0.78em;color:#4ADE80">{_esc(label)}</span>'
                    f'<span style="font-size:0.78em;font-weight:600;color:#14532D">'
                    f'{_esc(value)}</span></div>'
                )

            rows = ""
            if company_no:
                rows += _meta_row("Company No.", company_no)
            rows += _meta_row("Status", status if status else "—")
            rows += _meta_row("Jurisdiction", "UK")
            rows += _meta_row("Match score", f"{score}%", last=True)

            st.markdown(
                f'<div style="background:#F0FDF4;border:1px solid #BBF7D0;'
                f'border-left:4px solid #16A34A;border-radius:6px;'
                f'padding:10px 14px;margin:8px 0">'
                f'<div style="font-size:0.62em;font-weight:700;color:#16A34A;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:5px">'
                f'Identified Entity</div>'
                f'<div style="font-size:0.96em;color:#14532D;font-weight:800;'
                f'margin-bottom:7px;letter-spacing:0.01em">'
                f'{_esc(canonical.upper())}</div>'
                f'{rows}'
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
            icon  = "›"
            color = "#2563EB"
            weight = "600"
        else:
            icon  = "·"
            color = "#9CA3AF"
            weight = "400"
        rows_html += (
            f'<div style="display:flex;align-items:center;gap:8px;'
            f'padding:6px 0;border-bottom:1px solid #F3F4F6">'
            f'<span style="font-size:0.92em;width:16px;text-align:center;'
            f'color:{color};font-weight:700">{icon}</span>'
            f'<span style="font-size:0.83em;color:{color};font-weight:{weight}">'
            f'{_esc(label)}</span>'
            f'</div>'
        )

    if rows_html:
        st.markdown(
            f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
            f'border-radius:8px;padding:10px 14px;margin:4px 0">'
            f'{rows_html}'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_assessment_card_skeleton(
    message: str = "Analysis in progress…",
    show_pending_rows: bool = True,
) -> None:
    """Skeleton assessment card shown before results arrive.

    When show_pending_rows=False (idle), renders only the status message.
    When True, shows the decision-first card shape with pending placeholders.
    """
    if not show_pending_rows:
        st.markdown(
            f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
            f'border-left:5px solid #CBD5E1;border-radius:8px;'
            f'padding:16px 20px;margin:4px 0 12px 0;'
            f'color:#94A3B8;font-size:0.87em;line-height:1.6">'
            f'{_esc(message)}</div>',
            unsafe_allow_html=True,
        )
        return

    _PENDING = '<span style="color:#CBD5E1;font-size:0.84em">Pending…</span>'
    st.markdown(
        f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
        f'border-left:5px solid #CBD5E1;border-radius:8px;'
        f'padding:16px 20px;margin:4px 0 12px 0">'
        # Title placeholder
        f'<div style="font-size:1.0em;font-weight:800;color:#CBD5E1;margin-bottom:12px">'
        f'{_esc(message)}</div>'
        # Primary driver placeholder
        f'<div style="font-size:0.62em;font-weight:700;color:#94A3B8;'
        f'text-transform:uppercase;letter-spacing:0.06em;margin:0 0 4px 0">'
        f'Primary Risk Driver</div>'
        f'<div style="color:#CBD5E1;font-size:0.84em;line-height:1.55;margin-bottom:12px">'
        f'{_PENDING}</div>'
        # Actions placeholder
        f'<div style="font-size:0.62em;font-weight:700;color:#94A3B8;'
        f'text-transform:uppercase;letter-spacing:0.06em;margin:0 0 4px 0">'
        f'Recommended Actions</div>'
        f'<div style="color:#CBD5E1;font-size:0.84em">{_PENDING}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _extract_graph_insights(result: Any) -> dict:
    """Extract ownership graph metrics from ownership_complexity_check findings.

    Returns dict with keys: ownership_depth, beneficial_owner, structure_complexity.
    Values are display strings ("3 hops", "Yes", "High") or "—" when unavailable.
    """
    out = {"ownership_depth": "—", "beneficial_owner": "—", "structure_complexity": "—"}
    for sr in (result.step_results or []):
        if not sr.success:
            continue
        findings_sr = sr.findings or {}
        if sr.task == "ownership_complexity_check":
            data = findings_sr.get("ownership_complexity_check") or {}
        elif sr.task == "summarize_risk_for_company":
            data = findings_sr.get("ownership_complexity_check") or {}
        else:
            continue
        if not isinstance(data, dict) or not data:
            continue
        depth = data.get("max_chain_depth")
        if depth is not None:
            out["ownership_depth"] = f"{depth} hop{'s' if depth != 1 else ''}"
        has_ubos = data.get("has_individual_ubos")
        if has_ubos is not None:
            out["beneficial_owner"] = "Yes" if has_ubos else "No"
        risk_lvl = data.get("risk_level", "")
        _cmap = {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}
        if risk_lvl in _cmap:
            out["structure_complexity"] = _cmap[risk_lvl]
        break
    # Fallback: derive graph insights from expand_ownership when complexity check didn't run
    if out["ownership_depth"] == "—":
        for sr in (result.step_results or []):
            if sr.task != "expand_ownership" or not sr.success:
                continue
            data = (sr.findings or {}).get("expand_ownership") or {}
            paths = data.get("paths") or []
            ubos  = data.get("ultimate_owners") or []
            if not paths and not ubos:
                break
            max_d    = max((r.get("path_depth", 0) for r in paths), default=0)
            unique_n = len({r.get("from_name") for r in paths if r.get("from_name")})
            has_ubos_flag = len(ubos) > 0
            corporate = len(paths) > 0 and not has_ubos_flag
            out["ownership_depth"]  = f"{max_d} hop{'s' if max_d != 1 else ''}"
            out["beneficial_owner"] = "Yes" if has_ubos_flag else "No"
            score = 0
            if max_d >= 4:      score += 2
            elif max_d >= 2:    score += 1
            if unique_n >= 5:   score += 2
            elif unique_n >= 2: score += 1
            if corporate:       score += 2
            out["structure_complexity"] = "High" if score >= 4 else ("Medium" if score >= 2 else "Low")
            break
    return out


# ---------------------------------------------------------------------------
# Context Graph — streamlit-agraph data builder
# ---------------------------------------------------------------------------

# Node colour dicts (background / border / highlight) by entity type.
# Using dicts lets vis-network apply richer selection highlighting.
_GRAPH_COLOR_FOCAL: dict = {
    "background": "#1D4ED8", "border": "#1E3A8A",
    "highlight":  {"background": "#3B82F6", "border": "#1E3A8A"},
}
_GRAPH_COLOR_COMPANY: dict = {
    "background": "#DBEAFE", "border": "#93C5FD",
    "highlight":  {"background": "#BFDBFE", "border": "#60A5FA"},
}
_GRAPH_COLOR_PERSON: dict = {
    "background": "#D1FAE5", "border": "#34D399",
    "highlight":  {"background": "#A7F3D0", "border": "#10B981"},
}
_GRAPH_COLOR_ADDRESS: dict = {
    "background": "#FEF3C7", "border": "#FCD34D",
    "highlight":  {"background": "#FDE68A", "border": "#F59E0B"},
}

# Legend colours (flat hex, for the HTML legend below the graph)
_LEGEND_FOCAL   = "#1D4ED8"
_LEGEND_COMPANY = "#93C5FD"
_LEGEND_PERSON  = "#34D399"
_LEGEND_ADDRESS = "#FCD34D"

_GRAPH_MAX_PATH_DEPTH = 3   # max ownership hops rendered
_GRAPH_MAX_NODES      = 12  # cap non-focal nodes for readability


def _build_agraph_data(result: Any) -> tuple[list, list, dict]:
    """Build Node and Edge lists plus per-node metadata from an investigation result.

    Data sources (in priority order):
      1. expand_ownership  — ownership paths + UBOs
      2. company_profile   — direct_owners (fallback), address node
      3. resolved_entities — focal node always present

    Returns (nodes, edges, node_meta) where node_meta maps each node id to
    {"full_name", "type", "context"} for the selection panel.
    """
    from streamlit_agraph import Edge, Node  # local import — optional dependency

    nodes: list[Node] = []
    edges: list[Edge] = []
    seen:  set[str]   = set()
    node_meta: dict[str, dict] = {}

    def add_node(
        nid: str, label: str, color: dict, size: int,
        full_name: str, node_type: str, context: str = "",
        border_width: int = 1,
    ) -> None:
        if nid not in seen:
            seen.add(nid)
            # title = hover tooltip (full, untruncated name)
            nodes.append(Node(
                id=nid, label=label, color=color, size=size,
                title=full_name, borderWidth=border_width,
            ))
            node_meta[nid] = {"full_name": full_name, "type": node_type, "context": context}

    def add_edge(src: str, dst: str, label: str = "", color: str = "#9CA3AF") -> None:
        edges.append(Edge(
            source=src, target=dst, label=label, color=color,
            width=2,
            font={"size": 10, "align": "middle",
                  "strokeWidth": 2, "strokeColor": "#FFFFFF"},
        ))

    def _short(name: str, n: int = 22) -> str:
        return name if len(name) <= n else name[: n - 1] + "\u2026"

    def _pct_label(lo: Any, hi: Any) -> str:
        if lo is None:
            return ""
        lo_i = int(lo)
        hi_i = int(hi) if hi is not None else lo_i
        return f"{lo_i}%" if lo_i == hi_i else f"{lo_i}\u2013{hi_i}%"

    # ── Focal entity ──────────────────────────────────────────────────────
    focal_id = ""
    focal_number = ""
    for _, edata in (result.resolved_entities or {}).items():
        if edata:
            focal_id     = edata.get("canonical_name", "")
            focal_number = edata.get("company_number", "")
            break
    if not focal_id:
        focal_id = result.query or "Entity"

    focal_ctx = f"Company No. {focal_number}" if focal_number else "Investigated entity"
    add_node(focal_id, _short(focal_id, 24), _GRAPH_COLOR_FOCAL, size=34,
             full_name=focal_id, node_type="Focal Company",
             context=focal_ctx, border_width=3)

    non_focal: int = 0
    ownership_found = False

    # ── Ownership paths from expand_ownership ─────────────────────────────
    for sr in (result.step_results or []):
        if sr.task != "expand_ownership" or not sr.success:
            continue
        eo    = (sr.findings or {}).get("expand_ownership") or {}
        paths = eo.get("paths") or []
        ubos  = eo.get("ultimate_owners") or []

        for row in paths:
            if non_focal >= _GRAPH_MAX_NODES:
                break
            if (row.get("path_depth") or 0) > _GRAPH_MAX_PATH_DEPTH:
                continue
            from_name = (row.get("from_name") or "").strip()
            to_name   = (row.get("to_name") or "").strip()
            if not from_name or not to_name:
                continue
            from_labels = row.get("from_labels") or []
            is_person   = "Person" in from_labels
            color       = _GRAPH_COLOR_PERSON if is_person else _GRAPH_COLOR_COMPANY
            node_type   = "Individual" if is_person else "Company"
            pct         = _pct_label(row.get("ownership_pct_min"), row.get("ownership_pct_max"))
            if from_name not in seen:
                non_focal += 1
            add_node(from_name, _short(from_name), color,
                     size=22 if is_person else 18,
                     full_name=from_name, node_type=node_type,
                     context=f"Ownership: {pct}" if pct else "Owner")
            add_edge(from_name, to_name, label=pct, color="#9CA3AF")
            ownership_found = True

        # UBOs not already captured via path rows
        for ubo in ubos:
            if non_focal >= _GRAPH_MAX_NODES:
                break
            name = (ubo.get("owner_name") or "").strip()
            if not name:
                continue
            pct = _pct_label(ubo.get("ownership_pct_min"), ubo.get("ownership_pct_max"))
            if name not in seen:
                non_focal += 1
            add_node(name, _short(name), _GRAPH_COLOR_PERSON, size=26,
                     full_name=name, node_type="Individual / Beneficial Owner",
                     context=f"Ownership: {pct}" if pct else "Beneficial owner")
            if not any(e.source == name and e.target == focal_id for e in edges):
                add_edge(name, focal_id, color="#34D399")
            ownership_found = True
        break  # only process the first expand_ownership step

    # ── Fallback: direct owners from company_profile ──────────────────────
    if not ownership_found:
        for sr in (result.step_results or []):
            if sr.task != "company_profile" or not sr.success:
                continue
            cp = (sr.findings or {}).get("company_profile") or {}
            for owner in (cp.get("direct_owners") or []):
                if non_focal >= _GRAPH_MAX_NODES:
                    break
                name = (owner.get("owner_name") or "").strip()
                if not name:
                    continue
                labels    = owner.get("owner_labels") or []
                is_person = "Person" in labels
                color     = _GRAPH_COLOR_PERSON if is_person else _GRAPH_COLOR_COMPANY
                node_type = "Individual" if is_person else "Company"
                pct       = _pct_label(owner.get("ownership_pct_min"), owner.get("ownership_pct_max"))
                if name not in seen:
                    non_focal += 1
                add_node(name, _short(name), color, size=20,
                         full_name=name, node_type=node_type,
                         context=f"Ownership: {pct}" if pct else "Direct owner")
                add_edge(name, focal_id, label=pct, color="#9CA3AF")
            break

    # ── Address node from company_profile ─────────────────────────────────
    for sr in (result.step_results or []):
        if sr.task != "company_profile" or not sr.success:
            continue
        cp      = (sr.findings or {}).get("company_profile") or {}
        address = cp.get("address") or {}
        if address and non_focal < _GRAPH_MAX_NODES:
            postal     = (address.get("postal_code") or "").strip()
            town       = (address.get("post_town") or "").strip()
            addr_label = postal or town or "Address"
            full_addr  = ", ".join(filter(None, [
                address.get("address_line_1", ""),
                town,
                postal,
            ]))
            addr_id = f"__addr__{focal_id}"
            if addr_id not in seen:
                non_focal += 1
            add_node(addr_id, addr_label, _GRAPH_COLOR_ADDRESS, size=14,
                     full_name=full_addr or addr_label,
                     node_type="Registered Address",
                     context=full_addr or addr_label)
            add_edge(focal_id, addr_id, label="at", color="#F59E0B")
        break

    return nodes, edges, node_meta


# ===========================================================================
# STRUCTURED ASSESSMENT — decision-first rendering
# ===========================================================================

_DIM_TASK_MAP: dict[str, str] = {
    "ownership": "ownership_complexity_check",
    "control":   "control_signal_check",
    "address":   "address_risk_check",
    "industry":  "industry_context_check",
}
_TASK_DIM_MAP: dict[str, str] = {v: k for k, v in _DIM_TASK_MAP.items()}

_DIM_DISPLAY_LABELS: dict[str, str] = {
    "ownership": "Ownership Complexity",
    "control":   "Control Concerns",
    "address":   "Address Concentration",
    "industry":  "Industry Risk",
}

# Priority order for picking primary driver when risk levels tie
_DIM_PRIORITY = ["ownership", "control", "address", "industry"]


def _get_all_risk_findings(result: Any) -> dict[str, dict]:
    """Return {task_name: findings_dict} for all risk tasks that ran."""
    out: dict[str, dict] = {}
    for sr in (result.step_results or []):
        if not sr.success or not sr.findings:
            continue
        if sr.task == "summarize_risk_for_company":
            for task in _RISK_TASKS:
                data = sr.findings.get(task)
                if isinstance(data, dict):
                    out[task] = data
        elif sr.task in _RISK_TASKS:
            data = sr.findings.get(sr.task)
            if isinstance(data, dict):
                out[sr.task] = data
    return out


def _format_risk_driver_text(task: str, findings: dict, company_name: str) -> str:
    """1-2 sentence explanation of a risk driver, derived from structured findings."""
    name = company_name or "This company"
    if task == "address_risk_check":
        total = findings.get("co_located_total", 0)
        rate  = findings.get("dissolution_rate", 0.0)
        rate_pct = round(rate * 100)
        if total > 0:
            text = f"{name} is registered at an address shared with {total} other entities"
            if rate_pct > 10:
                text += f", {rate_pct}% of which are dissolved"
            text += "."
            if total > 30:
                text += " This is consistent with a formation-agent or registered-office provider."
            return text
        return "The registered address shows no significant co-location patterns."

    if task == "ownership_complexity_check":
        depth     = findings.get("max_chain_depth", 0)
        has_ubos  = findings.get("has_individual_ubos", False)
        corp_only = findings.get("corporate_chain_only", False)
        ubo_count = findings.get("ubo_count", 0)
        if corp_only:
            return (f"{name} has no identified natural-person beneficial owner — "
                    "the full ownership chain consists of corporate entities only.")
        if depth >= 4:
            text = f"{name} has a complex ownership chain spanning {depth} hops"
            if not has_ubos:
                text += " with no natural-person UBO identified"
            return text + "."
        if depth >= 2:
            text = f"{name} has a {depth}-hop ownership chain"
            if ubo_count > 0:
                s = "s" if ubo_count != 1 else ""
                text += f" with {ubo_count} beneficial owner{s} identified"
            return text + "."
        return f"{name} has a shallow, standard ownership structure."

    if task == "control_signal_check":
        elevated = findings.get("elevated_control_types", [])
        if elevated:
            types_str = "; ".join(
                str(e).replace("-", " ").replace("_", " ") for e in elevated[:2]
            )
            return f"{name} shows elevated PSC control signals: {types_str}."
        if findings.get("mixed_control"):
            return f"{name} shows mixed control arrangements beyond standard share ownership."
        return f"{name} shows no elevated control signals beyond standard share ownership."

    if task == "industry_context_check":
        high      = findings.get("high_scrutiny_sic_codes", [])
        is_hold   = findings.get("is_holding_structure", False)
        peer_rate = findings.get("peer_dissolution_rate", 0.0)
        if high:
            codes  = ", ".join(str(c.get("sic_code", "")) for c in high[:2] if c.get("sic_code"))
            reason = high[0].get("reason", "") if high else ""
            text   = f"{name} is classified under high-scrutiny SIC code(s): {codes}"
            if reason:
                text += f" ({reason})"
            return text + "."
        if is_hold:
            return (f"{name} is classified as a holding structure — "
                    "a category that warrants additional scrutiny.")
        if round(peer_rate * 100) > 30:
            return (f"{name}'s industry sector has a {round(peer_rate*100)}% "
                    "peer dissolution rate.")
        return f"{name}'s industry classification shows no high-scrutiny risk signals."

    return ""


def _build_secondary_signals(all_findings: dict, primary_task: str) -> list[str]:
    """Extract up to 3 material secondary signals (skipping the primary dimension)."""
    signals: list[str] = []

    addr = all_findings.get("address_risk_check", {})
    own  = all_findings.get("ownership_complexity_check", {})
    ctrl = all_findings.get("control_signal_check", {})
    ind  = all_findings.get("industry_context_check", {})

    if primary_task != "address_risk_check":
        total = addr.get("co_located_total", 0)
        if total > 10:
            signals.append(f"Registered address shared with {total} other entities")
        rate = addr.get("dissolution_rate", 0.0)
        if rate > 0.3 and total <= 10:
            signals.append(f"{round(rate*100)}% dissolution rate among address-linked entities")

    if primary_task != "ownership_complexity_check" and own:
        if not own.get("has_individual_ubos") and own.get("path_count", 1) > 0:
            signals.append("No natural-person beneficial owner identified")
        elif own.get("max_chain_depth", 0) >= 4:
            signals.append(f"Ownership chain spans {own['max_chain_depth']} hops")

    if primary_task != "control_signal_check":
        if ctrl.get("elevated_control_types"):
            signals.append("Elevated PSC control signals present")

    if primary_task != "industry_context_check":
        if ind.get("high_scrutiny_sic_codes"):
            signals.append("Classified under high-scrutiny industry sector")
        elif ind.get("peer_dissolution_rate", 0.0) > 0.4:
            signals.append(f"{round(ind['peer_dissolution_rate']*100)}% dissolution rate among industry peers")

    return signals[:3]


def _build_no_concerns(dims: dict, all_findings: dict) -> list[str]:
    """Return what was checked and found clear (LOW-rated dimensions only)."""
    concerns: list[str] = []
    own = all_findings.get("ownership_complexity_check", {})

    if dims.get("address") == "LOW":
        concerns.append("Registered address shows no co-location concerns")
    if dims.get("ownership") == "LOW":
        if own.get("has_individual_ubos"):
            concerns.append("Beneficial owner identified — ownership structure is transparent")
        else:
            concerns.append("Ownership structure appears standard")
    if dims.get("control") == "LOW":
        concerns.append("Control structure shows no elevated PSC signals")
    if dims.get("industry") == "LOW":
        concerns.append("Industry classification shows no high-scrutiny codes")
    return concerns


def _build_recommended_actions(dims: dict, all_findings: dict, overall_risk: str) -> list[str]:
    """Generate 2-3 concrete recommended actions based on the risk profile."""
    actions: list[str] = []
    addr = all_findings.get("address_risk_check", {})
    own  = all_findings.get("ownership_complexity_check", {})
    ctrl = all_findings.get("control_signal_check", {})

    if dims.get("address") in ("HIGH", "MEDIUM"):
        if addr.get("co_located_total", 0) > 20:
            actions.append("Check whether entity belongs to a known formation cluster")
        actions.append("Validate legitimacy of the registered address before onboarding")

    if dims.get("ownership") in ("HIGH", "MEDIUM"):
        if not (own or {}).get("has_individual_ubos"):
            actions.append("Request beneficial ownership documentation from the entity")
        elif (own or {}).get("max_chain_depth", 0) >= 4:
            actions.append("Map ownership chain to natural-person level before proceeding")

    if dims.get("control") in ("HIGH", "MEDIUM"):
        if ctrl.get("elevated_control_types"):
            actions.append("Obtain PSC register and verify stated control arrangements")

    if not actions:
        if overall_risk == "HIGH":
            actions.append("Conduct enhanced due diligence before any onboarding decision")
        elif overall_risk == "MEDIUM":
            actions.append("Apply standard enhanced checks before proceeding")
        else:
            actions.append("No immediate action required — standard monitoring applies")

    if overall_risk == "HIGH":
        edd = "Conduct enhanced due diligence before any onboarding decision"
        if edd not in actions:
            actions.insert(0, edd)

    return actions[:3]


def _build_structured_assessment(result: Any) -> dict:
    """Deterministically build a decision-first assessment from step findings.

    Returns a dict suitable for _render_decision_first_assessment.
    """
    all_findings = _get_all_risk_findings(result)
    dims         = _collect_risk_dims(result)
    overall_risk = _overall_risk_from_result(result) or "UNKNOWN"
    key          = overall_risk.upper()

    # Find primary dimension: highest risk, priority-ordered on tie
    primary_dim  = None
    primary_risk = "UNKNOWN"
    for dim in _DIM_PRIORITY:
        lvl = dims.get(dim, "NOT RUN")
        if _RISK_ORDER.get(lvl, -1) > _RISK_ORDER.get(primary_risk, -1):
            primary_risk = lvl
            primary_dim  = dim

    # Decision title
    any_material = any(v in ("HIGH", "MEDIUM") for v in dims.values())
    if key in ("LOW", "UNKNOWN") and not any_material:
        decision_title = "Low Risk — No Material Risk Signals"
    elif primary_dim and key in ("HIGH", "MEDIUM", "LOW"):
        level_word     = {"HIGH": "High Risk", "MEDIUM": "Moderate Risk", "LOW": "Low Risk"}[key]
        decision_title = f"{level_word} — {_DIM_DISPLAY_LABELS.get(primary_dim, primary_dim.title())}"
    elif key in ("HIGH", "MEDIUM", "LOW"):
        decision_title = {
            "HIGH":   "High Risk Identified",
            "MEDIUM": "Moderate Risk Identified",
            "LOW":    "Low Risk — Standard Profile",
        }[key]
    else:
        decision_title = "Investigation Complete"

    # Company name for narrative text
    company_name = ""
    for _, data in (result.resolved_entities or {}).items():
        if data:
            company_name = data.get("canonical_name", "")
            break
    if not company_name:
        company_name = result.query or ""

    # Primary driver text: deterministic from findings; fall back to final_answer
    primary_task = _DIM_TASK_MAP.get(primary_dim or "", "")
    if primary_task and primary_task in all_findings:
        primary_driver_text = _format_risk_driver_text(
            primary_task, all_findings[primary_task], company_name
        )
    else:
        primary_driver_text = _first_sentences(result.final_answer or "", 2)

    return {
        "overall_risk":          key,
        "decision_title":        decision_title,
        "primary_driver_label":  _DIM_DISPLAY_LABELS.get(primary_dim or "", ""),
        "primary_driver_text":   primary_driver_text,
        "secondary_signals":     _build_secondary_signals(all_findings, primary_task),
        "no_immediate_concerns": _build_no_concerns(dims, all_findings),
        "recommended_actions":   _build_recommended_actions(dims, all_findings, key),
    }


def _render_decision_first_assessment(assessment: dict) -> None:
    """Decision-first assessment card: title → driver → signals → concerns → actions."""
    risk   = assessment["overall_risk"]
    tc, bg, border = _RISK_COLORS.get(risk, _RISK_COLORS["UNKNOWN"])

    # Neutral styling for UNKNOWN so it never looks alarming
    if risk == "UNKNOWN":
        tc, bg, border = "#64748B", "#F8FAFC", "#E2E8F0"

    title           = assessment["decision_title"]
    primary_label   = assessment["primary_driver_label"]
    primary_text    = assessment["primary_driver_text"]
    secondary       = assessment["secondary_signals"]
    no_concerns     = assessment["no_immediate_concerns"]
    actions         = assessment["recommended_actions"]

    def _subsection(label: str) -> str:
        return (
            f'<div style="font-size:0.62em;font-weight:700;color:#6B7280;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin:12px 0 5px 0">'
            f'{_esc(label)}</div>'
        )

    def _bullet(text: str, color: str, icon: str) -> str:
        return (
            f'<div style="display:flex;gap:7px;margin:3px 0">'
            f'<span style="color:{color};flex-shrink:0;font-size:0.84em;'
            f'line-height:1.55">{icon}</span>'
            f'<span style="font-size:0.84em;color:#374151;line-height:1.55">'
            f'{_esc(text)}</span></div>'
        )

    # Primary driver section
    driver_html = ""
    if primary_text:
        driver_lbl  = primary_label or "Primary Risk Driver"
        driver_html = (
            _subsection(driver_lbl)
            + f'<div style="color:#374151;font-size:0.87em;line-height:1.6;'
            f'border-left:3px solid {border};padding:4px 0 4px 10px">'
            f'{_esc(primary_text)}</div>'
        )

    # Secondary signals
    secondary_html = ""
    if secondary:
        items = "".join(_bullet(s, "#9CA3AF", "·") for s in secondary)
        secondary_html = _subsection("Secondary Signals") + items

    # No immediate concerns
    concerns_html = ""
    if no_concerns:
        items = "".join(_bullet(c, "#16A34A", "✔") for c in no_concerns)
        concerns_html = _subsection("No Immediate Concerns") + items

    # Recommended actions
    actions_html = ""
    if actions:
        items = "".join(_bullet(a, "#1D4ED8", "→") for a in actions)
        actions_html = _subsection("Recommended Actions") + items

    badge = _risk_badge(risk) if risk and risk != "UNKNOWN" else ""

    st.markdown(
        f'<div style="background:{bg};border:1px solid {border};'
        f'border-left:5px solid {tc};border-radius:8px;'
        f'padding:16px 20px;margin:4px 0 12px 0">'
        # Title row with risk badge
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;'
        f'gap:10px;margin-bottom:2px">'
        f'<div style="font-size:1.0em;font-weight:800;color:{tc};line-height:1.3">'
        f'{_esc(title)}</div>'
        f'{badge}</div>'
        f'{driver_html}{secondary_html}{concerns_html}{actions_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _build_replay_assessment(replay_data: dict) -> dict:
    """Build a structured assessment dict from replay trace data.

    Uses the same logic as ``_build_structured_assessment`` by reading the
    full per-task findings from trace event data_json fields.
    """
    dims         = _extract_replay_risk_dimensions(replay_data)
    all_findings = _extract_replay_all_findings(replay_data)
    summary      = (replay_data.get("final_summary") or "").strip()
    query        = replay_data.get("query", "")

    # Overall risk = highest rated dimension
    key = "UNKNOWN"
    for v in dims.values():
        if _RISK_ORDER.get(v, -1) > _RISK_ORDER.get(key, -1):
            key = v

    # Primary dimension — same priority order as _build_structured_assessment
    primary_dim  = None
    primary_risk = "UNKNOWN"
    for dim in _DIM_PRIORITY:
        lvl = dims.get(dim, "NOT RUN")
        if _RISK_ORDER.get(lvl, -1) > _RISK_ORDER.get(primary_risk, -1):
            primary_risk = lvl
            primary_dim  = dim

    # Decision title — same logic as _build_structured_assessment
    any_material = any(v in ("HIGH", "MEDIUM") for v in dims.values())
    if key in ("LOW", "UNKNOWN") and not any_material:
        decision_title = "Low Risk — No Material Risk Signals"
    elif primary_dim and key in ("HIGH", "MEDIUM", "LOW"):
        level_word     = {"HIGH": "High Risk", "MEDIUM": "Moderate Risk", "LOW": "Low Risk"}[key]
        decision_title = f"{level_word} — {_DIM_DISPLAY_LABELS.get(primary_dim, primary_dim.title())}"
    elif key in ("HIGH", "MEDIUM", "LOW"):
        decision_title = {
            "HIGH":   "High Risk Identified",
            "MEDIUM": "Moderate Risk Identified",
            "LOW":    "Low Risk — Standard Profile",
        }[key]
    else:
        decision_title = "Investigation Complete"

    # Primary driver text — from findings; fall back to final_summary sentences
    primary_task = _DIM_TASK_MAP.get(primary_dim or "", "")
    if primary_task and primary_task in all_findings:
        primary_driver_text = _format_risk_driver_text(
            primary_task, all_findings[primary_task], query
        )
    else:
        primary_driver_text = _first_sentences(summary, 2) if summary else "—"

    return {
        "overall_risk":          key,
        "decision_title":        decision_title,
        "primary_driver_label":  _DIM_DISPLAY_LABELS.get(primary_dim or "", ""),
        "primary_driver_text":   primary_driver_text,
        "secondary_signals":     _build_secondary_signals(all_findings, primary_task),
        "no_immediate_concerns": _build_no_concerns(dims, all_findings),
        "recommended_actions":   _build_recommended_actions(dims, all_findings, key),
    }


def _chip_click(prompt: str) -> None:
    """on_click callback for quick-prompt chips — populates the textarea."""
    st.session_state["_input_question"] = prompt
    state.set_question(prompt)


def _get_company_for_chips() -> str:
    """Best-guess company name to use in chip prompt templates."""
    result = state.get_result()
    if result and result.resolved_entities:
        for _, data in result.resolved_entities.items():
            if data:
                return data.get("canonical_name", "")
    for _, data in state.get_live_entities().items():
        if data:
            return data.get("canonical_name", "")
    return ""


def _confirm_entity_click(sorted_candidates: list) -> None:
    """on_click callback for 'Continue with selected entity' button.

    Puts the confirmed candidate into the entity confirmation queue so the
    blocked orchestrator thread can resume, then resets the selection state.
    """
    idx = st.session_state.get("_entity_selection_idx", 0) or 0
    if 0 <= idx < len(sorted_candidates):
        confirmed = sorted_candidates[idx]
        confirm_q = st.session_state.get("entity_confirm_queue")
        if confirm_q is not None:
            try:
                confirm_q.put_nowait(confirmed)
            except Exception:  # noqa: BLE001
                pass
    # Clear modal state; let thread emit entity_resolved which advances phase
    st.session_state["live_entity_candidates"] = []
    st.session_state["live_entity_name"] = ""
    state.set_live_phase("resolving")


def _cancel_entity_click() -> None:
    """on_click callback for entity selection 'Cancel' — resets to idle."""
    confirm_q = st.session_state.get("entity_confirm_queue")
    if confirm_q is not None:
        try:
            confirm_q.put_nowait(None)
        except Exception:  # noqa: BLE001
            pass
    state.reset_live_state()
    state.set_live_phase("idle")
    st.session_state["run_queue"] = None  # discard stale run events


def _render_entity_selection_modal(candidates: list, entity_name: str) -> None:
    """Blocking entity selection panel — shown when multiple matches are found.

    The investigation is paused until the user selects an entity and clicks
    'Continue'.  Sorted Active-first, then by match score (preserved from
    resolve_entity ordering which is already score-DESC).
    """
    def _pct(c: dict) -> int:
        return _name_similarity(entity_name, c.get("name") or "")

    sorted_candidates = sorted(candidates, key=lambda c: -_pct(c))

    st.markdown(
        f'<div style="background:#FFFBEB;border:1px solid #FDE68A;'
        f'border-left:5px solid #D97706;border-radius:8px;'
        f'padding:14px 18px;margin:8px 0 12px 0">'
        f'<div style="font-size:0.72em;font-weight:700;color:#D97706;'
        f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">'
        f'Entity selection required</div>'
        f'<div style="font-size:0.88em;font-weight:700;color:#78350F;margin-bottom:2px">'
        f'Multiple companies match &ldquo;{_esc(entity_name)}&rdquo;</div>'
        f'<div style="font-size:0.80em;color:#92400E">'
        f'Choose the correct entity to proceed.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    selected_idx = st.radio(
        "Select entity",
        options=list(range(len(sorted_candidates))),
        format_func=lambda i: (
            f"{sorted_candidates[i].get('name', '?')}  ·  "
            f"No. {sorted_candidates[i].get('company_number', '?')}  ·  "
            f"{sorted_candidates[i].get('status', 'Unknown')}  ·  "
            f"{_pct(sorted_candidates[i])}% match"
        ),
        label_visibility="collapsed",
        key="_entity_selection_idx",
    )

    # Detail card for the highlighted selection
    if selected_idx is not None and 0 <= selected_idx < len(sorted_candidates):
        c = sorted_candidates[selected_idx]
        cname  = (c.get("name") or "").upper()
        cno    = c.get("company_number") or ""
        cstatus = c.get("status") or ""
        exact  = (c.get("name") or "").lower() == entity_name.lower()
        confidence = "High — exact match" if exact else "Closest match"

        def _meta_row(label: str, value: str, last: bool = False) -> str:
            border = "" if last else "border-bottom:1px solid #FEF3C7;"
            return (
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;{border}">'
                f'<span style="font-size:0.78em;color:#D97706">{_esc(label)}</span>'
                f'<span style="font-size:0.78em;font-weight:600;color:#78350F">{_esc(value)}</span>'
                f'</div>'
            )

        rows = ""
        if cno:
            rows += _meta_row("Company No.", cno)
        if cstatus:
            rows += _meta_row("Status", cstatus)
        rows += _meta_row("Match score", f"{_pct(c)}%")
        rows += _meta_row("Jurisdiction", "UK")
        rows += _meta_row("Match confidence", confidence, last=True)

        st.markdown(
            f'<div style="background:#FFFBEB;border:1px solid #FDE68A;'
            f'border-left:4px solid #D97706;border-radius:6px;'
            f'padding:10px 14px;margin:4px 0 10px 0">'
            f'<div style="font-size:0.62em;font-weight:700;color:#D97706;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:5px">'
            f'Selected Entity</div>'
            f'<div style="font-size:0.94em;color:#78350F;font-weight:800;'
            f'margin-bottom:7px">{_esc(cname)}</div>'
            f'{rows}'
            f'</div>',
            unsafe_allow_html=True,
        )

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        st.button(
            "Continue with selected entity",
            type="primary",
            use_container_width=True,
            on_click=_confirm_entity_click,
            args=(sorted_candidates,),
            disabled=(selected_idx is None),
        )
    with btn_col2:
        st.button(
            "Cancel",
            use_container_width=True,
            on_click=_cancel_entity_click,
        )


# ===========================================================================
# INVESTIGATE TAB
# ===========================================================================


# Three-phase labels shown in the progress bar, mapping task groups → user-facing step
_PROGRESS_PHASE1 = frozenset({"entity_lookup", "company_profile"})
_PROGRESS_PHASE2 = frozenset({"expand_ownership", "sic_context", "shared_address_check"})
_PROGRESS_PHASE3 = frozenset({
    "ownership_complexity_check", "control_signal_check",
    "address_risk_check", "industry_context_check", "summarize_risk_for_company",
})


def _render_progress_section() -> None:
    """Thin progress bar at the top of the Investigate tab during a run.

    Maps the investigation lifecycle to 3 user-friendly phases:
        Step 1/3 — Identifying entity
        Step 2/3 — Mapping ownership
        Step 3/3 — Assessing risk
    Hidden when idle or done.
    """
    phase = state.get_live_phase()
    if phase not in ("planning", "resolving", "executing"):
        return

    live_cur     = state.get_live_current_step()
    current_task = (live_cur or {}).get("task", "") if live_cur else ""

    if phase in ("planning", "resolving") or current_task in _PROGRESS_PHASE1:
        pct  = 0.12
        text = "Step 1/3 — Identifying entity"
    elif current_task in _PROGRESS_PHASE2:
        pct  = 0.45
        text = "Step 2/3 — Mapping ownership"
    elif current_task in _PROGRESS_PHASE3:
        pct  = 0.78
        text = "Step 3/3 — Assessing risk"
    else:
        # Fallback: use raw step counters if task doesn't map to a known phase
        num   = state.get_live_step_num()
        total = state.get_live_step_total()
        pct   = (num / total) if num and total else 0.12
        text  = f"Step {num}/{total}" if num and total else "Running…"

    st.progress(pct, text=text)
    st.markdown('<div style="margin-bottom:4px"></div>', unsafe_allow_html=True)


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
    """Col 1 of the Investigate tab: question input, chips, entity card, risk assessment."""
    _section_header(
        "🔍 Company Risk Investigator",
        "Investigate ownership, control, and risk signals for a UK company",
    )

    question = st.text_area(
        label="Question",
        label_visibility="collapsed",
        value=state.get_question(),
        height=100,
        placeholder=(
            "e.g. Who owns Vodafone 2 and are there any ownership, "
            "control, or address risks?"
        ),
        key="_input_question",
    )

    # Quick-prompt chips — 2-row layout prevents overflow
    company = _get_company_for_chips()
    _c = f" {company}" if company else " [COMPANY]"
    _chip_defs = [
        ("Ownership",    f"Who owns{_c}?"),
        ("Address",      f"Does{_c} show any address-related risk signals?"),
        ("Control",      f"Does{_c} show any control-related risk signals?"),
        ("Industry",     f"Does{_c} show any industry-related risk signals?"),
        ("Full Analysis", f"Who owns{_c} and are there any risks?"),
    ]
    _chip_row1 = st.columns(4)
    for col, (label, prompt) in zip(_chip_row1, _chip_defs[:4]):
        col.button(
            label,
            use_container_width=True,
            key=f"_chip_{label.replace(' ', '_')}",
            on_click=_chip_click,
            args=(prompt,),
        )
    st.button(
        "Full analysis",
        use_container_width=True,
        key="_chip_Full_analysis",
        on_click=_chip_click,
        args=(_chip_defs[4][1],),
    )

    live_phase = state.get_live_phase()
    _running   = live_phase in ("planning", "resolving", "selecting", "executing")
    _btn_label = "Running…" if _running else "Run Risk Analysis"
    submitted  = st.button(
        _btn_label,
        type="primary",
        use_container_width=True,
        disabled=_running,
    )
    if submitted and question.strip() and not _running:
        state.set_question(question.strip())
        state.reset_all_run_state()
        st.session_state["_trigger_run"] = True
        st.rerun()

    # Entity selection modal — blocking until user confirms (phase == "selecting")
    if live_phase == "selecting":
        candidates  = state.get_live_candidates()
        entity_name = state.get_live_entity_name()
        if candidates:
            _render_entity_selection_modal(candidates, entity_name)
            st.divider()
            _render_live_risk_assessment(live_dims)
            return

    # Entity card — shown as soon as entity is resolved (before full result)
    live_entities = state.get_live_entities()
    if live_entities:
        _render_resolved_entity_banner(live_entities)

    st.divider()
    _render_live_risk_assessment(live_dims)


def _render_live_risk_assessment(live_dims: dict) -> None:
    """Risk Assessment for the Investigate tab — staged progressive rendering.

    1. idle             → skeleton card (no pending rows)
    2. planning         → execution progress list + skeleton card
    3. resolving        → execution progress list + skeleton card
    4. executing        → execution progress list + skeleton + partial signals
    5. done / success   → decision-first assessment card
    6. done / failed    → error card
    """
    _section_header("📊 Risk Assessment")

    live_phase = state.get_live_phase()
    result     = state.get_result()

    # ── Stages 1–4: no result yet ─────────────────────────────────────
    if result is None:
        if live_phase == "idle":
            _render_assessment_card_skeleton(
                "Run a risk analysis to see the assessment.",
                show_pending_rows=False,
            )
        else:
            _render_assessment_card_skeleton()
            # If any signals arrived (individual tasks mode), show them
            has_signals = any(
                v not in ("UNKNOWN", "NOT RUN") for v in live_dims.values()
            )
            if has_signals:
                _label_row("Risk Signals (in progress)")
                _render_risk_drivers_grid(live_dims)
        return

    # ── Stage 5–6: result ready ────────────────────────────────────────
    if result.success:
        assessment = _build_structured_assessment(result)
        _render_decision_first_assessment(assessment)
    else:
        answer = result.final_answer or "The investigation encountered an error."
        _render_assessment_card(
            "Investigation Failed", "🔴", None, answer,
            "#B91C1C", "#FEF2F2", "#FECACA",
        )

    if not result.success and result.errors:
        for e in result.errors:
            st.error(e)

    if result.warnings:
        with st.expander(f"⚠️ {len(result.warnings)} warning(s)", expanded=False):
            for w in result.warnings:
                st.warning(w)

    # Compact entity chip row (after run; the full entity card shows during run)
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
    """Col 2 of the Investigate tab: hierarchical interactive ownership graph when
    done; live step checklist during execution."""
    _section_header("🕸️ Context Graph", "Entity ownership and relationship map")

    live_phase    = state.get_live_phase()
    live_entities = state.get_live_entities()
    live_plan     = state.get_live_plan()
    result        = state.get_result()

    # Planning: nothing useful yet
    if live_phase == "planning":
        st.markdown(
            '<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
            'border-radius:8px;padding:40px 20px;text-align:center;'
            'color:#94A3B8;font-size:0.85em">'
            'Generating investigation plan…'
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

    # Show live step checklist while executing
    if live_phase == "executing" and live_plan:
        _render_live_step_checklist()
        return

    # Done: render interactive hierarchical graph
    if result is not None and result.resolved_entities:
        # Clear node selection when a new investigation result arrives
        trace_key = getattr(result, "trace_id", None) or id(result)
        if st.session_state.get("_graph_result_trace") != trace_key:
            st.session_state["_graph_result_trace"] = trace_key
            st.session_state.pop("_graph_selected_node", None)

        node_meta: dict = {}
        try:
            from streamlit_agraph import Config, agraph

            nodes, edges, node_meta = _build_agraph_data(result)
            if nodes:
                config = Config(
                    height=560,
                    directed=True,
                    physics=False,
                    hierarchical=True,
                    **{
                        "layout": {
                            "hierarchical": {
                                "enabled":             True,
                                "direction":           "LR",
                                "sortMethod":          "directed",
                                "levelSeparation":     220,
                                "nodeSpacing":         130,
                                "treeSpacing":         150,
                                "blockShifting":       True,
                                "edgeMinimization":    True,
                                "parentCentralization": False,
                            }
                        },
                        "interaction": {
                            "hover":                True,
                            "tooltipDelay":         100,
                            "selectConnectedEdges": True,
                        },
                        "edges": {
                            "smooth":  {"enabled": False},
                            "arrows":  {"to": {"enabled": True, "scaleFactor": 0.7}},
                            "font":    {"size": 10, "align": "middle",
                                        "strokeWidth": 2, "strokeColor": "#F8FAFC"},
                        },
                        "nodes": {
                            "font": {"size": 13},
                        },
                    },
                )
                raw_selection = agraph(nodes=nodes, edges=edges, config=config)
                # Persist the last non-None selection across reruns
                if raw_selection is not None:
                    st.session_state["_graph_selected_node"] = raw_selection
            else:
                st.caption("No graph data available for this entity.")
        except Exception:
            st.caption("Graph could not be rendered.")

        # Compact colour legend (matches actual node fill colours)
        legend_html = (
            f'<span style="margin-right:12px;font-size:0.73em;color:#6B7280">'
            f'<span style="color:{_LEGEND_FOCAL}">■</span> Focal entity</span>'
            f'<span style="margin-right:12px;font-size:0.73em;color:#6B7280">'
            f'<span style="color:{_LEGEND_COMPANY}">■</span> Company</span>'
            f'<span style="margin-right:12px;font-size:0.73em;color:#6B7280">'
            f'<span style="color:{_LEGEND_PERSON}">■</span> Individual / UBO</span>'
            f'<span style="font-size:0.73em;color:#6B7280">'
            f'<span style="color:{_LEGEND_ADDRESS}">■</span> Address</span>'
        )
        st.markdown(f'<div style="margin:4px 0 10px">{legend_html}</div>',
                    unsafe_allow_html=True)

        # Selected node detail panel (shown only after a node is clicked)
        selected_id = st.session_state.get("_graph_selected_node")
        if selected_id and selected_id in node_meta:
            meta = node_meta[selected_id]
            _label_row("Selected Node")
            with st.container(border=True):
                st.markdown(
                    f'<div style="font-weight:600;font-size:0.9em;color:#111827;'
                    f'margin-bottom:2px">{_esc(meta["full_name"])}</div>',
                    unsafe_allow_html=True,
                )
                st.caption(meta["type"])
                if meta.get("context"):
                    st.caption(meta["context"])

        # Graph Insights — derived from ownership analysis
        insights = _extract_graph_insights(result)
        _label_row("Graph Insights")
        gi_rows = (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:5px 0;border-bottom:1px solid #F3F4F6">'
            f'<span style="font-size:0.82em;color:#6B7280">Ownership Depth</span>'
            f'<span style="font-size:0.82em;font-weight:600;color:#111827">'
            f'{_esc(insights["ownership_depth"])}</span></div>'
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:5px 0;border-bottom:1px solid #F3F4F6">'
            f'<span style="font-size:0.82em;color:#6B7280">Beneficial Owner Identified</span>'
            f'<span style="font-size:0.82em;font-weight:600;color:#111827">'
            f'{_esc(insights["beneficial_owner"])}</span></div>'
            f'<div style="display:flex;justify-content:space-between;padding:5px 0">'
            f'<span style="font-size:0.82em;color:#6B7280">Structure Complexity</span>'
            f'<span style="font-size:0.82em;font-weight:600;color:#111827">'
            f'{_esc(insights["structure_complexity"])}</span></div>'
        )
        st.markdown(
            f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
            f'border-radius:8px;padding:10px 14px;margin:6px 0">'
            f'{gi_rows}</div>',
            unsafe_allow_html=True,
        )
        return

    if live_phase == "idle" and result is None:
        st.markdown(
            '<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
            'border-radius:8px;padding:40px 20px;text-align:center;'
            'color:#94A3B8;font-size:0.85em">'
            'Entity graph will appear here after an investigation.'
            '</div>',
            unsafe_allow_html=True,
        )


def _render_insights_column(live_dims: dict) -> None:
    """Col 3 of the Investigate tab: Assessment panel.

    Structure
    ---------
    A. Assessment (top)
       - Outcome badge
       - Key Risk Drivers (directly below outcome)
       - Reasoning summary
    B. Details
       - Steps completed / agents
       - Trace ID (copy button)
    C. Expander
       - "How this was assessed"

    During execution: shows investigation type + live risk signal list.
    """
    _section_header("⚡ Assessment", "Outcome and risk factor breakdown")

    live_phase = state.get_live_phase()
    result     = state.get_result()
    live_plan  = state.get_live_plan()
    plan       = (result.planner_output if result is not None else None) or live_plan

    # ── Idle, no data ──────────────────────────────────────────────────
    if live_phase == "idle" and result is None:
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:10px 0">'
            'Assessment details will appear here after a run.'
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
                icon, c_icon   = "✔", "#16A34A"
                badge = (
                    f'<span style="background:{bg};color:{tc};border:1px solid {border};'
                    f'border-radius:4px;padding:1px 8px;font-size:0.76em;font-weight:700">'
                    f'{_esc(risk)}</span>'
                )
            elif task_key == current_task:
                icon, c_icon = "›", "#2563EB"
                badge = '<span style="color:#2563EB;font-size:0.76em;font-style:italic">Computing…</span>'
            else:
                icon, c_icon = "·", "#9CA3AF"
                badge = '<span style="color:#9CA3AF;font-size:0.76em">Pending</span>'
            signal_rows += (
                f'<div style="display:flex;align-items:center;justify-content:space-between;'
                f'padding:6px 0;border-bottom:1px solid #F3F4F6">'
                f'<span style="font-size:0.83em;color:{c_icon};font-weight:500">'
                f'{icon} {_esc(label)}</span>{badge}</div>'
            )
        if signal_rows:
            st.markdown(
                f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
                f'border-radius:8px;padding:10px 14px;margin:4px 0">'
                f'{signal_rows}</div>',
                unsafe_allow_html=True,
            )

    # ── Full result ────────────────────────────────────────────────────
    elif result is not None:

        # A. Outcome badge
        outcome_color = "#16A34A" if result.success else "#DC2626"
        outcome_text  = "✓ Completed" if result.success else "✗ Failed"
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0 10px 0">'
            f'<span style="font-size:0.66em;font-weight:700;color:#6B7280;'
            f'text-transform:uppercase;letter-spacing:0.06em">Outcome</span>'
            f'<span style="background:{outcome_color}18;color:{outcome_color};'
            f'border:1px solid {outcome_color}40;border-radius:6px;'
            f'padding:2px 10px;font-size:0.80em;font-weight:700">'
            f'{_esc(outcome_text)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # A. Key Risk Drivers — directly below outcome
        dims = _collect_risk_dims(result)
        if any(v in ("HIGH", "MEDIUM", "LOW") for v in dims.values()):
            _label_row("Key Risk Drivers")
            _render_risk_drivers_grid(dims)

        # A. Reasoning summary
        if plan:
            reason = plan.get("reason", "")
            if reason:
                _label_row("Assessment Summary")
                st.markdown(
                    f'<div style="font-size:0.84em;color:#374151;'
                    f'border-left:3px solid #BFDBFE;padding:5px 0 5px 10px;'
                    f'margin:0 0 10px 0;line-height:1.55">'
                    f'{_esc(reason)}</div>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # B. Details
        steps      = result.step_results or []
        n_done     = sum(1 for s in steps if s.status == "success")
        n_total    = len(steps)
        agents_run = sorted({
            _AGENT_LABELS.get(s.agent, s.agent)
            for s in steps if s.status == "success"
        })

        _label_row("Details")
        st.metric("Steps", f"{n_done}/{n_total}")
        for s in steps:
            icon  = "✓" if s.status == "success" else "✗"
            color = "#16A34A" if s.status == "success" else "#DC2626"
            st.markdown(
                f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
                f'border-radius:6px;padding:6px 10px;margin:3px 0;'
                f'display:flex;justify-content:space-between;align-items:center">'
                f'<div style="display:flex;align-items:center;gap:8px">'
                f'<span style="color:{color};font-size:0.70em">●</span>'
                f'<span style="font-size:0.82em;color:#1F2937;font-weight:500">'
                f'{_esc(_task_label(s.task))}</span>'
                f'</div>'
                f'<span style="font-size:0.72em;background:#EFF6FF;color:#1D4ED8;'
                f'border:1px solid #BFDBFE;border-radius:8px;padding:1px 8px;'
                f'white-space:nowrap">'
                f'{_esc(_agent_display(s.agent))}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        if agents_run:
            st.markdown(
                f'<div style="font-size:0.78em;color:#374151;margin:6px 0 6px 0">'
                f'<span style="color:#6B7280">Agents:</span> '
                f'{_esc(", ".join(agents_run))}</div>',
                unsafe_allow_html=True,
            )

        # B. Trace ID
        trace_id = result.trace_id
        if trace_id:
            _st_components.html(
                f"""
                <div style="display:flex;align-items:center;gap:6px;padding:4px 0 10px 2px;
                            font-size:11.5px;color:#9CA3AF;font-family:monospace">
                  <span style="font-family:sans-serif;font-weight:600;letter-spacing:.04em;
                               font-size:10px;color:#6B7280">TRACE ID</span>
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
                height=38,
            )

        if result.warnings:
            with st.expander(f"⚠️ {len(result.warnings)} warning(s)", expanded=False):
                for w in result.warnings:
                    st.warning(w)

    # ── C. How this was assessed ───────────────────────────────────────
    if result is not None or live_plan is not None:
        st.markdown('<div style="margin-top:10px"></div>', unsafe_allow_html=True)
        with st.expander("🔍 How this was assessed", expanded=False):
            _render_analysis_expander()


def _render_analysis_expander() -> None:
    """Content for the 'How this was assessed' expander.

    Shows investigation plan and step-by-step audit trail.
    Rendered at the bottom of the Assessment column, always collapsed.
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

    # ── Audit Trail ─────────────────────────────────────────────────────
    _section_header("📋 Audit Trail", "Step-by-step record of how the analysis was performed")

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
            'Steps will appear as they complete…</div>',
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



# ===========================================================================
# REPLAY / AUDIT TAB
# ===========================================================================


def render_replay_tab(components: "AppComponents") -> None:
    """Render the Replay / Audit tab.

    Layout mirrors the Investigate tab exactly:
    [Col 1 — Replay loader + Assessment]  [Col 2 — Context Graph]  [Col 3 — Assessment panel]
    """
    col1, col2, col3 = st.columns([2, 2, 2])

    with col1:
        _render_replay_input_column(components)

    with col2:
        _render_replay_graph_column()

    with col3:
        _render_replay_insights_column()


def _render_replay_input_column(components: "AppComponents") -> None:
    """Col 1 of the Replay tab: trace loader + entity banner + assessment card.

    Reuses _render_resolved_entity_banner and _render_decision_first_assessment
    to keep identical structure to the Investigate tab.
    """
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()
    replay_error  = state.get_replay_error()

    _section_header("🔍 Company Risk Investigator", "Investigate ownership, control, and risk signals for a UK company")

    _loading = (replay_status == "loading")
    replay_id = st.text_input(
        label="Trace ID",
        label_visibility="collapsed",
        value=state.get_replay_trace_id() or "",
        placeholder="Enter a trace ID to load a past investigation…",
        key="_input_replay_trace_id",
        disabled=_loading,
    )

    if replay_status == "loaded" and replay_data:
        if st.button("Clear", type="primary", use_container_width=True):
            st.session_state["_clear_replay"] = True
    else:
        load_clicked = st.button(
            "Loading…" if _loading else "Load Replay",
            type="primary",
            use_container_width=True,
            disabled=_loading,
        )
        if load_clicked and replay_id.strip():
            state.set_replay_trace_id(replay_id.strip())
            st.session_state["_trigger_replay"] = True

    if replay_status == "loading":
        st.markdown(
            '<div style="color:#D97706;font-size:0.85em;padding:6px 0">'
            '⏳ &nbsp;Loading trace…</div>',
            unsafe_allow_html=True,
        )
    elif replay_status == "error" and replay_error:
        st.markdown(
            f'<div style="background:#FEF2F2;border:1px solid #FECACA;'
            f'border-left:4px solid #DC2626;border-radius:6px;'
            f'padding:10px 14px;margin:8px 0">'
            f'<div style="font-size:0.66em;font-weight:700;color:#DC2626;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:3px">'
            f'Failed to load</div>'
            f'<div style="font-size:0.87em;color:#7F1D1D">{_esc(replay_error)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    elif replay_status == "loaded" and replay_data:
        # Original question — secondary priority, shown as a compact card
        question = replay_data.get("question", "")
        if question:
            st.markdown(
                f'<div style="background:#EFF6FF;border:1px solid #BFDBFE;'
                f'border-left:3px solid #3B82F6;border-radius:6px;'
                f'padding:10px 14px;margin:8px 0">'
                f'<div style="font-size:0.66em;font-weight:700;color:#3B82F6;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">'
                f'Original Question</div>'
                f'<div style="font-size:0.88em;color:#1E3A8A;line-height:1.55;'
                f'font-style:italic">&ldquo;{_esc(question)}&rdquo;</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Identified entity — uses the same card as Investigate tab
        query = replay_data.get("query", "")
        if query:
            events_col1 = replay_data.get("events") or []
            entity_info = _extract_replay_entity(events_col1, query)
            _render_resolved_entity_banner({query: entity_info})

    st.divider()

    # Risk Assessment card — uses the same component as Investigate tab
    _section_header("📊 Risk Assessment")
    if replay_status == "idle":
        _render_assessment_card_skeleton("Load a trace to see the assessment.", show_pending_rows=False)
    elif replay_status == "loading":
        _render_assessment_card_skeleton("Loading investigation…")
    elif replay_status == "error":
        _render_assessment_card_skeleton("Could not load investigation.")
    elif replay_status == "loaded" and replay_data:
        has_summary = bool(replay_data.get("final_summary"))
        has_dims    = any(
            v in ("HIGH", "MEDIUM", "LOW")
            for v in _extract_replay_risk_dimensions(replay_data).values()
        )
        if has_summary or has_dims:
            assessment = _build_replay_assessment(replay_data)
            _render_decision_first_assessment(assessment)
        else:
            _render_assessment_card_skeleton("No summary recorded for this investigation.", show_pending_rows=False)


def _render_replay_graph_column() -> None:
    """Col 2 of the Replay tab: entity context panel.

    Mirrors _render_graph_column from the Investigate tab.
    """
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()

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

    if replay_status != "loaded" or not replay_data:
        st.markdown(
            '<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
            'border-radius:8px;padding:40px 20px;text-align:center;'
            'color:#94A3B8;font-size:0.85em">'
            'Load a trace to view the entity context.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Entity details box
    query = replay_data.get("query", "")
    events_col2 = replay_data.get("events") or []
    company_no_col2 = _extract_replay_company_number(events_col2)
    no_str_col2 = f". (No. {company_no_col2})" if company_no_col2 else ""
    _label_row("Entity Details")
    with st.container(border=True):
        st.markdown(
            f'<div style="font-weight:600;color:#111827;font-size:0.92em;'
            f'margin-bottom:4px">🔵 {_esc(query)}{_esc(no_str_col2)}</div>',
            unsafe_allow_html=True,
        )
        st.caption("loaded from trace")

    # Graph insights derived from events
    events  = replay_data.get("events") or []
    insights = _extract_replay_graph_insights(events)
    _label_row("Graph Insights")
    gi_rows = (
        f'<div style="display:flex;justify-content:space-between;'
        f'padding:5px 0;border-bottom:1px solid #F3F4F6">'
        f'<span style="font-size:0.82em;color:#6B7280">Ownership Depth</span>'
        f'<span style="font-size:0.82em;font-weight:600;color:#111827">'
        f'{_esc(insights["ownership_depth"])}</span></div>'
        f'<div style="display:flex;justify-content:space-between;'
        f'padding:5px 0;border-bottom:1px solid #F3F4F6">'
        f'<span style="font-size:0.82em;color:#6B7280">Beneficial Owner Identified</span>'
        f'<span style="font-size:0.82em;font-weight:600;color:#111827">'
        f'{_esc(insights["beneficial_owner"])}</span></div>'
        f'<div style="display:flex;justify-content:space-between;padding:5px 0">'
        f'<span style="font-size:0.82em;color:#6B7280">Structure Complexity</span>'
        f'<span style="font-size:0.82em;font-weight:600;color:#111827">'
        f'{_esc(insights["structure_complexity"])}</span></div>'
    )
    st.markdown(
        f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
        f'border-radius:8px;padding:10px 14px;margin:6px 0">'
        f'{gi_rows}</div>',
        unsafe_allow_html=True,
    )


def _render_replay_insights_column() -> None:
    """Col 3 of the Replay tab: assessment details panel.

    Mirrors _render_insights_column from the Investigate tab.
    """
    replay_status = state.get_replay_status()
    replay_data   = state.get_replay_data()

    _section_header("⚡ Assessment", "Outcome and risk factor breakdown")

    if replay_status != "loaded" or not replay_data:
        st.markdown(
            '<div style="color:#9CA3AF;font-size:0.85em;padding:10px 0">'
            'Assessment details will appear here after loading a trace.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    events       = replay_data.get("events") or []
    mode         = replay_data.get("mode", "")
    mode_display = _MODE_DISPLAY.get(mode, mode.title() if mode else "")
    trace_id     = replay_data.get("trace_id", "")

    # Investigation Type
    if mode_display:
        st.markdown(
            f'<div style="font-size:0.72em;font-weight:700;color:#6B7280;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">'
            f'Investigation Type</div>'
            f'<div style="font-size:0.88em;color:#1F2937;font-weight:600;'
            f'margin-bottom:10px">{_esc(mode_display)}</div>',
            unsafe_allow_html=True,
        )

    # Outcome badge
    st.markdown(
        '<div style="display:flex;align-items:center;gap:8px;margin:4px 0 10px 0">'
        '<span style="font-size:0.66em;font-weight:700;color:#6B7280;'
        'text-transform:uppercase;letter-spacing:0.06em">Outcome</span>'
        '<span style="background:#16A34A18;color:#16A34A;'
        'border:1px solid #16A34A40;border-radius:6px;'
        'padding:2px 10px;font-size:0.80em;font-weight:700">'
        '✓ Completed</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    replay_dims = _extract_replay_risk_dimensions(replay_data)

    # Key Risk Drivers
    if any(v in ("HIGH", "MEDIUM", "LOW") for v in replay_dims.values()):
        _label_row("Key Risk Drivers")
        _render_risk_drivers_grid(replay_dims)

    # Assessment Summary (plan reason)
    plan_reason = ""
    for ev in events:
        if ev.get("event_type") == "plan_created":
            raw = ev.get("input_summary", "") or ""
            m = _re.search(r"reason:\s*(.+)$", raw, _re.IGNORECASE | _re.DOTALL)
            if m:
                plan_reason = m.group(1).strip()
            break
    if plan_reason:
        _label_row("Assessment Summary")
        st.markdown(
            f'<div style="font-size:0.84em;color:#374151;'
            f'border-left:3px solid #BFDBFE;padding:5px 0 5px 10px;'
            f'margin:0 0 10px 0;line-height:1.55">'
            f'{_esc(plan_reason)}</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # Details
    _label_row("Details")
    replay_steps = _replay_plan_steps(events)
    n = len(replay_steps)
    st.metric("Steps", f"{n}/{n}")
    for s in replay_steps:
        color = "#16A34A" if s["success"] else "#DC2626"
        st.markdown(
            f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
            f'border-radius:6px;padding:6px 10px;margin:3px 0;'
            f'display:flex;justify-content:space-between;align-items:center">'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="color:{color};font-size:0.70em">●</span>'
            f'<span style="font-size:0.82em;color:#1F2937;font-weight:500">'
            f'{_esc(_task_label(s["task"]))}</span>'
            f'</div>'
            f'<span style="font-size:0.72em;background:#EFF6FF;color:#1D4ED8;'
            f'border:1px solid #BFDBFE;border-radius:8px;padding:1px 8px;'
            f'white-space:nowrap">'
            f'{_esc(_agent_display(s["agent"]))}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    agents_run = sorted({
        _AGENT_LABELS.get(ev.get("agent_name", ""), ev.get("agent_name", ""))
        for ev in events
        if ev.get("agent_name")
    } - {""})
    if agents_run:
        st.markdown(
            f'<div style="font-size:0.78em;color:#374151;margin:6px 0">'
            f'<span style="color:#6B7280">Agents:</span> '
            f'{_esc(", ".join(agents_run))}</div>',
            unsafe_allow_html=True,
        )

    # Trace ID with copy button
    if trace_id:
        _st_components.html(
            f"""
            <div style="display:flex;align-items:center;gap:6px;padding:4px 0 10px 2px;
                        font-size:11.5px;color:#9CA3AF;font-family:monospace">
              <span style="font-family:sans-serif;font-weight:600;letter-spacing:.04em;
                           font-size:10px;color:#6B7280">TRACE ID</span>
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
            height=38,
        )

    # How this was assessed expander
    st.markdown('<div style="margin-top:10px"></div>', unsafe_allow_html=True)
    with st.expander("🔍 How this was assessed", expanded=False):
        _render_replay_plan(replay_data)
        st.divider()
        _section_header(
            "📋 Audit Trail",
            "Step-by-step record of what was done during this investigation",
        )
        _render_replay_step_cards(events)
