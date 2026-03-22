"""
TraceAgent — specialist agent for retrieving and explaining investigation traces.

Responsibilities:
  - retrieve stored traces from Neo4j via trace MCP tools through MCPToolClient
  - find traces linked to a specific business entity
  - produce audit-friendly summaries (AI-enriched or template-based fallback)

Does NOT contain:
  - Cypher or direct Neo4j usage
  - risk-scoring logic (→ RiskAgent)
  - graph exploration (→ GraphAgent)
  - direct references to TraceTools — all tool access goes through MCP

Recursion constraint
--------------------
TraceAgent logs its own activity into an *operational* trace (the `trace`
parameter in `run()`).  The *target* trace — the historical record being
retrieved or summarised — is a separate object returned as data inside
AgentResult.findings.  These two must never be the same trace.

If a caller passes `trace_id` equal to the operational trace's own
`request_id`, `run()` returns an error rather than risk creating a
self-referential trace.

Supported tasks
---------------
  retrieve_trace               load a full trace dict by ID
  find_traces_by_entity        list traces linked to a named entity
  summarize_trace              produce a narrative from a trace dict in context
  retrieve_and_summarize_trace retrieve + summarise in one call
"""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.clients.ai_client import AIClient
from src.clients.mcp_tool_client import MCPToolClient
from src.domain.models import AgentResult, EventType, InvestigationTrace
from src.tracing.trace_service import TraceService


_SUPPORTED_TASKS = frozenset({
    "retrieve_trace",
    "find_traces_by_entity",
    "summarize_trace",
    "retrieve_and_summarize_trace",
})

_SYSTEM_PROMPT = (
    "You are a financial crime compliance analyst reviewing an investigation audit trail. "
    "Given a structured log of agent actions and tool calls, write a concise audit summary "
    "(3-5 sentences) that explains: what was investigated, what tools were run, "
    "what risk signals were found, and whether any follow-up or escalation appears warranted. "
    "Do not use bullet points or markdown."
)


