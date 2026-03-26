"""
RiskAgent — specialist agent for interpreting graph-derived risk signals.

Responsibilities:
  - call risk MCP tools via MCPToolClient for deterministic risk heuristics
  - log every tool call via BaseAgent helpers (→ Neo4j trace)
  - for summarize_risk_for_company: gather all 4 risk signals and use
    AIClient to produce a concise natural-language risk assessment

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
  summarize_risk_for_company   run all 4 checks + AI narrative synthesis
"""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.clients.ai_client import AIClient
from src.clients.mcp_tool_client import MCPToolClient
from src.domain.models import AgentResult, EventType, InvestigationTrace, TraceEvent
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

_SYSTEM_PROMPT = """You are a financial crime compliance analyst. \
Given structured risk signals for a company, write a concise risk assessment \
(2-4 sentences) for a compliance analyst deciding whether to escalate. \
Reference the specific signals: ownership chain, control types, address \
co-location, and industry. State the overall risk level (LOW / MEDIUM / HIGH). \
Do not use bullet points or markdown.

── SCORING REFERENCE ────────────────────────────────────────────────────────

Use the heuristics below to verify and contextualise the risk levels supplied
in the signals. Do not recalculate them — they are already computed. Use this
reference to ground your language and ensure your narrative is consistent with
the underlying logic.

OWNERSHIP COMPLEXITY
Inputs: max_depth (longest ownership chain in hops), unique_owners (distinct
owner nodes), corporate_only (True when no individual beneficial owners appear
anywhere in the chain).

Scoring:
  max_depth >= 4 hops      → +2 points
  max_depth 2 or 3 hops    → +1 point
  max_depth <= 1 hop        → +0 points (may also return UNKNOWN if no data)
  unique_owners >= 5        → +2 points
  unique_owners 2, 3, or 4 → +1 point
  unique_owners <= 1        → +0 points
  corporate_only = True     → +2 points (no natural-person UBO identified)

Risk level: score >= 4 → HIGH | score 2 or 3 → MEDIUM | score < 2 → LOW
Special case: if max_depth == 0 (no ownership data found) → UNKNOWN

Compliance interpretation:
  HIGH ownership complexity may indicate layered corporate structures used to
  obscure beneficial ownership — a common typology in money-laundering schemes
  and sanctions evasion. A corporate-only chain with no natural-person UBO is
  particularly significant: it may mean the ultimate beneficial owner has not
  been disclosed, which is a requirement under UK PSC rules.

CONTROL SIGNALS
Inputs: elevated (set of non-standard control types detected), mixed (True
when both share-based and non-share-based controls appear), has_data (False
when no ownership/control records exist).

Elevated control types that trigger HIGH risk:
  right-to-appoint-and-remove-directors
  right-to-appoint-and-remove-majority-of-directors
  significant-influence-or-control
  significant-influence-or-control-as-a-member-of-a-firm
  right-to-appoint-and-remove-members

Standard (non-elevated) control types:
  ownership-of-shares-25-to-50-percent
  ownership-of-shares-50-to-75-percent
  ownership-of-shares-75-to-100-percent
  voting-rights-25-to-50-percent
  voting-rights-50-to-75-percent
  voting-rights-75-to-100-percent

Risk level:
  elevated set is non-empty → HIGH (regardless of share ownership)
  mixed controls present     → MEDIUM (elevated absent but non-share types found)
  share/voting only          → LOW
  has_data = False           → UNKNOWN

Compliance interpretation:
  Elevated controls (especially significant-influence-or-control and
  right-to-appoint) are the hallmarks of shadow director arrangements and
  undisclosed controllers — common in corporate abuse typologies. Mixed
  controls warrant scrutiny because they may signal that formal share
  ownership is being supplemented with informal influence mechanisms.

ADDRESS RISK
Inputs: total (number of companies registered at the same address),
dissolution_rate (proportion of co-located companies that are dissolved),
threshold (default = 5, the minimum count before flagging).

Scoring:
  total >= threshold * 10   → +2 points  (mass co-location)
  total >= threshold         → +1 point
  total == 0                 → score stays 0, return LOW immediately
  dissolution_rate >= 0.50   → +2 points  (majority dissolved)
  dissolution_rate >= 0.25   → +1 point

Risk level: score >= 3 → HIGH | score >= 1 → MEDIUM | score == 0 → LOW

Compliance interpretation:
  Mass co-location at a single registered address (often a formation agent or
  virtual office) combined with a high dissolution rate is a well-documented
  shell-company indicator. The Companies House UBO data regularly shows
  hundreds of companies sharing a single address; when most of those companies
  are dissolved, it suggests systematic exploitation of registered address
  services for short-lived entities.

INDUSTRY CONTEXT
Inputs: is_holding (True when any of the company's SIC codes appears in the
high-scrutiny set), dissolution_rate (proportion of SIC-peer companies that
are dissolved), peer_total (total number of companies sharing the same SIC
code(s)).

High-scrutiny SIC codes:
  64205 — Activities of financial services holding companies
  70100 — Activities of head offices (non-financial holding companies)
  74990 — Non-trading company
  99999 — Dormant company

Risk level:
  is_holding AND dissolution_rate >= 0.40 → HIGH
  is_holding AND dissolution_rate < 0.40  → MEDIUM
  peer_total > 0 AND dissolution_rate >= 0.50 → MEDIUM
  otherwise → LOW

Compliance interpretation:
  Holding companies and dormant entities in the Companies House register are
  frequently used as intermediate layers in ownership chains. A holding company
  with a high peer dissolution rate indicates that similar entities in the same
  SIC group are being regularly struck off, which is consistent with
  disposable-vehicle typologies used in fraud and tax evasion schemes.

COMBINING SIGNALS
When synthesising the four risk dimensions into a single narrative:

  - If any single dimension is HIGH: the overall assessment should note that
    the profile warrants escalation consideration, even if other dimensions
    are LOW. Explain which dimension drives the concern.

  - If two or more dimensions are MEDIUM and none is HIGH: flag for enhanced
    due diligence. Cumulative MEDIUM signals are materially more concerning
    than a single MEDIUM in isolation.

  - If all four dimensions are LOW: the profile is consistent with a standard
    trading company. Note any caveats (e.g. UNKNOWN dimensions where data was
    absent).

  - Always name the overall risk level explicitly as the final word in the
    assessment (LOW / MEDIUM / HIGH).

────────────────────────────────────────────────────────────────────────────"""


