"""
Anthropic SDK implementation of AIClient.

Default model is Haiku (fast, cheap). Pass model=settings.model_sonnet
for tasks that need stronger reasoning.

Kong AI Gateway (Phase 506)
----------------------------
When ``KongAIGatewaySettings.enabled`` is True the client routes all
Anthropic calls through Kong's ai-proxy plugin (the actual Kong AI Gateway
feature) instead of calling the Anthropic API directly.

  Direct mode  (default):
    App → Anthropic SDK → api.anthropic.com
    Auth: x-api-key from ANTHROPIC_API_KEY

  Kong mode  (KONG_AI_GATEWAY_ENABLED=true):
    App → POST KONG_PROXY_URL/ai → Kong ai-proxy plugin → api.anthropic.com
    Auth: X-Kong-API-Key sent to Kong (key-auth plugin validates it).
          Kong ai-proxy injects x-api-key (Anthropic credential) upstream.
          The app does NOT send the Anthropic key in Kong mode.

  Plugin clarification:
    ai-proxy           — Kong AI Gateway plugin. Routes to provider, injects
                         upstream auth. This is what we use.
    request-transformer — Static header edits. Not used here.
    ai-request-transformer — Uses an LLM to rewrite request content.
                              Completely unrelated to key injection.

The public interface (generate_text / generate_json) is identical in
both modes.  Callers never need to know which path is active.
"""

import json
import logging
import re
import time
from types import SimpleNamespace

import anthropic
import requests as _requests

_log = logging.getLogger(__name__)

