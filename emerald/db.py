"""One local SQLite file. It works with no network, which is what the offline lane needs."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
  seq INTEGER PRIMARY KEY, device TEXT NOT NULL, ts TEXT NOT NULL, case_id TEXT, type TEXT NOT NULL,
  payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL, signature TEXT NOT NULL,
  synced INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, farmer_id TEXT NOT NULL, reported_at TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
  species TEXT NOT NULL, signs TEXT NOT NULL, weight_kg REAL, candidates TEXT NOT NULL, red_flags TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS signoffs (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL, action_hash TEXT NOT NULL,
  summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', vet_id TEXT, signature TEXT, note TEXT,
  requested_at TEXT NOT NULL, decided_at TEXT, used_at TEXT, UNIQUE (case_id, action_hash)
);
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, case_id TEXT, to_person TEXT NOT NULL, to_role TEXT NOT NULL, purpose TEXT NOT NULL,
  script TEXT NOT NULL, provider TEXT NOT NULL, status TEXT NOT NULL, placed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL, to_vet TEXT NOT NULL, amount REAL NOT NULL, currency TEXT NOT NULL,
  provider TEXT NOT NULL, status TEXT NOT NULL, reference TEXT, paid_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY, case_ids TEXT NOT NULL, disease TEXT NOT NULL, body TEXT NOT NULL, filed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbreak_claims (
  disease TEXT NOT NULL, action TEXT NOT NULL, case_id TEXT NOT NULL, claimed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prescriptions (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL, disease TEXT NOT NULL, drug TEXT NOT NULL, detail TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


_prepared: set[str] = set()
_prepare_lock = threading.Lock()


def _prepare(conn: sqlite3.Connection, path: str) -> None:
    """Set up once per process. Switching to WAL can't wait on a busy database, so it retries instead."""
    with _prepare_lock:
        if path in _prepared:
            return
        for attempt in range(60):
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(SCHEMA)
                break
            except sqlite3.OperationalError:
                if attempt == 59:
                    raise
                time.sleep(0.1)
        _prepared.add(path)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    # MCP servers run as separate processes, so all of them share this file. WAL lets them do that safely.
    path = str(config.db_path())
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    _prepare(conn, path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
