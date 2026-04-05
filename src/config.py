"""
src.config — Application configuration from environment variables.

Loads ``.env`` via python-dotenv.  Call ``get_neo4j_settings()`` and
``get_anthropic_settings()`` to get validated settings objects.
Both raise ``EnvironmentError`` listing any missing required keys.

``get_remote_mcp_url()`` returns ``REMOTE_MCP_URL`` or an empty string.

``get_kong_settings()`` returns a ``KongSettings`` object with Phase 505
Konnect control-plane targeting vars.  All fields are optional.

``get_kong_ai_gateway_settings()`` returns a ``KongAIGatewaySettings`` object
for Phase 506 AI Gateway routing.  When ``enabled`` is False (the default) the
app uses the direct Anthropic path — no Kong vars need to be set.

``get_kong_mcp_gateway_settings()`` returns a ``KongMCPGatewaySettings`` object
for Phase 507 MCP Gateway transport setup.  When ``enabled`` is False (the
default) the app uses the direct remote MCP path unchanged.

``kong_acl_enforcement_active(mcp_mode, settings)`` returns True only when ALL
THREE Phase 509 ACL conditions are met: KONG_MCP_GATEWAY_ENABLED=true,
KONG_MCP_ACL_POLICY_ENABLED=true, and the UI MCP backend is "kong".
"""

from dataclasses import dataclass, replace
from dotenv import load_dotenv
import os

load_dotenv()

_NEO4J_REQUIRED = [
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
]

_ANTHROPIC_REQUIRED = [
    "ANTHROPIC_API_KEY",
]

_ANTHROPIC_MODEL_HAIKU_DEFAULT = "claude-haiku-4-5-20251001"
_ANTHROPIC_MODEL_SONNET_DEFAULT = "claude-sonnet-4-6"


@dataclass
class Neo4jSettings:
    uri: str
    username: str
    password: str
    database: str

    def masked(self) -> dict:
        """Return a safe repr with password redacted."""
        return {
            "uri": self.uri,
            "username": self.username,
            "password": "***",
            "database": self.database,
        }


def get_neo4j_settings() -> Neo4jSettings:
    missing = [key for key in _NEO4J_REQUIRED if not os.getenv(key)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in the values."
        )

    return Neo4jSettings(
        uri=os.environ["NEO4J_URI"],
        username=os.environ["NEO4J_USERNAME"],
        password=os.environ["NEO4J_PASSWORD"],
        database=os.environ["NEO4J_DATABASE"],
    )


@dataclass
class AnthropicSettings:
    api_key: str
    model_haiku: str
    model_sonnet: str
    planner_model: str  # model used exclusively by InvestigationPlanner (defaults to model_sonnet)

    def masked(self) -> dict:
        """Return a safe repr with the API key redacted."""
        return {
            "api_key": f"{self.api_key[:8]}…***",
            "model_haiku": self.model_haiku,
            "model_sonnet": self.model_sonnet,
            "planner_model": self.planner_model,
        }


def get_remote_mcp_url() -> str:
    """Return the remote MCP server URL, or empty string if not configured."""
    return os.getenv("REMOTE_MCP_URL", "")


# ---------------------------------------------------------------------------
# Kong Konnect / Gateway settings (all optional)
# ---------------------------------------------------------------------------
#
# Phase 505 — Konnect control plane targeting (KongSettings below)
#    KONG_KONNECT_ADDR               — full Konnect API URL (e.g. https://au.api.konghq.com)
#                                      The region is encoded in the URL; no separate region var.
#    KONG_KONNECT_CONTROL_PLANE_NAME — name of your Serverless control plane
#    KONG_KONNECT_TOKEN              — Konnect Personal Access Token (PAT)
#    KONG_KONNECT_CONTROL_PLANE_ID   — UUID of the control plane (from Gateway Manager)
#
# Phase 506 — AI Gateway routing (loaded by KongAIGatewaySettings below)
#    KONG_PROXY_URL                  — Serverless proxy URL (shown in Konnect Gateway Manager)
#                                      NOTE: this is NOT the Konnect API URL (KONG_KONNECT_ADDR)
#    KONG_AI_GATEWAY_ENABLED         — "true" to route AI calls through Kong (default: false)
#    KONG_AI_GATEWAY_ROUTE_PATH      — proxy route path (default: /ai)
#    KONG_AI_GATEWAY_SONNET_ROUTE_PATH — planner-only Sonnet route path (default: /ai/sonnet)
#    KONG_AI_GATEWAY_API_KEY         — key sent as X-Kong-API-Key to Kong
#
# Phase 507 — MCP Gateway transport (loaded by KongMCPGatewaySettings below)
#    KONG_MCP_GATEWAY_ENABLED        — "true" to route MCP smoke tests through Kong (default: false)
#    KONG_MCP_GATEWAY_ROUTE_PATH     — proxy route path for MCP (default: /mcp)
#    KONG_MCP_GATEWAY_API_KEY        — separate key sent as X-Kong-API-Key for MCP traffic
#    KONG_MCP_UPSTREAM_URL           — upstream remote MCP server URL Kong forwards to
#                                      (default: https://entity-risk-ai-production.up.railway.app/mcp)
#
# Notebook live-test gate
#    ENABLE_LIVE_KONG_NOTEBOOK_TESTS — "true" to run cells that hit real Konnect / proxy
#
# The direct Anthropic path and remote-MCP path remain the default.  Kong
# routing only activates when explicitly enabled via the flags above.


