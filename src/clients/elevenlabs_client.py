"""
ElevenLabs text-to-speech client for voice alerts.

Security model
--------------
The client authenticates directly to api.elevenlabs.io using the official
``elevenlabs`` Python SDK, which sends the API key (loaded from
``ELEVENLABS_API_KEY``) as ``xi-api-key`` on every request.  There is no
Kong route on this path — voice alert traffic does not pass through the
AI Gateway or any other proxy.  The API key is never logged; only the
voice id, text length, and response time appear in INFO logs.

The client raises ``RuntimeError`` with a clear, analyst-safe message on
auth failures (401), validation errors (422), and upstream 5xx errors so
the caller can decide whether to surface or swallow the failure.  In the
Streamlit trigger path the error is always swallowed and logged as a
warning — voice alert failures must never block the investigation result.
"""

from __future__ import annotations

import logging
import time

from src.config import ElevenLabsSettings

_log = logging.getLogger(__name__)

_DEFAULT_MODEL_ID = "eleven_multilingual_v2"


class ElevenLabsClient:
    """Thin synchronous wrapper around the official ``elevenlabs`` SDK.

    Args:
        settings: ``ElevenLabsSettings`` loaded from environment.  Callers
                  should check ``settings.enabled`` before instantiating;
                  this class does not re-check.
    """

    def __init__(self, settings: ElevenLabsSettings) -> None:
        # Import inside __init__ so the module remains importable in test
        # environments that don't have the elevenlabs SDK installed.
        from elevenlabs.client import ElevenLabs
        from elevenlabs.types.voice_settings import VoiceSettings

        self._settings       = settings
        self._client         = ElevenLabs(api_key=settings.api_key)
        self._voice_settings = VoiceSettings(stability=0.5, similarity_boost=0.75)

    def synthesize(self, text: str) -> bytes:
        """Synthesise ``text`` to MP3 audio and return the raw bytes.

        Calls ``text_to_speech.convert`` on the SDK with the standard
        monolingual model and default voice settings.  Returns the audio
        body verbatim on success.  Raises ``RuntimeError`` with a redacted
        message on 401, 422, or 5xx (and any other transport failure).
        """
        start = time.monotonic()
        try:
            audio_iter = self._client.text_to_speech.convert(
                voice_id=self._settings.voice_id,
                text=text,
                model_id=_DEFAULT_MODEL_ID,
                voice_settings=self._voice_settings,
            )
            audio_bytes = b"".join(audio_iter)
        except Exception as exc:  # noqa: BLE001 — SDK exposes many sub-exception classes
            elapsed_ms = (time.monotonic() - start) * 1000.0
            status = getattr(exc, "status_code", None)
            detail = _extract_error_detail(exc)
            _log.warning(
                "ElevenLabs synthesize failed: voice_id=%s text_len=%d status=%s elapsed_ms=%.0f detail=%s",
                self._settings.voice_id,
                len(text),
                status,
                elapsed_ms,
                detail or exc,
            )
            if status == 401:
                raise RuntimeError(
                    f"ElevenLabs auth/permission failure (401): {detail or 'check ELEVENLABS_API_KEY and model permissions'}"
                ) from exc
            if status == 422:
                raise RuntimeError(
                    f"ElevenLabs rejected the request (422): {detail or exc}"
                ) from exc
            if isinstance(status, int) and status >= 500:
                raise RuntimeError(
                    f"ElevenLabs upstream error ({status}): {detail or 'try again later'}"
                ) from exc
            raise RuntimeError(f"ElevenLabs request failed: {detail or exc}") from exc

        elapsed_ms = (time.monotonic() - start) * 1000.0
        _log.info(
            "ElevenLabs synthesize: voice_id=%s text_len=%d audio_bytes=%d elapsed_ms=%.0f",
            self._settings.voice_id,
            len(text),
            len(audio_bytes),
            elapsed_ms,
        )
        return audio_bytes


def _extract_error_detail(exc: Exception) -> str:
    """Pull the human-readable ``detail.message`` out of an SDK ApiError.

    The SDK's ``ApiError`` exposes the parsed JSON response on ``.body``.
    Returns an empty string when no useful detail can be extracted, so the
    caller can fall back to ``str(exc)``.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict):
            msg = detail.get("message") or detail.get("status") or detail.get("code")
            if msg:
                return str(msg)
        if isinstance(detail, str):
            return detail
    return ""
