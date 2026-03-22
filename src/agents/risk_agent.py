"""
RiskAgent — specialist agent for interpreting graph-derived risk signals.

Responsibilities:
  - call RiskTools for deterministic risk heuristics
  - log every tool call via BaseAgent helpers (→ Neo4j trace)
  - for summarize_risk_for_company: gather all 4 risk signals and use
    AIClient to produce a concise natural-language risk assessment

Does NOT contain:
  - Cypher or direct Neo4j usage
  - graph exploration logic (→ GraphAgent)
  - trace retrieval (→ TraceAgent)

Supported tasks
---------------
  ownership_complexity_check   structural complexity of the ownership chain
  control_signal_check         nature-of-control types across the chain
  address_risk_check           registered address co-location signals
  industry_context_check       SIC-code industry risk flags
  summarize_risk_for_company   run all 4 checks + AI narrative synthesis
"""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.clients.ai_client import AIClient
from src.domain.models import AgentResult, InvestigationTrace
from src.tools.risk_tools import RiskTools
from src.tracing.trace_service import TraceService


_SUPPORTED_TASKS = frozenset({
    "ownership_complexity_check",
    "control_signal_check",
    "address_risk_check",
    "industry_context_check",
    "summarize_risk_for_company",
})

_DIRECT_TOOL_TASKS = frozenset({
    "ownership_complexity_check",
    "control_signal_check",
    "address_risk_check",
    "industry_context_check",
})

_SYSTEM_PROMPT = (
    "You are a financial crime compliance analyst. "
    "Given structured risk signals for a company, write a concise risk assessment "
    "(2-4 sentences) for a compliance analyst deciding whether to escalate. "
    "Reference the specific signals: ownership chain, control types, address "
    "co-location, and industry. State the overall risk level (LOW / MEDIUM / HIGH). "
    "Do not use bullet points or markdown."
)


class RiskAgent(BaseAgent):
    """
    Investigation agent that interprets risk signals from the Neo4j business graph.

    Args:
        tools:         RiskTools instance for deterministic risk heuristics.
        trace_service: Shared TraceService for structured event logging.
        ai_client:     Optional AI client. Required for summarize_risk_for_company.
                       Haiku is used by default; pass ``model=<id>`` in context
                       to override (e.g. ``settings.model_sonnet`` for Sonnet).
    """

    def __init__(
        self,
        tools: RiskTools,
        trace_service: TraceService,
        ai_client: AIClient | None = None,
    ) -> None:
        super().__init__("risk-agent", trace_service, ai_client)
        self._tools = tools

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
                     ``summarize_risk_for_company`` accepts ``model: str`` to
                     override the AI model (e.g. ``settings.model_sonnet``).
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
            )

        if not company_name:
            return AgentResult(
                request_id=trace.request_id,
                entity_name="",
                success=False,
                error="context must include a non-empty 'company_name'.",
                trace=trace,
            )

        if task in _DIRECT_TOOL_TASKS:
            return self._run_direct_task(task, company_name, context, trace)

        # summarize_risk_for_company
        return self._run_summary_task(company_name, context, trace)

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
            )

        return AgentResult(
            request_id=trace.request_id,
            entity_name=company_name,
            success=True,
            summary=result.summary,
            findings={task: result.data},
            trace=trace,
        )

    # ------------------------------------------------------------------
    # Private — summarize_risk_for_company
    # ------------------------------------------------------------------

    def _run_summary_task(
        self,
        company_name: str,
        context: dict[str, Any],
        trace: InvestigationTrace,
    ) -> AgentResult:
        """
        Run all 4 deterministic risk checks, then synthesise with AI.

        Each tool call is logged individually so the trace is fully
        auditable. The AI summary sits on top of the structured findings
        and does not replace them — both are returned in AgentResult.findings.
        """
        company_ref = [{"label": "Company", "name": company_name}]
        findings: dict[str, Any] = {}
        tool_summaries: list[str] = []
        all_success = True

        for task in sorted(_DIRECT_TOOL_TASKS):  # stable alphabetical order
            result = self._call_tool(task, company_name, context)
            input_summary = ", ".join(f"{k}={v}" for k, v in result.input.items())
            self.log_tool_event(
                trace,
                tool_name=result.tool_name,
                input_summary=input_summary,
                output_summary=result.summary,
                decision=(
                    "risk signal collected for synthesis"
                    if result.success
                    else "step failed — partial summary only"
                ),
                entity_refs=company_ref,
            )
            if result.success and result.data is not None:
                findings[task] = result.data
                tool_summaries.append(result.summary)
            else:
                findings[task] = None
                if not result.success:
                    all_success = False

        # ---- deterministic summary (always present) ------------------
        deterministic_summary = (
            " | ".join(tool_summaries)
            if tool_summaries
            else f"No risk signals could be retrieved for '{company_name}'."
        )

        # ---- optional AI synthesis -----------------------------------
        final_summary = deterministic_summary
        if self._ai_client and tool_summaries:
            user_prompt = (
                f"Company: {company_name}\n\n"
                + "\n".join(f"- {s}" for s in tool_summaries)
            )
            model = context.get("model")  # None → client default (Haiku)
            ai_text = self.generate_ai_summary(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=model,
            )
            if ai_text:
                final_summary = ai_text
                usage = self._last_ai_usage
                token_info = (
                    f" | tokens in={usage['input_tokens']} out={usage['output_tokens']}"
                    if usage
                    else ""
                )
                self.log_decision_event(
                    trace,
                    decision=f"AI risk summary generated for '{company_name}'{token_info}",
                    why=ai_text,
                    entity_refs=company_ref,
                )

        findings["deterministic_summary"] = deterministic_summary
        return AgentResult(
            request_id=trace.request_id,
            entity_name=company_name,
            success=all_success,
            summary=final_summary,
            findings=findings,
            trace=trace,
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
        """Call the matching RiskTools method and return its ToolResult."""
        max_depth = int(context.get("max_depth", 5))

        if task == "ownership_complexity_check":
            return self._tools.ownership_complexity_check(
                company_name, max_depth=max_depth
            )
        if task == "control_signal_check":
            return self._tools.control_signal_check(company_name, max_depth=max_depth)
        if task == "address_risk_check":
            return self._tools.address_risk_check(company_name)
        # industry_context_check
        return self._tools.industry_context_check(company_name)
