"""Persistencia en SQLite (biblioteca estándar, sin dependencias)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,            -- '<fuente>:<id nativo>', p. ej. 'futdb:12345'
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    rating INTEGER,
    position TEXT,
    alt_positions TEXT,
    league_id INTEGER, league TEXT,
    nation_id INTEGER, nation TEXT,
    club_id INTEGER, club TEXT,
    rarity_id INTEGER, rarity TEXT,
    external_ids TEXT,              -- JSON: futbin/futwiz/ea ids si la fuente los da
    is_demo INTEGER NOT NULL DEFAULT 0,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_players_rating ON players(rating);

CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    platform TEXT NOT NULL,         -- 'ps' (consola) | 'pc'
    price INTEGER NOT NULL,
    min_price INTEGER,              -- rango de precios de EA, si la fuente lo da
    max_price INTEGER,
    source TEXT NOT NULL,
    observed_at REAL NOT NULL,      -- momento del precio según la fuente
    fetched_at REAL NOT NULL,       -- momento en que lo obtuvimos
    verified INTEGER NOT NULL DEFAULT 1,
    is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_unique ON prices(player_id, platform, source, observed_at);
CREATE INDEX IF NOT EXISTS idx_prices_time ON prices(observed_at);

CREATE TABLE IF NOT EXISTS watchlist (
    player_id TEXT PRIMARY KEY,
    note TEXT,
    target_buy INTEGER,
    target_sell INTEGER,
    added_at REAL
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    player_id TEXT,
    platform TEXT,
    threshold REAL NOT NULL,
    window_hours REAL,
    label TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fired_at REAL,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    fired_at REAL,
    message TEXT,
    data TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT,
    player_name TEXT,
    platform TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    buy_price INTEGER NOT NULL,
    buy_at REAL,
    sell_price INTEGER,
    sell_at REAL,
    strategy TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT,                      -- sbc | promo | recompensas | otro
    starts_at REAL,
    ends_at REAL,
    player_ids TEXT,                -- JSON
    rating_min INTEGER,
    rating_max INTEGER,
    note TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS source_status (
    source TEXT PRIMARY KEY,
    state TEXT,
    detail TEXT,
    last_success REAL,
    last_attempt REAL,
    last_error TEXT,
    last_error_at REAL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    requests_made INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL,
    catalog_synced_at REAL
);

CREATE TABLE IF NOT EXISTS update_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    started_at REAL,
    finished_at REAL,
    prices_saved INTEGER,
    errors INTEGER,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---- utilidades -------------------------------------------------------------
    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def executemany(self, sql: str, rows) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    def query(self, sql: str, params=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- ajustes ----------------------------------------------------------------
    def get_setting(self, key: str, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    # ---- jugadores --------------------------------------------------------------
    def upsert_players(self, players: list[dict]) -> int:
        now = time.time()
        rows = [
            (
                p["id"], p["source"], p["name"], p.get("rating"), p.get("position"),
                ",".join(p.get("alt_positions") or []),
                p.get("league_id"), p.get("league"), p.get("nation_id"), p.get("nation"),
                p.get("club_id"), p.get("club"), p.get("rarity_id"), p.get("rarity"),
                json.dumps(p.get("external_ids") or {}), int(bool(p.get("is_demo"))), now,
            )
            for p in players
        ]
        self.executemany(
            """INSERT INTO players(id, source, name, rating, position, alt_positions,
                   league_id, league, nation_id, nation, club_id, club, rarity_id, rarity,
                   external_ids, is_demo, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   source=excluded.source, name=excluded.name, rating=excluded.rating,
                   position=excluded.position, alt_positions=excluded.alt_positions,
                   league_id=excluded.league_id, league=excluded.league,
                   nation_id=excluded.nation_id, nation=excluded.nation,
                   club_id=excluded.club_id, club=excluded.club,
                   rarity_id=excluded.rarity_id, rarity=excluded.rarity,
                   external_ids=excluded.external_ids, is_demo=excluded.is_demo,
                   updated_at=excluded.updated_at""",
            rows,
        )
        return len(rows)

    def get_player(self, player_id: str) -> dict | None:
        return self.one("SELECT * FROM players WHERE id=?", (player_id,))

    # ---- precios ----------------------------------------------------------------
    def insert_prices(self, quotes: list[dict]) -> int:
        """Guarda cotizaciones. Ignora duplicados (mismo jugador, plataforma, fuente y
        momento de observación) para no inflar el historial si la fuente no ha cambiado."""
        if not quotes:
            return 0
        now = time.time()
        rows = [
            (
                q["player_id"], q["platform"], int(q["price"]), q.get("min_price"),
                q.get("max_price"), q["source"], q["observed_at"], q.get("fetched_at", now),
                int(q.get("verified", True)), int(bool(q.get("is_demo"))),
            )
            for q in quotes
        ]
        with self._lock:
            before = self._conn.total_changes
            self._conn.executemany(
                """INSERT OR IGNORE INTO prices(player_id, platform, price, min_price, max_price,
                       source, observed_at, fetched_at, verified, is_demo)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            self._conn.commit()
            return self._conn.total_changes - before

    def latest_prices(self, platform: str | None = None) -> list[dict]:
        sql = """SELECT p.* FROM prices p
                 JOIN (SELECT player_id, platform, MAX(observed_at) AS mx FROM prices
                       GROUP BY player_id, platform) last
                 ON p.player_id=last.player_id AND p.platform=last.platform
                    AND p.observed_at=last.mx"""
        params: tuple = ()
        if platform:
            sql += " WHERE p.platform=?"
            params = (platform,)
        rows = self.query(sql, params)
        # En caso de empate de observed_at se queda la última insertada.
        out: dict = {}
        for r in rows:
            key = (r["player_id"], r["platform"])
            if key not in out or r["id"] > out[key]["id"]:
                out[key] = r
        return list(out.values())

    def price_history(self, player_id: str, platform: str | None, since: float) -> list[dict]:
        sql = "SELECT * FROM prices WHERE player_id=? AND observed_at>=?"
        params: list = [player_id, since]
        if platform:
            sql += " AND platform=?"
            params.append(platform)
        sql += " ORDER BY observed_at"
        return self.query(sql, params)

    def history_since(self, since: float, platform: str | None = None) -> list[dict]:
        sql = ("SELECT player_id, platform, price, min_price, max_price, source, observed_at, "
               "verified, is_demo FROM prices WHERE observed_at>=?")
        params: list = [since]
        if platform:
            sql += " AND platform=?"
            params.append(platform)
        sql += " ORDER BY observed_at"
        return self.query(sql, params)

    # ---- estado de fuentes ------------------------------------------------------
    def get_source_status(self, source: str) -> dict:
        row = self.one("SELECT * FROM source_status WHERE source=?", (source,))
        if row:
            return row
        self.execute("INSERT OR IGNORE INTO source_status(source, state) VALUES(?, 'pending')", (source,))
        return self.one("SELECT * FROM source_status WHERE source=?", (source,))

    def update_source_status(self, source: str, **fields) -> None:
        self.get_source_status(source)
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE source_status SET {cols} WHERE source=?", (*fields.values(), source))
