"""
Remote MCP tool client — calls tools on a remote MCP server over HTTP.

Uses the MCP streamable-http transport so the same 15 tools exposed by the
local ``src.mcp.server`` can be called on any publicly-hosted FastMCP server
(e.g. the Railway deployment at REMOTE_MCP_URL).

Interface is identical to ``MCPToolClient`` — agents consume either client
without modification.

Design note
-----------
Each ``call_tool()`` invocation opens a fresh HTTP session, calls initialize,
invokes the tool, and closes.  This is stateless and safe for Streamlit's
multi-threaded model and Railway's stateless HTTP deployment.
``asyncio.run()`` is used to bridge the synchronous agent call-path to the
async MCP SDK; it creates a temporary event loop per call, which is fine
because tool calls happen in a background daemon thread (not the main
asyncio loop).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.domain.models import ToolResult

_TOOL_NAMES = sorted([
    "resolve_entity",
    "validate_plan",
    "evaluate_stop_conditions",
    "entity_lookup",
    "company_profile",
    "expand_ownership",
    "shared_address_check",
    "sic_context",
    "ownership_complexity_check",
    "control_signal_check",
    "address_risk_check",
    "industry_context_check",
    "retrieve_trace",
    "find_traces_by_entity",
    "list_recent_traces",
])


class RemoteMCPToolClient:
    """
    Synchronous HTTP MCP client for the entity-risk investigation system.

    Calls tools on a remote FastMCP server via the streamable-http transport.
    Returns ``ToolResult`` objects so downstream agent code is unchanged.

    Usage::

        client = RemoteMCPToolClient("https://example.up.railway.app/mcp")
        result = client.call_tool("entity_lookup", {"name": "ACME"})
        print(result.summary)
    """

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """
        Call a remote MCP tool by name and return a ToolResult.

        Opens a new HTTP session for each call (stateless).
        """
        t0 = time.monotonic()
        try:
            raw = asyncio.run(self._call_tool_async(tool_name, arguments))
            duration = round((time.monotonic() - t0) * 1000, 1)

            if raw is None:
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error="Remote MCP server returned no content",
                    duration_ms=duration,
                    input=arguments,
                    summary=f"{tool_name} failed: no content",
                )

            return ToolResult(
                tool_name=raw.get("tool_name", tool_name),
                success=raw.get("success", True),
                data=raw.get("data"),
                error=raw.get("error"),
                duration_ms=raw.get("duration_ms", duration),
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
        return list(_TOOL_NAMES)

    def close(self) -> None:
        """No-op — stateless client holds no persistent connections."""

    # ------------------------------------------------------------------
    # Internal async implementation
    # ------------------------------------------------------------------

    async def _call_tool_async(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict | None:
        async with streamablehttp_client(self.server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)

                if not result.content:
                    return None

                # FastMCP serialises tool return values as JSON text content.
                text = result.content[0].text  # type: ignore[union-attr]

                if result.isError:
                    return {
                        "tool_name": tool_name,
                        "success": False,
                        "error": text,
                        "input": arguments,
                        "summary": f"{tool_name} failed: {text}",
                    }

                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    # Unexpected plain-text response — treat as raw summary
                    return {
                        "tool_name": tool_name,
                        "success": True,
                        "data": {"raw": text},
                        "input": arguments,
                        "summary": text[:200],
                    }
