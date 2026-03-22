"""
InvestigationPlanner — LLM-based query classifier and plan generator.

Parses a free-text user query and returns a PlannerResult containing:
  - mode         (investigate | trace)
  - reason       model explanation of the chosen plan
  - entities     named entities extracted from the query, each with a type
  - plan         ordered list of (agent, task, parameters) steps
  - stop_conditions  optional termination criteria

Uses the existing AIClient abstraction. Haiku is the default model.
JSON output is enforced via generate_json(); the system prompt is kept
constrained to known agents and tasks so the executor never receives
an unrecognised step.

Known agents and tasks
----------------------
  graph-agent:
    entity_lookup          search companies by partial name
    company_profile        address + SIC codes + direct owners
    expand_ownership       walk ownership chain up to max_depth hops
    shared_address_check   co-location count at registered address
    sic_context            SIC codes and industry peer list

  risk-agent:
    ownership_complexity_check   structural chain complexity
    control_signal_check         nature-of-control types
    address_risk_check           address co-location risk
    industry_context_check       SIC-based industry risk
    summarize_risk_for_company   full 4-signal risk synthesis

  trace-agent:
    retrieve_trace         load a full trace by its ID
    find_traces_by_entity  find traces linked to an entity name
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.clients.ai_client import AIClient

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known values — used for validation and as documentation
# ---------------------------------------------------------------------------

VALID_MODES: frozenset[str] = frozenset({"investigate", "trace"})

VALID_ENTITY_TYPES: frozenset[str] = frozenset({
    "Company",
    "Individual",
    "LegalEntity",
    "Address",
    "SIC",
    "Trace",
})

VALID_AGENTS: frozenset[str] = frozenset({
    "graph-agent",
    "risk-agent",
    "trace-agent",
})

VALID_TASKS: frozenset[str] = frozenset({
    # graph-agent
    "entity_lookup",
    "company_profile",
    "expand_ownership",
    "shared_address_check",
    "sic_context",
    # risk-agent
    "ownership_complexity_check",
    "control_signal_check",
    "address_risk_check",
    "industry_context_check",
    "summarize_risk_for_company",
    # trace-agent
    "retrieve_trace",
    "find_traces_by_entity",
})

# Tasks belonging to each agent, for validation
_AGENT_TASKS: dict[str, frozenset[str]] = {
    "graph-agent": frozenset({
        "entity_lookup", "company_profile", "expand_ownership",
        "shared_address_check", "sic_context",
    }),
    "risk-agent": frozenset({
        "ownership_complexity_check", "control_signal_check",
        "address_risk_check", "industry_context_check",
        "summarize_risk_for_company",
    }),
    "trace-agent": frozenset({
        "retrieve_trace", "find_traces_by_entity",
    }),
}

# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EntityRef:
    """An entity extracted from the query."""

    name: str
    entity_type: str  # Company | Individual | LegalEntity | Address | SIC | Trace


@dataclass
class PlanStep:
    """One step in the execution plan produced by the planner."""

    step_id: str
    agent: str                               # graph-agent | risk-agent | trace-agent
    task: str                                # task name within that agent
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlannerResult:
    """
    Structured output from InvestigationPlanner.plan().

    Attributes:
        mode:            investigate | trace
        reason:          model's plain-English explanation of the plan
        entities:        entities extracted from the query
        plan:            ordered execution steps (agent + task + parameters)
        stop_conditions: optional termination criteria requested in the query
        raw:             raw JSON dict returned by the model (for debugging)
    """

    mode: str
    reason: str
    entities: list[EntityRef]
    plan: list[PlanStep]
    stop_conditions: list[str]
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a clean, serialisable representation (excludes raw)."""
        return {
            "mode": self.mode,
            "reason": self.reason,
            "entities": [
                {"name": e.name, "type": e.entity_type} for e in self.entities
            ],
            "plan": [
                {
                    "step_id": s.step_id,
                    "agent": s.agent,
                    "task": s.task,
                    "parameters": s.parameters,
                }
                for s in self.plan
            ],
            "stop_conditions": self.stop_conditions,
        }


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an investigation planner for a UK financial crime compliance system.
Parse the user query and return a JSON execution plan.

