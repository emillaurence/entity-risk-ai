"""
BaseAgent — shared foundation for all specialist agents.

Provides:
  - agent identity (name)
  - optional AI client access
  - trace logging helpers (log_tool_event, log_decision_event)
  - stdlib logger per agent (namespaced under "agent.<name>")

Does NOT contain:
  - Cypher or repository logic
  - graph, risk, or trace-specific task handling
  - orchestration or planning logic

Dependency chain:
    ConcreteAgent
        └── BaseAgent
                ├── TraceService  (structured Neo4j trace persistence)
                └── AIClient      (optional, provider-agnostic AI access)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from src.clients.ai_client import AIClient
from src.domain.models import AgentResult, EventType, InvestigationTrace
from src.tracing.trace_service import TraceService


class BaseAgent(ABC):
    """
    Abstract base class for all investigation agents.

    Args:
        name:          Stable agent identifier, e.g. "graph-agent".
                       Used as the logger name and stored on trace events.
        trace_service: The single write surface for Neo4j trace persistence.
        ai_client:     Optional AI abstraction for agents that generate
                       summaries or reasoning text via an LLM.
    """

    def __init__(
        self,
        name: str,
        trace_service: TraceService,
        ai_client: AIClient | None = None,
    ) -> None:
        self.name = name
        self._trace_service = trace_service
        self._ai_client = ai_client
        # Logger namespaced under "agent.<name>" so all agent loggers
        # can be filtered or routed together at the app level.
        self._log = logging.getLogger(f"agent.{name}")
        # Token usage from the most recent generate_ai_summary() call.
        # None when no AI client is configured or the call failed.
        self._last_ai_usage: dict[str, int] | None = None

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def run(
        self,
        task: str,
        context: dict[str, Any],
        trace: InvestigationTrace,
    ) -> AgentResult:
        """
        Execute a task and return an AgentResult.

        Args:
            task:    The action to perform (e.g. "ownership_check").
            context: Structured input data for the task
                     (e.g. {"company_name": "ACME Ltd", "max_depth": 3}).
            trace:   The active InvestigationTrace to log events into.

        Returns:
            An AgentResult with success flag, summary, findings, and trace.
        """

    # ------------------------------------------------------------------
    # Trace helpers — called by subclasses, never override needed
    # ------------------------------------------------------------------

    def log_tool_event(
        self,
        trace: InvestigationTrace,
        tool_name: str,
        input_summary: str = "",
        output_summary: str = "",
        decision: str = "",
        why: str = "",
        step_id: str | None = None,
        entity_refs: list[dict] | None = None,
    ) -> None:
        """
        Persist a TOOL_RETURNED event attributed to this agent.

        Call this after a tool returns so the trace records what the agent
        called, what came back, and what it decided to do next.

        Args:
            trace:          The active trace.
            tool_name:      Name of the tool that was called.
            input_summary:  Short description of what was passed to the tool.
            output_summary: Short description of what the tool returned.
            decision:       What the agent will do next based on the result.
            why:            Reasoning behind the decision.
            step_id:        Plan step this event belongs to, if any.
            entity_refs:    Business nodes to link via :ABOUT
                            (e.g. [{"label": "Company", "name": "ACME Ltd"}]).
        """
        self._log.debug(
            "tool_returned tool=%s input=%r output=%r decision=%r",
            tool_name, input_summary, output_summary, decision,
        )
        self._trace_service.create_tool_event(
            trace,
            event_type=EventType.TOOL_RETURNED,
            tool_name=tool_name,
            step_id=step_id,
            input_summary=input_summary,
            output_summary=output_summary,
            decision=decision,
            why=why,
            agent_name=self.name,
            entity_refs=entity_refs,
        )

    def log_decision_event(
        self,
        trace: InvestigationTrace,
        decision: str,
        why: str | None = None,
        step_id: str | None = None,
        entity_refs: list[dict] | None = None,
    ) -> None:
        """
        Persist an AGENT_REASONING event attributed to this agent.

        Use when the agent makes a planning or routing decision not tied to
        a specific tool call — e.g. choosing which step runs next, deciding
        to skip a step, or summarising intermediate findings.

        Args:
            trace:       The active trace.
            decision:    The decision made (also used as the event message).
            why:         Reasoning behind the decision.
            step_id:     Plan step this event belongs to, if any.
            entity_refs: Business nodes to link via :ABOUT.
        """
        self._log.debug("decision=%r why=%r", decision, why)
        self._trace_service.create_agent_decision_event(
            trace,
            message=decision,
            decision=decision,
            why=why or "",
            step_id=step_id,
            agent_name=self.name,
            entity_refs=entity_refs,
        )

    # ------------------------------------------------------------------
    # AI helper — optional, generic, no domain-specific prompts here
    # ------------------------------------------------------------------

    def generate_ai_summary(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str | None:
        """
        Return an AI-generated text summary, or None if no client is set.

        Subclasses supply their own prompts; BaseAgent stays generic.
        Failures are caught and logged — the agent remains operational
        even when AI is unavailable.

        Args:
            system_prompt: Instructions that set the model's behaviour.
            user_prompt:   The content the model should respond to.
            model:         Override the client's default model.

        Returns:
            A text string, or None if ai_client is absent or the call fails.
        """
        if self._ai_client is None:
            self._log.debug("generate_ai_summary skipped — no ai_client configured")
            return None
        self._last_ai_usage = None
        try:
            text = self._ai_client.generate_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
            )
            self._last_ai_usage = getattr(self._ai_client, "last_usage", None)
            return text
        except Exception as exc:
            self._log.warning("generate_ai_summary failed: %s", exc)
            return None
