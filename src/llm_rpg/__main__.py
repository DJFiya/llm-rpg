"""Allow ``python -m llm_rpg`` as well as ``python -m llm_rpg.main``."""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
