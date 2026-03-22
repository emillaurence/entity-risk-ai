"""
Shared investigation lifecycle tools.

These tools support orchestration-level operations that sit above individual
domain queries:

- resolve_entity:          canonicalise a name to a known graph entity
- validate_plan:           validate plan steps before execution
- evaluate_stop_conditions: decide whether the investigation has enough evidence
"""

import time

from src.domain.models import ToolResult
from src.tools.graph_tools import GraphTools


# All tool names that may appear in a plan step.
_KNOWN_TOOLS: frozenset[str] = frozenset(
    {
        "resolve_entity",
        "validate_plan",
        "evaluate_stop_conditions",
        "entity_lookup",
        "company_profile",
        "expand_ownership",
        "shared_address_check",
        "sic_context",
        "ownership_complexity_check",
        "control_signal_check",
        "address_risk_check",
        "industry_context_check",
        "retrieve_trace",
        "find_traces_by_entity",
        "list_recent_traces",
    }
)

# Signal keys expected in the findings dict passed to evaluate_stop_conditions.
_REQUIRED_SIGNALS: frozenset[str] = frozenset(
    {
        "ownership_complexity",
        "control_signals",
        "address_risk",
        "industry_context",
    }
)

_RISK_ORDER: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "UNKNOWN": -1}


