"""
Deterministic risk-signal tools built on top of Neo4jRepository.

These tools compute structured heuristics from graph data only — no LLM
calls are made here. Each returns a ToolResult with a plain-English
summary and a structured `data` dict that agents or notebooks can consume.

Risk levels: "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN"
"""

import time
from collections import Counter

from src.domain.models import ToolResult
from src.storage.neo4j_repository import Neo4jRepository


# ---------------------------------------------------------------------------
# Reference sets
# ---------------------------------------------------------------------------

# SIC codes associated with holding structures, dormancy, or high-opacity
# industries that warrant extra scrutiny in a UBO/risk context.
_HIGH_SCRUTINY_SIC = {
    "64205": "Financial services holding companies",
    "64209": "Other holding companies",
    "64302": "Investment trusts",
    "64999": "Other financial service activities",
    "70100": "Activities of head offices",
    "74990": "Non-trading company",
    "99999": "Dormant company",
}

# PSC natures-of-control that go beyond simple share ownership and indicate
# structural or influential control that is harder to trace.
_ELEVATED_CONTROL_TYPES = {
    "significant-influence-or-control",
    "right-to-appoint-and-remove-directors",
    "right-to-appoint-and-remove-members",
}


class RiskTools:
    def __init__(self, repo: Neo4jRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Public tools
    # ------------------------------------------------------------------

    def ownership_complexity_check(
        self, company_name: str, max_depth: int = 5
    ) -> ToolResult:
        """
        Measure the structural complexity of the ownership chain.

        Signals computed:
        - max_chain_depth:    deepest ownership hop found
        - unique_owner_count: distinct nodes appearing as owners across all paths
        - path_count:         total hop-rows returned (proxy for number of paths)
        - has_individual_ubos: True if at least one non-company leaf owner exists
        - corporate_chain_only: True if no individual UBOs found at any depth
        - risk_level:         LOW / MEDIUM / HIGH
        """
        t0 = time.monotonic()
        try:
            paths = self._repo.get_ownership_paths(
                company_name, max_depth=max_depth, limit=500
            )
            ubos = self._repo.get_ultimate_individual_owners(company_name)

            max_depth_found = max((r["path_depth"] for r in paths), default=0)
            unique_owners = {r["from_name"] for r in paths if r["from_name"]}
            corporate_owners = {
                r["from_name"]
                for r in paths
                if r["from_name"] and "Company" in (r["from_labels"] or [])
            }
            has_ubos = len(ubos) > 0
            corporate_only = len(paths) > 0 and not has_ubos

            risk_level = _ownership_risk(max_depth_found, len(unique_owners), corporate_only)

            data = {
                "max_chain_depth": max_depth_found,
                "unique_owner_count": len(unique_owners),
                "corporate_owner_count": len(corporate_owners),
                "path_count": len(paths),
                "ubo_count": len(ubos),
                "has_individual_ubos": has_ubos,
                "corporate_chain_only": corporate_only,
                "risk_level": risk_level,
                "ubos": ubos,
            }

            if not paths:
                summary = (
                    f"No ownership data found for '{company_name}'. "
                    "Risk level: UNKNOWN."
                )
                data["risk_level"] = "UNKNOWN"
            else:
                summary = (
                    f"Ownership chain for '{company_name}': "
                    f"max depth {max_depth_found}, "
                    f"{len(unique_owners)} unique owner(s), "
                    f"{len(ubos)} individual UBO(s). "
                    f"Complexity risk: {risk_level}."
                )
                if corporate_only:
                    summary += " All chains terminate at corporate entities — no individual UBOs resolved."

            return ToolResult(
                tool_name="ownership_complexity_check",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"company_name": company_name, "max_depth": max_depth},
                summary=summary,
            )
        except Exception as e:
            return _error(
                "ownership_complexity_check",
                {"company_name": company_name, "max_depth": max_depth},
                e,
                _ms(t0),
            )

    def control_signal_check(
        self, company_name: str, max_depth: int = 5
    ) -> ToolResult:
        """
        Inspect the nature-of-control types used across the ownership chain.

        Signals computed:
        - all_control_types:      deduplicated set of PSC control strings
        - elevated_control_types: subset matching _ELEVATED_CONTROL_TYPES
        - ownership_only:         True if every hop is simple share ownership
        - mixed_control:          True if both share and non-share controls exist
        - risk_level:             LOW / MEDIUM / HIGH
        """
        t0 = time.monotonic()
        try:
            paths = self._repo.get_ownership_paths(
                company_name, max_depth=max_depth, limit=500
            )
            direct = self._repo.get_direct_owners(company_name)

            # Flatten all ownership_controls lists from every hop
            all_types: set[str] = set()
            for row in paths + direct:
                controls = row.get("ownership_controls") or []
                if isinstance(controls, list):
                    all_types.update(controls)
                elif isinstance(controls, str):
                    all_types.add(controls)

            elevated = all_types & _ELEVATED_CONTROL_TYPES
            share_only_types = {t for t in all_types if t.startswith("ownership-of-shares")}
            ownership_only = bool(all_types) and all_types == share_only_types
            mixed_control = bool(elevated) and bool(share_only_types)

            risk_level = _control_risk(elevated, mixed_control, ownership_only, bool(all_types))

            data = {
                "all_control_types": sorted(all_types),
                "elevated_control_types": sorted(elevated),
                "ownership_only": ownership_only,
                "mixed_control": mixed_control,
                "risk_level": risk_level,
            }

            if not all_types:
                summary = f"No ownership control data found for '{company_name}'. Risk: UNKNOWN."
                data["risk_level"] = "UNKNOWN"
            elif elevated:
                summary = (
                    f"'{company_name}' has elevated control signal(s): "
                    f"{', '.join(sorted(elevated))}. "
                    f"Control risk: {risk_level}."
                )
            elif ownership_only:
                summary = (
                    f"'{company_name}' ownership is via standard share ownership only. "
                    f"Control risk: {risk_level}."
                )
            else:
                summary = (
                    f"'{company_name}' has {len(all_types)} control type(s): "
                    f"{', '.join(sorted(all_types))}. "
                    f"Control risk: {risk_level}."
                )

            return ToolResult(
                tool_name="control_signal_check",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"company_name": company_name, "max_depth": max_depth},
                summary=summary,
            )
        except Exception as e:
            return _error(
                "control_signal_check",
                {"company_name": company_name, "max_depth": max_depth},
                e,
                _ms(t0),
            )

    def address_risk_check(
        self, company_name: str, same_address_threshold: int = 5
    ) -> ToolResult:
        """
        Assess risk from registered address co-location.

        Signals computed:
        - co_located_total:    companies sharing the exact same address node
        - co_located_active:   subset with Active status
        - dissolution_rate:    fraction of co-located companies that are dissolved
        - exceeds_threshold:   True if co_located_total >= same_address_threshold
        - risk_level:          LOW / MEDIUM / HIGH
        """
        t0 = time.monotonic()
        try:
            address = self._repo.get_company_address_context(company_name)
            co_located = self._repo.get_companies_at_same_address(
                company_name, limit=500
            )

            total = len(co_located)
            active = sum(1 for c in co_located if c.get("status") == "Active")
            dissolved = total - active
            dissolution_rate = round(dissolved / total, 2) if total else 0.0
            exceeds = total >= same_address_threshold

            risk_level = _address_risk(total, dissolution_rate, same_address_threshold)

            data = {
                "address": address,
                "co_located_total": total,
                "co_located_active": active,
                "co_located_dissolved": dissolved,
                "dissolution_rate": dissolution_rate,
                "exceeds_threshold": exceeds,
                "risk_level": risk_level,
            }

            if not address:
                summary = f"No address found for '{company_name}'. Risk: UNKNOWN."
                data["risk_level"] = "UNKNOWN"
            elif total == 0:
                summary = (
                    f"'{company_name}' is the only company at its address "
                    f"({address.get('postal_code', '?')}). Address risk: LOW."
                )
            else:
                summary = (
                    f"'{company_name}' shares address "
                    f"({address.get('postal_code', '?')}) "
                    f"with {total} other companies "
                    f"({active} active, {dissolved} dissolved — "
                    f"{dissolution_rate:.0%} dissolution rate). "
                    f"Address risk: {risk_level}."
                )

            return ToolResult(
                tool_name="address_risk_check",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={
                    "company_name": company_name,
                    "same_address_threshold": same_address_threshold,
                },
                summary=summary,
            )
        except Exception as e:
            return _error(
                "address_risk_check",
                {
                    "company_name": company_name,
                    "same_address_threshold": same_address_threshold,
                },
                e,
                _ms(t0),
            )

    def industry_context_check(self, company_name: str) -> ToolResult:
        """
        Flag industry-level risk based on SIC codes.

        Signals computed:
        - sic_codes:               list of the company's codes + descriptions
        - high_scrutiny_sic_codes: subset matching known holding/dormant codes
        - is_holding_structure:    True if any high-scrutiny code is present
        - peer_dissolution_rate:   fraction of same-SIC peers that are dissolved
        - peer_count:              number of same-SIC peers found
        - risk_level:              LOW / MEDIUM / HIGH
        """
        t0 = time.monotonic()
        try:
            sics = self._repo.get_company_sic_context(company_name)
            peers = self._repo.get_companies_with_same_sic(company_name, limit=200)

            sic_codes = [s["sic_code"] for s in sics]
            flagged = [
                {"sic_code": s["sic_code"], "reason": _HIGH_SCRUTINY_SIC[s["sic_code"]]}
                for s in sics
                if s["sic_code"] in _HIGH_SCRUTINY_SIC
            ]
            is_holding = bool(flagged)

            peer_total = len(peers)
            peer_dissolved = sum(
                1 for p in peers if p.get("status") not in ("Active", None)
            )
            peer_dissolution_rate = (
                round(peer_dissolved / peer_total, 2) if peer_total else 0.0
            )

            risk_level = _industry_risk(is_holding, peer_dissolution_rate, peer_total)

            data = {
                "sic_codes": sics,
                "high_scrutiny_sic_codes": flagged,
                "is_holding_structure": is_holding,
                "peer_count": peer_total,
                "peer_dissolved": peer_dissolved,
                "peer_dissolution_rate": peer_dissolution_rate,
                "risk_level": risk_level,
            }

            if not sics:
                summary = f"No SIC codes found for '{company_name}'. Risk: UNKNOWN."
                data["risk_level"] = "UNKNOWN"
            elif flagged:
                flagged_codes = ", ".join(f["sic_code"] for f in flagged)
                summary = (
                    f"'{company_name}' operates under high-scrutiny SIC code(s): "
                    f"{flagged_codes}. "
                    f"Peer dissolution rate: {peer_dissolution_rate:.0%} "
                    f"({peer_dissolved}/{peer_total}). "
                    f"Industry risk: {risk_level}."
                )
            else:
                summary = (
                    f"'{company_name}' SIC codes {sic_codes} are standard. "
                    f"Peer dissolution rate: {peer_dissolution_rate:.0%} "
                    f"({peer_dissolved}/{peer_total}). "
                    f"Industry risk: {risk_level}."
                )

            return ToolResult(
                tool_name="industry_context_check",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"company_name": company_name},
                summary=summary,
            )
        except Exception as e:
            return _error(
                "industry_context_check", {"company_name": company_name}, e, _ms(t0)
            )