@dataclass
class KongSettings:
    """Optional Kong Konnect and Gateway configuration.

    All fields default to empty strings / False so the app runs without any
    Kong environment variables present.  Callers should check
    ``ai_gateway_enabled`` / ``mcp_gateway_enabled`` before using Kong paths.
    """

    # -- Control plane targeting -------------------------------------------
    konnect_region: str                 # deprecated: region is encoded in konnect_addr
    konnect_addr: str                   # e.g. "https://au.api.konghq.com"
    konnect_control_plane_name: str     # name as shown in Konnect UI
    konnect_token: str                  # Konnect PAT (secret)
    konnect_control_plane_id: str       # ID of the control plane (UUID)

    # -- Notebook test gate ------------------------------------------------
    notebook_live_tests: bool           # True = notebook cells hit real Konnect

    def masked(self) -> dict:
        """Return a safe repr with secrets redacted."""
        token_preview = f"{self.konnect_token[:8]}…***" if self.konnect_token else ""
        return {
            "konnect_region": self.konnect_region,
            "konnect_addr": self.konnect_addr,
            "konnect_control_plane_name": self.konnect_control_plane_name,
            "konnect_token": token_preview,
            "konnect_control_plane_id": self.konnect_control_plane_id,
            "notebook_live_tests": self.notebook_live_tests,
        }


def get_kong_settings() -> KongSettings:
    """Return Kong settings read from environment variables.

    All fields are optional.  Missing variables fall back to safe defaults so
    existing code paths are completely unaffected when Kong is not configured.
    """

    def _bool(key: str) -> bool:
        return os.getenv(key, "").strip().lower() == "true"

    return KongSettings(
        konnect_region=os.getenv("KONG_KONNECT_REGION", ""),
        konnect_addr=os.getenv("KONG_KONNECT_ADDR", ""),
        konnect_control_plane_name=os.getenv("KONG_KONNECT_CONTROL_PLANE_NAME", ""),
        konnect_token=os.getenv("KONG_KONNECT_TOKEN", ""),
        konnect_control_plane_id=os.getenv("KONG_KONNECT_CONTROL_PLANE_ID", ""),
        notebook_live_tests=_bool("ENABLE_LIVE_KONG_NOTEBOOK_TESTS"),
    )


# ---------------------------------------------------------------------------
# Phase 506 — Kong AI Gateway routing settings
# ---------------------------------------------------------------------------

