"""OpenAI-backed provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import LLMError, LLMProvider

if TYPE_CHECKING:
    from ..config import ProviderConfig


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, config: "ProviderConfig") -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - import guard
            raise LLMError(
                "The 'openai' package is required for the OpenAI provider. "
                "Install it with: pip install openai"
            ) from exc

        if not config.api_key:
            raise LLMError(
                "No OpenAI API key found. Set OPENAI_API_KEY or providers.openai.api_key."
            )
        self._client = OpenAI(api_key=config.api_key)
        self._model = config.model or "gpt-4o-mini"
        self._temperature = config.temperature

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        kwargs = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
