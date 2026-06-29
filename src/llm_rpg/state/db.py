"""SQLite connection management and schema initialization."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def _load_schema_sql() -> str:
    """Read the bundled schema.sql (works both from source and installed)."""
    try:
        return resources.files("llm_rpg.state").joinpath("schema.sql").read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, ModuleNotFoundError):
        return (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) a SQLite database and ensure the schema exists.

    The connection uses ``Row`` so columns are accessible by name, and enables
    foreign-key enforcement.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(_load_schema_sql())
    conn.commit()
    return conn


def connect_memory() -> sqlite3.Connection:
    """Open an in-memory database (used by tests)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(_load_schema_sql())
    conn.commit()
    return conn
