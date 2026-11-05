"""Peer comparison (task A8): 20-50 companies with the same industry, size band and country, cached per buyer
in the `peers` table. Buyer features are reported as percentiles against them."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from clearance import config
from clearance.capability.profile import CompanyProfile, parse_company
from clearance.crustdata_client import CrustdataClient, norm_key


def _filters(p: CompanyProfile) -> dict:
    conds = []
    if p.industry:
        conds.append({"field": "taxonomy.professional_network_industry", "type": "in", "value": [p.industry]})
    if p.headcount:
        conds += [{"field": "headcount.total", "type": "=>", "value": max(1, p.headcount // 4)},
                  {"field": "headcount.total", "type": "=<", "value": max(50, p.headcount * 4)}]
    if p.country:
        conds.append({"field": "locations.country", "type": "=", "value": p.country})
    return {"op": "and", "conditions": conds}


def peer_set(client: CrustdataClient, conn: sqlite3.Connection, profile: CompanyProfile) -> list[CompanyProfile]:
    key = norm_key(profile.domain or profile.name or "")
    row = conn.execute("SELECT peer_set_json FROM peers WHERE company_key=?", (key,)).fetchone()
    if row:
        raw = json.loads(row["peer_set_json"])
    else:
        raw = client.search_companies(_filters(profile), limit=config.PEER_SET_MAX, fixture_industry=profile.industry)
        raw = [c for c in raw if norm_key((c.get("basic_info") or {}).get("primary_domain") or "") != key]
        conn.execute("INSERT OR REPLACE INTO peers VALUES (?,?,?)",
                     (key, json.dumps(raw), datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return [parse_company(c) for c in raw]


def percentile(value: float | None, others: list[float | None]) -> float | None:
    """Share of peers strictly below `value`, 0-100. None if fewer than PEER_SET_MIN peers have the feature."""
    vals = [v for v in others if v is not None]
    if value is None or len(vals) < config.PEER_SET_MIN:
        return None
    return round(100 * sum(v < value for v in vals) / len(vals), 1)


def peer_percentiles(profile: CompanyProfile, peers: list[CompanyProfile]) -> tuple[dict[str, float], int]:
    feats = {
        "engineering_share": (profile.engineering_share, [p.engineering_share for p in peers]),
        "headcount": (profile.headcount, [p.headcount for p in peers]),
        "monthly_visitors": (profile.monthly_visitors, [p.monthly_visitors for p in peers]),
    }
    out = {k: pct for k, (v, others) in feats.items() if (pct := percentile(v, others)) is not None}
    return out, len(peers)
