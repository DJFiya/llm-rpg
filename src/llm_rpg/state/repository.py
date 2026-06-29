"""Repository: all reads/writes to the world-state database.

Every query that the game needs lives here so the rest of the codebase never
touches SQL directly. "Lookup values, not constants" is implemented by these
methods: facts, stats, locations and entities are always fetched from the store.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from .models import (
    ActionLogEntry,
    Connection,
    ConversationEntry,
    Entity,
    EntityType,
    Fact,
    Location,
    Quest,
    Run,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def commit(self) -> None:
        self.conn.commit()

    # --- Runs -----------------------------------------------------------------
    def create_run(
        self,
        world_prompt: str,
        seed: int,
        genre: str | None = None,
        run_id: str | None = None,
    ) -> Run:
        run_id = run_id or new_id("run")
        ts = _now()
        self.conn.execute(
            """INSERT INTO runs (id, world_prompt, genre, seed, turn, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)""",
            (run_id, world_prompt, genre, seed, ts, ts),
        )
        return Run(
            id=run_id,
            world_prompt=world_prompt,
            genre=genre,
            seed=seed,
            turn=0,
            created_at=ts,
            updated_at=ts,
        )

    def get_run(self, run_id: str) -> Run | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return Run.model_validate(dict(row)) if row else None

    def latest_run(self) -> Run | None:
        row = self.conn.execute(
            "SELECT * FROM runs ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return Run.model_validate(dict(row)) if row else None

    def set_run_player(self, run_id: str, player_id: str) -> None:
        self.conn.execute(
            "UPDATE runs SET player_id = ?, updated_at = ? WHERE id = ?",
            (player_id, _now(), run_id),
        )

    def set_run_genre(self, run_id: str, genre: str) -> None:
        self.conn.execute(
            "UPDATE runs SET genre = ?, updated_at = ? WHERE id = ?",
            (genre, _now(), run_id),
        )

    def advance_turn(self, run_id: str) -> int:
        cur = self.conn.execute(
            "UPDATE runs SET turn = turn + 1, updated_at = ? WHERE id = ? RETURNING turn",
            (_now(), run_id),
        )
        return int(cur.fetchone()[0])

    # --- Locations ------------------------------------------------------------
    def create_location(
        self,
        run_id: str,
        name: str,
        x: int,
        y: int,
        region: str = "world",
        description: str = "",
    ) -> Location:
        loc_id = new_id("loc")
        self.conn.execute(
            """INSERT INTO locations (id, run_id, name, region, x, y, description, discovered)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (loc_id, run_id, name, region, x, y, description),
        )
        return Location(
            id=loc_id,
            run_id=run_id,
            name=name,
            region=region,
            x=x,
            y=y,
            description=description,
        )

    def get_location(self, loc_id: str) -> Location | None:
        row = self.conn.execute(
            "SELECT * FROM locations WHERE id = ?", (loc_id,)
        ).fetchone()
        return Location.model_validate(dict(row)) if row else None

    def location_at(
        self, run_id: str, region: str, x: int, y: int
    ) -> Location | None:
        row = self.conn.execute(
            "SELECT * FROM locations WHERE run_id = ? AND region = ? AND x = ? AND y = ?",
            (run_id, region, x, y),
        ).fetchone()
        return Location.model_validate(dict(row)) if row else None

    def set_location_description(self, loc_id: str, description: str) -> None:
        self.conn.execute(
            "UPDATE locations SET description = ? WHERE id = ?", (description, loc_id)
        )

    def all_locations(self, run_id: str) -> list[Location]:
        rows = self.conn.execute(
            "SELECT * FROM locations WHERE run_id = ? ORDER BY region, y, x", (run_id,)
        ).fetchall()
        return [Location.model_validate(dict(r)) for r in rows]

    # --- Connections ----------------------------------------------------------
    def add_connection(
        self, run_id: str, from_location: str, to_location: str, direction: str
    ) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO connections (run_id, from_location, to_location, direction)
               VALUES (?, ?, ?, ?)""",
            (run_id, from_location, to_location, direction),
        )

    def connections_from(self, location_id: str) -> list[Connection]:
        rows = self.conn.execute(
            "SELECT * FROM connections WHERE from_location = ?", (location_id,)
        ).fetchall()
        return [
            Connection(
                run_id=r["run_id"],
                from_location=r["from_location"],
                to_location=r["to_location"],
                direction=r["direction"],
            )
            for r in rows
        ]

    def connection_in_direction(
        self, location_id: str, direction: str
    ) -> Connection | None:
        row = self.conn.execute(
            "SELECT * FROM connections WHERE from_location = ? AND direction = ?",
            (location_id, direction),
        ).fetchone()
        if not row:
            return None
        return Connection(
            run_id=row["run_id"],
            from_location=row["from_location"],
            to_location=row["to_location"],
            direction=row["direction"],
        )

    # --- Entities -------------------------------------------------------------
    def create_entity(
        self, run_id: str, type_: EntityType, name: str, status: str = "active"
    ) -> Entity:
        ent_id = new_id(type_.value)
        self.conn.execute(
            "INSERT INTO entities (id, run_id, type, name, status) VALUES (?, ?, ?, ?, ?)",
            (ent_id, run_id, type_.value, name, status),
        )
        return Entity(id=ent_id, run_id=run_id, type=type_, name=name, status=status)

    def get_entity(self, ent_id: str) -> Entity | None:
        row = self.conn.execute(
            "SELECT * FROM entities WHERE id = ?", (ent_id,)
        ).fetchone()
        return Entity.model_validate(dict(row)) if row else None

    def find_entity_by_name(self, run_id: str, name: str) -> Entity | None:
        row = self.conn.execute(
            "SELECT * FROM entities WHERE run_id = ? AND name = ? COLLATE NOCASE",
            (run_id, name),
        ).fetchone()
        return Entity.model_validate(dict(row)) if row else None

    def set_entity_status(self, ent_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE entities SET status = ? WHERE id = ?", (status, ent_id)
        )

    def entities_at(
        self, location_id: str, exclude_id: str | None = None
    ) -> list[Entity]:
        rows = self.conn.execute(
            """SELECT e.* FROM entities e
               JOIN entity_location el ON el.entity_id = e.id
               WHERE el.location_id = ?""",
            (location_id,),
        ).fetchall()
        result = [
            Entity.model_validate(dict(r))
            for r in rows
            if dict(r).get("status") != "dead"
        ]
        if exclude_id:
            result = [e for e in result if e.id != exclude_id]
        return result

    def defeated_enemies(self, run_id: str) -> list[Entity]:
        rows = self.conn.execute(
            """SELECT * FROM entities
               WHERE run_id = ? AND type = 'enemy' AND status = 'dead'""",
            (run_id,),
        ).fetchall()
        return [Entity.model_validate(dict(r)) for r in rows]

    def recent_conversation_partner_name(self, run_id: str) -> str | None:
        row = self.conn.execute(
            """SELECT e.name FROM conversation_log cl
               JOIN entities e ON e.id = cl.entity_id
               WHERE cl.run_id = ? AND e.type IN ('npc', 'enemy')
               ORDER BY cl.id DESC LIMIT 1""",
            (run_id,),
        ).fetchone()
        return row["name"] if row else None

    def recent_conversation_npc_name(self, run_id: str) -> str | None:
        """Alias for interaction focus (NPCs and enemies)."""
        return self.recent_conversation_partner_name(run_id)

    # --- Entity location ------------------------------------------------------
    def place_entity(
        self, run_id: str, entity_id: str, location_id: str | None
    ) -> None:
        self.conn.execute(
            """INSERT INTO entity_location (entity_id, location_id, run_id)
               VALUES (?, ?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET location_id = excluded.location_id""",
            (entity_id, location_id, run_id),
        )

    def entity_location(self, entity_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT location_id FROM entity_location WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        return row["location_id"] if row else None

    # --- Stats ----------------------------------------------------------------
    def set_stat(self, entity_id: str, key: str, value: float) -> None:
        self.conn.execute(
            """INSERT INTO stats (entity_id, key, value) VALUES (?, ?, ?)
               ON CONFLICT(entity_id, key) DO UPDATE SET value = excluded.value""",
            (entity_id, key, value),
        )

    def get_stat(self, entity_id: str, key: str) -> float | None:
        row = self.conn.execute(
            "SELECT value FROM stats WHERE entity_id = ? AND key = ?",
            (entity_id, key),
        ).fetchone()
        return float(row["value"]) if row else None

    def get_stats(self, entity_id: str) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT key, value FROM stats WHERE entity_id = ?", (entity_id,)
        ).fetchall()
        return {r["key"]: float(r["value"]) for r in rows}

    # --- Inventory ------------------------------------------------------------
    def add_to_inventory(self, owner_id: str, item_id: str, qty: int = 1) -> None:
        self.conn.execute(
            """INSERT INTO inventory (owner_id, item_id, qty) VALUES (?, ?, ?)
               ON CONFLICT(owner_id, item_id) DO UPDATE SET qty = qty + excluded.qty""",
            (owner_id, item_id, qty),
        )

    def remove_from_inventory(self, owner_id: str, item_id: str) -> None:
        self.conn.execute(
            "DELETE FROM inventory WHERE owner_id = ? AND item_id = ?",
            (owner_id, item_id),
        )

    def inventory(self, owner_id: str) -> list[tuple[Entity, int]]:
        rows = self.conn.execute(
            """SELECT e.*, i.qty AS qty FROM inventory i
               JOIN entities e ON e.id = i.item_id
               WHERE i.owner_id = ?""",
            (owner_id,),
        ).fetchall()
        result: list[tuple[Entity, int]] = []
        for r in rows:
            data = dict(r)
            qty = int(data.pop("qty"))
            result.append((Entity.model_validate(data), qty))
        return result

    def set_inventory_qty(self, owner_id: str, item_id: str, qty: int) -> None:
        if qty <= 0:
            self.remove_from_inventory(owner_id, item_id)
            return
        self.conn.execute(
            "UPDATE inventory SET qty = ? WHERE owner_id = ? AND item_id = ?",
            (qty, owner_id, item_id),
        )

    def inventory_holder(self, item_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT owner_id FROM inventory WHERE item_id = ? LIMIT 1",
            (item_id,),
        ).fetchone()
        return row["owner_id"] if row else None

    def inventory_qty(self, owner_id: str, item_id: str) -> int:
        row = self.conn.execute(
            "SELECT qty FROM inventory WHERE owner_id = ? AND item_id = ?",
            (owner_id, item_id),
        ).fetchone()
        return int(row["qty"]) if row else 0

    # --- Equipment ------------------------------------------------------------
    def equip(self, owner_id: str, slot: str, item_id: str) -> None:
        self.conn.execute(
            """INSERT INTO equipped (owner_id, slot, item_id) VALUES (?, ?, ?)
               ON CONFLICT(owner_id, slot) DO UPDATE SET item_id = excluded.item_id""",
            (owner_id, slot, item_id),
        )

    def unequip(self, owner_id: str, slot: str) -> None:
        self.conn.execute(
            "DELETE FROM equipped WHERE owner_id = ? AND slot = ?",
            (owner_id, slot),
        )

    def get_equipped(self, owner_id: str, slot: str) -> str | None:
        row = self.conn.execute(
            "SELECT item_id FROM equipped WHERE owner_id = ? AND slot = ?",
            (owner_id, slot),
        ).fetchone()
        return row["item_id"] if row else None

    def all_equipped(self, owner_id: str) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT slot, item_id FROM equipped WHERE owner_id = ?",
            (owner_id,),
        ).fetchall()
        return {r["slot"]: r["item_id"] for r in rows}

    # --- Facts ----------------------------------------------------------------
    def set_fact(self, run_id: str, subject_id: str, key: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO facts (run_id, subject_id, key, value) VALUES (?, ?, ?, ?)
               ON CONFLICT(run_id, subject_id, key) DO UPDATE SET value = excluded.value""",
            (run_id, subject_id, key, value),
        )

    def get_fact(self, run_id: str, subject_id: str, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM facts WHERE run_id = ? AND subject_id = ? AND key = ?",
            (run_id, subject_id, key),
        ).fetchone()
        return row["value"] if row else None

    def facts_for(self, run_id: str, subject_id: str) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE run_id = ? AND subject_id = ?",
            (run_id, subject_id),
        ).fetchall()
        return [
            Fact(
                run_id=r["run_id"],
                subject_id=r["subject_id"],
                key=r["key"],
                value=r["value"],
            )
            for r in rows
        ]

    # --- Quests ---------------------------------------------------------------
    def create_quest(self, run_id: str, title: str, summary: str = "") -> Quest:
        quest_id = new_id("quest")
        self.conn.execute(
            "INSERT INTO quests (id, run_id, title, summary, status) VALUES (?, ?, ?, ?, 'active')",
            (quest_id, run_id, title, summary),
        )
        return Quest(id=quest_id, run_id=run_id, title=title, summary=summary)

    def active_quests(self, run_id: str) -> list[Quest]:
        rows = self.conn.execute(
            "SELECT * FROM quests WHERE run_id = ? AND status = 'active'", (run_id,)
        ).fetchall()
        return [Quest.model_validate(dict(r)) for r in rows]

    # --- Action log -----------------------------------------------------------
    def log_action(
        self,
        run_id: str,
        turn: int,
        action_type: str,
        player_text: str,
        outcome: str,
        location_id: str | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO action_log
               (run_id, turn, location_id, action_type, player_text, outcome, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, turn, location_id, action_type, player_text, outcome, _now()),
        )

    def recent_actions(self, run_id: str, limit: int) -> list[ActionLogEntry]:
        rows = self.conn.execute(
            "SELECT * FROM action_log WHERE run_id = ? ORDER BY id DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
        entries = [ActionLogEntry.model_validate(dict(r)) for r in rows]
        entries.reverse()  # chronological order
        return entries

    # --- Conversation log -----------------------------------------------------
    def log_conversation(
        self,
        run_id: str,
        entity_id: str,
        turn: int,
        speaker: str,
        text: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO conversation_log
               (run_id, entity_id, turn, speaker, text, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, entity_id, turn, speaker, text, _now()),
        )

    def conversation_with(
        self, run_id: str, entity_id: str, limit: int = 20
    ) -> list[ConversationEntry]:
        rows = self.conn.execute(
            """SELECT turn, speaker, text FROM conversation_log
               WHERE run_id = ? AND entity_id = ?
               ORDER BY id DESC LIMIT ?""",
            (run_id, entity_id, limit),
        ).fetchall()
        entries = [
            ConversationEntry(turn=r["turn"], speaker=r["speaker"], text=r["text"])
            for r in rows
        ]
        entries.reverse()
        return entries
