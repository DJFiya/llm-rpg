#!/usr/bin/env python3
"""Launch LLM RPG without a prior ``pip install -e .`` (dev convenience).

Prefer installing the package once:
  pip install -e .
  python -m llm_rpg
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from llm_rpg.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
