"""
Abstract base class for all AI client implementations.

Concrete clients (e.g. AnthropicClient) implement this interface so
the rest of the codebase remains independent of any specific provider SDK.
"""

from abc import ABC, abstractmethod


class AIClient(ABC):
    """Provider-agnostic interface for text and JSON generation."""

    @abstractmethod
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
    ) -> str:
        """
        Generate a plain-text response.

        Args:
            system_prompt: Instructions that set the model's behaviour.
            user_prompt:   The user's input or question.
            model:         Override the client's default model.
            max_tokens:    Upper bound on response length.

        Returns:
            The model's response as a string.

        Raises:
            RuntimeError: If the API call fails after retries.
        """

    @abstractmethod
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
    ) -> dict:
        """
        Generate a structured JSON response.

        The implementation is responsible for instructing the model to
        return valid JSON and for parsing the response safely.

        Args:
            system_prompt: Instructions that set the model's behaviour.
            user_prompt:   The user's input or question.
            model:         Override the client's default model.
            max_tokens:    Upper bound on response length.

        Returns:
            Parsed response as a dict.

        Raises:
            ValueError:   If the model returns text that cannot be parsed as JSON.
            RuntimeError: If the API call fails after retries.
        """
