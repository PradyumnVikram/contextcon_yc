"""Crustdata watcher + webhook. OWNER: Person A (task A11).

STUB (S5): register/simulate_event only write the customers table. Replace
with the FastAPI app (POST /webhook/crustdata) and real watcher registration.
"""
from __future__ import annotations

import sqlite3

from clearance import store
from clearance.models import Party

STUB = True


def company_key(party: Party) -> str:
    return (party.domain or party.name).strip().lower()


def register(conn: sqlite3.Connection, party: Party, tier: str) -> None:
    """Called by pipeline when a RELEASE is signed."""
    store.upsert_customer(conn, company_key(party), party.name, tier, watcher_id="stub-watcher")


def simulate_event(conn: sqlite3.Connection, party: Party, new_tier: str = "medium_risk") -> None:
    """Demo button: pretend Crustdata reported a change and re-tier the customer."""
    store.upsert_customer(conn, company_key(party), party.name, new_tier)
