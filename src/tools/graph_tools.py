"""
Deterministic graph tools built on top of Neo4jRepository.

Each method executes one or more repository queries, wraps the result
in a ToolResult, and writes a plain-English summary. No LLM calls are
made here — these tools are the factual layer that agents can call.
"""

import time

from src.domain.models import ToolResult
from src.storage.neo4j_repository import Neo4jRepository


class GraphTools:
    def __init__(self, repo: Neo4jRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def entity_lookup(self, name: str) -> ToolResult:
        """
        Search for companies whose name contains the given string.
        Uses the full-text index; returns up to 10 ranked matches.
        """
        t0 = time.monotonic()
        try:
            results = self._repo.find_company_by_name(name, limit=10)
            duration = _ms(t0)
            if results:
                summary = (
                    f"Found {len(results)} company match(es) for '{name}'. "
                    f"Top match: {results[0]['name']!r} "
                    f"(number: {results[0]['company_number']}, status: {results[0]['status']})."
                )
            else:
                summary = f"No companies found matching '{name}'."
            return ToolResult(
                tool_name="entity_lookup",
                success=True,
                data=results,
                duration_ms=duration,
                input={"name": name},
                summary=summary,
            )
        except Exception as e:
            return _error("entity_lookup", {"name": name}, e, _ms(t0))

    def company_profile(self, company_name: str) -> ToolResult:
        """
        Retrieve a full company profile: address, SIC codes, and direct owners
        in a single logical call (three repository queries).
        """
        t0 = time.monotonic()
        try:
            company = self._repo.get_company_by_exact_name(company_name)
            if not company:
                return ToolResult(
                    tool_name="company_profile",
                    success=True,
                    data=None,
                    duration_ms=_ms(t0),
                    input={"company_name": company_name},
                    summary=f"No company found with exact name '{company_name}'.",
                )

            address = self._repo.get_company_address_context(company_name)
            sics = self._repo.get_company_sic_context(company_name)
            owners = self._repo.get_direct_owners(company_name)

            data = {
                "company": company,
                "address": address,
                "sic_codes": sics,
                "direct_owners": owners,
            }

            sic_summary = (
                ", ".join(
                    f"{s['sic_code']} ({s['sic_description']})" for s in sics
                ) if sics else "none"
            )
            owner_summary = (
                ", ".join(o["owner_name"] or "?" for o in owners) if owners else "none recorded"
            )
            summary = (
                f"{company_name} (#{company['company_number']}, {company['status']}). "
                f"SIC codes: {sic_summary}. "
                f"Direct owners: {owner_summary}."
            )

            return ToolResult(
                tool_name="company_profile",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"company_name": company_name},
                summary=summary,
            )
        except Exception as e:
            return _error("company_profile", {"company_name": company_name}, e, _ms(t0))

    def expand_ownership(
        self, company_name: str, max_depth: int = 5
    ) -> ToolResult:
        """
        Walk the ownership graph up to max_depth hops and identify
        ultimate individual owners (UBOs).
        """
        t0 = time.monotonic()
        try:
            paths = self._repo.get_ownership_paths(
                company_name, max_depth=max_depth, limit=100
            )
            ubos = self._repo.get_ultimate_individual_owners(company_name)

            data = {"paths": paths, "ultimate_owners": ubos}

            depths = sorted({r["path_depth"] for r in paths}) if paths else []
            ubo_names = [u["owner_name"] for u in ubos]

            if not paths:
                summary = f"No ownership paths found for '{company_name}'."
            elif ubos:
                summary = (
                    f"Found {len(paths)} ownership hop(s) across depths {depths} "
                    f"for '{company_name}'. "
                    f"Ultimate individual owner(s): {', '.join(ubo_names)}."
                )
            else:
                summary = (
                    f"Found {len(paths)} ownership hop(s) across depths {depths} "
                    f"for '{company_name}'. "
                    "All chains terminate at corporate entities — no individual UBOs found."
                )

            return ToolResult(
                tool_name="expand_ownership",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"company_name": company_name, "max_depth": max_depth},
                summary=summary,
            )
        except Exception as e:
            return _error(
                "expand_ownership",
                {"company_name": company_name, "max_depth": max_depth},
                e,
                _ms(t0),
            )

    def shared_address_check(self, company_name: str) -> ToolResult:
        """
        Check how many other companies share the same registered address.
        High co-location counts are a common shell-company risk signal.
        """
        t0 = time.monotonic()
        try:
            address = self._repo.get_company_address_context(company_name)
            co_located = self._repo.get_companies_at_same_address(
                company_name, limit=200
            )

            active_count = sum(
                1 for c in co_located if c.get("status") == "Active"
            )

            data = {
                "address": address,
                "co_located_companies": co_located,
                "total_co_located": len(co_located),
                "active_co_located": active_count,
            }

            if not address:
                summary = f"No registered address found for '{company_name}'."
            elif not co_located:
                summary = (
                    f"'{company_name}' is the only company at its registered address "
                    f"({address.get('post_code', 'unknown postcode')})."
                )
            else:
                risk = _address_risk_label(len(co_located))
                summary = (
                    f"'{company_name}' shares its address "
                    f"({address.get('post_code', 'unknown postcode')}) "
                    f"with {len(co_located)} other companies "
                    f"({active_count} active). "
                    f"Address co-location risk: {risk}."
                )

            return ToolResult(
                tool_name="shared_address_check",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"company_name": company_name},
                summary=summary,
            )
        except Exception as e:
            return _error(
                "shared_address_check", {"company_name": company_name}, e, _ms(t0)
            )

    def sic_context(self, company_name: str) -> ToolResult:
        """
        Return the company's SIC codes and companies sharing at least one
        of those codes, ordered by overlap count.
        """
        t0 = time.monotonic()
        try:
            sics = self._repo.get_company_sic_context(company_name)
            peers = self._repo.get_companies_with_same_sic(
                company_name, limit=50
            )

            data = {"sic_codes": sics, "peers": peers}

            if not sics:
                summary = f"No SIC codes found for '{company_name}'."
            else:
                code_list = ", ".join(
                    f"{s['sic_code']} ({s['sic_description']})" for s in sics
                )
                summary = (
                    f"'{company_name}' operates under SIC code(s): {code_list}. "
                    f"Found {len(peers)} peer company(ies) sharing at least one code."
                )

            return ToolResult(
                tool_name="sic_context",
                success=True,
                data=data,
                duration_ms=_ms(t0),
                input={"company_name": company_name},
                summary=summary,
            )
        except Exception as e:
            return _error("sic_context", {"company_name": company_name}, e, _ms(t0))


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


def _address_risk_label(count: int) -> str:
    if count >= 50:
        return "HIGH"
    if count >= 10:
        return "MEDIUM"
    return "LOW"