@dataclass
class KongAIGatewaySettings:
    """Kong AI Gateway configuration for Phase 506.

    Controls whether the app routes Anthropic calls through a Kong proxy
    instead of calling the Anthropic API directly.

    All fields default to safe "disabled" values.  When ``enabled`` is False
    (the default) the app uses the direct Anthropic path and none of the
    other fields matter.

    Security model
    --------------
    The app authenticates to Kong using ``api_key`` (sent as ``X-Kong-API-Key``).
    Kong validates this key via the key-auth plugin on the ``/ai`` route.
    Kong injects the upstream Anthropic ``x-api-key`` header via a
    request-transformer plugin — the app does **not** need to send the
    Anthropic credential when routing through Kong.

    URL breakdown (three separate things)
    --------------------------------------
    proxy_url   — Serverless gateway proxy URL (e.g. https://abc.eu.kong.tech).
                  This is NOT the Konnect API URL (https://au.api.konghq.com).
    route_path  — The route Kong is listening on (default: /ai).
    gateway_url — proxy_url + route_path.  This is the endpoint the app sends
                  requests to.  Kong strips the route prefix before forwarding.
    """

    enabled: bool           # True = route AI calls through Kong; False = direct Anthropic
    proxy_url: str          # Serverless proxy base URL (from Konnect Gateway Manager)
    route_path: str         # Generic AI route path (default: /ai)
    api_key: str            # Key sent as X-Kong-API-Key to authenticate to Kong
    sonnet_route_path: str  # Planner-only Sonnet route path (default: /ai/sonnet)

    @property
    def gateway_url(self) -> str:
        """Full URL of the generic AI gateway route (proxy_url + route_path)."""
        return self.proxy_url.rstrip("/") + self.route_path

    @property
    def sonnet_gateway_url(self) -> str:
        """Full URL of the planner-only Sonnet route (proxy_url + sonnet_route_path)."""
        return self.proxy_url.rstrip("/") + self.sonnet_route_path

    def for_planner(self) -> "KongAIGatewaySettings":
        """Return a copy of these settings routing to the Sonnet/planner Kong route.

        Used by factory.py to create a dedicated AnthropicClient for the planner
        that sends traffic to /ai/sonnet instead of /ai.  All other fields
        (enabled, proxy_url, api_key) are unchanged so the fallback to direct
        Anthropic mode works correctly when enabled=False.
        """
        return replace(self, route_path=self.sonnet_route_path)

    def masked(self) -> dict:
        """Return a safe repr with secrets redacted."""
        key_preview = f"{self.api_key[:8]}…***" if self.api_key else ""
        return {
            "enabled": self.enabled,
            "proxy_url": self.proxy_url,
            "route_path": self.route_path,
            "sonnet_route_path": self.sonnet_route_path,
            "api_key": key_preview,
            "gateway_url": self.gateway_url if self.proxy_url else "(proxy_url not set)",
            "sonnet_gateway_url": self.sonnet_gateway_url if self.proxy_url else "(proxy_url not set)",
        }


def get_kong_ai_gateway_settings() -> KongAIGatewaySettings:
    """Return Kong AI Gateway settings from environment variables.

    All fields are optional.  When ``enabled`` is False (the default), the
    app continues to use the direct Anthropic path unchanged.
    """
    def _bool(key: str) -> bool:
        return os.getenv(key, "").strip().lower() == "true"

    return KongAIGatewaySettings(
        enabled=_bool("KONG_AI_GATEWAY_ENABLED"),
        proxy_url=os.getenv("KONG_PROXY_URL", ""),
        route_path=os.getenv("KONG_AI_GATEWAY_ROUTE_PATH", "/ai"),
        api_key=os.getenv("KONG_AI_GATEWAY_API_KEY", ""),
        sonnet_route_path=os.getenv("KONG_AI_GATEWAY_SONNET_ROUTE_PATH", "/ai/sonnet"),
    )


# ---------------------------------------------------------------------------
# Phase 507 — Kong MCP Gateway routing settings
# ---------------------------------------------------------------------------

@dataclass
class KongMCPGatewaySettings:
    """Kong MCP Gateway configuration for Phase 507.

    Controls whether smoke tests (and eventually the app) route MCP calls
    through a Kong proxy instead of calling the upstream Railway endpoint
    directly.

    All fields default to safe "disabled" values.  When ``enabled`` is False
    (the default) no Kong MCP vars are read or required, and the existing
    remote MCP path is completely unaffected.

    Security model
    --------------
    The caller authenticates to Kong using ``api_key`` (sent as
    ``X-Kong-API-Key``).  Kong validates this key via the key-auth plugin on
    the ``/mcp`` route, then forwards the request to ``upstream_url``
    preserving the path and body exactly as received.

    URL breakdown (three separate things)
    --------------------------------------
    proxy_url    — Serverless gateway proxy URL (e.g. https://abc.eu.kong.tech).
                   This is NOT the Konnect API URL (https://au.api.konghq.com).
    route_path   — The route Kong is listening on (default: /mcp).
    gateway_url  — proxy_url + route_path.  Callers POST MCP requests here.
                   Kong preserves the path when forwarding to upstream_url.
    upstream_url — The actual remote MCP server sitting behind Kong.
    """

    enabled: bool            # True = route MCP calls through Kong; False = direct remote MCP
    proxy_url: str           # Serverless proxy base URL (from Konnect Gateway Manager)
    route_path: str          # MCP route path (default: /mcp)
    api_key: str             # Shared key (fallback when no per-role key is set)
    upstream_url: str        # Upstream MCP server URL (full path, preserved by Kong)
    acl_policy_enabled: bool # Phase 509 — True = Kong enforces tool ACL per consumer group
    jr_api_key: str          # Phase 509 — key for jr-analyst-app consumer (KONG_MCP_ACL_JR_API_KEY)
    sr_api_key: str          # Phase 509 — key for sr-analyst-app consumer (KONG_MCP_ACL_SR_API_KEY)

    @property
    def gateway_url(self) -> str:
        """Full URL of the Kong MCP gateway route (proxy_url + route_path)."""
        return self.proxy_url.rstrip("/") + self.route_path

    def resolve_api_key(self, role: str) -> str:
        """Return the API key to use for *role*.

        When ACL is active, each role has a dedicated consumer with its own
        key so Kong can attribute the request to the correct consumer group.
        Falls back to the shared ``api_key`` when no role-specific key is set.

        Role strings match the stable identifiers in ``src.app.policy``:
            ``"jr_risk_analyst"`` → ``jr_api_key`` (KONG_MCP_ACL_JR_API_KEY)
            ``"sr_risk_analyst"`` → ``sr_api_key`` (KONG_MCP_ACL_SR_API_KEY)
        """
        if role == "jr_risk_analyst" and self.jr_api_key:
            return self.jr_api_key
        if role == "sr_risk_analyst" and self.sr_api_key:
            return self.sr_api_key
        return self.api_key

    def masked(self) -> dict:
        """Return a safe repr with secrets redacted."""
        def _preview(key: str) -> str:
            return f"{key[:8]}…***" if key else ""
        return {
            "enabled": self.enabled,
            "proxy_url": self.proxy_url,
            "route_path": self.route_path,
            "api_key": _preview(self.api_key),
            "upstream_url": self.upstream_url,
            "gateway_url": self.gateway_url if self.proxy_url else "(proxy_url not set)",
            "acl_policy_enabled": self.acl_policy_enabled,
            "jr_api_key": _preview(self.jr_api_key),
            "sr_api_key": _preview(self.sr_api_key),
        }


