"""Lightweight usage analytics for the ColorPlate GUI.

An append-only SQLite event log so you can answer "is the platform being used,
and how much." Deliberately privacy-conscious: it never stores artwork, full
filenames, or raw IPs — only event types, small numeric metadata, and a *salted
one-way hash* of the client IP for distinct-visitor counts.

Storage is a single SQLite file under ``COLORPLATE_DATA_DIR`` (a mounted disk in
production, a local ``.data/`` dir in dev). Writes are best-effort and wrapped so
analytics can never break or slow down a real request.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import threading

_LOCK = threading.Lock()
_DB_PATH: str | None = None
_SALT = os.environ.get("COLORPLATE_SALT", "dev-salt-not-for-prod")


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        data_dir = os.environ.get("COLORPLATE_DATA_DIR") or os.path.join(os.getcwd(), ".data")
        os.makedirs(data_dir, exist_ok=True)
        _DB_PATH = os.path.join(data_dir, "colorplate.db")
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    """Create the events table. Safe to call repeatedly."""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events(
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts       TEXT NOT NULL,   -- UTC ISO-8601, second precision
                    day      TEXT NOT NULL,   -- UTC date (YYYY-MM-DD) for grouping
                    type     TEXT NOT NULL,   -- detect | generate | download | ...
                    visitor  TEXT,            -- salted hash of client IP (not the IP)
                    meta     TEXT             -- small JSON blob, no PII
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_day ON events(day)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(type)")
            conn.commit()
        finally:
            conn.close()


def _visitor_hash(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(f"{_SALT}|{ip}".encode()).hexdigest()[:16]


def client_ip(request) -> str | None:
    """Best-effort real client IP. Render sits behind a proxy, so the real
    address is the first hop in X-Forwarded-For."""
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def record(event_type: str, request=None, **meta) -> None:
    """Append one event. Best-effort: never raises into the caller."""
    try:
        now = _utcnow()
        visitor = _visitor_hash(client_ip(request))
        payload = json.dumps(meta, separators=(",", ":")) if meta else None
        with _LOCK:
            conn = _connect()
            try:
                conn.execute(
                    "INSERT INTO events(ts, day, type, visitor, meta) VALUES(?,?,?,?,?)",
                    (now.isoformat(timespec="seconds"), now.date().isoformat(),
                     event_type, visitor, payload),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass  # analytics must never break a request


def stats() -> dict:
    """Aggregate counts for the /stats view."""
    today = _utcnow().date()
    cutoff7 = (today - datetime.timedelta(days=7)).isoformat()
    cutoff14 = (today - datetime.timedelta(days=14)).isoformat()
    with _LOCK:
        conn = _connect()
        try:
            c = conn.cursor()
            totals = dict(c.execute("SELECT type, COUNT(*) FROM events GROUP BY type").fetchall())
            last7 = dict(c.execute(
                "SELECT type, COUNT(*) FROM events WHERE day >= ? GROUP BY type", (cutoff7,)
            ).fetchall())
            uniq_total = c.execute(
                "SELECT COUNT(DISTINCT visitor) FROM events WHERE visitor IS NOT NULL"
            ).fetchone()[0]
            uniq_7 = c.execute(
                "SELECT COUNT(DISTINCT visitor) FROM events WHERE visitor IS NOT NULL AND day >= ?",
                (cutoff7,),
            ).fetchone()[0]
            daily = [
                {"day": d, "events": n, "visitors": v}
                for d, n, v in c.execute(
                    "SELECT day, COUNT(*), COUNT(DISTINCT visitor) FROM events "
                    "WHERE day >= ? GROUP BY day ORDER BY day DESC", (cutoff14,)
                ).fetchall()
            ]
            first_ts, last_ts, total = c.execute(
                "SELECT MIN(ts), MAX(ts), COUNT(*) FROM events"
            ).fetchone()
            return {
                "total_events": total,
                "first_event": first_ts,
                "last_event": last_ts,
                "unique_visitors_total": uniq_total,
                "unique_visitors_7d": uniq_7,
                "totals_by_type": totals,
                "last7_by_type": last7,
                "daily": daily,
            }
        finally:
            conn.close()
