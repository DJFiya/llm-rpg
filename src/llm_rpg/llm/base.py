"""LLM provider interface plus a structured-output helper with repair retries.

The interface is deliberately tiny: a provider only needs to turn a
(system, user) pair into text. Everything else -- JSON parsing, schema
validation, and repair retries -- is handled here so every provider benefits
from the same anti-hallucination guardrails.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Type, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from ..config import Config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the LLM cannot produce a valid structured response."""


class LLMProvider(ABC):
    """Abstract base for all LLM backends."""

    name: str = "base"

    @abstractmethod
    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        """Return the model's text completion for the given prompts."""

    def generate_json(
        self,
        system: str,
        user: str,
        schema: Type[T],
        *,
        retries: int = 2,
    ) -> T:
        """Call the model and parse its output into ``schema``.

        On parse/validation failure, the error is fed back to the model up to
        ``retries`` times before giving up. This is the core guardrail that keeps
        malformed or partially hallucinated structures out of the world state.
        """
        schema_hint = _schema_hint(schema)
        full_system = (
            f"{system}\n\nRespond with ONLY a single JSON object that conforms to "
            f"this schema. Do not include markdown fences or commentary.\n{schema_hint}"
        )
        current_user = user
        last_error: Exception | None = None

        for _ in range(retries + 1):
            raw = self.complete(full_system, current_user, json_mode=True)
            try:
                payload = _extract_json(raw)
                return schema.model_validate(payload)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                current_user = (
                    f"{user}\n\nYour previous response was invalid: {exc}\n"
                    f"Return corrected JSON only."
                )

        raise LLMError(
            f"{self.name} failed to produce valid {schema.__name__}: {last_error}"
        )


def _schema_hint(schema: Type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), indent=2)


def _extract_json(raw: str) -> dict:
    """Best-effort extraction of a JSON object from a model response."""
    text = raw.strip()
    if text.startswith("```"):
        # Strip markdown code fences if the model added them anyway.
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    # Narrow to the outermost object braces.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in response")
    return json.loads(text[start : end + 1])


def build_provider(config: "Config") -> LLMProvider:
    """Factory: instantiate the provider named in the config."""
    name = config.provider.lower()
    pc = config.provider_config()

    if name == "mock":
        from .mock_provider import MockProvider

        return MockProvider()
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(pc)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(pc)
    if name == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(pc)

    raise LLMError(f"unknown provider: {config.provider!r}")
