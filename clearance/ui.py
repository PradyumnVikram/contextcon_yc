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
    eng = sum(v for k, v in p.by_role.items() if "engineer" in k.lower() or "research" in k.lower()) \
        if p.by_role and not p.by_role_is_pct else None
    raw = {"name": p.name, "domain": p.domain, "industry": p.industry, "country": p.country, "year": p.year_founded,
           "headcount": p.headcount, "engineers": eng, "eng_share": p.engineering_share, "growth": p.growth_yoy_pct,
           "visitors": p.monthly_visitors}
    return {"raw": raw, "company_data": cd, "profile": {k: v for k, v in profile.items() if v not in (None, "—")}, "source": source,
            "by_function": by_fn, "people": people, "peers": peers, "description": p.description or "",
            "self": {"Company": f"★ {p.name}", "Headcount": p.headcount, "Engineering share": p.engineering_share,
                     "Monthly visitors": p.monthly_visitors}}


# --------------------------------------------------------------------------- plain-English Crustdata report
RULE_TEXT = {  # one entry per rule in config.CAPABILITY_POINTS (names as of the dev2 merge, 2026-11-06)
    "C1_not_a_technical_business": "the company does not look like a technical business that could use these parts",
    "C2_low_engineering_share": "engineering share is low compared with similar companies",
    "C3_small_staff": "the staff is very small for this kind of order",
    "C4_headcount_decline": "headcount fell by more than 20% in a year",
    "C5_low_traffic": "web traffic is low compared with similar companies (recorded, not scored)",
    "O1_quantity_vs_technical_staff": "the order quantity is too large for the company's technical staff",
    "O2_transshipment_hub": "goods ship to a transshipment hub in another country (recorded, not scored)",
    "O3_ship_to_mismatch": "goods ship to a different country from the buyer's (recorded, not scored)",
    "D1_small_staff": "the distributor's staff is very small",
    "D2_small_distributor": "the distributor is small compared with peers (recorded, not scored)",
    "D3_low_traffic_distributor": "the distributor's web traffic is low (recorded, not scored)",
    "D4_large_order_small_distributor": "a small distributor is ordering a large quantity",
}


def _ord(n: float) -> str:
    n = int(round(n))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def crustdata_summary(snap: dict[str, Any], cap: Any | None) -> list[tuple[str, str]]:
    """What Crustdata returned, as (heading, sentence) pairs a compliance officer can read aloud."""
    if not snap.get("profile"):
        return [("Company record", "Crustdata returned no record for this company. Clearance treats missing data as a "
                                   "risk signal, never a pass, and asks the buyer for an end-use statement.")]
    r = snap["raw"]
    out: list[tuple[str, str]] = []
    parts = [f"Crustdata returned a company record for **{md_escape(r['name'] or '')}**"
             + (f" ({r['domain']})" if r["domain"] else "") + ":"]
    desc = []
    if r["industry"]:
        desc.append(f"a {r['industry']} company")
    if r["country"]:
        desc.append(f"headquartered in {r['country']}")
    if r["year"]:
        desc.append(f"founded in {r['year']}")
    parts.append(", ".join(desc) + "." if desc else "")
    if r["headcount"] is not None:
        s = f"It has {readable_value(r['headcount'])} employees"
        if r["engineers"] is not None and r["eng_share"] is not None:
            s += f", {readable_value(int(r['engineers']))} in engineering and research ({r['eng_share']:.0%})"
        parts.append(s + ".")
    if r["growth"] is not None:
        g = r["growth"]
        parts.append("Headcount was flat over the last 12 months." if abs(g) < 0.5 else
                     f"Headcount {'grew' if g > 0 else 'fell'} {abs(g):.0f}% over the last 12 months.")
    if r["visitors"] is not None:
        parts.append(f"Its website gets about {readable_value(r['visitors'])} visitors a month.")
    out.append(("Company record", " ".join(x for x in parts if x)))

    f = (cap.features if cap else {}) or {}
    people = snap.get("people") or []
    if people:
        mix = {}
        for person in people:
            mix[person["Function"]] = mix.get(person["Function"], 0) + 1
        top = ", ".join(f"{n} in {fn.lower()}" for fn, n in sorted(mix.items(), key=lambda kv: -kv[1])[:3] if fn != "—")
        s = f"An employee search returned {len(people)} employee profiles" + (f" ({top})" if top else "") + "."
        if f.get("matching_people") is not None:
            s += f" {f['matching_people']} have skills matching what the ordered parts need."
        pe = f.get("past_employer_profile") or {}
        if pe.get("employers_seen"):
            if pe.get("tech_share", 0) >= pe.get("trading_share", 0):
                s += f" Their past employers are mostly technical firms ({pe['tech_share']:.0%} electronics, defence or telecom)."
            else:
                s += f" Their past employers are mostly trading firms ({pe['trading_share']:.0%})."
        out.append(("Employees", s))
    else:
        out.append(("Employees", "The employee search returned no profiles for this company."))

    peers = snap.get("peers") or []
    pct = (cap.percentiles if cap else {}) or {}
    if peers and pct:
        names = {"engineering_share": "engineering share", "headcount": "headcount", "monthly_visitors": "web traffic"}
        ranks = "; ".join(f"{_ord(v)} percentile for {names.get(k, k)}" for k, v in pct.items())
        low = [names.get(k, k) for k, v in pct.items() if v < 10]
        s = (f"Compared with {len(peers)} similar companies (same industry, similar size, same country), the buyer "
             f"ranks at the {ranks}.")
        s += f" Low compared with peers: {', '.join(low)}." if low else " Nothing is unusually low compared with peers."
        out.append(("Peer comparison", s))
    elif peers:
        out.append(("Peer comparison", f"Crustdata returned {len(peers)} similar companies, but too few had comparable "
                                       "data to rank the buyer."))

    if cap:
        tier = {"consistent": "Consistent", "medium_risk": "Medium risk", "high_risk": "High risk",
                "no_data": "No data"}.get(cap.tier, cap.tier)
        reasons = [RULE_TEXT.get(x, x) for x in cap.triggered_rules]
        s = f"From this data Clearance scored **{cap.mismatch_score:g} points: {tier}** (buyer type: {cap.buyer_type})."
        s += (" Reasons: " + "; ".join(reasons) + ".") if reasons else " No capability rule was triggered."
        out.append(("Verdict", s))
    return out
