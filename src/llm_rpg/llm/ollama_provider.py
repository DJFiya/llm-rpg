"""Local model provider via the Ollama HTTP API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import LLMError, LLMProvider

if TYPE_CHECKING:
    from ..config import ProviderConfig


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, config: "ProviderConfig") -> None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - import guard
            raise LLMError(
                "The 'httpx' package is required for the Ollama provider. "
                "Install it with: pip install httpx"
            ) from exc

        self._httpx = httpx
        self._host = (config.host or "http://localhost:11434").rstrip("/")
        self._model = config.model or "llama3.1"
        self._temperature = config.temperature

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "options": {"temperature": self._temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["format"] = "json"
        try:
            response = self._httpx.post(
                f"{self._host}/api/chat", json=payload, timeout=120.0
            )
            response.raise_for_status()
        except self._httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        data = response.json()
        return data.get("message", {}).get("content", "")
