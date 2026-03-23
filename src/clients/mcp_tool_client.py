"""
MCP tool client — the single tool-access point for all agents in Phase 3.

Calls tool functions registered on the local MCP server by name with
structured input dicts, and returns ToolResult objects so agents consume
the same interface they always have — without holding direct references to
GraphTools, RiskTools, or TraceTools.

The underlying Neo4j connection is managed lazily by the MCP server module
and shared across all MCPToolClient instances in the same process.

Design note
-----------
This is an in-process dispatch client.  Every call goes through the
module-level functions in src.mcp.server, which wrap the actual tool
classes.  The interface is identical to what a subprocess-based MCP client
would expose (call by name, arguments as a dict, result as a structured
dict), so the transport can be swapped to stdio or HTTP later without
changing any agent code.
"""

from __future__ import annotations

import time
from typing import Any

import src.mcp.server as _srv
from src.domain.models import ToolResult


class MCPToolClient:
    """
    Synchronous in-process MCP client for the entity-risk investigation system.

    Routes ``call_tool(name, arguments)`` to the corresponding module-level
    function in ``src.mcp.server``.  Returns a ``ToolResult`` so downstream
    agent code is unchanged.

    Usage::

        mcp = MCPToolClient()
        result = mcp.call_tool("entity_lookup", {"name": "ACME"})
        print(result.summary)
        mcp.close()
    """

    # Dispatch table — built once at class definition time.
    # Points to the module-level functions registered as MCP tools.
    _DISPATCH: dict[str, Any] = {
        # Shared tools
        "resolve_entity":          _srv.resolve_entity,
        "validate_plan":           _srv.validate_plan,
        "evaluate_stop_conditions": _srv.evaluate_stop_conditions,
        # Graph tools
        "entity_lookup":           _srv.entity_lookup,
        "company_profile":         _srv.company_profile,
        "expand_ownership":        _srv.expand_ownership,
        "shared_address_check":    _srv.shared_address_check,
        "sic_context":             _srv.sic_context,
        # Risk tools
        "ownership_complexity_check": _srv.ownership_complexity_check,
        "control_signal_check":    _srv.control_signal_check,
        "address_risk_check":      _srv.address_risk_check,
        "industry_context_check":  _srv.industry_context_check,
        # Trace tools
        "retrieve_trace":          _srv.retrieve_trace,
        "find_traces_by_entity":   _srv.find_traces_by_entity,
        "list_recent_traces":      _srv.list_recent_traces,
    }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """
        Call an MCP tool by name and return a ToolResult.

        Args:
            tool_name:  Name of the registered tool (see ``list_tools()``).
            arguments:  Keyword arguments forwarded to the tool function.

        Returns:
            ToolResult with ``success=True`` on a clean call.
            ToolResult with ``success=False`` on unknown tool or runtime error.
        """
        if tool_name not in self._DISPATCH:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=(
                    f"Unknown tool '{tool_name}'. "
                    f"Available: {self.list_tools()}"
                ),
                input=arguments,
                summary=f"call_tool failed: unknown tool '{tool_name}'",
            )

        t0 = time.monotonic()
        try:
            raw: dict = self._DISPATCH[tool_name](**arguments)
            return ToolResult(
                tool_name=raw.get("tool_name", tool_name),
                success=raw.get("success", True),
                data=raw.get("data"),
                error=raw.get("error"),
                duration_ms=raw.get(
                    "duration_ms", round((time.monotonic() - t0) * 1000, 1)
                ),
                input=raw.get("input", arguments),
                summary=raw.get("summary", ""),
            )
        except Exception as exc:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=str(exc),
                duration_ms=round((time.monotonic() - t0) * 1000, 1),
                input=arguments,
                summary=f"{tool_name} failed: {exc}",
            )

    def list_tools(self) -> list[str]:
        """Return the names of all available MCP tools, sorted."""
        return sorted(self._DISPATCH)

    def close(self) -> None:
        """Close the shared Neo4j connection opened by the MCP server layer."""
        _srv.close()
