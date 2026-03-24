"""
src.app.contextual_graph — Deterministic, evidence-driven context graph builder.

Replaces the single-intent model with multi-dimension extraction.  The graph is
built from the actual investigation result and risk findings, supplemented by
targeted Neo4j enrichment only when needed.

Public API
----------
GraphPayload
    Typed dataclass returned by build_contextual_graph_model and
    GraphCompositionService.compose.

extract_requested_dimensions(question)
    Returns an ordered list of the dimensions requested by the question.
    Returns ["generic_risk"] when no specific dimension keyword is found.

determine_primary_graph_driver(evidence, requested_dims)
    Returns the dimension that should drive visual emphasis.

collect_graph_evidence(step_results, risk_findings)
    Extracts structured per-dimension evidence from investigation step results.

enrich_graph_evidence_from_repo_if_needed(evidence, focal_id, dims, repo)
    Fills evidence gaps with scoped, targeted Neo4j queries.

build_contextual_graph_model(question, result, repo) -> GraphPayload
    Main entry point.  Returns a fully typed GraphPayload.

GraphCompositionService
    Stateful wrapper; holds the repo reference so callers need not pass it
    on every call.  Use .compose(question, result) -> GraphPayload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# GraphPayload — typed output contract
# ---------------------------------------------------------------------------


@dataclass
class GraphPayload:
    """Fully typed output from graph composition.

    Attributes
    ----------
    view_label
        Human-readable label such as "Ownership + Address" built from
        *rendered* dimensions (not requested ones).
    primary_driver
        The single dimension that drives visual emphasis and edge colouring.
    requested_dimensions
        Dimensions extracted from the user question (may include
        "generic_risk").
    assessed_dimensions
        Dimensions for which the investigation produced meaningful evidence.
    rendered_dimensions
        Dimensions that actually have node presence in the built graph.
    nodes / edges
        streamlit_agraph Node / Edge lists ready for agraph().
    node_meta / edge_meta
        Rich metadata dicts keyed by node/edge id — power the detail panel.
    insights
        Ownership graph metrics dict with keys: ownership_depth,
        beneficial_owner, structure_complexity.
    default_selection
        Optional node id to pre-select; None by default.
    """

    view_label:            str
    primary_driver:        str
    requested_dimensions:  list[str]
    assessed_dimensions:   list[str]
    rendered_dimensions:   list[str]
    nodes:                 list
    edges:                 list
    node_meta:             dict[str, dict]
    edge_meta:             dict[str, dict]
    insights:              dict
    default_selection:     str | None = None


# ---------------------------------------------------------------------------
# Dimension detection
# ---------------------------------------------------------------------------

_GENERIC_RISK_DIM = "generic_risk"

_DIM_KEYWORDS: dict[str, set[str]] = {
    "ownership": {
        "own", "owner", "owned", "ubo", "beneficial", "parent",
        "who owns", "holds", "shareholder", "holding", "subsidiary",
    },
    "address": {
        "address", "location", "registered at", "where is", "office",
        "postcode", "postal", "same address", "co-located", "collocated",
        "registered address",
    },
    "control": {
        "control", "psc", "significant control", "director", "signatory",
        "appointed", "appoint", "officer", "authority",
        "person with significant control",
    },
    "industry": {
        "industry", "sector", "sic", "business type", "trade",
        "classification", "peer company", "similar companies",
    },
}

_RISK_KEYWORDS: set[str] = {
    "risk", "risky", "suspicious", "flag", "concern", "shell", "red flag",
}

_DIM_ORDER: list[str] = ["ownership", "address", "control", "industry"]


def extract_requested_dimensions(question: str) -> list[str]:
    """Return an ordered list of dimensions requested by the question.

    Returns ["generic_risk"] when no specific dimension keyword is matched,
    covering pure risk questions ("is it risky?") and generic queries.
    Specific dimension keywords always win over generic risk keywords.
    """
    q = question.lower()
    found = [d for d in _DIM_ORDER if any(kw in q for kw in _DIM_KEYWORDS[d])]
    if not found:
        return [_GENERIC_RISK_DIM]
    return found


def determine_primary_graph_driver(
    evidence: dict,
    requested_dims: list[str],
) -> str:
    """Return the dimension that should drive visual emphasis.

    Picks the requested dimension with the highest risk level.  Falls back to
    the first requested dimension, then 'ownership'.
    """
    _RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}

    best_dim: str | None = None
    best_rank = -1
    for dim in requested_dims:
        risk  = evidence.get(dim, {}).get("risk_level", "UNKNOWN")
        rank  = _RANK.get((risk or "UNKNOWN").upper(), 0)
        if rank > best_rank:
            best_rank, best_dim = rank, dim

    return best_dim or (requested_dims[0] if requested_dims else "ownership")


def _view_label(dims: list[str], primary: str) -> str:
    """Generate a human-readable mixed-dimension view label.

    Built from *rendered* dimensions, not requested ones.
    """
    _LABELS: dict[str, str] = {
        "ownership": "Ownership",
        "address":   "Address",
        "control":   "Control",
        "industry":  "Industry",
    }
    if not dims:
        return f"{_LABELS.get(primary, primary)} view"
    if len(dims) == 1:
        return f"{_LABELS.get(dims[0], dims[0])} view"
    # Primary dimension first, then others in canonical order
    ordered = [primary] + [d for d in dims if d != primary]
    return " + ".join(_LABELS.get(d, d) for d in ordered[:3])


# ---------------------------------------------------------------------------
# Evidence collection
# ---------------------------------------------------------------------------

_RISK_TASK_TO_DIM: dict[str, str] = {
    "ownership_complexity_check": "ownership",
    "control_signal_check":       "control",
    "address_risk_check":         "address",
    "industry_context_check":     "industry",
}
_RISK_TASKS: frozenset[str] = frozenset(_RISK_TASK_TO_DIM)


def _collect_risk_findings_from_result(result: Any) -> dict[str, dict]:
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


def collect_graph_evidence(
    step_results: list,
    risk_findings: dict,
) -> dict:
    """Extract structured per-dimension evidence from investigation step results.

    Returns an evidence dict keyed by dimension (plus a '_meta' key for
    company-level info extracted from company_profile).
    """
    ev: dict[str, Any] = {d: {} for d in _DIM_ORDER}
    ev["_meta"] = {}

    for sr in step_results:
        if not sr.success:
            continue
        f = sr.findings or {}
        t = sr.task

        if t == "expand_ownership":
            eo = f.get("expand_ownership") or {}
            ev["ownership"].setdefault("paths",          eo.get("paths") or [])
            ev["ownership"].setdefault("ultimate_owners", eo.get("ultimate_owners") or [])

        elif t == "company_profile":
            cp = f.get("company_profile") or {}
            ev["ownership"].setdefault("direct_owners", cp.get("direct_owners") or [])
            addr = cp.get("address") or {}
            if addr:
                ev["address"].setdefault("address", addr)
            sics = cp.get("sic_codes") or []
            if sics:
                ev["industry"].setdefault("sic_codes", sics)
            company = cp.get("company") or {}
            if company:
                ev["_meta"]["company"] = company

        elif t == "shared_address_check":
            sad = f.get("shared_address_check") or {}
            ev["address"]["address"] = (
                sad.get("address")
                or ev["address"].get("address")
                or {}
            )
            ev["address"]["co_located_companies"] = sad.get("co_located_companies") or []
            ev["address"]["total_co_located"]     = sad.get("total_co_located", 0)
            ev["address"]["active_co_located"]    = sad.get("active_co_located", 0)

        elif t == "sic_context":
            sc = f.get("sic_context") or {}
            ev["industry"]["sic_codes"] = sc.get("sic_codes") or []
            ev["industry"]["peers"]     = sc.get("peers") or []

    # Inject risk levels and dimension-specific structured fields
    for task, dim in _RISK_TASK_TO_DIM.items():
        td = risk_findings.get(task) or {}
        if not td:
            continue
        ev[dim]["risk_level"] = td.get("risk_level", "UNKNOWN")
        if dim == "ownership":
            ev[dim]["corporate_chain_only"] = td.get("corporate_chain_only", False)
            ev[dim]["chain_depth"]          = td.get("chain_depth", td.get("max_chain_depth", 0))
            ev[dim]["unique_owner_count"]   = td.get("unique_owner_count", 0)
            ev[dim]["has_individual_ubos"]  = td.get("has_individual_ubos", False)
        elif dim == "address":
            ev[dim]["co_located_total"]     = td.get("co_located_total", ev["address"].get("total_co_located", 0))
            ev[dim]["dissolution_rate"]     = td.get("dissolution_rate", 0.0)
        elif dim == "control":
            ev[dim]["elevated_control"]     = td.get("elevated_control", False)
            ev[dim]["mixed_controls"]       = td.get("mixed_controls", False)
            ev[dim]["control_types"]        = td.get("control_types", [])
        elif dim == "industry":
            ev[dim]["is_holding"]           = td.get("is_holding", False)
            if not ev[dim].get("sic_codes") and td.get("sic_codes"):
                ev[dim]["sic_codes"]        = td["sic_codes"]

    return ev


def _compute_assessed_dimensions(evidence: dict) -> list[str]:
    """Return dimensions that have meaningful evidence from investigation steps.

    A dimension is 'assessed' if its evidence sub-dict has a non-UNKNOWN
    risk_level OR contains at least one concrete data field.
    """
    assessed: list[str] = []
    for dim in _DIM_ORDER:
        d = evidence.get(dim, {})
        if not d:
            continue
        risk = (d.get("risk_level") or "").upper()
        has_risk_level = bool(risk) and risk != "UNKNOWN"
        has_data = (
            bool(d.get("paths"))
            or bool(d.get("direct_owners"))
            or bool(d.get("ultimate_owners"))
            or bool(d.get("co_located_companies"))
            or bool(d.get("address"))
            or bool(d.get("sic_codes"))
            or d.get("elevated_control") is True
            or d.get("mixed_controls") is True
        )
        if has_risk_level or has_data:
            assessed.append(dim)
    return assessed


def _compute_rendered_dimensions(node_meta: dict[str, dict]) -> list[str]:
    """Return dimensions that actually have node presence in the built graph.

    Reads the 'dimension' field from node_meta entries and returns the
    matching dims in canonical _DIM_ORDER.  The focal node contributes
    its primary_driver dimension, so rendered_dimensions is never empty
    after a successful build.
    """
    seen: set[str] = set()
    for meta in node_meta.values():
        dim = meta.get("dimension", "")
        if dim and dim in _DIM_ORDER:
            seen.add(dim)
    return [d for d in _DIM_ORDER if d in seen]


def _ran_full_analysis(step_results: list) -> bool:
    """Return True when a summarize_risk_for_company step ran (full 4-dim synthesis)."""
    return any(
        getattr(sr, "task", "") == "summarize_risk_for_company"
        for sr in step_results
    )


def _resolve_generic_risk_dims(
    assessed_dims: list[str],
    evidence: dict,
) -> list[str]:
    """Resolve generic_risk to concrete active dimensions based on evidence.

    Prefers dimensions with positive risk signals (HIGH/MEDIUM/LOW).
    Falls back to all assessed dims, then to ["ownership"] as last resort.
    """
    _RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    risky = [
        d for d in assessed_dims
        if _RANK.get((evidence.get(d, {}).get("risk_level") or "").upper(), 0) > 0
    ]
    if risky:
        return risky
    if assessed_dims:
        return assessed_dims
    return ["ownership"]


def enrich_graph_evidence_from_repo_if_needed(
    evidence: dict,
    focal_id: str,
    dims: list[str],
    repo: Any,
) -> dict:
    """Fill evidence gaps with scoped, targeted Neo4j queries.

    Only queries dimensions that are active and only when the investigation
    steps did not already produce the required data.
    """
    if repo is None:
        return evidence

    try:
        # Ownership: direct owners if no path data available
        if "ownership" in dims:
            own = evidence.get("ownership", {})
            if not own.get("paths") and not own.get("direct_owners"):
                try:
                    owners = repo.get_direct_owners(focal_id)
                    if owners:
                        evidence["ownership"]["direct_owners"] = owners[:8]
                except Exception:
                    pass

        # Address: registered address + co-located companies
        if "address" in dims:
            addr_ev = evidence.get("address", {})
            if not addr_ev.get("address"):
                try:
                    db_addr = repo.get_company_address_context(focal_id)
                    if db_addr:
                        evidence["address"]["address"] = db_addr
                except Exception:
                    pass
            if not addr_ev.get("co_located_companies") and evidence["address"].get("address"):
                try:
                    co = repo.get_companies_at_same_address(focal_id, limit=50)
                    if co:
                        evidence["address"]["co_located_companies"] = co
                        evidence["address"]["total_co_located"]     = len(co)
                        evidence["address"]["active_co_located"]    = sum(
                            1 for c in co if c.get("status") == "Active"
                        )
                except Exception:
                    pass

        # Industry: SIC codes
        if "industry" in dims:
            ind = evidence.get("industry", {})
            if not ind.get("sic_codes"):
                try:
                    sics = repo.get_company_sic_context(focal_id)
                    if sics:
                        evidence["industry"]["sic_codes"] = sics
                except Exception:
                    pass

    except Exception:
        pass  # Repo unavailable — silent fallback

    return evidence


# ---------------------------------------------------------------------------
# Graph constants
# ---------------------------------------------------------------------------

_GRAPH_MAX_COLOCATED  = 10
_GRAPH_MAX_PATH_DEPTH = 3
_GRAPH_MAX_NODES      = 15

# Node colour palettes
_C_FOCAL       = {"background": "#1D4ED8", "border": "#1E3A8A",
                  "highlight":  {"background": "#3B82F6", "border": "#1E3A8A"}}
_C_COMPANY     = {"background": "#DBEAFE", "border": "#93C5FD",
                  "highlight":  {"background": "#BFDBFE", "border": "#60A5FA"}}
_C_PERSON      = {"background": "#D1FAE5", "border": "#34D399",
                  "highlight":  {"background": "#A7F3D0", "border": "#10B981"}}
_C_ADDRESS     = {"background": "#FEF3C7", "border": "#FCD34D",
                  "highlight":  {"background": "#FDE68A", "border": "#F59E0B"}}
_C_ADDRESS_KEY = {"background": "#FDE68A", "border": "#D97706",
                  "highlight":  {"background": "#FCD34D", "border": "#B45309"}}
_C_NOUBO       = {"background": "#FFF7ED", "border": "#F97316",
                  "highlight":  {"background": "#FED7AA", "border": "#EA580C"}}
_C_CLUSTER     = {"background": "#F1F5F9", "border": "#94A3B8",
                  "highlight":  {"background": "#E2E8F0", "border": "#64748B"}}
_C_COLOC_ACTIVE    = {"background": "#FEF9C3", "border": "#EAB308",
                      "highlight":  {"background": "#FEF08A", "border": "#CA8A04"}}
_C_COLOC_DISSOLVED = {"background": "#F3F4F6", "border": "#9CA3AF",
                      "highlight":  {"background": "#E5E7EB", "border": "#6B7280"}}
_C_CONTROL_SIGNAL  = {"background": "#FEF2F2", "border": "#FCA5A5",
                      "highlight":  {"background": "#FEE2E2", "border": "#F87171"}}
_C_SIC         = {"background": "#EDE9FE", "border": "#8B5CF6",
                  "highlight":  {"background": "#DDD6FE", "border": "#7C3AED"}}

_RISK_EDGE_COLORS: dict[str, str] = {
    "HIGH": "#EF4444", "MEDIUM": "#F59E0B", "LOW": "#22C55E",
}
_GREY = "#9CA3AF"

# Legend hex colours (flat, for HTML legend strip)
LEGEND_FOCAL      = "#1D4ED8"
LEGEND_COMPANY    = "#93C5FD"
LEGEND_PERSON     = "#34D399"
LEGEND_ADDRESS    = "#FCD34D"
LEGEND_COLOC      = "#EAB308"
LEGEND_CLUSTER    = "#94A3B8"

# Dimension badge colours (bg, fg)
DIM_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "ownership": ("#DBEAFE", "#1D4ED8"),
    "address":   ("#FEF3C7", "#D97706"),
    "control":   ("#F3E8FF", "#7C3AED"),
    "industry":  ("#F0FDF4", "#15803D"),
}


def _risk_color(level: str) -> str:
    return _RISK_EDGE_COLORS.get((level or "").upper(), _GREY)


def _short(name: str, n: int = 22) -> str:
    return name if len(name) <= n else name[: n - 1] + "\u2026"


def _pct(lo: Any, hi: Any) -> str:
    if lo is None:
        return ""
    lo_i = int(lo)
    hi_i = int(hi) if hi is not None else lo_i
    return f"{lo_i}%" if lo_i == hi_i else f"{lo_i}\u2013{hi_i}%"


# ---------------------------------------------------------------------------
# Internal graph builder
# ---------------------------------------------------------------------------


class _Builder:
    """Mutable state container for incremental node / edge assembly."""

    def __init__(self) -> None:
        from streamlit_agraph import Edge, Node  # deferred to avoid import at module load
        self._Node = Node
        self._Edge = Edge
        self.nodes:     list      = []
        self.edges:     list      = []
        self.seen:      set[str]  = set()
        self.node_meta: dict[str, dict] = {}
        self.edge_meta: dict[str, dict] = {}
        self.non_focal: int = 0

    # ------------------------------------------------------------------

    def add_node(
        self,
        nid: str,
        label: str,
        color: dict,
        size: int,
        *,
        full_name: str,
        node_type: str,
        why_in_graph: str = "",
        dimension: str = "",
        company_number: str = "",
        status: str = "",
        risk_relevance: str = "",
        address_count: int = 0,
        ubo_found: bool | None = None,
        border_width: int = 1,
        focal: bool = False,
    ) -> bool:
        """Add node if not already seen.  Returns True if actually inserted."""
        if nid in self.seen:
            return False
        self.seen.add(nid)
        self.nodes.append(self._Node(
            id=nid, label=label, color=color, size=size,
            title=full_name, borderWidth=border_width,
        ))
        self.node_meta[nid] = {
            "id":             nid,
            "type":           node_type,
            "role":           node_type,
            "full_name":      full_name,
            "why_in_graph":   why_in_graph or node_type,
            "dimension":      dimension,
            "company_number": company_number,
            "status":         status,
            "risk_relevance": risk_relevance,
            "address_count":  address_count,
            "ubo_found":      ubo_found,
        }
        if not focal:
            self.non_focal += 1
        return True

    def add_edge(
        self,
        src: str,
        dst: str,
        *,
        etype: str = "",
        label: str = "",
        color: str = _GREY,
        is_key: bool = False,
        ownership_pct: str = "",
        why_in_graph: str = "",
        dimension: str = "",
        risk_relevance: str = "",
    ) -> None:
        eid = f"{src}__{dst}__{etype}"
        if eid not in self.edge_meta:
            parts = [p for p in [label, why_in_graph,
                                  f"Risk: {risk_relevance}" if risk_relevance else "",
                                  f"Dim: {dimension}" if dimension else ""] if p]
            hover_title = " · ".join(parts) if parts else (etype or "edge")
            self.edges.append(self._Edge(
                source=src, target=dst,
                label=label if is_key else "",
                title=hover_title,
                color=color,
                width=3 if is_key else 1,
                font={"size": 10, "align": "middle",
                      "strokeWidth": 2, "strokeColor": "#FFFFFF"},
            ))
        self.edge_meta[eid] = {
            "id":             eid,
            "source":         src,
            "target":         dst,
            "type":           etype or "—",
            "ownership_pct":  ownership_pct,
            "why_in_graph":   why_in_graph or etype,
            "dimension":      dimension,
            "risk_relevance": risk_relevance,
            "is_highlighted": is_key,
        }

    def has_room(self) -> bool:
        return self.non_focal < _GRAPH_MAX_NODES


# ---------------------------------------------------------------------------
# Layer builders
# ---------------------------------------------------------------------------


def _add_ownership_layer(
    b: _Builder,
    focal_id: str,
    ev: dict,
    primary: str,
) -> None:
    own      = ev.get("ownership", {})
    risk_lvl = own.get("risk_level", "")
    is_key   = (primary == "ownership")
    ec       = _risk_color(risk_lvl) if is_key else _GREY

    ownership_found = False

    # Full ownership paths
    for row in (own.get("paths") or []):
        if not b.has_room():
            break
        if (row.get("path_depth") or 0) > _GRAPH_MAX_PATH_DEPTH:
            continue
        from_name = (row.get("from_name") or "").strip()
        to_name   = (row.get("to_name")   or "").strip()
        if not from_name or not to_name:
            continue
        is_person = "Person" in (row.get("from_labels") or [])
        color     = _C_PERSON if is_person else _C_COMPANY
        ntype     = "Individual" if is_person else "Company"
        pct       = _pct(row.get("ownership_pct_min"), row.get("ownership_pct_max"))
        b.add_node(
            from_name, _short(from_name), color,
            size=22 if is_person else 18,
            full_name=from_name, node_type=ntype,
            why_in_graph="Member of ownership chain",
            dimension="ownership",
            risk_relevance=risk_lvl,
        )
        b.add_edge(
            from_name, to_name,
            etype="OWNS", label=pct,
            color=ec, is_key=is_key,
            ownership_pct=pct,
            why_in_graph="Ownership relationship",
            dimension="ownership",
            risk_relevance=risk_lvl,
        )
        ownership_found = True

    # UBOs not already in path rows
    for ubo in (own.get("ultimate_owners") or []):
        if not b.has_room():
            break
        name = (ubo.get("owner_name") or "").strip()
        if not name:
            continue
        pct = _pct(ubo.get("ownership_pct_min"), ubo.get("ownership_pct_max"))
        b.add_node(
            name, _short(name), _C_PERSON, size=26,
            full_name=name,
            node_type="Individual / Beneficial Owner",
            why_in_graph="Ultimate beneficial owner",
            dimension="ownership",
            risk_relevance=risk_lvl,
        )
        if not any(
            e.source == name and e.target == focal_id for e in b.edges
        ):
            b.add_edge(
                name, focal_id,
                etype="OWNS",
                color=ec if is_key else "#34D399",
                is_key=is_key,
                ownership_pct=pct,
                why_in_graph="UBO relationship",
                dimension="ownership",
                risk_relevance=risk_lvl,
            )
        ownership_found = True

    # Fallback: direct owners from company_profile or repo enrichment
    if not ownership_found:
        for owner in (own.get("direct_owners") or []):
            if not b.has_room():
                break
            name = (owner.get("owner_name") or "").strip()
            if not name:
                continue
            is_person = "Person" in (owner.get("owner_labels") or [])
            color     = _C_PERSON if is_person else _C_COMPANY
            ntype     = "Individual" if is_person else "Company"
            pct       = _pct(owner.get("ownership_pct_min"), owner.get("ownership_pct_max"))
            b.add_node(
                name, _short(name), color, size=20,
                full_name=name, node_type=ntype,
                why_in_graph="Direct owner",
                dimension="ownership",
                risk_relevance=risk_lvl,
            )
            b.add_edge(
                name, focal_id,
                etype="OWNS", label=pct,
                color=ec, is_key=is_key,
                ownership_pct=pct,
                why_in_graph="Direct ownership",
                dimension="ownership",
                risk_relevance=risk_lvl,
            )
            ownership_found = True

    # "No UBO" phantom node when chain is corporate-only
    if own.get("corporate_chain_only") is True and b.has_room():
        nid = "__no_ubo__"
        b.add_node(
            nid, "? No UBO", _C_NOUBO, size=14,
            full_name="No individual beneficial owner identified",
            node_type="Missing UBO",
            why_in_graph="Full ownership chain consists of corporate entities only",
            dimension="ownership",
            risk_relevance="HIGH",
            border_width=2,
        )
        b.add_edge(
            focal_id, nid,
            etype="NO_UBO",
            color="#F97316",
            why_in_graph="Corporate chain — no identifiable individual UBO",
            dimension="ownership",
            risk_relevance="HIGH",
        )


def _add_address_layer(
    b: _Builder,
    focal_id: str,
    ev: dict,
    primary: str,
) -> None:
    addr_ev = ev.get("address", {})
    address = addr_ev.get("address") or {}
    if not address:
        return

    is_key     = (primary == "address")
    risk_lvl   = addr_ev.get("risk_level", "")
    edge_color = _risk_color(risk_lvl) if is_key else "#F59E0B"
    addr_color = _C_ADDRESS_KEY if is_key else _C_ADDRESS
    addr_size  = 24 if is_key else 16

    postal     = (address.get("postal_code") or address.get("post_code") or "").strip()
    town       = (address.get("post_town") or "").strip()
    addr_label = postal or town or "Address"
    full_addr  = ", ".join(filter(None, [
        address.get("address_line_1", ""), town, postal,
    ]))

    co_total   = int(
        addr_ev.get("co_located_total")
        or addr_ev.get("total_co_located")
        or 0
    )
    diss_rate  = float(addr_ev.get("dissolution_rate") or 0.0)

    display_label = f"{addr_label} ({co_total})" if co_total else addr_label
    addr_id       = f"__addr__{focal_id}"

    if not b.has_room():
        return

    b.add_node(
        addr_id, _short(display_label, 22), addr_color, size=addr_size,
        full_name=full_addr or addr_label,
        node_type="Registered Address",
        why_in_graph="Registered address of focal entity",
        dimension="address",
        risk_relevance=risk_lvl,
        address_count=co_total,
    )
    b.add_edge(
        focal_id, addr_id,
        etype="REGISTERED_AT",
        label="at",
        color=edge_color,
        is_key=is_key,
        why_in_graph="Registered address link",
        dimension="address",
        risk_relevance=risk_lvl,
    )

    co_companies = addr_ev.get("co_located_companies") or []

    if co_companies:
        # Show actual co-located entities whenever address is in the graph.
        # Primary: up to 10 (full detail); secondary context: up to 5 (de-emphasised).
        max_show = _GRAPH_MAX_COLOCATED if is_key else min(5, _GRAPH_MAX_COLOCATED)
        co_node_size = 12 if is_key else 10

        sorted_co = sorted(
            co_companies,
            key=lambda c: (0 if c.get("status") == "Active" else 1, c.get("name", "")),
        )
        shown    = sorted_co[:max_show]
        overflow = max(0, co_total - len(shown)) if co_total > len(shown) else max(0, len(sorted_co) - len(shown))

        for co in shown:
            if not b.has_room():
                break
            co_name = (co.get("name") or "").strip()
            if not co_name:
                continue
            co_status = co.get("status", "")
            co_num    = co.get("company_number", "")
            co_color  = _C_COLOC_ACTIVE if co_status == "Active" else _C_COLOC_DISSOLVED
            b.add_node(
                f"__co__{co_name}", _short(co_name, 20), co_color, size=co_node_size,
                full_name=co_name,
                node_type="Co-located Company",
                why_in_graph="Shares registered address with focal entity",
                dimension="address",
                company_number=co_num,
                status=co_status,
                risk_relevance=risk_lvl,
            )
            b.add_edge(
                addr_id, f"__co__{co_name}",
                etype="CO_LOCATED",
                color="#D1D5DB",
                why_in_graph="Co-located at same registered address",
                dimension="address",
            )

        # Overflow node when there are more entities than shown
        if overflow > 0 and b.has_room():
            diss_pct = round(diss_rate * 100)
            ovf_id   = "__colocated_overflow__"
            ovf_ctx  = f"{overflow} additional co-located companies"
            if diss_pct:
                ovf_ctx += f" · {diss_pct}% dissolved"
            b.add_node(
                ovf_id, f"+{overflow} more", _C_CLUSTER, size=14,
                full_name=ovf_ctx,
                node_type="Co-located Cluster",
                why_in_graph=f"{overflow} additional co-located companies (overflow)",
                dimension="address",
                risk_relevance=risk_lvl,
                address_count=overflow,
            )
            b.add_edge(
                addr_id, ovf_id,
                etype="CO_LOCATED_OVERFLOW",
                color="#D1D5DB",
                why_in_graph="Overflow of co-located entities",
                dimension="address",
            )

    elif co_total > 5 and b.has_room():
        # No raw co-located data available — show a cluster summary node
        diss_pct  = round(diss_rate * 100)
        clust_ctx = f"{co_total} companies share this address"
        if diss_pct:
            clust_ctx += f" · {diss_pct}% dissolved"
        b.add_node(
            "__colocated_cluster__", f"+{co_total} entities", _C_CLUSTER, size=14,
            full_name=clust_ctx,
            node_type="Co-located Cluster",
            why_in_graph="Summary: co-located entities at same address",
            dimension="address",
            address_count=co_total,
        )
        b.add_edge(
            addr_id, "__colocated_cluster__",
            etype="CO_LOCATED",
            color=edge_color,
            why_in_graph="Co-location summary",
            dimension="address",
        )


def _add_control_layer(
    b: _Builder,
    focal_id: str,
    ev: dict,
    primary: str,
) -> None:
    ctrl_ev  = ev.get("control", {})
    risk_lvl = ctrl_ev.get("risk_level", "")

    if not (ctrl_ev.get("elevated_control") or ctrl_ev.get("mixed_controls")):
        return
    if not b.has_room():
        return

    ctrl_types   = ctrl_ev.get("control_types") or []
    ctrl_summary = ", ".join(ctrl_types[:3]) if ctrl_types else "Significant control detected"
    b.add_node(
        "__control_signal__", "⚠ Control Signal", _C_CONTROL_SIGNAL, size=14,
        full_name=ctrl_summary,
        node_type="Control Signal",
        why_in_graph="Elevated or mixed control mechanism detected",
        dimension="control",
        risk_relevance=risk_lvl,
    )
    b.add_edge(
        focal_id, "__control_signal__",
        etype="CONTROL",
        color=_risk_color(risk_lvl),
        is_key=(primary == "control"),
        why_in_graph="Control mechanism link",
        dimension="control",
        risk_relevance=risk_lvl,
    )


def _add_industry_layer(
    b: _Builder,
    focal_id: str,
    ev: dict,
    primary: str,
) -> None:
    ind_ev   = ev.get("industry", {})
    risk_lvl = ind_ev.get("risk_level", "")

    for sic in (ind_ev.get("sic_codes") or [])[:2]:
        if not b.has_room():
            break
        code = (sic.get("sic_code") or "").strip()
        desc = (sic.get("sic_description") or "").strip()
        if not code and not desc:
            continue
        node_id    = f"__sic__{code or desc[:20]}"
        node_label = f"SIC {code}" if code else (desc[:20] if desc else "Industry")
        full_name  = f"{code}: {desc}" if (code and desc) else (code or desc or "Industry")
        b.add_node(
            node_id, node_label, _C_SIC, size=14,
            full_name=full_name,
            node_type="Industry Classification",
            why_in_graph="Industry classification of focal entity",
            dimension="industry",
            risk_relevance=risk_lvl,
        )
        b.add_edge(
            focal_id, node_id,
            etype="HAS_SIC",
            color=_risk_color(risk_lvl) if primary == "industry" else _GREY,
            is_key=(primary == "industry"),
            why_in_graph="Industry classification link",
            dimension="industry",
            risk_relevance=risk_lvl,
        )


# ---------------------------------------------------------------------------
# Insights builder (moved from components.py)
# ---------------------------------------------------------------------------


def _build_insights(result: Any) -> dict:
    """Build ownership graph insight metrics from investigation step results.

    Returns dict with keys: ownership_depth, beneficial_owner,
    structure_complexity.  Values are display strings or "—" when unavailable.
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
    # Fallback: derive from expand_ownership when complexity check didn't run
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
# Focal entity helpers
# ---------------------------------------------------------------------------


