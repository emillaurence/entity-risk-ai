"""
Local MCP server — single tool-access layer for Phase 3.

Exposes all investigation tools (shared, graph, risk, trace) via the Model
Context Protocol. Wraps the existing Python tool classes without reimplementing
any logic.

Start the server (stdio transport, for Claude Desktop / MCP clients):

    python -m src.mcp.server

Or via the MCP CLI (dev inspector):

    mcp dev src/mcp/server.py

The tool layer is lazy-initialised on the first call so the server starts
without a Neo4j connection until a tool is actually invoked.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when invoked via `mcp dev`
sys.path.insert(0, str(Path(__file__).parents[2]))

import dataclasses
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

from src.config import get_neo4j_settings
from src.storage.neo4j_repository import Neo4jRepository
from src.storage.trace_repository import TraceRepository
from src.tools.graph_tools import GraphTools
from src.tools.risk_tools import RiskTools
from src.tools.shared_tools import SharedTools
from src.tools.trace_tools import TraceTools

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "entity-risk-ai",
    instructions=(
        "Investigation system for UK Companies House entity ownership and risk analysis. "
        "Start with resolve_entity to canonicalise the company name, then run graph and "
        "risk tools to gather signals, and evaluate_stop_conditions to decide when the "
        "investigation is complete. Use trace tools to retrieve prior investigations."
    ),
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ---------------------------------------------------------------------------
# Lazy tool layer — initialised once on first call
# ---------------------------------------------------------------------------

_graph_tools: GraphTools | None = None
_risk_tools: RiskTools | None = None
_trace_tools: TraceTools | None = None
_shared_tools: SharedTools | None = None
_repo: Neo4jRepository | None = None


def _get_tools() -> tuple[GraphTools, RiskTools, TraceTools, SharedTools]:
    global _graph_tools, _risk_tools, _trace_tools, _shared_tools, _repo
    if _graph_tools is None:
        settings = get_neo4j_settings()
        _repo = Neo4jRepository(**vars(settings))
        _graph_tools = GraphTools(_repo)
        _risk_tools = RiskTools(_repo)
        trace_repo = TraceRepository(_repo)
        _trace_tools = TraceTools(trace_repo)
        _shared_tools = SharedTools(_graph_tools)
    return _graph_tools, _risk_tools, _trace_tools, _shared_tools


def _serialise(result: Any) -> dict[str, Any]:
    """
    Convert a ToolResult dataclass to a plain, JSON-serialisable dict.

    ``dataclasses.asdict`` handles nested dataclasses. ``_sanitise`` converts
    any remaining non-serialisable types (e.g. datetime) to strings.
    """
    return _sanitise(dataclasses.asdict(result))


def _sanitise(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable types to strings."""
    if isinstance(obj, dict):
        return {k: _sanitise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitise(v) for v in obj]
    if hasattr(obj, "isoformat"):  # datetime / date
        return obj.isoformat()
    return obj


# ---------------------------------------------------------------------------
# Shared tools
# ---------------------------------------------------------------------------


@mcp.tool()
def resolve_entity(name: str) -> dict:
    """
    Resolve a company name to its canonical form in the graph.

    Performs full-text search then selects the exact-name match if present,
    otherwise the highest-ranked fuzzy match. Returns canonical_name,
    company_number, status, exact_match flag, and all candidates.
    """
    _, _, _, shared = _get_tools()
    return _serialise(shared.resolve_entity(name))


@mcp.tool()
def validate_plan(steps: list[dict]) -> dict:
    """
    Validate a list of investigation plan steps before execution.

    Each step dict must contain step_id (non-empty string) and tool_name
    (must match a known tool). Returns valid steps, errors, and an overall
    valid flag.
    """
    _, _, _, shared = _get_tools()
    return _serialise(shared.validate_plan(steps))


@mcp.tool()
def evaluate_stop_conditions(findings: dict) -> dict:
    """
    Evaluate whether the investigation has gathered sufficient evidence.

    Pass findings keyed by signal: ownership_complexity, control_signals,
    address_risk, industry_context — each a dict with a risk_level key
    (LOW / MEDIUM / HIGH / UNKNOWN). Returns should_stop, escalate,
    overall_risk, and any missing signals.
    """
    _, _, _, shared = _get_tools()
    return _serialise(shared.evaluate_stop_conditions(findings))


# ---------------------------------------------------------------------------
# Graph tools
# ---------------------------------------------------------------------------


