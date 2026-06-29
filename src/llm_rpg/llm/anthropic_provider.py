"""Anthropic (Claude)-backed provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import LLMError, LLMProvider

if TYPE_CHECKING:
    from ..config import ProviderConfig


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, config: "ProviderConfig") -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - import guard
            raise LLMError(
                "The 'anthropic' package is required for the Anthropic provider. "
                "Install it with: pip install anthropic"
            ) from exc

        if not config.api_key:
            raise LLMError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY or "
                "providers.anthropic.api_key."
            )
        self._client = anthropic.Anthropic(api_key=config.api_key)
        self._model = config.model or "claude-3-5-sonnet-latest"
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        # Claude has no dedicated JSON mode; the base class already instructs the
        # model to emit JSON only, and we extract/repair on our side.
        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [block.text for block in message.content if block.type == "text"]
        return "".join(parts)
