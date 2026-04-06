"""
Kong MCP Gateway tool client — routes MCP tool calls through Kong proxy.

Phase 508: Switch the shared MCP client path to Kong MCP Gateway.

Behavior
--------
- Uses the streamable-http MCP transport (same as RemoteMCPToolClient)
- Injects ``X-Kong-API-Key`` and ``Accept`` headers for Kong authentication
- Fail-closed: raises ``RuntimeError`` on any failure — no silent fallback
  to direct remote MCP
- Logs endpoint at construction time; never logs the API key

Security model
--------------
The app authenticates to Kong using the API key (sent as ``X-Kong-API-Key``).
Kong validates the key via the key-auth plugin on the ``/mcp`` route and
forwards the request to the upstream MCP server unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.clients.remote_mcp_tool_client import _TOOL_NAMES
from src.config import KongMCPGatewaySettings
from src.domain.models import ToolResult

_log = logging.getLogger(__name__)

# Substrings that indicate a Kong ACL / key-auth denial (case-insensitive).
# Kong's default ACL plugin message is "You cannot consume this service".
_ACL_DENIAL_PATTERNS = (
    "403",
    "forbidden",
    "you cannot consume",
    "acl",
    "not allowed",
    "unauthorized",
    "unauthorised",
    "permission",
    "consumer group",
)


def _is_acl_denial(text: str) -> bool:
    """Return True when *text* looks like a Kong ACL or key-auth denial."""
    lower = text.lower()
    return any(pat in lower for pat in _ACL_DENIAL_PATTERNS)


def _collect_exception_messages(exc: BaseException, _seen: set | None = None) -> list[str]:
    """Recursively collect all exception messages from a nested exception chain.

    Handles:
    - ``BaseExceptionGroup`` / ``ExceptionGroup`` (Python 3.11+ TaskGroup failures)
    - ``__cause__`` (explicit chaining via ``raise X from Y``)
    - ``__context__`` (implicit chaining)
    """
    if _seen is None:
        _seen = set()
    exc_id = id(exc)
    if exc_id in _seen:
        return []
    _seen.add(exc_id)

    messages = [str(exc)]

    # Walk ExceptionGroup / BaseExceptionGroup sub-exceptions (Python 3.11+
    # TaskGroup failures).  Use hasattr so this also works on Python 3.10 test
    # environments where BaseExceptionGroup is not a builtin.
    sub_exceptions = getattr(exc, "exceptions", None)
    if sub_exceptions:
        for sub in sub_exceptions:
            if isinstance(sub, BaseException):
                messages.extend(_collect_exception_messages(sub, _seen))

    # Walk explicit cause first, then implicit context
    if exc.__cause__ is not None:
        messages.extend(_collect_exception_messages(exc.__cause__, _seen))
    elif exc.__context__ is not None:
        messages.extend(_collect_exception_messages(exc.__context__, _seen))

    return messages


def _is_acl_denial_nested(exc: BaseException) -> bool:
    """Return True when *any* nested exception message looks like an ACL denial."""
    messages = _collect_exception_messages(exc)
    return any(_is_acl_denial(msg) for msg in messages)


class KongMCPToolClient:
    """
    Synchronous MCP client that routes all calls through Kong MCP Gateway.

    Authenticates to Kong using ``X-Kong-API-Key``.  Kong validates the key
    via key-auth and forwards the request to the upstream MCP server.

    Fail-closed design: any Kong-layer failure raises ``RuntimeError`` with a
    clear message — there is no silent fallback to direct remote MCP.

    Usage::

        settings = get_kong_mcp_gateway_settings()
        client = KongMCPToolClient(settings)
        result = client.call_tool("entity_lookup", {"name": "ACME"})
    """

    def __init__(self, settings: KongMCPGatewaySettings) -> None:
        self._endpoint = settings.gateway_url
        self._headers: dict[str, str] = {
            "X-Kong-API-Key": settings.api_key,
            "Accept": "text/event-stream",
        }
        _log.info("Using Kong MCP Gateway")
        _log.info("Endpoint: %s", self._endpoint)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """
        Call an MCP tool via Kong gateway and return a ToolResult.

        Raises ``RuntimeError`` (fail-closed) on any Kong or transport error.
        Does NOT fall back to direct remote MCP.
        """
        _log.info("[kong_mcp] → %s", tool_name)
        t0 = time.monotonic()
        try:
            raw = asyncio.run(self._call_tool_async(tool_name, arguments))
        except Exception as exc:
            if _is_acl_denial_nested(exc):
                nested_msgs = _collect_exception_messages(exc)
                denial_detail = next(
                    (m for m in reversed(nested_msgs) if _is_acl_denial(m)), str(exc)
                )
                _log.info("[kong_mcp] ACL denial for '%s': %s", tool_name, denial_detail)
                _log.debug(
                    "[kong_mcp] ACL denial full chain for '%s': %s",
                    tool_name, " | ".join(nested_msgs),
                )
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    acl_denied=True,
                    error=denial_detail,
                    input=arguments,
                    summary=f"{tool_name} denied by Kong ACL policy",
                )
            raise RuntimeError(
                f"Kong MCP Gateway call failed for tool '{tool_name}'.\n"
                f"Endpoint: {self._endpoint}\n"
                f"Reason: {exc}\n"
                "Suggestion: check Kong gateway health or set "
                "KONG_MCP_GATEWAY_ENABLED=false to disable."
            ) from exc

        duration = round((time.monotonic() - t0) * 1000, 1)

        if raw is None:
            raise RuntimeError(
                f"Kong MCP Gateway returned no content for tool '{tool_name}'.\n"
                f"Endpoint: {self._endpoint}\n"
                "Suggestion: check Kong gateway health or set "
                "KONG_MCP_GATEWAY_ENABLED=false to disable."
            )

        return ToolResult(
            tool_name=raw.get("tool_name", tool_name),
            success=raw.get("success", True),
            data=raw.get("data"),
            error=raw.get("error"),
            duration_ms=raw.get("duration_ms", duration),
            input=raw.get("input", arguments),
            summary=raw.get("summary", ""),
            acl_denied=raw.get("acl_denied", False),
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
        async with streamablehttp_client(
            self._endpoint, headers=self._headers
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)

                if not result.content:
                    return None

                text = result.content[0].text  # type: ignore[union-attr]

                if result.isError:
                    if _is_acl_denial(text):
                        _log.info("[kong_mcp] ACL denial (isError) for '%s': %s", tool_name, text)
                        return {
                            "tool_name": tool_name,
                            "success": False,
                            "acl_denied": True,
                            "error": text,
                            "input": arguments,
                            "summary": f"{tool_name} denied by Kong ACL policy",
                        }
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
                    return {
                        "tool_name": tool_name,
                        "success": True,
                        "data": {"raw": text},
                        "input": arguments,
                        "summary": text[:200],
                    }
