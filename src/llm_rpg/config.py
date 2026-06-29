"""Configuration loading and validation.

Resolution order for the config file:
  1. An explicit path passed to :func:`load_config`.
  2. ``config.yaml`` in the current working directory.
  3. ``config.example.yaml`` next to the project root.
  4. Built-in defaults (provider = "mock").

Environment variables ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` are used as
fallbacks for the corresponding provider API keys.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Settings for a single LLM provider. Extra keys are allowed."""

    model: str | None = None
    api_key: str | None = None
    host: str | None = None
    temperature: float = 0.8
    max_tokens: int = 1024

    model_config = {"extra": "allow"}


class Config(BaseModel):
    provider: str = "mock"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    saves_dir: str = "saves"
    memory_window: int = 12
    json_repair_retries: int = 2

    def provider_config(self) -> ProviderConfig:
        """Return the config block for the active provider (empty if missing)."""
        return self.providers.get(self.provider, ProviderConfig())


def _default_search_paths() -> list[Path]:
    cwd = Path.cwd()
    here = Path(__file__).resolve()
    project_root = here.parents[2]  # .../llm-rpg
    return [
        cwd / "config.yaml",
        project_root / "config.yaml",
        project_root / "config.example.yaml",
    ]


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load configuration from YAML, falling back to defaults."""
    raw: dict[str, Any] = {}
    chosen: Path | None = None

    candidates = [Path(path)] if path else _default_search_paths()
    for candidate in candidates:
        if candidate and candidate.is_file():
            chosen = candidate
            break

    if chosen is not None:
        with chosen.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if isinstance(loaded, dict):
            raw = loaded

    config = Config.model_validate(raw)
    _apply_env_fallbacks(config)
    return config


def _apply_env_fallbacks(config: Config) -> None:
    env_keys = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    for provider_name, env_var in env_keys.items():
        block = config.providers.get(provider_name)
        if block is None:
            block = ProviderConfig()
            config.providers[provider_name] = block
        if not block.api_key:
            block.api_key = os.environ.get(env_var)