from src.clients.ai_client import AIClient
from src.config import AnthropicSettings, KongAIGatewaySettings, get_anthropic_settings

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
        kong_settings: KongAIGatewaySettings instance. When provided and enabled,
            all calls are routed through the Kong proxy instead of the Anthropic
            API directly.  If omitted or disabled, direct mode is used.
    """

    def __init__(
        self,
        settings: AnthropicSettings | None = None,
        kong_settings: KongAIGatewaySettings | None = None,
    ) -> None:
        self._settings = settings or get_anthropic_settings()
        self._kong = kong_settings  # None or KongAIGatewaySettings
        self._default_model = self._settings.model_haiku
        # Populated after every _call() so callers can inspect token usage.
        self.last_usage: dict[str, int] | None = None

        if self._kong and self._kong.enabled:
            # Kong mode: use HTTP via requests; SDK client is not needed.
            self._client: anthropic.Anthropic | None = None
            _log.info(
                "AnthropicClient: Kong AI Gateway mode enabled → %s",
                self._kong.gateway_url,
            )
        else:
            # Direct mode: use the Anthropic SDK as before.
            self._client = anthropic.Anthropic(api_key=self._settings.api_key)
            _log.info("AnthropicClient: direct Anthropic mode")

    # ------------------------------------------------------------------
    # Public interface (identical in both modes)
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
    # Routing dispatcher
    # ------------------------------------------------------------------

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        cache_system: bool = False,
    ) -> SimpleNamespace:
        """Dispatch to Kong or direct path and return a response namespace."""
        if self._kong and self._kong.enabled:
            return self._call_via_kong(
                system_prompt, user_prompt, model, max_tokens, cache_system
            )
        return self._call_direct(
            system_prompt, user_prompt, model, max_tokens, cache_system
        )

    # ------------------------------------------------------------------
    # Direct mode (Anthropic SDK)
    # ------------------------------------------------------------------

    def _call_direct(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        cache_system: bool = False,
    ) -> SimpleNamespace:
        """
        Call the Anthropic Messages API via the SDK and update ``last_usage``.

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
        t0 = time.monotonic()
        try:
            msg = self._client.messages.create(  # type: ignore[union-attr]
                model=model,
                max_tokens=max_tokens,
                system=system_arg,
                messages=[{"role": "user", "content": user_prompt}],
            )
            elapsed = time.monotonic() - t0
            cache_read = getattr(msg.usage, "cache_read_input_tokens", 0) or 0
            cache_written = getattr(msg.usage, "cache_creation_input_tokens", 0) or 0
            in_tok  = msg.usage.input_tokens
            out_tok = msg.usage.output_tokens
            self.last_usage = {
                "input_tokens":               in_tok,
                "output_tokens":              out_tok,
                "total_tokens":               in_tok + out_tok,
                "cache_read_input_tokens":    cache_read,
                "cache_creation_input_tokens": cache_written,
            }
            _log.info(
                "%s %.2fs | in=%d out=%d total=%d cached=%d created=%d",
                model, elapsed, in_tok, out_tok, in_tok + out_tok,
                cache_read, cache_written,
            )
            # Wrap in a SimpleNamespace so _call() has a uniform return type.
            return SimpleNamespace(
                content=[SimpleNamespace(text=msg.content[0].text)]
            )
        except anthropic.AuthenticationError as e:
            raise RuntimeError(f"Anthropic authentication failed: {e}") from e
        except anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic rate limit exceeded: {e}") from e
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"Anthropic connection error: {e}") from e

    # ------------------------------------------------------------------
    # Kong mode (HTTP via requests)
    # ------------------------------------------------------------------

    def _call_via_kong(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        cache_system: bool = False,
    ) -> SimpleNamespace:
        """
        Call the Anthropic Messages API through the Kong ai-proxy plugin
        (Kong AI Gateway) and update ``last_usage``.

        The app sends ``X-Kong-API-Key`` to authenticate to Kong.  Kong
        validates the key (key-auth plugin) and the ai-proxy plugin routes
        the request to api.anthropic.com, injecting the Anthropic ``x-api-key``
        credential — the app does NOT send the Anthropic key in this mode.

        Request path:
            POST {KONG_PROXY_URL}{KONG_AI_GATEWAY_ROUTE_PATH}

        The ai-proxy plugin (route_type: llm/v1/chat) intercepts the request
        at the route and forwards to https://api.anthropic.com/v1/messages
        internally.  The app does NOT append /v1/messages — ai-proxy handles
        the upstream path.

        The anthropic-version header is configured in the ai-proxy plugin
        (model.options.anthropic_version) and injected by Kong.

        Response format
        ---------------
        Kong ai-proxy normalises responses to OpenAI chat.completion format
        (`choices[0].message.content`, `prompt_tokens`/`completion_tokens`)
        regardless of ``llm_format: anthropic`` — that setting controls the
        accepted *request* format only.  Both shapes are handled.

        Error mapping
        -------------
        401  — Kong rejected X-Kong-API-Key (check KONG_AI_GATEWAY_API_KEY)
        403  — Key valid but consumer lacks permission (check consumer config)
        404  — Route /ai not found in Konnect
        429  — Rate limit exceeded (rate-limiting plugin)
        5xx  — ai-proxy misconfiguration or Anthropic upstream error

        Raises:
            RuntimeError: On Kong auth failure, rate limit, connectivity issue,
                          or unexpected upstream error.
        """
        assert self._kong is not None  # guarded by caller

        if not self._kong.proxy_url:
            raise RuntimeError(
                "Kong AI Gateway is enabled but KONG_PROXY_URL is not set. "
                "Set KONG_PROXY_URL to the Serverless proxy URL shown in "
                "Konnect Gateway Manager (e.g. https://abc.eu.kong.tech). "
                "Note: this is NOT the Konnect API URL (https://au.api.konghq.com)."
            )
        if not self._kong.api_key:
            raise RuntimeError(
                "Kong AI Gateway is enabled but KONG_AI_GATEWAY_API_KEY is not set. "
                "Set KONG_AI_GATEWAY_API_KEY to the consumer credential key you "
                "created in Konnect for this application."
            )

        # Kong ai-proxy (llm/v1/chat route_type) uses OpenAI Chat Completions
        # format for requests.  The top-level "system" key is Anthropic-native
        # and is silently ignored by Kong — the system prompt must be sent as a
        # {"role": "system"} message inside the messages array instead.
        # cache_control blocks are also dropped (Kong does not relay them to
        # Anthropic's prompt-caching endpoint), so we extract the plain text.
        if cache_system:
            system_text = system_prompt  # cache_control stripped — not supported via Kong
        else:
            system_text = system_prompt

        messages: list[dict] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": user_prompt})

        # The ai-proxy plugin intercepts at the route; the app sends to the route
        # path only.  ai-proxy handles the /v1/messages upstream path internally.
        url = self._kong.gateway_url
        headers = {
            "Content-Type": "application/json",
            "X-Kong-API-Key": self._kong.api_key,
            # anthropic-version is NOT sent from the app — the ai-proxy plugin
            # injects it via model.options.anthropic_version in Konnect config.
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        t0 = time.monotonic()
        try:
            resp = _requests.post(url, headers=headers, json=payload, timeout=60)
        except _requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"Cannot reach Kong proxy at {url}. "
                "Check that KONG_PROXY_URL is the Serverless proxy URL "
                "(not the Konnect API URL) and that the gateway is running. "
                f"Underlying error: {e}"
            ) from e
        except _requests.exceptions.Timeout:
            raise RuntimeError(
                f"Request to Kong proxy timed out after 60s (url={url})."
            )

        elapsed = time.monotonic() - t0

        # Map common HTTP error codes to actionable messages.
        if resp.status_code == 401:
            raise RuntimeError(
                f"Kong rejected the API key (HTTP 401). "
                "Check that KONG_AI_GATEWAY_API_KEY matches the consumer "
                "credential configured in Konnect. "
                f"Response: {resp.text[:200]}"
            )
        if resp.status_code == 403:
            raise RuntimeError(
                f"Kong denied access (HTTP 403). "
                "The API key is valid but the consumer lacks permission on "
                "this route. Check ACL or plugin configuration in Konnect. "
                f"Response: {resp.text[:200]}"
            )
        if resp.status_code == 404:
            raise RuntimeError(
                f"Kong route not found (HTTP 404) at {url}. "
                "Check that the /ai route exists in Konnect and that the "
                "ai-proxy plugin is enabled on it. "
                f"Response: {resp.text[:200]}"
            )
        if resp.status_code == 429:
            raise RuntimeError(
                "Kong rate limit exceeded (HTTP 429). "
                "Wait and retry, or raise the rate-limiting plugin limit in Konnect. "
                f"Response: {resp.text[:200]}"
            )
        if resp.status_code >= 500:
            raise RuntimeError(
                f"Kong or upstream Anthropic error (HTTP {resp.status_code}). "
                "Common causes: ai-proxy plugin not configured on the /ai route, "
                "missing or wrong Anthropic API key in ai-proxy auth.header_value, "
                "or a transient Anthropic outage. "
                f"Response: {resp.text[:400]}"
            )
        if not resp.ok:
            raise RuntimeError(
                f"Unexpected HTTP {resp.status_code} from Kong proxy. "
                f"Response: {resp.text[:400]}"
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(
                f"Kong returned non-JSON response (HTTP {resp.status_code}). "
                f"Raw: {resp.text[:400]}"
            ) from e

        # Kong ai-proxy normalises responses to OpenAI chat.completion format
        # regardless of llm_format: anthropic (which controls the request format only).
        # Support both shapes so the code works regardless of Kong version behaviour.
        usage = data.get("usage", {})
        if "choices" in data:
            # OpenAI chat.completion format (Kong ai-proxy normalised response)
            try:
                text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                raise RuntimeError(
                    f"Unexpected Kong ai-proxy response shape (OpenAI format): {data}"
                ) from e
            in_tok  = usage.get("prompt_tokens", 0)
            out_tok = usage.get("completion_tokens", 0)
            self.last_usage = {
                "input_tokens":               in_tok,
                "output_tokens":              out_tok,
                "total_tokens":               usage.get("total_tokens", in_tok + out_tok),
                "cache_read_input_tokens":    0,
                "cache_creation_input_tokens": 0,
            }
        elif "content" in data:
            # Native Anthropic format (future-proof / direct pass-through mode)
            try:
                text = data["content"][0]["text"]
            except (KeyError, IndexError) as e:
                raise RuntimeError(
                    f"Unexpected Kong ai-proxy response shape (Anthropic format): {data}"
                ) from e
            in_tok  = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            self.last_usage = {
                "input_tokens":               in_tok,
                "output_tokens":              out_tok,
                "total_tokens":               in_tok + out_tok,
                "cache_read_input_tokens":    usage.get("cache_read_input_tokens", 0),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            }
        else:
            raise RuntimeError(
                f"Unrecognised response shape from Kong ai-proxy: {data}"
            )
        _log.info(
            "kong/%s %.2fs | in=%d out=%d total=%d",
            model, elapsed, in_tok, out_tok, in_tok + out_tok,
        )
        return SimpleNamespace(content=[SimpleNamespace(text=text)])

    # ------------------------------------------------------------------
    # JSON parsing helper
    # ------------------------------------------------------------------

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