class SharedTools:
    """
    Lifecycle tools for orchestrating multi-step investigations.

    Wraps GraphTools for entity resolution and applies heuristic rules
    for plan validation and stop-condition evaluation.

    Args:
        graph_tools: An initialised GraphTools instance.
    """

    def __init__(self, graph_tools: GraphTools) -> None:
        self._graph = graph_tools

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def resolve_entity(self, name: str) -> ToolResult:
        """
        Resolve a company name to its canonical form in the graph.

        Performs a full-text search, then selects the exact-name match if
        present or falls back to the highest-ranked fuzzy match. Returns the
        canonical name, company number, status, and match quality.
        """
        t0 = time.monotonic()
        try:
            if not name or not name.strip():
                raise ValueError("name must be a non-empty string.")

            lookup = self._graph.entity_lookup(name)
            if not lookup.success:
                return ToolResult(
                    tool_name="resolve_entity",
                    success=False,
                    error=lookup.error,
                    duration_ms=_ms(t0),
                    input={"name": name},
                    summary=f"resolve_entity failed: {lookup.error}",
                )

            matches = lookup.data or []
            if not matches:
                return ToolResult(
                    tool_name="resolve_entity",
                    success=True,
                    data={"resolved": False, "name": name, "matches": []},
                    duration_ms=_ms(t0),
                    input={"name": name},
                    summary=f"No entity found matching '{name}'.",
                )

            exact = next(
                (m for m in matches if m.get("name", "").lower() == name.lower()),
                None,
            )
            best = exact or matches[0]
            exact_match = exact is not None

            data = {
                "resolved": True,
                "canonical_name": best["name"],
                "company_number": best.get("company_number"),
                "status": best.get("status"),
                "exact_match": exact_match,
                "match_count": len(matches),
                "all_matches": matches,
            }
            qualifier = "exact" if exact_match else "best fuzzy"
            summary = (
                f"Resolved '{name}' → '{best['name']}' "
                f"(#{best.get('company_number')}, {best.get('status')}) "
                f"[{qualifier} match, {len(matches)} candidate(s)]."
            )
            return ToolResult(
                tool_name="resolve_entity",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"name": name},
                summary=summary,
            )
        except Exception as e:
            return _error("resolve_entity", {"name": name}, e, _ms(t0))

    def validate_plan(self, steps: list[dict]) -> ToolResult:
        """
        Validate a list of investigation plan steps before execution.

        Each step must have:
        - ``step_id``:   a non-empty string identifier
        - ``tool_name``: a string matching a known investigation tool

        Returns a structured report with valid steps and any validation errors.
        """
        t0 = time.monotonic()
        n = len(steps) if isinstance(steps, list) else 0
        try:
            if not isinstance(steps, list):
                raise ValueError("steps must be a list of dicts.")

            errors: list[dict] = []
            valid_steps: list[dict] = []

            for i, step in enumerate(steps):
                step_id = step.get("step_id", f"step_{i + 1}")
                tool_name = step.get("tool_name", "")
                step_errors: list[str] = []

                if not step_id:
                    step_errors.append("step_id is required")
                if not tool_name:
                    step_errors.append("tool_name is required")
                elif tool_name not in _KNOWN_TOOLS:
                    step_errors.append(
                        f"unknown tool '{tool_name}'; "
                        f"valid tools: {sorted(_KNOWN_TOOLS)}"
                    )

                if step_errors:
                    errors.append({"step_id": step_id, "errors": step_errors})
                else:
                    valid_steps.append(step)

            is_valid = len(errors) == 0
            data = {
                "valid": is_valid,
                "step_count": len(steps),
                "valid_steps": valid_steps,
                "errors": errors,
            }
            if is_valid:
                summary = f"Plan is valid: {len(steps)} step(s) ready to execute."
            else:
                summary = (
                    f"Plan has {len(errors)} validation error(s) "
                    f"across {len(steps)} step(s)."
                )
            return ToolResult(
                tool_name="validate_plan",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"step_count": n},
                summary=summary,
            )
        except Exception as e:
            return _error("validate_plan", {"step_count": n}, e, _ms(t0))

    def evaluate_stop_conditions(self, findings: dict) -> ToolResult:
        """
        Evaluate whether the investigation has gathered sufficient evidence.

        Expected findings keys (all optional):
        - ``ownership_complexity``: ``{"risk_level": "LOW"|"MEDIUM"|"HIGH"|"UNKNOWN"}``
        - ``control_signals``:      ``{"risk_level": ...}``
        - ``address_risk``:         ``{"risk_level": ...}``
        - ``industry_context``:     ``{"risk_level": ...}``

        Returns ``should_stop`` (all required signals present), ``escalate``
        (overall risk is HIGH), ``overall_risk``, and any missing signals.
        """
        t0 = time.monotonic()
        n = len(findings) if isinstance(findings, dict) else 0
        try:
            if not isinstance(findings, dict):
                raise ValueError("findings must be a dict.")

            present = set(findings.keys()) & _REQUIRED_SIGNALS
            missing = _REQUIRED_SIGNALS - present

            levels = []
            for key in present:
                signal = findings[key]
                if isinstance(signal, dict):
                    lvl = signal.get("risk_level", "UNKNOWN")
                    if lvl in _RISK_ORDER:
                        levels.append(lvl)

            known = [l for l in levels if l != "UNKNOWN"]
            if known:
                overall_risk = max(known, key=lambda l: _RISK_ORDER[l])
            elif levels:
                overall_risk = "UNKNOWN"
            else:
                overall_risk = "UNKNOWN"

            should_stop = len(missing) == 0
            escalate = overall_risk == "HIGH"

            data = {
                "should_stop": should_stop,
                "escalate": escalate,
                "overall_risk": overall_risk,
                "signals_present": sorted(present),
                "signals_missing": sorted(missing),
                "signal_count": len(present),
                "required_count": len(_REQUIRED_SIGNALS),
            }

            if should_stop and escalate:
                summary = (
                    f"Investigation complete. All {len(_REQUIRED_SIGNALS)} signals gathered. "
                    "Overall risk: HIGH — escalate for review."
                )
            elif should_stop:
                summary = (
                    f"Investigation complete. All {len(_REQUIRED_SIGNALS)} signals gathered. "
                    f"Overall risk: {overall_risk}."
                )
            else:
                summary = (
                    f"Investigation incomplete: {len(missing)} signal(s) still needed: "
                    f"{', '.join(sorted(missing))}."
                )

            return ToolResult(
                tool_name="evaluate_stop_conditions",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"signal_count": n},
                summary=summary,
            )
        except Exception as e:
            return _error("evaluate_stop_conditions", {"signal_count": n}, e, _ms(t0))


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

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
