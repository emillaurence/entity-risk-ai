"""
Tools for retrieving and listing Neo4j-backed investigation traces.
"""

import time

from src.domain.models import ToolResult
from src.storage.trace_repository import TraceRepository


class TraceTools:
    def __init__(self, repo: TraceRepository) -> None:
        self._repo = repo

    def retrieve_trace(self, trace_id: str) -> ToolResult:
        """Load a full trace by its ID."""
        t0 = time.monotonic()
        try:
            if not trace_id or not trace_id.strip():
                raise ValueError("trace_id must be a non-empty string.")

            trace = self._repo.load_trace(trace_id)
            event_count = len(trace.get("events", []))

            summary = (
                f"Trace '{trace_id}' for '{trace.get('query', '')}': "
                f"{event_count} event(s)."
            )
            return ToolResult(
                tool_name="retrieve_trace",
                success=True,
                data=trace,
                duration_ms=_ms(t0),
                input={"trace_id": trace_id},
                summary=summary,
            )
        except KeyError:
            return ToolResult(
                tool_name="retrieve_trace",
                success=False,
                error=f"No trace found with id '{trace_id}'.",
                duration_ms=_ms(t0),
                input={"trace_id": trace_id},
                summary=f"Trace '{trace_id}' not found.",
            )
        except Exception as e:
            return _error("retrieve_trace", {"trace_id": trace_id}, e, _ms(t0))

    def find_traces_by_entity(self, entity_name: str) -> ToolResult:
        """Find traces linked to a business entity by exact name."""
        t0 = time.monotonic()
        try:
            if not entity_name or not entity_name.strip():
                raise ValueError("entity_name must be a non-empty string.")

            rows = self._repo.find_traces_by_entity(entity_name)
            summary = (
                f"Found {len(rows)} trace(s) connected to '{entity_name}'."
                if rows
                else f"No traces found connected to '{entity_name}'."
            )
            return ToolResult(
                tool_name="find_traces_by_entity",
                success=True,
                data=rows,
                duration_ms=_ms(t0),
                input={"entity_name": entity_name},
                summary=summary,
            )
        except Exception as e:
            return _error(
                "find_traces_by_entity", {"entity_name": entity_name}, e, _ms(t0)
            )

    def list_recent_traces(self, limit: int = 20) -> ToolResult:
        """Return the most recent traces, newest first."""
        t0 = time.monotonic()
        try:
            if limit < 1:
                raise ValueError("limit must be >= 1.")

            rows = self._repo.list_traces(limit=limit)
            summary = (
                f"Found {len(rows)} recent trace(s)."
                if rows
                else "No traces stored yet."
            )
            return ToolResult(
                tool_name="list_recent_traces",
                success=True,
                data=rows,
                duration_ms=_ms(t0),
                input={"limit": limit},
                summary=summary,
            )
        except Exception as e:
            return _error("list_recent_traces", {"limit": limit}, e, _ms(t0))


def _ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 1)


def _error(tool_name: str, input_: dict, exc: Exception, duration_ms: float) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        success=False,
        error=str(exc),
        duration_ms=duration_ms,
        input=input_,
        summary=f"{tool_name} failed: {exc}",
    )