OUTPUT SCHEMA — return exactly this structure, no additional keys:
{
  "mode": "investigate" | "trace",
  "reason": "<1-2 sentences: what you understood and why you chose this plan>",
  "entities": [
    {"name": "<extracted entity name>", "type": "<entity type>"}
  ],
  "plan": [
    {"step_id": "step_1", "agent": "<agent>", "task": "<task>", "parameters": {}}
  ],
  "stop_conditions": ["<condition text>"]
}

ENTITY TYPES (use exact spelling):
  Company | Individual | LegalEntity | Address | SIC | Trace

MODES:
  investigate — query is about a company, person, address, or ownership structure
  trace       — query is about retrieving or replaying a prior investigation record

AVAILABLE AGENTS AND TASKS — use only these exact values:

  graph-agent
    entity_lookup          search companies by partial name
                           parameters: {"name": str}
    company_profile        address + SIC codes + direct owners
                           parameters: {"company_name": str}
    expand_ownership       walk the ownership chain
                           parameters: {"company_name": str, "max_depth": int}
    shared_address_check   co-location count at the registered address
                           parameters: {"company_name": str}
    sic_context            SIC codes and industry peers
                           parameters: {"company_name": str}

  risk-agent
    ownership_complexity_check   structural chain complexity
                                 parameters: {"company_name": str}
    control_signal_check         nature-of-control types across the chain
                                 parameters: {"company_name": str}
    address_risk_check           address co-location risk
                                 parameters: {"company_name": str}
    industry_context_check       SIC-based industry risk
                                 parameters: {"company_name": str}
    summarize_risk_for_company   full 4-signal risk synthesis (covers all four
                                 dimensions above in one call)
                                 parameters: {"company_name": str}

  trace-agent
    retrieve_trace         load a full investigation trace by its ID
                           parameters: {"trace_id": str}
    find_traces_by_entity  find prior investigation traces by entity name
                           parameters: {"entity_name": str}

PLANNING RULES:
1. Company queries: always start with graph-agent entity_lookup (step_1) to
   resolve the canonical company name before running any other step.
2. Ownership queries: add graph-agent expand_ownership after entity_lookup.
   Default max_depth to 5 unless the query specifies otherwise.
3. Risk queries: add risk-agent summarize_risk_for_company. This single task
   covers all four risk dimensions — do NOT list them individually as well.
4. Combined ownership + risk: include both expand_ownership AND
   summarize_risk_for_company as separate steps.
5. Profile queries: add graph-agent company_profile after entity_lookup.
6. Address queries: add graph-agent shared_address_check after entity_lookup.
7. SIC / industry queries: add graph-agent sic_context after entity_lookup.
8. Trace queries: use trace-agent only; skip entity_lookup entirely.
   - Query contains a trace ID (UUID or numeric string): use retrieve_trace.
   - Query names an entity but has no trace ID: use find_traces_by_entity.
9. stop_conditions: include only when the query implies a termination
   criterion (e.g. "stop if no UBOs are found"). Otherwise return [].
10. parameters: fill in the extracted entity name for company_name / name /
    entity_name fields. Fill in the extracted ID for trace_id.

EXAMPLES:

Query: "who owns ACME Holdings?"
{"mode":"investigate","reason":"Ownership query for a company. Resolving canonical name first, then walking the full ownership chain.","entities":[{"name":"ACME Holdings","type":"Company"}],"plan":[{"step_id":"step_1","agent":"graph-agent","task":"entity_lookup","parameters":{"name":"ACME Holdings"}},{"step_id":"step_2","agent":"graph-agent","task":"expand_ownership","parameters":{"company_name":"ACME Holdings","max_depth":5}}],"stop_conditions":[]}

Query: "who owns ACME Holdings and is it risky?"
{"mode":"investigate","reason":"Combined ownership and risk query. Walking the ownership chain, then synthesising all four risk signals.","entities":[{"name":"ACME Holdings","type":"Company"}],"plan":[{"step_id":"step_1","agent":"graph-agent","task":"entity_lookup","parameters":{"name":"ACME Holdings"}},{"step_id":"step_2","agent":"graph-agent","task":"expand_ownership","parameters":{"company_name":"ACME Holdings","max_depth":5}},{"step_id":"step_3","agent":"risk-agent","task":"summarize_risk_for_company","parameters":{"company_name":"ACME Holdings"}}],"stop_conditions":[]}

