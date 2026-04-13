"""
src.app.policy — Central role-based authorization policy.

All authorization decisions flow through this module.  No other module
should make role/permission decisions independently.

Roles
-----
Two stable role identifiers are defined here and must be kept in sync
with the mock user registry in src.app.auth and any future Kong consumer
configuration:

    jr_risk_analyst   — limited to Investigate; cannot run address-risk or
                        industry-risk MCP tools; cannot access Replay / Audit.
    sr_risk_analyst   — full access to all tabs and MCP tools.

MCP tool categories
-------------------
Categories map directly to future Kong MCP Gateway scopes.  When Kong
enforcement is added, replace `can_invoke_mcp_tool` with a Kong JWT
claim check and map each category to a Kong consumer ACL group:

    ADDRESS_RISK_TOOLS  → Kong scope "mcp:address_risk"
    INDUSTRY_RISK_TOOLS → Kong scope "mcp:industry_risk"

Usage
-----
    from src.app.policy import get_policy_for_user

    policy = get_policy_for_user(user)          # AuthenticatedUser
    policy.can_replay                           # bool
    policy.can_invoke_mcp_tool("address_risk_check")  # bool
    policy.allowed_mcp_tools                    # frozenset[str]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.auth import AuthenticatedUser

# ---------------------------------------------------------------------------
# Stable role identifiers
# Keep in sync with src.app.auth._MOCK_USERS and future Kong consumer config.
# ---------------------------------------------------------------------------

ROLE_JR_RISK_ANALYST = "jr_risk_analyst"
ROLE_SR_RISK_ANALYST = "sr_risk_analyst"

# ---------------------------------------------------------------------------
# MCP tool categories
#
# These are the stable building blocks of the authorization model.
# Kong MCP Gateway enforcement maps each category to a consumer ACL scope.
# ---------------------------------------------------------------------------

#: Tools that perform address risk assessment.
#: Kong scope: "mcp:address_risk"
ADDRESS_RISK_TOOLS: frozenset[str] = frozenset({"address_risk_check"})

#: Tools that perform industry / sector risk assessment.
#: Kong scope: "mcp:industry_risk"
INDUSTRY_RISK_TOOLS: frozenset[str] = frozenset({"industry_context_check"})

#: Complete set of MCP tool names known to the system.
#: Includes infrastructure tools (validate_plan, resolve_entity) that are
#: always allowed, domain tools, and the synthetic summarize_risk_for_company
#: task that is dispatched through agents but not registered as an MCP endpoint.
ALL_MCP_TOOLS: frozenset[str] = frozenset({
    # Infrastructure / shared
    "resolve_entity",
    "validate_plan",
    "evaluate_stop_conditions",
    # Graph tools
    "entity_lookup",
    "company_profile",
    "expand_ownership",
    "shared_address_check",
    "sic_context",
    # Risk tools
    "ownership_complexity_check",
    "control_signal_check",
    "address_risk_check",       # in ADDRESS_RISK_TOOLS
    "industry_context_check",   # in INDUSTRY_RISK_TOOLS
    # Trace / audit tools
    "retrieve_trace",
    "find_traces_by_entity",
    "list_recent_traces",
})

#: Tools restricted from the Jr analyst role.
# summarize_risk_for_company is a synthetic RiskAgent task (not an MCP endpoint),
# so it is absent from ALL_MCP_TOOLS above.  It is included here as a safety net
# so that if the planner emits it as a step, Jr analysts cannot invoke it.
_JR_DENIED_TOOLS: frozenset[str] = (
    ADDRESS_RISK_TOOLS | INDUSTRY_RISK_TOOLS | frozenset({"summarize_risk_for_company"})
)

#: Allowlist for the Jr analyst role.
JR_ALLOWED_MCP_TOOLS: frozenset[str] = ALL_MCP_TOOLS - _JR_DENIED_TOOLS


# ---------------------------------------------------------------------------
# RolePolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RolePolicy:
    """Immutable capability descriptor for a role.

    Attributes:
        role:                   Stable role identifier string.
        can_investigate:        Investigate tab and investigation flow accessible.
        can_replay:             Replay / Audit tab and trace-load path accessible.
        can_view_tech_evidence: Raw technical evidence (JSON findings, plan
                                details) may be shown in the Investigate flow.
        allowed_mcp_tools:      Frozenset of MCP tool names this role may invoke.
    """

    role: str
    can_investigate: bool
    can_replay: bool
    can_view_tech_evidence: bool
    allowed_mcp_tools: frozenset[str] = field(default_factory=frozenset)

    # ------------------------------------------------------------------
    # Permission helpers
    # ------------------------------------------------------------------

    def can_invoke_mcp_tool(self, tool_name: str) -> bool:
        """Return True when this role is permitted to invoke *tool_name*."""
        return tool_name in self.allowed_mcp_tools

    def denied_from(self, tools: frozenset[str]) -> frozenset[str]:
        """Return the subset of *tools* that are denied for this role."""
        return tools - self.allowed_mcp_tools


# ---------------------------------------------------------------------------
# Policy registry
# ---------------------------------------------------------------------------

_POLICIES: dict[str, RolePolicy] = {
    ROLE_JR_RISK_ANALYST: RolePolicy(
        role=ROLE_JR_RISK_ANALYST,
        can_investigate=True,
        can_replay=False,
        can_view_tech_evidence=True,
        allowed_mcp_tools=JR_ALLOWED_MCP_TOOLS,
    ),
    ROLE_SR_RISK_ANALYST: RolePolicy(
        role=ROLE_SR_RISK_ANALYST,
        can_investigate=True,
        can_replay=True,
        can_view_tech_evidence=True,
        allowed_mcp_tools=ALL_MCP_TOOLS,
    ),
}

# Deny-all fallback for unknown / unauthenticated roles.
_DENY_ALL = RolePolicy(
    role="__deny_all__",
    can_investigate=False,
    can_replay=False,
    can_view_tech_evidence=False,
    allowed_mcp_tools=frozenset(),
)


def get_policy(role: str) -> RolePolicy:
    """Return the RolePolicy for *role*.

    Falls back to a deny-all policy for unknown role strings so the app
    fails closed rather than open when an unrecognised role appears.
    """
    return _POLICIES.get(role, _DENY_ALL)


def get_policy_for_user(user: "AuthenticatedUser") -> RolePolicy:
    """Convenience wrapper — extracts role from an AuthenticatedUser."""
    return get_policy(user.role)


# ---------------------------------------------------------------------------
# Phase 509 — Kong consumer group mapping
#
# Maps stable app role identifiers → Kong Consumer Group names.
# Kong uses these group names to enforce tool-level ACL when
# KONG_MCP_ACL_POLICY_ENABLED=true and the UI backend is "kong".
#
# Keep in sync with kong/consumer_groups.yaml and kong/acl_policy.yaml.
# ---------------------------------------------------------------------------

#: Maps app role → Kong Consumer Group name.
KONG_CONSUMER_GROUP_MAP: dict[str, str] = {
    ROLE_JR_RISK_ANALYST: "jr-analyst",
    ROLE_SR_RISK_ANALYST: "sr-analyst",
}


def get_kong_consumer_group(role: str) -> str | None:
    """Return the Kong Consumer Group name for *role*, or None if unmapped.

    Used for logging when Kong ACL enforcement is active.  The actual ACL
    decision is made by Kong — this is informational only.
    """
    return KONG_CONSUMER_GROUP_MAP.get(role)
