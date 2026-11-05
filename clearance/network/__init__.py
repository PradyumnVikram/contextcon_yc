"""Cross-order network: memory across orders and buyers. SHARED (A: identifiers from Crustdata; B: systems + rules).

record()  : every assessed order leaves its identifiers (shared people, email domain, phones, ship-to address,
            forwarder, middleman) and its part functions behind, in network_links / network_orders.
analyse() : for a new order, find buyers linked to this one (weighted so common identifiers like DHL count
            for almost nothing), pool their recent orders, and test the pooled part functions against the
            controlled-system templates in data/systems.csv. Also screens the buyer's staff's past employers.
Deterministic: no LLM decides anything here. Every finding is recorded as evidence.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable

from clearance import config, crustdata_client
from clearance.capability.profile import parse_company
from clearance.crustdata_client import norm_key
from clearance.evidence import Ledger
from clearance.models import (Classification, ListedStaff, NetworkLink, NetworkResult, Order, Party,
                              ScreeningResult, SystemFinding)

ScreenFn = Callable[[Party, Ledger], ScreeningResult]

SYSTEMS_CSV = config.DATA_DIR / "systems.csv"
LOOKBACK_DAYS = 180
LINK_THRESHOLD = 0.45          # sum of damped link weights needed to treat two buyers as connected
MAX_DEPTH = 2                  # buyer -> linked company -> its linked company
BASE_WEIGHT = {"person": 1.0, "email_domain": 1.0, "phone": 1.0, "address": 0.9, "middleman": 0.6, "forwarder": 0.5}
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
_LABEL = {"person": "shared person", "email_domain": "shared email domain", "phone": "shared phone number",
          "address": "shared ship-to address", "middleman": "shared middleman", "forwarder": "shared freight forwarder"}


def company_key(party: Party) -> str:
    return norm_key(party.domain or party.name)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_address(a: str) -> str:
    a = re.sub(r"[^a-z0-9 ]+", " ", (a or "").lower())
    a = re.sub(r"\b(p ?o ?box|post box)\b", "pobox", a)
    return " ".join(a.split())


def _people_conn() -> sqlite3.Connection:
    """The employee cache lives where the capability check wrote it: the Crustdata client's connection."""
    return crustdata_client.get_client().conn


def _people_rows(conn: sqlite3.Connection, party: Party) -> list[sqlite3.Row]:
    pconn = _people_conn()
    for k in [x for x in (party.domain, party.name) if x]:
        rows = pconn.execute("SELECT * FROM people WHERE company_key=?", (norm_key(k),)).fetchall()
        if rows:
            return rows
    return []


# --------------------------------------------------------------------------- record
def identifiers(conn: sqlite3.Connection, order: Order, email_text: str = "") -> list[tuple[str, str, str]]:
    """(kind, matching key, display text) for everything this order reveals about who is behind it."""
    buyer = order.buyer
    out: list[tuple[str, str, str]] = []
    for r in _people_rows(conn, buyer):
        out.append(("person", f"{r['name']} · id {r['person_id']}", f"{r['name']} ({r['title']})"))
    if buyer.domain and crustdata_client.is_domain(norm_key(buyer.domain)):
        out.append(("email_domain", norm_key(buyer.domain), norm_key(buyer.domain)))
    for m in _PHONE_RE.findall(email_text or ""):
        digits = re.sub(r"\D", "", m)
        if len(digits) >= 10:
            out.append(("phone", digits[-10:], m.strip()))
    for p in order.parties:
        if p.role == "ship_to" and p.address:
            out.append(("address", _norm_address(p.address), p.address))
        if p.role in ("shipper", "middleman") and p.name:
            out.append(("forwarder" if p.role == "shipper" else "middleman", norm_key(p.name), p.name))
    seen, unique = set(), []
    for kind, key, shown in out:
        if (kind, key) not in seen:
            seen.add((kind, key))
            unique.append((kind, key, shown))
    return unique


