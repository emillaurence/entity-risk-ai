"""
GraphAgent — specialist agent for graph exploration and entity context retrieval.

Responsibilities:
  - call the correct graph MCP tool for each supported task via MCPToolClient
  - log every tool call via BaseAgent helpers (→ Neo4j trace)
  - optionally enrich the result with an AI-generated natural-language summary

Does NOT contain:
  - Cypher or direct Neo4j usage
  - risk-scoring logic (→ RiskAgent)
  - trace retrieval (→ TraceAgent)
  - direct references to GraphTools — all tool access goes through MCP

Supported tasks
---------------
  entity_lookup          search by partial name (full-text index)
  company_profile        address + SIC codes + direct owners
  expand_ownership       ownership paths up to max_depth hops + UBOs
  shared_address_check   co-location count at registered address
  sic_context            SIC codes + industry peer list
"""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.clients.ai_client import AIClient
from src.clients.mcp_tool_client import MCPToolClient
from src.domain.models import AgentResult, InvestigationTrace
from src.tracing.trace_service import TraceService


# Tasks this agent knows how to handle.
_SUPPORTED_TASKS = frozenset({
    "entity_lookup",
    "company_profile",
    "expand_ownership",
    "shared_address_check",
    "sic_context",
})

# Tasks whose output is not suitable for AI enrichment:
#   entity_lookup  — returns multiple name-match candidates, not a single-company finding
#   sic_context    — factual SIC code + peer list; low compliance narrative value
_NO_AI_ENRICHMENT_TASKS = frozenset({"entity_lookup", "sic_context"})

_SYSTEM_PROMPT = (
    "You are a financial crime risk analyst. "
    "Given a structured finding about a company, write one clear, concise sentence "
    "in plain English that captures what a compliance analyst needs to know. "
    "Do not use bullet points or markdown."
)


class GraphAgent(BaseAgent):
    """
    Investigation agent that explores the Neo4j business graph via MCP.

    Args:
        mcp_client:    MCPToolClient — all tool calls go through this.
        trace_service: Shared TraceService for structured event logging.
        ai_client:     Optional AI client. When present, each result is
                       enriched with a one-sentence natural-language summary
                       (Haiku by default for speed).
    """

    def __init__(
        self,
        mcp_client: MCPToolClient,
        trace_service: TraceService,
        ai_client: AIClient | None = None,
    ) -> None:
        super().__init__("graph-agent", trace_service, ai_client)
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
        Execute a graph task and return an AgentResult.

        Args:
            task:    One of the supported task names (see module docstring).
            context: Must contain ``company_name: str``.
                     ``expand_ownership`` also accepts ``max_depth: int`` (default 5).
            trace:   The active InvestigationTrace to log events into.
        """
        company_name = context.get("company_name") or context.get("name", "")

        if task not in _SUPPORTED_TASKS:
            return AgentResult(
                request_id=trace.request_id,
                entity_name=company_name,
                success=False,
                error=(
                    f"Unknown task '{task}'. "
                    f"Supported tasks: {', '.join(sorted(_SUPPORTED_TASKS))}."
                ),
                trace=trace,
                tools_used=[],
            )

        if not company_name:
            return AgentResult(
                request_id=trace.request_id,
                entity_name="",
                success=False,
                error="context must include a non-empty 'company_name'.",
                trace=trace,
                tools_used=[],
            )

        # ---- dispatch ------------------------------------------------
        result, entity_refs = self._dispatch(task, company_name, context)

        # ---- build input summary from what was actually passed -------
        input_summary = ", ".join(f"{k}={v}" for k, v in result.input.items())

        # ---- log to trace --------------------------------------------
        self.log_tool_event(
            trace,
            tool_name=result.tool_name,
            input_summary=input_summary,
            output_summary=result.summary,
            decision="result available for downstream agents" if result.success else "step failed",
            entity_refs=entity_refs,
        )

        if not result.success:
            return AgentResult(
                request_id=trace.request_id,
                entity_name=company_name,
                success=False,
                summary=result.summary,
                findings={task: None},
                trace=trace,
                error=result.error,
                tools_used=[result.tool_name],
            )

        # ---- optional AI enrichment ----------------------------------
        summary = result.summary
        if self._ai_client and result.data and task not in _NO_AI_ENRICHMENT_TASKS:
            ai_text = self.generate_ai_summary(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=result.summary,
                max_tokens=80,
            )
            if ai_text:
                summary = ai_text
                usage = self._last_ai_usage
                token_info = (
                    f" | tokens in={usage['input_tokens']} out={usage['output_tokens']}"
                    if usage else ""
                )
                self.log_decision_event(
                    trace,
                    decision=f"AI summary generated for task '{task}'{token_info}",
                    why=ai_text,
                )

        return AgentResult(
            request_id=trace.request_id,
            entity_name=company_name,
            success=True,
            summary=summary,
            findings={task: result.data},
            trace=trace,
            tools_used=[result.tool_name],
        )

    # ------------------------------------------------------------------
    # Private dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        task: str,
        company_name: str,
        context: dict[str, Any],
    ):
        """
        Call the correct MCP tool and return (ToolResult, entity_refs).
        entity_refs is None for entity_lookup because the company may not yet
        exist as a node (the search is by partial name, not exact match).
        """
        company_ref = [{"label": "Company", "name": company_name}]

        if task == "entity_lookup":
            return self._mcp.call_tool("entity_lookup", {"name": company_name}), None

        if task == "company_profile":
            return (
                self._mcp.call_tool("company_profile", {"company_name": company_name}),
                company_ref,
            )

        if task == "expand_ownership":
            max_depth = int(context.get("max_depth", 5))
            return (
                self._mcp.call_tool(
                    "expand_ownership",
                    {"company_name": company_name, "max_depth": max_depth},
                ),
                company_ref,
            )

        if task == "shared_address_check":
            return (
                self._mcp.call_tool("shared_address_check", {"company_name": company_name}),
                company_ref,
            )

        # sic_context
        return (
            self._mcp.call_tool("sic_context", {"company_name": company_name}),
            company_ref,
        )