def get_kong_mcp_gateway_settings() -> KongMCPGatewaySettings:
    """Return Kong MCP Gateway settings from environment variables.

    All fields are optional.  When ``enabled`` is False (the default), the
    app continues to use the direct remote MCP path unchanged.
    """
    def _bool(key: str) -> bool:
        return os.getenv(key, "").strip().lower() == "true"

    return KongMCPGatewaySettings(
        enabled=_bool("KONG_MCP_GATEWAY_ENABLED"),
        proxy_url=os.getenv("KONG_PROXY_URL", ""),
        route_path=os.getenv("KONG_MCP_GATEWAY_ROUTE_PATH", "/mcp"),
        api_key=os.getenv("KONG_MCP_GATEWAY_API_KEY", ""),
        upstream_url=os.getenv(
            "KONG_MCP_UPSTREAM_URL",
            "https://entity-risk-ai-production.up.railway.app/mcp",
        ),
        acl_policy_enabled=_bool("KONG_MCP_ACL_POLICY_ENABLED"),
        jr_api_key=os.getenv("KONG_MCP_ACL_JR_API_KEY", ""),
        sr_api_key=os.getenv("KONG_MCP_ACL_SR_API_KEY", ""),
    )


# ---------------------------------------------------------------------------
# Phase 509 — Kong MCP ACL policy enforcement helper
# ---------------------------------------------------------------------------


def kong_acl_enforcement_active(
    mcp_mode: str,
    settings: "KongMCPGatewaySettings",
) -> bool:
    """Return True when all three Kong ACL enforcement conditions are met.

    Kong ACL is ACTIVE only when:
      1. settings.enabled is True        (KONG_MCP_GATEWAY_ENABLED=true)
      2. settings.acl_policy_enabled is True (KONG_MCP_ACL_POLICY_ENABLED=true)
      3. mcp_mode == "kong"              (UI backend selection)

    When any condition is False the app falls back to its own policy.py
    tool allowlist — Kong is either not in the path or not enforcing ACL.
    """
    return settings.enabled and settings.acl_policy_enabled and mcp_mode == "kong"


def get_anthropic_settings() -> AnthropicSettings:
    missing = [key for key in _ANTHROPIC_REQUIRED if not os.getenv(key)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in the values."
        )

    model_sonnet = os.getenv("ANTHROPIC_MODEL_SONNET", _ANTHROPIC_MODEL_SONNET_DEFAULT)
    return AnthropicSettings(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model_haiku=os.getenv("ANTHROPIC_MODEL_HAIKU", _ANTHROPIC_MODEL_HAIKU_DEFAULT),
        model_sonnet=model_sonnet,
        # PLANNER_MODEL defaults to model_sonnet so the planner always uses Sonnet
        # unless explicitly overridden (e.g. PLANNER_MODEL=claude-haiku-4-5-20251001).
        planner_model=os.getenv("PLANNER_MODEL", model_sonnet),
    )
