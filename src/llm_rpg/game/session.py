"""Save/load management: one SQLite file per run, discoverable on disk."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..state import db
from ..state.models import Run
from ..state.repository import Repository


@dataclass
class SaveInfo:
    path: Path
    run: Run


def saves_dir(config: Config) -> Path:
    path = Path(config.saves_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_saves(config: Config) -> list[SaveInfo]:
    """Discover all save files and read their run metadata."""
    saves: list[SaveInfo] = []
    for db_file in sorted(saves_dir(config).glob("*.db")):
        try:
            conn = db.connect(db_file)
            run = Repository(conn).latest_run()
            conn.close()
        except sqlite3.DatabaseError:
            continue
        if run is not None:
            saves.append(SaveInfo(path=db_file, run=run))
    saves.sort(key=lambda s: s.run.updated_at, reverse=True)
    return saves


@dataclass
class Session:
    conn: sqlite3.Connection
    repo: Repository
    run: Run
    path: Path

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()


def create_session(config: Config, world_prompt: str, seed: int) -> Session:
    """Create a fresh save file + run. World content is seeded separately."""
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    path = saves_dir(config) / f"{run_id}.db"
    conn = db.connect(path)
    repo = Repository(conn)
    run = repo.create_run(world_prompt=world_prompt, seed=seed, run_id=run_id)
    repo.commit()
    return Session(conn=conn, repo=repo, run=run, path=path)


def load_session(config: Config, path: str | Path) -> Session:
    path = Path(path)
    conn = db.connect(path)
    repo = Repository(conn)
    run = repo.latest_run()
    if run is None:
        conn.close()
        raise ValueError(f"no run found in save file: {path}")
    return Session(conn=conn, repo=repo, run=run, path=path)
