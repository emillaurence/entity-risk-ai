"""
Anthropic SDK implementation of AIClient.

Default model is Haiku (fast, cheap). Pass model=settings.model_sonnet
for tasks that need stronger reasoning.
"""

import json
import re

import anthropic

from src.clients.ai_client import AIClient
from src.config import AnthropicSettings, get_anthropic_settings

_JSON_SYSTEM_SUFFIX = (
    "\n\nYou must respond with valid JSON only. "
    "Do not include any text, explanation, or markdown outside the JSON object."
)

# Matches the first {...} or [...] block in a response, tolerating preamble.
_JSON_BLOCK_RE = re.compile(r"(\{[\s\S]*\}|\[[\s\S]*\])", re.DOTALL)


class AnthropicClient(AIClient):
    """
    AIClient backed by the Anthropic Messages API.

    Args:
        settings: AnthropicSettings instance. If omitted, loaded from environment.
    """

    def __init__(self, settings: AnthropicSettings | None = None) -> None:
        self._settings = settings or get_anthropic_settings()
        self._client = anthropic.Anthropic(api_key=self._settings.api_key)
        self._default_model = self._settings.model_haiku
        # Populated after every _call() so callers can inspect token usage.
        self.last_usage: dict[str, int] | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
    ) -> str:
        response = self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model or self._default_model,
            max_tokens=max_tokens,
        )
        return response.content[0].text

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
    ) -> dict:
        response = self._call(
            system_prompt=system_prompt + _JSON_SYSTEM_SUFFIX,
            user_prompt=user_prompt,
            model=model or self._default_model,
            max_tokens=max_tokens,
        )
        raw = response.content[0].text
        return self._parse_json(raw)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> anthropic.types.Message:
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            self.last_usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }
            return response
        except anthropic.AuthenticationError as e:
            raise RuntimeError(f"Anthropic authentication failed: {e}") from e
        except anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic rate limit exceeded: {e}") from e
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"Anthropic connection error: {e}") from e

    @staticmethod
    def _parse_json(raw: str) -> dict:
        # Fast path: the entire response is valid JSON.
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Slow path: extract the first JSON block from mixed text.
        match = _JSON_BLOCK_RE.search(raw)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        raise ValueError(
            f"Model response could not be parsed as JSON.\nRaw response:\n{raw}"
        )