def _get_focal_id(result: Any) -> str:
    for _, edata in (result.resolved_entities or {}).items():
        if edata and edata.get("canonical_name"):
            return edata["canonical_name"]
    return result.query or "Entity"


def _get_focal_number(result: Any) -> str:
    for _, edata in (result.resolved_entities or {}).items():
        if edata and edata.get("company_number"):
            return edata["company_number"]
    return ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_contextual_graph_model(
    question: str,
    result: Any,
    repo: Any = None,
) -> GraphPayload:
    """Build a contextual, evidence-driven graph from an investigation result.

    Returns a fully typed GraphPayload.  The view_label and rendered_dimensions
    fields reflect what was actually built in the graph, not merely what was
    requested.

    Dimension flow
    --------------
    requested_dimensions  — extracted from the question (may include generic_risk)
    assessed_dimensions   — dimensions with meaningful evidence in the result
    active_dims           — concrete dims used to build the graph
                            (generic_risk is resolved to assessed dims here)
    rendered_dimensions   — dims that produced at least one node in the graph
    """
    # 1. Dimensions requested by the question
    requested_dims = extract_requested_dimensions(question)

    # 2. Risk findings from step results
    rf = _collect_risk_findings_from_result(result)

    # 3. Structured evidence from investigation steps
    ev = collect_graph_evidence(result.step_results or [], rf)

    # 4. Assessed dimensions (what the investigation actually covered)
    assessed_dims = _compute_assessed_dimensions(ev)

    # 5. Resolve active dimensions
    if _GENERIC_RISK_DIM in requested_dims or _ran_full_analysis(result.step_results or []):
        # Generic risk question OR full analysis ran: expand to all evidence-backed dims
        active_dims = _resolve_generic_risk_dims(assessed_dims, ev)
    else:
        # Specific dimensions requested: use intersection with assessed,
        # fall back to requested if none are assessed yet
        active_dims = [d for d in requested_dims if d in assessed_dims] or list(requested_dims)

    # 6. Enrich from repo only where evidence is missing
    focal_id = _get_focal_id(result)
    ev = enrich_graph_evidence_from_repo_if_needed(ev, focal_id, active_dims, repo)

    # 7. Primary driver — highest-risk dimension among active dims
    primary = determine_primary_graph_driver(ev, active_dims)

    # 8. Focal node
    company_info = ev.get("_meta", {}).get("company") or {}
    focal_number = _get_focal_number(result) or company_info.get("company_number", "")
    focal_status = company_info.get("status", "")
    focal_ubo    = ev["ownership"].get("has_individual_ubos")
    focal_rlevel = ev.get(primary, {}).get("risk_level", "")

    b = _Builder()
    b.add_node(
        focal_id, _short(focal_id, 24), _C_FOCAL, size=34,
        full_name=focal_id,
        node_type="Focal Company",
        why_in_graph="Primary subject of investigation",
        dimension=primary,
        company_number=focal_number,
        status=focal_status,
        risk_relevance=focal_rlevel,
        ubo_found=focal_ubo,
        border_width=3,
        focal=True,
    )

    # 9. Dimension layers — all four treated equally; no industry restriction
    if "ownership" in active_dims:
        _add_ownership_layer(b, focal_id, ev, primary)

    if "address" in active_dims:
        _add_address_layer(b, focal_id, ev, primary)

    if "control" in active_dims:
        _add_control_layer(b, focal_id, ev, primary)

    if "industry" in active_dims:
        _add_industry_layer(b, focal_id, ev, primary)

    # 10. Rendered dimensions — what actually made it into the graph
    rendered_dims = _compute_rendered_dimensions(b.node_meta)

    # 11. View label from rendered dims (not requested)
    view_label = _view_label(rendered_dims, primary)

    # 12. Insights
    insights = _build_insights(result)

    return GraphPayload(
        view_label           = view_label,
        primary_driver       = primary,
        requested_dimensions = requested_dims,
        assessed_dimensions  = assessed_dims,
        rendered_dimensions  = rendered_dims,
        nodes                = b.nodes,
        edges                = b.edges,
        node_meta            = b.node_meta,
        edge_meta            = b.edge_meta,
        insights             = insights,
        default_selection    = None,
    )


# ---------------------------------------------------------------------------
# GraphCompositionService — stateful wrapper
# ---------------------------------------------------------------------------


class GraphCompositionService:
    """Stateful wrapper around build_contextual_graph_model.

    Holds a reference to the Neo4j repository so callers do not need to
    pass it on every call.

    Usage
    -----
    service = GraphCompositionService(repo=my_repo)
    payload = service.compose(question, result)
    """

    def __init__(self, repo: Any = None) -> None:
        self._repo = repo

    def compose(self, question: str, result: Any) -> GraphPayload:
        """Build and return a GraphPayload for the given question + result."""
        return build_contextual_graph_model(question, result, repo=self._repo)