class TraceAgent(BaseAgent):
    """
    Investigation agent for retrieving and explaining Neo4j-backed traces via MCP.

    Args:
        mcp_client:    MCPToolClient — all tool calls go through this.
        trace_service: Shared TraceService for logging the agent's own activity.
        ai_client:     Optional AI client. When present, summaries are AI-generated.
                       Haiku is used by default; pass ``model=<id>`` in context
                       to override (e.g. ``settings.model_sonnet``).
    """

    def __init__(
        self,
        mcp_client: MCPToolClient,
        trace_service: TraceService,
        ai_client: AIClient | None = None,
    ) -> None:
        super().__init__("trace-agent", trace_service, ai_client)
        self._mcp = mcp_client

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    def run(
        self,
        task: str,
        context: dict[str, Any],
        trace: InvestigationTrace,
    ) -> AgentResult:
        """
        Execute a trace task and return an AgentResult.

        Args:
            task:    One of the supported task names (see module docstring).
            context: Task-specific inputs:
                     - ``retrieve_trace``              → ``trace_id: str``
                     - ``find_traces_by_entity``       → ``entity_name: str``
                     - ``summarize_trace``             → ``trace_data: dict``
                                                         ``model: str`` (optional)
                     - ``retrieve_and_summarize_trace``→ ``trace_id: str``
                                                         ``model: str`` (optional)
            trace:   The agent's own *operational* trace. Must differ from any
                     target trace being retrieved (enforced for retrieve tasks).
        """
        if task not in _SUPPORTED_TASKS:
            return AgentResult(
                request_id=trace.request_id,
                entity_name="",
                success=False,
                error=(
                    f"Unknown task '{task}'. "
                    f"Supported tasks: {', '.join(sorted(_SUPPORTED_TASKS))}."
                ),
                trace=trace,
            )

        if task == "retrieve_trace":
            return self._retrieve(context, trace)
        if task == "find_traces_by_entity":
            return self._find_by_entity(context, trace)
        if task == "summarize_trace":
            return self._summarize(context, trace)
        # retrieve_and_summarize_trace
        return self._retrieve_and_summarize(context, trace)

    # ------------------------------------------------------------------
    # Private — retrieve_trace
    # ------------------------------------------------------------------

    def _retrieve(
        self, context: dict[str, Any], trace: InvestigationTrace
    ) -> AgentResult:
        trace_id = context.get("trace_id", "").strip()
        if not trace_id:
            return self._input_error(trace, "context must include a non-empty 'trace_id'.")

        # Recursion guard: refuse to retrieve the operational trace itself.
        if trace_id == trace.request_id:
            return self._input_error(
                trace,
                f"trace_id '{trace_id}' is the agent's own operational trace. "
                "Pass a different trace_id to avoid self-referential retrieval.",
            )

        result = self._mcp.call_tool("retrieve_trace", {"trace_id": trace_id})
        self.log_tool_event(
            trace,
            tool_name=result.tool_name,
            input_summary=f"trace_id={trace_id}",
            output_summary=result.summary,
            decision="trace data available" if result.success else "retrieval failed",
        )

        if not result.success:
            return AgentResult(
                request_id=trace.request_id,
                entity_name=trace_id,
                success=False,
                summary=result.summary,
                findings={"retrieve_trace": None},
                trace=trace,
                error=result.error,
            )

        entity_name = result.data.get("query", "") if result.data else ""
        return AgentResult(
            request_id=trace.request_id,
            entity_name=entity_name,
            success=True,
            summary=result.summary,
            findings={"retrieve_trace": result.data},
            trace=trace,
        )

    # ------------------------------------------------------------------
    # Private — find_traces_by_entity
    # ------------------------------------------------------------------

    def _find_by_entity(
        self, context: dict[str, Any], trace: InvestigationTrace
    ) -> AgentResult:
        entity_name = context.get("entity_name", "").strip()
        if not entity_name:
            return self._input_error(
                trace, "context must include a non-empty 'entity_name'."
            )

        result = self._mcp.call_tool(
            "find_traces_by_entity", {"entity_name": entity_name}
        )
        self.log_tool_event(
            trace,
            tool_name=result.tool_name,
            input_summary=f"entity_name={entity_name}",
            output_summary=result.summary,
            decision="trace list available" if result.success else "lookup failed",
            entity_refs=[{"label": "Company", "name": entity_name}],
        )

        if not result.success:
            return AgentResult(
                request_id=trace.request_id,
                entity_name=entity_name,
                success=False,
                summary=result.summary,
                findings={"find_traces_by_entity": None},
                trace=trace,
                error=result.error,
            )

        return AgentResult(
            request_id=trace.request_id,
            entity_name=entity_name,
            success=True,
            summary=result.summary,
            findings={"find_traces_by_entity": result.data},
            trace=trace,
        )

    # ------------------------------------------------------------------
    # Private — summarize_trace
    # ------------------------------------------------------------------

    def _summarize(
        self, context: dict[str, Any], trace: InvestigationTrace
    ) -> AgentResult:
        trace_data = context.get("trace_data")
        if not trace_data or not isinstance(trace_data, dict):
            return self._input_error(
                trace,
                "context must include 'trace_data' as a non-empty dict "
                "(use retrieve_trace first, then pass result.data here).",
            )

        target_id = trace_data.get("trace_id", "")
        entity_name = trace_data.get("query", "")

        # Recursion guard: refuse to summarise the operational trace itself.
        if target_id and target_id == trace.request_id:
            return self._input_error(
                trace,
                f"trace_data refers to the agent's own operational trace '{target_id}'. "
                "Pass a different trace to avoid self-referential summarisation.",
            )

        user_prompt = _trace_to_prompt(trace_data)
        model = context.get("model")

        if self._ai_client:
            ai_text = self.generate_ai_summary(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=model,
                max_tokens=250,
            )
        else:
            ai_text = None

        if ai_text:
            summary = ai_text
            usage = self._last_ai_usage
            token_info = (
                f" | tokens in={usage['input_tokens']} out={usage['output_tokens']}"
                if usage
                else ""
            )
            self.log_decision_event(
                trace,
                decision=f"AI audit summary generated for trace '{target_id}'{token_info}",
                why=ai_text,
            )
        else:
            summary = _template_summary(trace_data)
            self.log_decision_event(
                trace,
                decision=f"Template summary generated for trace '{target_id}'",
                why=summary,
            )

        return AgentResult(
            request_id=trace.request_id,
            entity_name=entity_name,
            success=True,
            summary=summary,
            findings={
                "summarize_trace": {
                    "target_trace_id": target_id,
                    "entity_name": entity_name,
                    "summary": summary,
                    "ai_enriched": ai_text is not None,
                }
            },
            trace=trace,
        )

    # ------------------------------------------------------------------
    # Private — retrieve_and_summarize_trace
    # ------------------------------------------------------------------

    def _retrieve_and_summarize(
        self, context: dict[str, Any], trace: InvestigationTrace
    ) -> AgentResult:
        trace_id = context.get("trace_id", "").strip()
        if not trace_id:
            return self._input_error(
                trace, "context must include a non-empty 'trace_id'."
            )

        # Recursion guard.
        if trace_id == trace.request_id:
            return self._input_error(
                trace,
                f"trace_id '{trace_id}' is the agent's own operational trace. "
                "Pass a different trace_id to avoid self-referential retrieval.",
            )

        # Step 1 — retrieve.
        retrieve_result = self._mcp.call_tool(
            "retrieve_trace", {"trace_id": trace_id}
        )
        self.log_tool_event(
            trace,
            tool_name=retrieve_result.tool_name,
            input_summary=f"trace_id={trace_id}",
            output_summary=retrieve_result.summary,
            decision=(
                "trace retrieved — proceeding to summarise"
                if retrieve_result.success
                else "retrieval failed — cannot summarise"
            ),
        )

        if not retrieve_result.success:
            return AgentResult(
                request_id=trace.request_id,
                entity_name=trace_id,
                success=False,
                summary=retrieve_result.summary,
                findings={"retrieve_and_summarize_trace": None},
                trace=trace,
                error=retrieve_result.error,
            )

        trace_data = retrieve_result.data
        entity_name = trace_data.get("query", "") if trace_data else ""

        # Step 2 — summarise (reuse _summarize logic via context).
        summarize_ctx = {
            "trace_data": trace_data,
            "model": context.get("model"),
        }
        summary_result = self._summarize(summarize_ctx, trace)

        return AgentResult(
            request_id=trace.request_id,
            entity_name=entity_name,
            success=summary_result.success,
            summary=summary_result.summary,
            findings={
                "retrieve_and_summarize_trace": {
                    "trace_data": trace_data,
                    **(summary_result.findings.get("summarize_trace") or {}),
                }
            },
            trace=trace,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _input_error(self, trace: InvestigationTrace, msg: str) -> AgentResult:
        return AgentResult(
            request_id=trace.request_id,
            entity_name="",
            success=False,
            error=msg,
            trace=trace,
        )


# ---------------------------------------------------------------------------
# Module-level helpers — no state, no imports from agents
# ---------------------------------------------------------------------------

def _trace_to_prompt(trace_data: dict) -> str:
    """
    Render a stored trace dict as a plain-text prompt for the AI summariser.
    Keeps each event to one line so the prompt stays compact.
    """
    entity = trace_data.get("query", "unknown entity")
    mode = trace_data.get("mode", "?")
    started = trace_data.get("started_at", "?")
    ended = trace_data.get("ended_at") or "not finalized"
    final = trace_data.get("final_summary") or ""
    events = trace_data.get("events", [])

    lines = [
        f"Investigation of: {entity}",
        f"Mode: {mode} | Started: {started} | Ended: {ended}",
    ]
    if final:
        lines.append(f"Stored summary: {final}")
    lines.append(f"Event log ({len(events)} event(s)):")

    for e in events:
        etype = e.get("event_type") or ""
        tool = e.get("tool_name") or ""
        output = (e.get("output_summary") or "")[:120]
        decision = (e.get("decision") or "")[:80]
        parts = [f"  [{etype}]"]
        if tool:
            parts.append(tool)
        if output:
            parts.append(f"→ {output}")
        if decision:
            parts.append(f"| {decision}")
        lines.append(" ".join(parts))

    return "\n".join(lines)


def _template_summary(trace_data: dict) -> str:
    """
    Deterministic fallback summary when no AI client is configured.
    Produces a single readable sentence from the trace metadata.
    """
    entity = trace_data.get("query", "unknown entity")
    events = trace_data.get("events", [])
    tools = sorted({e["tool_name"] for e in events if e.get("tool_name")})
    started = trace_data.get("started_at", "?")
    ended = trace_data.get("ended_at") or "not finalized"
    final = trace_data.get("final_summary") or ""

    tool_list = ", ".join(tools) if tools else "no tools recorded"
    base = (
        f"Investigation of '{entity}': {len(events)} event(s) using {tool_list}. "
        f"Started {started}, ended {ended}."
    )
    return f"{base} {final}".strip() if final else base