@mcp.tool()
def entity_lookup(name: str) -> dict:
    """
    Search for companies whose name contains the given string.

    Uses the full-text index. Returns up to 10 ranked matches with
    company_number, status, and relevance score.
    """
    graph, _, _, _ = _get_tools()
    return _serialise(graph.entity_lookup(name))


@mcp.tool()
def company_profile(company_name: str) -> dict:
    """
    Retrieve a full company profile: address, SIC codes, and direct owners.

    Requires an exact company name. Returns data from three repository
    queries combined into a single structured result.
    """
    graph, _, _, _ = _get_tools()
    return _serialise(graph.company_profile(company_name))


@mcp.tool()
def expand_ownership(company_name: str, max_depth: int = 5) -> dict:
    """
    Walk the ownership graph up to max_depth hops.

    Returns all ownership path rows and ultimate beneficial owners (UBOs).
    max_depth defaults to 5.
    """
    graph, _, _, _ = _get_tools()
    return _serialise(graph.expand_ownership(company_name, max_depth=max_depth))


@mcp.tool()
def shared_address_check(company_name: str) -> dict:
    """
    Check how many other companies share the same registered address.

    High co-location counts are a common shell-company risk signal.
    Returns address details, total and active co-located company counts.
    """
    graph, _, _, _ = _get_tools()
    return _serialise(graph.shared_address_check(company_name))


@mcp.tool()
def sic_context(company_name: str) -> dict:
    """
    Return the company's SIC codes and peer companies sharing those codes.

    Peers are sorted by overlap count. Returns up to 50 peers.
    """
    graph, _, _, _ = _get_tools()
    return _serialise(graph.sic_context(company_name))


# ---------------------------------------------------------------------------
# Risk tools
# ---------------------------------------------------------------------------


@mcp.tool()
def ownership_complexity_check(company_name: str, max_depth: int = 5) -> dict:
    """
    Measure structural complexity of the ownership chain.

    Computes max chain depth, unique owner count, UBO presence,
    corporate-chain-only flag, and risk_level (LOW / MEDIUM / HIGH / UNKNOWN).
    """
    _, risk, _, _ = _get_tools()
    return _serialise(risk.ownership_complexity_check(company_name, max_depth=max_depth))


@mcp.tool()
def control_signal_check(company_name: str, max_depth: int = 5) -> dict:
    """
    Inspect the nature-of-control types across the ownership chain.

    Detects elevated PSC controls (significant influence, right to appoint
    directors) and flags mixed vs. share-only control structures.
    """
    _, risk, _, _ = _get_tools()
    return _serialise(risk.control_signal_check(company_name, max_depth=max_depth))


@mcp.tool()
def address_risk_check(company_name: str, same_address_threshold: int = 5) -> dict:
    """
    Assess risk from registered address co-location.

    Computes co-located total, active count, dissolution rate, and
    risk_level. Threshold for flagging defaults to 5 co-located companies.
    """
    _, risk, _, _ = _get_tools()
    return _serialise(
        risk.address_risk_check(
            company_name, same_address_threshold=same_address_threshold
        )
    )


@mcp.tool()
def industry_context_check(company_name: str) -> dict:
    """
    Flag industry-level risk based on SIC codes.

    Checks against known high-scrutiny codes (holding companies, dormant
    entities) and computes peer dissolution rate.
    """
    _, risk, _, _ = _get_tools()
    return _serialise(risk.industry_context_check(company_name))


# ---------------------------------------------------------------------------
# Trace tools
# ---------------------------------------------------------------------------


@mcp.tool()
def retrieve_trace(trace_id: str) -> dict:
    """
    Load a full investigation trace by its ID.

    Returns the trace metadata and all events in chronological order,
    including entity links via the :ABOUT relationship.
    """
    _, _, trace, _ = _get_tools()
    return _serialise(trace.retrieve_trace(trace_id))


@mcp.tool()
def find_traces_by_entity(entity_name: str) -> dict:
    """
    Find investigation traces linked to a business entity by exact name.

    Matches traces where the query field equals entity_name or any trace
    event has an :ABOUT link to that entity.
    """
    _, _, trace, _ = _get_tools()
    return _serialise(trace.find_traces_by_entity(entity_name))


@mcp.tool()
def list_recent_traces(limit: int = 20) -> dict:
    """
    Return the most recent investigation traces, newest first.

    Limit defaults to 20. Each row contains trace_id, query, mode,
    started_at, ended_at, and event_count.
    """
    _, _, trace, _ = _get_tools()
    return _serialise(trace.list_recent_traces(limit=limit))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 0))
    if port:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio — unchanged for local use
