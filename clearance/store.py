"""SQLite storage: API cache, people/peer caches, orders, evidence, emails, customers. SHARED FILE.

Schema changes need both teammates (WORKFLOW.md §6).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearance import config
from clearance.models import Decision, Email, Evidence, Order, OrderState

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY, endpoint TEXT, request_json TEXT, response_json TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS people (
    company_key TEXT, person_id TEXT, name TEXT, title TEXT, function TEXT,
    skills TEXT, past_employers TEXT, fetched_at TEXT, PRIMARY KEY (company_key, person_id));
CREATE TABLE IF NOT EXISTS peers (
    company_key TEXT PRIMARY KEY, peer_set_json TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, order_json TEXT, state TEXT, decision_json TEXT);
CREATE TABLE IF NOT EXISTS state_history (
    order_id TEXT, state TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS evidence (
    order_id TEXT, id TEXT, claim TEXT, value_json TEXT, source TEXT, fetched_at TEXT,
    PRIMARY KEY (order_id, id));
CREATE TABLE IF NOT EXISTS emails (
    msg_id TEXT PRIMARY KEY, direction TEXT, order_id TEXT, subject TEXT, body TEXT,
    in_reply_to TEXT, received_at TEXT);
CREATE TABLE IF NOT EXISTS network_links (
    company_key TEXT, company_name TEXT, kind TEXT, value TEXT, order_id TEXT, source TEXT, created_at TEXT,
    PRIMARY KEY (company_key, kind, value));
CREATE TABLE IF NOT EXISTS network_orders (
    order_id TEXT, line INTEGER, company_key TEXT, company_name TEXT, part_number TEXT, function TEXT,
    quantity INTEGER, controlled INTEGER, created_at TEXT, PRIMARY KEY (order_id, line));
CREATE TABLE IF NOT EXISTS customers (
    company_key TEXT PRIMARY KEY, name TEXT, tier TEXT, watcher_id TEXT, updated_at TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and initialise) the DB. Pass ':memory:' in tests."""
    conn = sqlite3.connect(str(path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --- API cache (Crustdata + Claude) ------------------------------------------
def cache_key(endpoint: str, request: Any) -> str:
    blob = endpoint + "|" + json.dumps(request, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def cache_get(conn: sqlite3.Connection, endpoint: str, request: Any, max_age_days: float | None = None) -> Any | None:
    row = conn.execute("SELECT response_json, fetched_at FROM api_cache WHERE key=?",
                       (cache_key(endpoint, request),)).fetchone()
    if row is None or (max_age_days is not None and is_stale(row["fetched_at"], max_age_days)):
        return None
    return json.loads(row["response_json"])


def cache_fetched_at(conn: sqlite3.Connection, endpoint: str, request: Any) -> datetime | None:
    row = conn.execute("SELECT fetched_at FROM api_cache WHERE key=?", (cache_key(endpoint, request),)).fetchone()
    return datetime.fromisoformat(row["fetched_at"]) if row and row["fetched_at"] else None


def is_stale(fetched_at: str | datetime | None, max_age_days: float) -> bool:
    if not fetched_at:
        return True
    at = datetime.fromisoformat(fetched_at) if isinstance(fetched_at, str) else fetched_at
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - at).total_seconds() > max_age_days * 86400


def cache_put(conn: sqlite3.Connection, endpoint: str, request: Any, response: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO api_cache VALUES (?,?,?,?,?)",
        (cache_key(endpoint, request), endpoint, json.dumps(request, sort_keys=True, default=str),
         json.dumps(response, default=str), _now()),
    )
    conn.commit()


# --- Orders -------------------------------------------------------------------
def save_order(conn: sqlite3.Connection, order: Order, state: OrderState) -> None:
    conn.execute(
        "INSERT INTO orders(order_id, order_json, state) VALUES (?,?,?) "
        "ON CONFLICT(order_id) DO UPDATE SET order_json=excluded.order_json",
        (order.order_id, order.model_dump_json(), state.value),
    )
    conn.commit()
    if not get_state_history(conn, order.order_id):
        set_state(conn, order.order_id, state)


def load_order(conn: sqlite3.Connection, order_id: str) -> Order:
    row = conn.execute("SELECT order_json FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        raise KeyError(order_id)
    return Order.model_validate_json(row["order_json"])


def set_state(conn: sqlite3.Connection, order_id: str, state: OrderState) -> None:
    conn.execute("UPDATE orders SET state=? WHERE order_id=?", (state.value, order_id))
    conn.execute("INSERT INTO state_history VALUES (?,?,?)", (order_id, state.value, _now()))
    conn.commit()


def get_state(conn: sqlite3.Connection, order_id: str) -> OrderState:
    row = conn.execute("SELECT state FROM orders WHERE order_id=?", (order_id,)).fetchone()
    return OrderState(row["state"])


def get_state_history(conn: sqlite3.Connection, order_id: str) -> list[tuple[OrderState, datetime]]:
    rows = conn.execute("SELECT state, at FROM state_history WHERE order_id=? ORDER BY rowid", (order_id,))
    return [(OrderState(r["state"]), datetime.fromisoformat(r["at"])) for r in rows]


def save_decision(conn: sqlite3.Connection, decision: Decision) -> None:
    conn.execute("UPDATE orders SET decision_json=? WHERE order_id=?", (decision.model_dump_json(), decision.order_id))
    conn.commit()


def load_decision(conn: sqlite3.Connection, order_id: str) -> Decision | None:
    row = conn.execute("SELECT decision_json FROM orders WHERE order_id=?", (order_id,)).fetchone()
    return Decision.model_validate_json(row["decision_json"]) if row and row["decision_json"] else None


def save_evidence(conn: sqlite3.Connection, order_id: str, items: list[Evidence]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO evidence VALUES (?,?,?,?,?,?)",
        [(order_id, e.id, e.claim, json.dumps(e.value, default=str), e.source,
          e.fetched_at.isoformat() if e.fetched_at else None) for e in items],
    )
    conn.commit()


def load_evidence(conn: sqlite3.Connection, order_id: str) -> list[Evidence]:
    rows = conn.execute("SELECT * FROM evidence WHERE order_id=? ORDER BY CAST(SUBSTR(id,2) AS INTEGER)", (order_id,))
    return [Evidence(id=r["id"], claim=r["claim"], value=json.loads(r["value_json"]), source=r["source"],
                     fetched_at=datetime.fromisoformat(r["fetched_at"]) if r["fetched_at"] else None) for r in rows]


# --- Emails & customers -------------------------------------------------------
def save_email(conn: sqlite3.Connection, email: Email, direction: str, order_id: str | None = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO emails VALUES (?,?,?,?,?,?,?)",
        (email.msg_id, direction, order_id, email.subject, email.body, email.in_reply_to, email.received_at.isoformat()),
    )
    conn.commit()


def upsert_customer(conn: sqlite3.Connection, company_key: str, name: str, tier: str, watcher_id: str | None = None) -> None:
    conn.execute(
        "INSERT INTO customers VALUES (?,?,?,?,?) ON CONFLICT(company_key) DO UPDATE SET "
        "name=excluded.name, tier=excluded.tier, watcher_id=COALESCE(excluded.watcher_id, customers.watcher_id), "
        "updated_at=excluded.updated_at",
        (company_key, name, tier, watcher_id, _now()),
    )
    conn.commit()