# ---------------------------------------------------------------------------
# Risk heuristics
# ---------------------------------------------------------------------------

def _ownership_risk(max_depth: int, unique_owners: int, corporate_only: bool) -> str:
    if max_depth == 0:
        return "UNKNOWN"
    score = 0
    if max_depth >= 4:
        score += 2
    elif max_depth >= 2:
        score += 1
    if unique_owners >= 5:
        score += 2
    elif unique_owners >= 2:
        score += 1
    if corporate_only:
        score += 2
    if score >= 4:
        return "HIGH"
    if score >= 2:
        return "MEDIUM"
    return "LOW"


def _control_risk(
    elevated: set, mixed: bool, ownership_only: bool, has_data: bool
) -> str:
    if not has_data:
        return "UNKNOWN"
    if elevated:
        return "HIGH"
    if mixed:
        return "MEDIUM"
    return "LOW"


def _address_risk(total: int, dissolution_rate: float, threshold: int) -> str:
    if total == 0:
        return "LOW"
    score = 0
    if total >= threshold * 10:
        score += 2
    elif total >= threshold:
        score += 1
    if dissolution_rate >= 0.5:
        score += 2
    elif dissolution_rate >= 0.25:
        score += 1
    if score >= 3:
        return "HIGH"
    if score >= 1:
        return "MEDIUM"
    return "LOW"


def _industry_risk(is_holding: bool, dissolution_rate: float, peer_total: int) -> str:
    if is_holding:
        if dissolution_rate >= 0.4:
            return "HIGH"
        return "MEDIUM"
    if peer_total > 0 and dissolution_rate >= 0.5:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
