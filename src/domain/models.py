"""
Core domain models for entity risk investigation.

These are plain dataclasses with no framework dependencies.
They flow through the agent pipeline: a UserContext seeds an
InvestigationRequest, which the planner breaks into PlanSteps,
each step produces a ToolResult, and all activity is recorded
as TraceEvents collected into an InvestigationTrace. The final
AgentResult packages everything for the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class EventType(str, Enum):
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    TOOL_CALLED = "tool_called"
    TOOL_RETURNED = "tool_returned"
    AGENT_REASONING = "agent_reasoning"
    INVESTIGATION_COMPLETE = "investigation_complete"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class UserContext:
    """
    Describes who is running the investigation and with what permissions.

    Attributes:
        user_id:     Opaque identifier for the requesting user or system.
        session_id:  Identifier for the current work session (groups related requests).
        metadata:    Arbitrary key-value context (e.g. tenant, role, source system).
    """

    user_id: str
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InvestigationRequest:
    """
    A single investigation task submitted by a user.

    Attributes:
        entity_name:   The company or person name to investigate.
        context:       The user/session context that originated this request.
        request_id:    Unique identifier for this specific request.
        focus_areas:   Optional list of investigation aspects to prioritise
                       (e.g. ["ownership", "address_risk", "sic_anomaly"]).
        max_depth:     How many ownership hops the planner may traverse.
        created_at:    UTC timestamp when the request was created.
    """

    entity_name: str
    context: UserContext
    request_id: str = ""
    focus_areas: list[str] = field(default_factory=list)
    max_depth: int = 5
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PlanStep:
    """
    One discrete action in an investigation plan.

    Attributes:
        step_id:     Stable identifier within the plan (e.g. "step_1").
        tool_name:   The repository method or tool to call.
        description: Human-readable explanation of why this step is needed.
        parameters:  Arguments to pass to the tool.
        depends_on:  step_ids that must complete successfully before this runs.
        status:      Lifecycle state of the step.
        result:      Populated after the step executes.
    """

    step_id: str
    tool_name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: ToolResult | None = None


@dataclass
class ToolResult:
    """
    The outcome of executing a single PlanStep tool call.

    Attributes:
        tool_name:  The tool that produced this result.
        success:    False if the tool raised an exception.
        data:       The structured return value (list[dict], dict, etc.).
        error:      Exception message when success is False.
        duration_ms: Wall-clock time the tool call took.
    """

    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    input: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass
class TraceEvent:
    """
    An immutable record of one moment in the investigation lifecycle.

    Attributes:
        event_type:  Classifies what happened (see EventType).
        step_id:     The plan step this event belongs to, if any.
        message:     Human-readable description of the event.
        payload:     Structured data relevant to this event.
        timestamp:   UTC time the event was recorded.
    """

    event_type: EventType
    message: str
    step_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InvestigationTrace:
    """
    Append-only log of every event that occurred during an investigation.

    Use `add()` to record events. The trace is the source of truth for
    replay, auditing, and explanation generation.

    Attributes:
        request_id:  Links this trace to an InvestigationRequest.
        entity_name: The entity that was investigated (for search/listing).
        question:    Original free-text question submitted by the user.
        created_at:  UTC timestamp when the trace was created.
        events:      Ordered list of TraceEvents.
    """

    request_id: str
    entity_name: str = ""
    question: str = ""
    user_id: str = ""
    mode: str = "interactive"
    final_summary: str = ""
    ended_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    events: list[TraceEvent] = field(default_factory=list)

    def add(self, event: TraceEvent) -> None:
        """Append an event to the trace."""
        self.events.append(event)

    def events_for_step(self, step_id: str) -> list[TraceEvent]:
        """Return all events belonging to a specific plan step."""
        return [e for e in self.events if e.step_id == step_id]

    def failed_steps(self) -> list[str]:
        """Return step_ids of every step that emitted a STEP_FAILED event."""
        return [
            e.step_id
            for e in self.events
            if e.event_type == EventType.STEP_FAILED and e.step_id
        ]


@dataclass
class AgentResult:
    """
    The final output returned to the caller after an investigation completes.

    Attributes:
        request_id:  The originating request.
        entity_name: The entity that was investigated.
        success:     False if the investigation could not complete.
        summary:     Natural-language summary produced by the agent.
        findings:    Structured findings keyed by topic
                     (e.g. {"ownership": [...], "address_risk": [...]}).
        trace:       Full event trace for auditing and explanation.
        error:       Top-level error message if success is False.
        tools_used:  Ordered list of MCP tool names called during this task.
                     Empty when the agent failed before calling any tool.
    """

    request_id: str
    entity_name: str
    success: bool
    summary: str = ""
    findings: dict[str, Any] = field(default_factory=dict)
    trace: InvestigationTrace | None = None
    error: str | None = None
    tools_used: list[str] = field(default_factory=list)
