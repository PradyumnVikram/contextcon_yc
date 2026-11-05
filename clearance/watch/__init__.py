"""Continuous monitoring of approved customers (task A11). OWNER: Person A.

register(): called by the pipeline when an officer signs a RELEASE. Stores the customer and, when
  CRUSTDATA_API_KEY and CLEARANCE_WEBHOOK_URL (public https URL, e.g. ngrok) are set, creates a Crustdata
  company watch that posts to /webhook/crustdata (see watch/webhook.py).
handle_event(): a watch notification arrived; drop the cached data for each changed company,
  re-run the company-level capability check and re-tier the customer. Their NEXT order gets a full review.
simulate_event(): the demo button; either sets a tier directly or re-runs handle_event logic.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from clearance import capability, crustdata_client, store
from clearance.crustdata_client import norm_key
from clearance.evidence import Ledger
from clearance.models import Party

WEBHOOK_URL = os.getenv("CLEARANCE_WEBHOOK_URL", "")


def company_key(party: Party) -> str:
    return norm_key(party.domain or party.name)


def register(conn: sqlite3.Connection, party: Party, tier: str) -> str | None:
    watcher_id = None
    if WEBHOOK_URL:
        try:
            watcher_id = crustdata_client.get_client().watch_company(party.domain or party.name, WEBHOOK_URL)
        except crustdata_client.CrustdataError:
            watcher_id = None
    store.upsert_customer(conn, company_key(party), party.name, tier, watcher_id=watcher_id or "local")
    return watcher_id


def retier(conn: sqlite3.Connection, party: Party) -> str:
    """Re-run the company-level capability check (no parts) after cached data is invalidated."""
    client = crustdata_client.get_client()
    client.invalidate(party.domain or party.name)
    res = capability.assess(party, [], [], party.country or "", Ledger())
    store.upsert_customer(conn, company_key(party), party.name, res.tier)
    return res.tier


def handle_event(conn: sqlite3.Connection, payload: dict[str, Any]) -> list[dict[str, str]]:
    """Crustdata webhook body: {"metadata": {...}, "results": [{"changes": [...], "record": {...}}]}."""
    updated = []
    for result in payload.get("results") or []:
        rec = result.get("record") or {}
        bi = rec.get("basic_info") or {}
        name, domain = bi.get("name") or "", bi.get("primary_domain")
        key = norm_key(domain or name)
        row = conn.execute("SELECT name FROM customers WHERE company_key=?", (key,)).fetchone()
        if row is None:
            continue  # not one of our approved customers
        tier = retier(conn, Party(role="buyer", name=row["name"], domain=domain))
        updated.append({"company": row["name"], "tier": tier,
                        "changes": ", ".join(c.get("field", "") for c in result.get("changes") or [])})
    return updated


def simulate_event(conn: sqlite3.Connection, party: Party, new_tier: str | None = None) -> str:
    """Demo: force a tier (as if Crustdata reported a change), or re-run the real re-tier with new_tier=None."""
    if new_tier:
        store.upsert_customer(conn, company_key(party), party.name, new_tier)
        return new_tier
    return retier(conn, party)