def record(conn: sqlite3.Connection, order: Order, classifications: list[Classification], email_text: str = "") -> None:
    key, name, at = company_key(order.buyer), order.buyer.name, order.created_at.isoformat()
    for kind, value, shown in identifiers(conn, order, email_text):
        conn.execute("INSERT OR IGNORE INTO network_links VALUES (?,?,?,?,?,?,?)",
                     (key, name, kind, value, order.order_id, shown, at))
    by_part = {c.part_number.upper(): c for c in classifications}
    for i, line in enumerate(order.lines):
        c = by_part.get(line.part_number.upper())
        conn.execute("INSERT OR REPLACE INTO network_orders VALUES (?,?,?,?,?,?,?,?,?)",
                     (order.order_id, i, key, name, line.part_number.upper(), c.function if c else None,
                      line.quantity, int(bool(c and c.controlled)), at))
    conn.commit()


# --------------------------------------------------------------------------- analyse
def _links_from(conn: sqlite3.Connection, key: str) -> dict[str, list[NetworkLink]]:
    """Other companies sharing an identifier with `key`, with damped weights."""
    mine = conn.execute("SELECT kind, value, source FROM network_links WHERE company_key=?", (key,)).fetchall()
    found: dict[str, list[NetworkLink]] = {}
    for row in mine:
        sharers = conn.execute("SELECT DISTINCT company_key, company_name FROM network_links WHERE kind=? AND value=?",
                               (row["kind"], row["value"])).fetchall()
        n = len(sharers)
        if n < 2:
            continue
        w = BASE_WEIGHT[row["kind"]] / math.log2(1 + n)
        shown = row["source"] or row["value"].split(" · id ")[0]
        for s in sharers:
            if s["company_key"] != key:
                found.setdefault(s["company_key"], []).append(NetworkLink(
                    company=s["company_key"], company_name=s["company_name"], kind=row["kind"], value=shown,
                    weight=round(w, 2)))
    return {k: v for k, v in found.items() if sum(l.weight for l in v) >= LINK_THRESHOLD}


def _cluster(conn: sqlite3.Connection, key: str) -> tuple[dict[str, str], list[NetworkLink]]:
    """Companies reachable through strong-enough links (BFS to MAX_DEPTH). Returns {key: name}, direct links."""
    names = {key: None}
    direct = _links_from(conn, key)
    frontier, depth = [key], 0
    while frontier and depth < MAX_DEPTH:
        nxt = []
        for k in frontier:
            for other, links in (direct if k == key else _links_from(conn, k)).items():
                if other not in names:
                    names[other] = links[0].company_name
                    nxt.append(other)
        frontier, depth = nxt, depth + 1
    names.pop(key)
    return names, [l for links in direct.values() for l in links]


