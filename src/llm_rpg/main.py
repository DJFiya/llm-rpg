"""CLI entry point for LLM RPG."""

from __future__ import annotations

import argparse
import sys

from .cli import GameCLI
from .config import load_config
from .llm.base import LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llm-rpg",
        description="An LLM-narrated text RPG with a deterministic world engine.",
    )
    parser.add_argument(
        "--config",
        help="Path to a config YAML file (defaults to config.yaml / config.example.yaml).",
        default=None,
    )
    parser.add_argument(
        "--provider",
        help="Override the LLM provider (mock|openai|anthropic|ollama).",
        default=None,
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.provider:
        config.provider = args.provider

    try:
        GameCLI(config).run()
    except LLMError as exc:
        print(f"LLM error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