class RiskAgent(BaseAgent):
    """
    Investigation agent that interprets risk signals from the Neo4j business graph via MCP.

    Args:
        mcp_client:    MCPToolClient — all tool calls go through this.
        trace_service: Shared TraceService for structured event logging.
        ai_client:     Optional AI client. Required for summarize_risk_for_company.
                       Haiku is used by default; pass ``model=<id>`` in context
                       to override (e.g. ``settings.model_sonnet`` for Sonnet).
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
        failed_tasks: list[str] = []
        tools_called: list[str] = []

        for task in sorted(_DIRECT_TOOL_TASKS):  # stable alphabetical order
            result = self._call_tool(task, company_name, context)
            tools_called.append(result.tool_name)
            input_summary = ", ".join(f"{k}={v}" for k, v in result.input.items())
            self.log_tool_event(
                trace,
                tool_name=result.tool_name,
                input_summary=input_summary,
                output_summary=result.summary,
                decision=(
                    "risk signal collected for synthesis"
                    if result.success
                    else "tool unavailable — partial assessment"
                ),
                entity_refs=company_ref,
                data=result.data,
            )
            if result.success and result.data is not None:
                findings[task] = result.data
                tool_summaries.append(result.summary)
            else:
                findings[task] = None
                if not result.success:
                    failed_tasks.append(task)
                    self._trace_service.add_event(
                        trace,
                        TraceEvent(
                            event_type=EventType.STEP_FAILED,
                            message=(
                                f"Tool '{task}' unavailable for '{company_name}': "
                                f"{result.error or 'no error detail'}"
                            ),
                            payload={"tool": task, "error": result.error},
                        ),
                    )

        if failed_tasks:
            findings["unavailable_tools"] = failed_tasks

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
            # Pass model=settings.model_sonnet in context to enable prompt
            # caching (Sonnet threshold is 1024 tokens; _SYSTEM_PROMPT exceeds
            # that). Haiku requires 2048 tokens so caching won't activate on
            # the default model, but the call still works correctly.
            model = context.get("model")  # None → client default (Haiku)
            ai_text = self.generate_ai_summary(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=model,
                max_tokens=200,
                cache_system=True,
            )
            if ai_text:
                final_summary = ai_text
                usage = self._last_ai_usage
                cache_info = ""
                if usage:
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_write = usage.get("cache_creation_input_tokens", 0)
                    cache_info = (
                        f" cache_read={cache_read} cache_written={cache_write}"
                        if (cache_read or cache_write)
                        else ""
                    )
                token_info = (
                    f" | tokens in={usage['input_tokens']} out={usage['output_tokens']}{cache_info}"
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
            success=len(tool_summaries) >= 1,
            summary=final_summary,
            findings=findings,
            trace=trace,
            tools_used=tools_called,
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
