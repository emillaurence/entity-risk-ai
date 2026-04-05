"""
src.config — Application configuration from environment variables.

Loads ``.env`` via python-dotenv.  Call ``get_neo4j_settings()`` and
``get_anthropic_settings()`` to get validated settings objects.
Both raise ``EnvironmentError`` listing any missing required keys.

``get_remote_mcp_url()`` returns ``REMOTE_MCP_URL`` or an empty string.

``get_kong_settings()`` returns a ``KongSettings`` object populated from the
optional KONG_* environment variables.  **All Kong fields are optional and
default to safe "disabled" values.** No runtime path currently reads these
settings — they are scaffolded here so that future phases (506+) can import
them without changing the config module interface.
"""

from dataclasses import dataclass
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

    def masked(self) -> dict:
        """Return a safe repr with the API key redacted."""
        return {
            "api_key": f"{self.api_key[:8]}…***",
            "model_haiku": self.model_haiku,
            "model_sonnet": self.model_sonnet,
        }


def get_remote_mcp_url() -> str:
    """Return the remote MCP server URL, or empty string if not configured."""
    return os.getenv("REMOTE_MCP_URL", "")


# ---------------------------------------------------------------------------
# Kong Konnect / Gateway settings (all optional — future phases only)
# ---------------------------------------------------------------------------
#
# Phase 505 — Konnect control plane targeting (KongSettings below)
#    KONG_KONNECT_REGION             — Konnect region ("eu" | "us" | "au" | "in")
#    KONG_KONNECT_ADDR               — full Konnect API URL (e.g. https://au.api.konghq.com)
#    KONG_KONNECT_CONTROL_PLANE_NAME — name of your Serverless control plane
#    KONG_KONNECT_TOKEN              — Konnect Personal Access Token (PAT)
#    KONG_KONNECT_CONTROL_PLANE_ID   — UUID of the control plane (from Gateway Manager)
#
# Phase 506+ (NOT in KongSettings — loaded by future config objects in 506/507)
#    KONG_PROXY_URL                  — Serverless proxy URL (provided by Konnect UI)
#    KONG_AI_GATEWAY_ENABLED         — "true" to route AI calls through Kong
#    KONG_AI_GATEWAY_ROUTE_PATH      — proxy route path (default: /ai)
#    KONG_AI_GATEWAY_API_KEY         — key sent as X-Kong-API-Key
#    KONG_MCP_GATEWAY_ENABLED        — "true" to route MCP calls through Kong
#    KONG_MCP_GATEWAY_ROUTE_PATH     — proxy route path (default: /mcp)
#    KONG_MCP_GATEWAY_API_KEY        — key sent as X-Kong-API-Key
#
# Notebook live-test gate
#    ENABLE_LIVE_KONG_NOTEBOOK_TESTS — "true" to run cells that hit real Konnect
#
# None of these are required by the running app today.  The direct Anthropic
# and remote-MCP paths continue to be the primary runtime paths until a later
# phase explicitly switches to Kong-routed equivalents.


@dataclass
class KongSettings:
    """Optional Kong Konnect and Gateway configuration.

    All fields default to empty strings / False so the app runs without any
    Kong environment variables present.  Callers should check
    ``ai_gateway_enabled`` / ``mcp_gateway_enabled`` before using Kong paths.
    """

    # -- Control plane targeting -------------------------------------------
    konnect_region: str                 # e.g. "eu", "us", "au", "in"
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


def get_anthropic_settings() -> AnthropicSettings:
    missing = [key for key in _ANTHROPIC_REQUIRED if not os.getenv(key)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in the values."
        )

    return AnthropicSettings(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model_haiku=os.getenv("ANTHROPIC_MODEL_HAIKU", _ANTHROPIC_MODEL_HAIKU_DEFAULT),
        model_sonnet=os.getenv("ANTHROPIC_MODEL_SONNET", _ANTHROPIC_MODEL_SONNET_DEFAULT),
    )