Query: "replay investigation trace abc-123-def"
{"mode":"trace","reason":"User wants to retrieve a specific prior investigation by trace ID.","entities":[{"name":"abc-123-def","type":"Trace"}],"plan":[{"step_id":"step_1","agent":"trace-agent","task":"retrieve_trace","parameters":{"trace_id":"abc-123-def"}}],"stop_conditions":[]}

Query: "show me the company profile for VODAFONE UK"
{"mode":"investigate","reason":"Profile query requesting address, SIC codes, and direct owners.","entities":[{"name":"VODAFONE UK","type":"Company"}],"plan":[{"step_id":"step_1","agent":"graph-agent","task":"entity_lookup","parameters":{"name":"VODAFONE UK"}},{"step_id":"step_2","agent":"graph-agent","task":"company_profile","parameters":{"company_name":"VODAFONE UK"}}],"stop_conditions":[]}\
"""


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class InvestigationPlanner:
    """
    LLM-based planner for the entity risk investigation system.

    Converts a free-text query into a structured PlannerResult by calling
    the AI client's generate_json() method with the constrained system prompt.

    Args:
        ai_client: Any AIClient implementation. Haiku is recommended for
                   speed; Sonnet produces more precise plans on ambiguous
                   or multi-entity queries.
    """

    def __init__(self, ai_client: AIClient) -> None:
        self._ai_client = ai_client

    def plan(self, query: str) -> PlannerResult:
        """
        Parse a natural-language investigation query into a structured plan.

        Args:
            query: Free-text query from a user or upstream system.

        Returns:
            PlannerResult with mode, entities, plan steps, and reasoning.

        Raises:
            ValueError: Propagated from generate_json() if the model returns
                        unparseable output.
            RuntimeError: Propagated from generate_json() on API errors.
        """
        raw: dict[str, Any] = self._ai_client.generate_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=query.strip(),
            max_tokens=600,
        )
        result = _parse(raw)
        _warn_unknown(result)
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse(raw: dict[str, Any]) -> PlannerResult:
    """Convert raw model JSON into a typed PlannerResult with safe fallbacks."""
    mode = raw.get("mode", "investigate")
    if mode not in VALID_MODES:
        _log.warning("planner returned unknown mode %r — defaulting to 'investigate'", mode)
        mode = "investigate"

    reason = str(raw.get("reason", ""))

    entities: list[EntityRef] = []
    for e in raw.get("entities") or []:
        etype = e.get("type") or e.get("entity_type", "Company")
        if etype not in VALID_ENTITY_TYPES:
            _log.warning("unknown entity type %r — defaulting to 'Company'", etype)
            etype = "Company"
        entities.append(EntityRef(name=str(e.get("name", "")), entity_type=etype))

    plan: list[PlanStep] = []
    for i, s in enumerate(raw.get("plan") or [], start=1):
        step_id = s.get("step_id") or f"step_{i}"
        agent = str(s.get("agent", ""))
        task = str(s.get("task", ""))
        params = s.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}
        plan.append(PlanStep(step_id=step_id, agent=agent, task=task, parameters=params))

    stop_conditions: list[str] = [str(c) for c in (raw.get("stop_conditions") or [])]

    return PlannerResult(
        mode=mode,
        reason=reason,
        entities=entities,
        plan=plan,
        stop_conditions=stop_conditions,
        raw=raw,
    )


def _warn_unknown(result: PlannerResult) -> None:
    """Log warnings for any agent/task values not in the known sets."""
    for step in result.plan:
        if step.agent not in VALID_AGENTS:
            _log.warning(
                "plan step %r references unknown agent %r",
                step.step_id, step.agent,
            )
        elif step.task not in _AGENT_TASKS.get(step.agent, frozenset()):
            _log.warning(
                "plan step %r: task %r is not a known task for agent %r",
                step.step_id, step.task, step.agent,
            )