@lru_cache(maxsize=2)
def load_systems() -> list[dict]:
    with open(SYSTEMS_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["required"] = [x for x in r["required_functions"].split(";") if x]
        r["keywords"] = [x.strip().lower() for x in r["fits_keywords"].split(";") if x.strip()]
        r["min_coverage"] = float(r["min_coverage"])
    return rows


def _business_text(conn: sqlite3.Connection, keys: dict[str, str]) -> str:
    """What the companies are known to do: Crustdata description/industry + staff titles and skills (cached)."""
    client = crustdata_client.get_client()
    parts = []
    for key, name in keys.items():
        for k in [key, name]:
            cd = client.fixtures.company(k) if k else None
            if cd is None and k:
                body = {"domains" if crustdata_client.is_domain(norm_key(k)) else "names": [norm_key(k)],
                        "fields": crustdata_client.ENRICH_FIELDS}
                data = crustdata_client.store.cache_get(client.conn, "/company/enrich", body)
                matches = (data[0] or {}).get("matches") if data else None
                cd = matches[0]["company_data"] if matches else None
            if cd:
                p = parse_company(cd)
                parts += [p.description or "", p.industry or ""]
                break
        for r in _people_conn().execute("SELECT title, skills FROM people WHERE company_key=?", (key,)):
            parts += [r["title"] or "", " ".join(json.loads(r["skills"] or "[]"))]
    return " ".join(parts).lower()


def analyse(conn: sqlite3.Connection, order: Order, screen: ScreenFn, ledger: Ledger,
            now: datetime | None = None) -> NetworkResult:
    key = company_key(order.buyer)
    linked, links = _cluster(conn, key)
    res = NetworkResult(company=order.buyer.name, linked_companies=sorted(linked.values()), links=links)
    ids = res.evidence_ids
    for other, group in _group(links).items():
        ids.append(ledger.add(f"Linked to {group[0].company_name} through " +
                              ", ".join(f"{_LABEL[l.kind]} ({l.value})" for l in group),
                              {"weights": {l.kind: l.weight for l in group}}, "network:links"))

    # pool recent orders across the cluster and test them against the system templates
    cluster = {key: order.buyer.name, **linked}
    since = ((now or _now()) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    marks = ",".join("?" * len(cluster))
    rows = conn.execute(f"SELECT order_id, company_name, function FROM network_orders WHERE company_key IN ({marks}) "
                        f"AND created_at >= ? AND function IS NOT NULL", (*cluster, since)).fetchall()
    res.cluster_orders = sorted({r["order_id"] for r in rows})
    present = {r["function"] for r in rows}
    business = None
    for sysdef in load_systems():
        have = [req for req in sysdef["required"] if set(req.split("|")) & present]
        coverage = round(len(have) / len(sysdef["required"]), 2)
        supplying = [r for r in rows if any(r["function"] in req.split("|") for req in sysdef["required"])]
        orders = sorted({r["order_id"] for r in supplying})
        if coverage < sysdef["min_coverage"] or len(orders) < 2:
            continue                      # nothing that a single order would not already show
        if business is None:
            business = _business_text(conn, cluster)
        fits = any(k in business for k in sysdef["keywords"])
        f = SystemFinding(system=sysdef["system"], concern=sysdef["concern"], coverage=coverage,
                          functions_present=have, functions_missing=[r for r in sysdef["required"] if r not in have],
                          orders=orders, companies=sorted({r["company_name"] for r in supplying}),
                          fits_business=fits, flagged=not fits)
        res.systems.append(f)
        ids.append(ledger.add(
            f"Orders {', '.join(orders)} from {', '.join(f.companies)} together supply {len(have)} of "
            f"{len(sysdef['required'])} functions of a {f.system}"
            + ("; this matches their known business" if fits else f"; not explained by their known business "
                                                                   f"({f.concern})"),
            {"present": have, "missing": f.functions_missing, "coverage": coverage}, "network:systems"))

    # staff whose past employer is on a restricted list (local screening, no credits)
    seen: dict[str, ScreeningResult | None] = {}
    for r in _people_rows(conn, order.buyer):
        for emp in json.loads(r["past_employers"] or "[]"):
            if emp not in seen:
                seen[emp] = screen(Party(role="buyer", name=emp), Ledger())
            s = seen[emp]
            if s and s.status != "clear" and s.matches:
                hit = ListedStaff(person=r["name"], company=order.buyer.name, past_employer=emp,
                                  listed_name=s.matches[0].listed_name, status=s.status,
                                  source=str(s.matches[0].listed_record.get("source", "")))
                res.listed_staff.append(hit)
                ids.append(ledger.add(f"{hit.person} ({r['title']}) at {hit.company} previously worked at "
                                      f"{emp}, which matches listed entity {hit.listed_name}",
                                      {"status": hit.status, "list": hit.source}, "network:people"))
    return res


def _group(links: list[NetworkLink]) -> dict[str, list[NetworkLink]]:
    out: dict[str, list[NetworkLink]] = {}
    for l in links:
        out.setdefault(l.company, []).append(l)
    return out
