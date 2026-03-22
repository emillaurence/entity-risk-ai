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
        cache_system: bool = False,
    ) -> str:
        response = self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model or self._default_model,
            max_tokens=max_tokens,
            cache_system=cache_system,
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
        cache_system: bool = False,
    ) -> anthropic.types.Message:
        """
        Call the Anthropic Messages API and update ``last_usage``.

        Wraps all Anthropic SDK exceptions in RuntimeError so callers
        receive a consistent error type regardless of the underlying cause.
        Token counts (input, output, total) are stored in ``self.last_usage``
        after every successful call.

        When ``cache_system=True``, the system prompt is passed as a content
        block with ``cache_control: {type: ephemeral}``.  Requires the prompt
        to be ≥1024 tokens (Sonnet) or ≥2048 tokens (Haiku) for caching to
        activate; shorter prompts are accepted but not cached.

        Raises:
            RuntimeError: On authentication failure, rate limit, API error,
                          or connection error.
        """
        system_arg: str | list = (
            [{"type": "text", "text": system_prompt,
              "cache_control": {"type": "ephemeral"}}]
            if cache_system
            else system_prompt
        )
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_arg,
                messages=[{"role": "user", "content": user_prompt}],
            )
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cache_written = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            self.last_usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_written,
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
        """
        Parse a model response as JSON, tolerating preamble text.

        Fast path: tries ``json.loads`` on the full response.
        Slow path: extracts the first ``{...}`` or ``[...]`` block via regex,
        which handles models that prefix the JSON with explanation text.

        Raises:
            ValueError: If no valid JSON block can be extracted.
        """
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
