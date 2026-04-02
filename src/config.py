"""
src.config — Application configuration from environment variables.

Loads ``.env`` via python-dotenv.  Call ``get_neo4j_settings()`` and
``get_anthropic_settings()`` to get validated settings objects.
Both raise ``EnvironmentError`` listing any missing required keys.

``get_remote_mcp_url()`` returns ``REMOTE_MCP_URL`` or an empty string.
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
