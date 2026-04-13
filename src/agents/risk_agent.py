"""
RiskAgent — specialist agent for interpreting graph-derived risk signals.

Responsibilities:
  - call risk MCP tools via MCPToolClient for deterministic risk heuristics
  - log every tool call via BaseAgent helpers (→ Neo4j trace)

Does NOT contain:
  - Cypher or direct Neo4j usage
  - graph exploration logic (→ GraphAgent)
  - trace retrieval (→ TraceAgent)
  - direct references to RiskTools — all tool access goes through MCP

Supported tasks
---------------
  ownership_complexity_check   structural complexity of the ownership chain
  control_signal_check         nature-of-control types across the chain
  address_risk_check           registered address co-location signals
  industry_context_check       SIC-code industry risk flags

AI synthesis of risk signals is performed at finalization time by the
orchestrator's _build_final_answer(), not here.
"""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.clients.ai_client import AIClient
from src.clients.mcp_tool_client import MCPToolClient
from src.domain.models import AgentResult, InvestigationTrace
from src.tracing.trace_service import TraceService


_SUPPORTED_TASKS = frozenset({
    "ownership_complexity_check",
    "control_signal_check",
    "address_risk_check",
    "industry_context_check",
})


class RiskAgent(BaseAgent):
    """
    Investigation agent that interprets risk signals from the Neo4j business graph via MCP.

    Args:
        mcp_client:    MCPToolClient — all tool calls go through this.
        trace_service: Shared TraceService for structured event logging.
        ai_client:     Optional AI client (reserved for future per-step enrichment).
    """

    def __init__(
        self,
        mcp_client: MCPToolClient,
        trace_service: TraceService,
        ai_client: AIClient | None = None,
    ) -> None:
        super().__init__("risk-agent", trace_service, ai_client)
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
        Execute a risk task and return an AgentResult.

        Args:
            task:    One of the supported task names (see module docstring).
            context: Must contain ``company_name: str``.
                     ``ownership_complexity_check`` and ``control_signal_check``
                     also accept ``max_depth: int`` (default 5).
            trace:   The active InvestigationTrace to log events into.
        """
        company_name = context.get("company_name", "")

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

        return self._run_direct_task(task, company_name, context, trace)

    # ------------------------------------------------------------------
    # Private — direct tool tasks
    # ------------------------------------------------------------------

    def _run_direct_task(
        self,
        task: str,
        company_name: str,
        context: dict[str, Any],
        trace: InvestigationTrace,
    ) -> AgentResult:
        company_ref = [{"label": "Company", "name": company_name}]
        result = self._call_tool(task, company_name, context)

        input_summary = ", ".join(f"{k}={v}" for k, v in result.input.items())
        self.log_tool_event(
            trace,
            tool_name=result.tool_name,
            input_summary=input_summary,
            output_summary=result.summary,
            decision=(
                "risk signal available for downstream agents"
                if result.success
                else "step failed"
            ),
            entity_refs=company_ref,
            data=result.data,
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
                acl_denied=result.acl_denied,
                tools_used=[result.tool_name],
            )

        return AgentResult(
            request_id=trace.request_id,
            entity_name=company_name,
            success=True,
            summary=result.summary,
            findings={task: result.data},
            trace=trace,
            tools_used=[result.tool_name],
        )

    # ------------------------------------------------------------------
    # Private — tool dispatch
    # ------------------------------------------------------------------

    def _call_tool(
        self,
        task: str,
        company_name: str,
        context: dict[str, Any],
    ):
        """Call the matching MCP risk tool and return its ToolResult."""
        max_depth = int(context.get("max_depth", 20))

        if task == "ownership_complexity_check":
            return self._mcp.call_tool(
                "ownership_complexity_check",
                {"company_name": company_name, "max_depth": max_depth},
            )
        if task == "control_signal_check":
            return self._mcp.call_tool(
                "control_signal_check",
                {"company_name": company_name, "max_depth": max_depth},
            )
        if task == "address_risk_check":
            return self._mcp.call_tool(
                "address_risk_check", {"company_name": company_name}
            )
        # industry_context_check
        return self._mcp.call_tool(
            "industry_context_check", {"company_name": company_name}
        )
