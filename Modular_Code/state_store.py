"""SQLite-backed shared state for multi-worker safety.

Replaces in-process state (kb_status dict, threading.Lock rebuild coordination,
per-session chat histories) with a WAL-mode SQLite database so multiple uvicorn
workers/processes share one source of truth. Zero external infrastructure.

Tables:
  kv(key TEXT PRIMARY KEY, value TEXT)          -- kb_status JSON, index_version, metrics
  sessions(session_id PK, turns TEXT, updated_at REAL)
  locks(name PK, holder TEXT, acquired_at REAL) -- cross-process rebuild lock
"""

import json
import os
import sqlite3
import time
import uuid

_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
_DB_PATH = os.path.join(_STATE_DIR, "app_state.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    turns TEXT,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS locks (
    name TEXT PRIMARY KEY,
    holder TEXT,
    acquired_at REAL
);
"""


class StateStore:
    # Lock holders heartbeat acquired_at every ~30s while working, so a lock
    # not refreshed for LOCK_TTL seconds is orphaned (holder crashed) and can
    # be stolen.
    LOCK_TTL = 120
    SESSION_MAX_AGE = 86400
    SESSION_MAX_ROWS = 500

    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._holder = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._save_count = 0
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── kv helpers ────────────────────────────────────────────────────
    def _kv_get(self, key: str):
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _kv_set(self, key: str, value: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kv(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # ── KB status ─────────────────────────────────────────────────────
    def get_kb_status(self) -> dict:
        try:
            raw = self._kv_get("kb_status")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return {"state": "ready", "message": "Knowledge base ready.", "doc_count": 0}

    def set_kb_status(self, state: str, message: str, doc_count: int = None):
        try:
            status = self.get_kb_status()
            status["state"] = state
            status["message"] = message
            if doc_count is not None:
                status["doc_count"] = doc_count
            self._kv_set("kb_status", json.dumps(status))
        except Exception:
            pass

    # ── Index version (staleness detection across workers) ───────────
    def get_index_version(self) -> int:
        try:
            raw = self._kv_get("index_version")
            return int(raw) if raw else 0
        except Exception:
            return 0

    def bump_index_version(self) -> int:
        version = int(time.time() * 1000)
        try:
            self._kv_set("index_version", str(version))
        except Exception:
            pass
        return version

    # ── Cross-process lock ────────────────────────────────────────────
    def try_acquire_lock(self, name: str = "rebuild") -> bool:
        now = time.time()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO locks(name, holder, acquired_at) VALUES(?,?,?)",
                    (name, self._holder, now),
                )
                if cur.rowcount == 1:
                    return True
                # Steal only if the existing lock is older than TTL (orphaned).
                cur = conn.execute(
                    "UPDATE locks SET holder=?, acquired_at=? "
                    "WHERE name=? AND acquired_at < ?",
                    (self._holder, now, name, now - self.LOCK_TTL),
                )
                return cur.rowcount == 1
        except Exception:
            return False

    def refresh_lock(self, name: str = "rebuild") -> bool:
        """Heartbeat: bump acquired_at while we still hold the lock."""
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE locks SET acquired_at=? WHERE name=? AND holder=?",
                    (time.time(), name, self._holder),
                )
                return cur.rowcount == 1
        except Exception:
            return False

    def release_lock(self, name: str = "rebuild"):
        try:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM locks WHERE name=? AND holder=?",
                    (name, self._holder),
                )
        except Exception:
            pass

    def lock_is_held(self, name: str = "rebuild") -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT acquired_at FROM locks WHERE name=?", (name,)
                ).fetchone()
            return bool(row) and (time.time() - row[0]) < self.LOCK_TTL
        except Exception:
            return False

    # ── Pending rebuild flag ─────────────────────────────────────────
    def set_pending_rebuild(self):
        self._kv_set("pending_rebuild", "1")

    def consume_pending_rebuild(self) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM kv WHERE key='pending_rebuild'"
                ).fetchone()
                if row and row[0] == "1":
                    conn.execute(
                        "UPDATE kv SET value='0' WHERE key='pending_rebuild'"
                    )
                    return True
        except Exception:
            pass
        return False

    # ── Session chat histories ────────────────────────────────────────
    def get_history(self, session_id: str) -> list:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT turns FROM sessions WHERE session_id=?", (session_id,)
                ).fetchone()
            if row and row[0]:
                turns = json.loads(row[0])
                return [tuple(t) for t in turns]
        except Exception:
            pass
        return []

    def save_history(self, session_id: str, turns: list):
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO sessions(session_id, turns, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(session_id) DO UPDATE SET turns=excluded.turns, "
                    "updated_at=excluded.updated_at",
                    (session_id, json.dumps(turns, ensure_ascii=False), time.time()),
                )
            self._save_count += 1
            if self._save_count % 100 == 0:
                self.prune_sessions()
        except Exception:
            pass

    def prune_sessions(self):
        try:
            cutoff = time.time() - self.SESSION_MAX_AGE
            with self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
                conn.execute(
                    "DELETE FROM sessions WHERE session_id NOT IN ("
                    "SELECT session_id FROM sessions ORDER BY updated_at DESC LIMIT ?)",
                    (self.SESSION_MAX_ROWS,),
                )
        except Exception:
            pass

    # ── Metrics counters ──────────────────────────────────────────────
    def incr_metric(self, name: str, by: float = 1):
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO kv(key, value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "value=CAST(CAST(value AS REAL)+? AS TEXT)",
                    (f"metric:{name}", str(by), by),
                )
        except Exception:
            pass

    def set_metric(self, name: str, value):
        self._kv_set(f"metric:{name}", str(value))

    def get_metrics(self) -> dict:
        metrics = {}
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT key, value FROM kv WHERE key LIKE 'metric:%'"
                ).fetchall()
            for key, value in rows:
                name = key[len("metric:"):]
                try:
                    num = float(value)
                    metrics[name] = int(num) if num == int(num) else round(num, 2)
                except (TypeError, ValueError):
                    metrics[name] = value
        except Exception:
            pass
        return metrics
