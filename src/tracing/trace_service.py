"""
TraceService — the single write surface for investigation trace data.

Agents use this class to start traces, record events, and finalize results.
No agent or tool should write Cypher or call TraceRepository directly.

    TraceService
        └── TraceRepository  (Neo4j persistence)
            └── Neo4jRepository  (driver / query execution)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.domain.models import (
    EventType,
    InvestigationRequest,
    InvestigationTrace,
    TraceEvent,
    UserContext,
)
from src.storage.trace_repository import TraceRepository


class TraceService:
    """
    Structured event logging over a Neo4j-backed TraceRepository.

    Args:
        repo: An open TraceRepository instance.
    """

    def __init__(self, repo: TraceRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_trace(
        self,
        request: InvestigationRequest,
        user_context: UserContext,
    ) -> InvestigationTrace:
        """
        Create and persist a new InvestigationTrace node.

        Returns the trace object with request_id populated.
        The caller should hold onto this object and pass it to subsequent
        add_event / finalize_trace calls.
        """
        trace = InvestigationTrace(
            request_id=request.request_id,
            entity_name=request.entity_name,
            user_id=user_context.user_id,
            mode=user_context.metadata.get("mode", "interactive"),
            user_role=user_context.metadata.get("role", ""),
            auth_provider=user_context.metadata.get("auth_provider", ""),
            session_id=user_context.session_id,
            gateway_mode=user_context.metadata.get("gateway_mode", ""),
        )
        # save_trace generates a UUID if request_id is empty; updates in place.
        trace.request_id = self._repo.save_trace(trace)
        return trace

    def finalize_trace(
        self,
        trace: InvestigationTrace,
        final_summary: str | None = None,
    ) -> None:
        """
        Mark the trace as complete and persist the summary.

        Updates the in-memory trace object so callers see the final state.
        """
        trace.ended_at = datetime.now(timezone.utc)
        trace.final_summary = final_summary or ""
        self._repo.finalize_trace(
            trace.request_id,
            final_summary=trace.final_summary,
            ended_at=trace.ended_at.isoformat(),
        )

    def link_retrieved_trace(self, source_trace_id: str, target_trace_id: str) -> None:
        """
        Create a :RETRIEVED edge from the operational trace to the retrieved trace.
        Delegates to TraceRepository. No-op if either ID is empty.
        """
        if source_trace_id and target_trace_id:
            self._repo.link_retrieved_trace(source_trace_id, target_trace_id)

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def add_event(
        self,
        trace: InvestigationTrace,
        event: TraceEvent,
        entity_refs: list[dict] | None = None,
    ) -> None:
        """
        Append a TraceEvent to the trace — both in-memory and in Neo4j.

        Optionally resolves entity_refs and creates
        (event)-[:ABOUT]->(existing business node) edges.

        entity_refs format:
            [{"label": "Company", "name": "ACME Ltd"},
             {"label": "Address", "postal_code": "EC1A 1BB"},
             {"label": "SIC",     "code": "64205"}]

        Business nodes are never created here — only matched.
        Silently skips refs whose node cannot be found.
        """
        trace.add(event)
        self._repo.append_event(trace.request_id, event, entity_refs)

    def create_tool_event(
        self,
        trace: InvestigationTrace,
        event_type: EventType,
        tool_name: str,
        step_id: str | None = None,
        input_summary: str = "",
        output_summary: str = "",
        decision: str = "",
        why: str = "",
        message: str = "",
        agent_name: str = "",
        entity_refs: list[dict] | None = None,
        data: dict | None = None,
    ) -> TraceEvent:
        """
        Build, persist, and return a tool-related TraceEvent.

        Covers the full tool lifecycle:
            EventType.TOOL_CALLED   — before the call
            EventType.TOOL_RETURNED — after a successful call
            EventType.STEP_FAILED   — after a failed call
        """
        event = TraceEvent(
            event_type=event_type,
            step_id=step_id,
            message=message or f"{tool_name} — {event_type.value}",
            payload={
                "agent_name":     agent_name,
                "tool_name":      tool_name,
                "input_summary":  input_summary,
                "output_summary": output_summary,
                "decision":       decision,
                "why":            why,
                "data_json":      json.dumps(data) if data else "",
            },
        )
        self.add_event(trace, event, entity_refs)
        return event

    def create_agent_decision_event(
        self,
        trace: InvestigationTrace,
        message: str,
        decision: str = "",
        why: str = "",
        step_id: str | None = None,
        agent_name: str = "",
        entity_refs: list[dict] | None = None,
    ) -> TraceEvent:
        """
        Build, persist, and return an AGENT_REASONING TraceEvent.

        Use when the agent makes a planning or routing decision that is not
        directly tied to a tool call (e.g. choosing which step to run next,
        deciding to skip a step, or summarising intermediate findings).
        """
        event = TraceEvent(
            event_type=EventType.AGENT_REASONING,
            step_id=step_id,
            message=message,
            payload={
                "agent_name": agent_name,
                "decision":   decision,
                "why":        why,
            },
        )
        self.add_event(trace, event, entity_refs)
        return event
