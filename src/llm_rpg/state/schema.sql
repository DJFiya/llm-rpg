-- World-state schema. This database is the single source of truth for a run.
-- The LLM never holds state; it only reads facts retrieved from here and
-- proposes new rows that are validated before being committed.

PRAGMA foreign_keys = ON;

-- A single playthrough / save. The world prompt + seed make a run reproducible.
CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    world_prompt TEXT NOT NULL,
    genre        TEXT,
    seed         INTEGER NOT NULL,
    turn         INTEGER NOT NULL DEFAULT 0,
    player_id    TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- Map nodes. Coordinates are stored now so a spatial/grid UI can be added later
-- without regenerating the world. (run_id, x, y, region) must be unique to keep
-- the map collision-free and traversable.
CREATE TABLE IF NOT EXISTS locations (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    region      TEXT NOT NULL DEFAULT 'world',
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    discovered  INTEGER NOT NULL DEFAULT 1,
    UNIQUE (run_id, region, x, y)
);

-- Directed edges of the location graph. Reverse edges are created in pairs so
-- the map is bidirectionally traversable.
CREATE TABLE IF NOT EXISTS connections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    from_location TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    to_location   TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    direction     TEXT NOT NULL,
    UNIQUE (run_id, from_location, direction)
);

-- Every actor/object in the world: player, npc, enemy, item, faction.
CREATE TABLE IF NOT EXISTS entities (
    id      TEXT PRIMARY KEY,
    run_id  TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    type    TEXT NOT NULL,
    name    TEXT NOT NULL,
    status  TEXT NOT NULL DEFAULT 'active',
    UNIQUE (run_id, name)
);

-- Where each entity currently is (NULL location = carried/abstract).
CREATE TABLE IF NOT EXISTS entity_location (
    entity_id   TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    location_id TEXT REFERENCES locations(id) ON DELETE SET NULL,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE
);

-- Flexible numeric stats (HP, attack, etc.). No fixed per-genre schema.
CREATE TABLE IF NOT EXISTS stats (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    key       TEXT NOT NULL,
    value     REAL NOT NULL,
    PRIMARY KEY (entity_id, key)
);

-- Ownership of item entities by other entities.
CREATE TABLE IF NOT EXISTS inventory (
    owner_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    item_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    qty      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (owner_id, item_id)
);

-- Equipped gear: weapon, armor, etc. Mechanical bonuses flow from item stats.
CREATE TABLE IF NOT EXISTS equipped (
    owner_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    slot     TEXT NOT NULL,
    item_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (owner_id, slot)
);

-- Directed relationships between entities (e.g. a->b "trusts" 0.7).
CREATE TABLE IF NOT EXISTS relationships (
    a_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    b_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    kind  TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (a_id, b_id, kind)
);

-- Generic lookup lore. Replaces hardcoded "prestory constants": every fact is
-- a queryable row attached to a subject (an entity id, location id, or 'world').
CREATE TABLE IF NOT EXISTS facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    subject_id TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    UNIQUE (run_id, subject_id, key)
);

CREATE TABLE IF NOT EXISTS quests (
    id      TEXT PRIMARY KEY,
    run_id  TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    title   TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    status  TEXT NOT NULL DEFAULT 'active'
);

-- Append-only history of everything that happens. This is the long-term memory.
CREATE TABLE IF NOT EXISTS action_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    turn        INTEGER NOT NULL,
    location_id TEXT,
    action_type TEXT NOT NULL,
    player_text TEXT NOT NULL DEFAULT '',
    outcome     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

-- Append-only dialogue between the player and an NPC. This is the source of
-- truth for what was said; the narrator may not invent or change NPC lines.
CREATE TABLE IF NOT EXISTS conversation_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    entity_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    turn       INTEGER NOT NULL,
    speaker    TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entity_location_loc ON entity_location(location_id);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(run_id, subject_id);
CREATE INDEX IF NOT EXISTS idx_action_log_run ON action_log(run_id, turn);
CREATE INDEX IF NOT EXISTS idx_connections_from ON connections(run_id, from_location);
CREATE INDEX IF NOT EXISTS idx_conversation_entity ON conversation_log(run_id, entity_id, id);
