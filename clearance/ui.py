"""Presentation helpers shared by the two Streamlit apps (Person B). No Streamlit import: plain, testable functions.

- readable evidence: plain-English sources, formatted values, grouped by where the fact came from
- crustdata_snapshot: what Crustdata returned for a party, read from the cache/fixtures only (never spends credits)
"""
from __future__ import annotations

import json
import re
from typing import Any

from clearance import crustdata_client
from clearance.capability.profile import parse_company
from clearance.crustdata_client import CrustdataClient, norm_key
from clearance.models import Evidence, Party

GROUP_ORDER = ["Order email", "Parts & licence", "Screening", "Crustdata", "Analysis", "End-use", "Actions"]

_CRUST_ENDPOINT = {"/company/enrich": "company record", "/person/search": "employee search",
                   "/company/search": "peer companies"}


def md_escape(text: str) -> str:
    """Show text literally inside st.markdown (emails are data, not Markdown)."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~$:])", r"\\\1", text or "")


def readable_value(v: Any) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    if isinstance(v, (list, tuple, set)):
        items = [readable_value(x) for x in v]
        if not items:
            return "none"
        return ", ".join(items[:8]) + (f" … (+{len(items) - 8} more)" if len(items) > 8 else "")
    if isinstance(v, dict):
        return " · ".join(f"{k.replace('_', ' ').capitalize()}: {readable_value(x)}" for k, x in v.items())
    s = str(v)
    return s if len(s) <= 240 else s[:237] + "…"


def friendly_source(source: str) -> str:
    kind, _, rest = (source or "").partition(":")
    if kind in ("crustdata", "crustdata-fixture"):
        endpoint = rest.split("#")[0]
        what = _CRUST_ENDPOINT.get(endpoint, "derived" if endpoint.startswith("derived") else "data")
        return f"Crustdata · {what} ({'demo data' if kind == 'crustdata-fixture' else 'live'})"
    if kind == "email":
        return "Sender address" if rest.endswith("#from") else "Order email"
    if kind == "catalog":
        return "Parts catalog" + (f" · row {rest.split('/')[-1]}" if rest.startswith("row/") else " · not listed")
    if kind == "licence_rules":
        return "Licence rules" + (f" · row {rest.split('/')[-1]}" if rest.startswith("row/") else "")
    if kind == "csl":
        return f"US screening list · entry {rest.split('/')[-1]}" if rest.startswith("entry/") else "US screening list"
    return {"screening": "Name check", "derived": "Clearance calculation", "enduse": "End-use check",
            "pipeline": "Clearance action", "officer": f"Officer {rest}".strip()}.get(kind, source)


def group_of(source: str) -> str:
    kind, _, rest = (source or "").partition(":")
    if kind in ("crustdata", "crustdata-fixture"):
        return "Analysis" if rest.startswith("derived") else "Crustdata"
    return {"email": "Order email", "catalog": "Parts & licence", "licence_rules": "Parts & licence",
            "csl": "Screening", "screening": "Screening", "derived": "Analysis", "enduse": "End-use",
            "pipeline": "Actions", "officer": "Actions"}.get(kind, "Analysis")


def readable_claim(claim: str) -> str:
    m = re.match(r"Order field '(\w+)' from email", claim)
    if m:
        return f"{m.group(1).replace('_', ' ').capitalize()} (from the email)"
    return claim


def evidence_groups(items: list[Evidence], cited: set[str]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in items:
        groups.setdefault(group_of(e.source), []).append(
            {"ID": e.id, "Cited": e.id in cited, "What": readable_claim(e.claim), "Value": readable_value(e.value),
             "Source": friendly_source(e.source)})
    return {g: groups[g] for g in GROUP_ORDER if g in groups}


# --------------------------------------------------------------------------- Crustdata snapshot (cache only)
def _cached_company(client: CrustdataClient, key: str) -> tuple[dict | None, str]:
    if (fx := client.fixtures.company(key)) is not None:
        return fx, "demo data"
    k = norm_key(key)
    body = {"domains" if crustdata_client.is_domain(k) else "names": [k], "fields": crustdata_client.ENRICH_FIELDS}
    data = crustdata_client.store.cache_get(client.conn, "/company/enrich", body)
    matches = (data[0] or {}).get("matches") if data else None
    return (matches[0]["company_data"], "live Crustdata") if matches else (None, "")


def crustdata_snapshot(client: CrustdataClient, party: Party) -> dict[str, Any]:
    """Everything Crustdata returned for this party, as display-ready data. Reads only cached results."""
    cd, source, key = None, "", None
    for k in [x for x in (party.domain, party.name) if x]:
        cd, source = _cached_company(client, k)
        if cd is not None:
            key = k
            break
    if cd is None:
        return {"profile": None, "source": "", "by_function": {}, "people": [], "peers": [], "description": ""}
    p = parse_company(cd)
    profile = {"Company": p.name, "Domain": p.domain, "Industry": p.industry, "Headquarters": p.country,
               "Founded": str(p.year_founded) if p.year_founded else None, "Headcount": readable_value(p.headcount),
               "Headcount change, 12 months": f"{p.growth_yoy_pct:+.1f}%" if p.growth_yoy_pct is not None else None,
               "Monthly web visitors": readable_value(p.monthly_visitors),
               "Engineering share": f"{p.engineering_share:.0%}" if p.engineering_share is not None else None}
    conn = client.conn
    ck = norm_key(key)
    people = [{"Name": r["name"], "Title": r["title"], "Function": r["function"] or "—",
               "Skills": json.loads(r["skills"] or "[]"), "Past employers": json.loads(r["past_employers"] or "[]")}
              for r in conn.execute("SELECT * FROM people WHERE company_key=?", (ck,))]
    row = conn.execute("SELECT peer_set_json FROM peers WHERE company_key=?", (ck,)).fetchone()
    peers = []
    for c in (json.loads(row["peer_set_json"]) if row else []):
        q = parse_company(c)
        peers.append({"Company": q.name, "Headcount": q.headcount, "Engineering share": q.engineering_share,
                      "Monthly visitors": q.monthly_visitors})
    by_fn = dict(sorted(p.by_role.items(), key=lambda kv: -kv[1])) if p.by_role and not p.by_role_is_pct else {}
    return {"profile": {k: v for k, v in profile.items() if v not in (None, "—")}, "source": source,
            "by_function": by_fn, "people": people, "peers": peers, "description": p.description or "",
            "self": {"Company": f"★ {p.name}", "Headcount": p.headcount, "Engineering share": p.engineering_share,
                     "Monthly visitors": p.monthly_visitors}}
