"""Employee background check and buyer type (tasks A6-A7).

People are fetched ONCE per company (capped at config.PEOPLE_CAP_PER_COMPANY) and stored in the `people`
table; every later call (buyer check, end-user check, watcher recompute) reads the table. Only a watcher
event (client.invalidate) causes a refetch.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from clearance import config
from clearance.capability.profile import CompanyProfile, PersonProfile, func_bucket, parse_person
from clearance.crustdata_client import CrustdataClient, norm_key

NEEDS_KEYWORDS: dict[str, list[str]] = {
    "rf": ["rf", "radio frequency", "microwave", "mmwave", "antenna", "hfss", "gaas", "power amplifier"],
    "antenna": ["antenna"],
    "radar": ["radar"],
    "fpga": ["fpga", "verilog", "vhdl", "xilinx", "altera", "rtl"],
    "mixed_signal": ["adc", "dac", "mixed signal", "mixed-signal", "analog", "data converter"],
    "test_lab": ["test engineer", "validation", "test lab", "lab"],
    "telecom": ["telecom", "5g", "lte", "5g nr", "wireless"],
    "satellite": ["satellite", "space", "avionics"],
    "defence": ["defence", "defense", "military"],
}
TECH_EMPLOYER_WORDS = ["electronics", "semiconductor", "defence", "defense", "telecom", "radar", "aerospace",
                       "systems", "labs", "technologies", "instruments"]
TRADING_EMPLOYER_WORDS = ["trading", "traders", "import", "export", "general", "enterprises", "logistics"]


@dataclass
class PeopleCheck:
    people: list[PersonProfile]
    fetched_at: datetime | None
    source: str

    @property
    def n(self) -> int:
        return len(self.people)

    def function_mix(self) -> dict[str, float]:
        if not self.people:
            return {}
        mix = {"engineering": 0, "sales": 0, "operations": 0, "other": 0}
        for p in self.people:
            mix[func_bucket(p.function)] += 1
        return {k: round(v / self.n, 3) for k, v in mix.items()}

    def technical_share(self) -> float | None:
        return self.function_mix().get("engineering") if self.people else None

    def matching(self, needs: list[str]) -> list[PersonProfile]:
        words = {w for n in needs for w in NEEDS_KEYWORDS.get(n, [n])}
        pats = [re.compile(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])") for w in words]
        out = []
        for p in self.people:
            text = " ".join([p.title, *p.skills]).lower()
            if any(pt.search(text) for pt in pats):
                out.append(p)
        return out

    def past_employer_profile(self) -> dict[str, float]:
        names = [e.lower() for p in self.people for e in p.past_employers]
        if not names:
            return {}
        tech = sum(any(w in n for w in TECH_EMPLOYER_WORDS) for n in names)
        trade = sum(any(w in n for w in TRADING_EMPLOYER_WORDS) for n in names)
        return {"tech_share": round(tech / len(names), 3), "trading_share": round(trade / len(names), 3),
                "employers_seen": len(names)}


def _rows_to_people(rows) -> list[PersonProfile]:
    return [PersonProfile(person_id=r["person_id"], name=r["name"], title=r["title"], function=r["function"],
                          seniority="", skills=json.loads(r["skills"] or "[]"),
                          past_employers=json.loads(r["past_employers"] or "[]")) for r in rows]


def background_check(client: CrustdataClient, conn: sqlite3.Connection, company_key: str) -> PeopleCheck | None:
    """None when the company is unknown to Crustdata (and to the fixtures)."""
    key = norm_key(company_key)
    rows = conn.execute("SELECT * FROM people WHERE company_key=?", (key,)).fetchall()
    if rows:
        fetched = datetime.fromisoformat(rows[0]["fetched_at"]) if rows[0]["fetched_at"] else None
        return PeopleCheck(_rows_to_people(rows), fetched, "people-cache")
    raw = client.search_people(company_key, limit=config.PEOPLE_CAP_PER_COMPANY)
    if raw is None:
        return None
    people = [parse_person(p) for p in raw][: config.PEOPLE_CAP_PER_COMPANY]
    now = datetime.now(timezone.utc)
    conn.executemany("INSERT OR REPLACE INTO people VALUES (?,?,?,?,?,?,?,?)",
                     [(key, p.person_id or f"{key}-{i}", p.name, p.title, p.function, json.dumps(p.skills),
                       json.dumps(p.past_employers), now.isoformat()) for i, p in enumerate(people)])
    conn.commit()
    return PeopleCheck(people, now, "crustdata:/person/search")


def keyword_vote(profile: CompanyProfile | None) -> str | None:
    """Guide only, from the company's own description. The industry label is ignored:
    "Electronics Manufacturing" is how distributors are filed, not proof they build anything."""
    if profile is None:
        return None
    text = (profile.description or "").lower()
    d = sum(k in text for k in config.DISTRIBUTOR_KEYWORDS)
    m = sum(k in text for k in config.MANUFACTURER_KEYWORDS)
    return "distributor" if d > m else "manufacturer" if m > d else None


def _snippets(obj: object, limit: int = 40) -> list[str]:
    out: list[str] = []

    def walk(v: object) -> None:
        if len(out) >= limit:
            return
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, dict):
            for item in v.values():
                walk(item)
        elif isinstance(v, list):
            for item in v[:limit]:
                walk(item)

    walk(obj)
    return out


def domain_evidence(profile: CompanyProfile | None, pc: PeopleCheck | None, needs: list[str]) -> list[str]:
    """Short bits of text showing the company already does this kind of work.

    Description, hiring, news, and past employers. A missing keyword is not a finding.
    There is no purchase-order feed; this is the public trail of the work.
    """
    if profile is None or not needs:
        return []
    words = {w for n in needs for w in NEEDS_KEYWORDS.get(n, [n])}
    blobs = [profile.description or "", profile.industry or ""]
    blobs += _snippets((profile.raw or {}).get("hiring"))
    blobs += _snippets((profile.raw or {}).get("news"))
    if pc:
        for person in pc.people:
            blobs.append(person.title)
            blobs.extend(person.past_employers)
    hits: list[str] = []
    for blob in blobs:
        low = blob.lower()
        if any(w in low for w in words) and blob not in hits:
            hits.append(blob[:180])
        if len(hits) >= 3:
            break
    return hits


def decide_buyer(profile: CompanyProfile | None, pc: PeopleCheck | None) -> tuple[str, str]:
    """Who the company is, and which fact decided it.

    Order: the whole workforce (headcount by role), then an explicit "distributor"
    in the description when the workforce is not a large engineering team, then the
    employee sample, and only then the description on its own.
    """
    eng = None if profile is None else profile.engineering_share
    hint = keyword_vote(profile)
    sample = people_vote(pc)
    if eng is not None and eng >= 0.40:
        return "manufacturer", "workforce_engineering_share"
    if hint == "distributor" and (eng is None or eng < 0.40):
        return "distributor", "description_and_workforce"
    if eng is not None and eng >= 0.30 and hint != "distributor":
        return "manufacturer", "workforce_engineering_share"
    if sample:
        return sample, "employee_sample"
    if hint:
        return hint, "description_only"
    return "unclear", "insufficient"


def people_vote(pc: PeopleCheck | None, min_people: int = 3) -> str | None:
    if pc is None or pc.n < min_people:
        return None
    mix = pc.function_mix()
    eng, sales_ops = mix.get("engineering", 0), mix.get("sales", 0) + mix.get("operations", 0)
    if eng >= config.PEOPLE_VOTE_MANUFACTURER_ENG_SHARE:
        return "manufacturer"
    if sales_ops >= config.PEOPLE_VOTE_DISTRIBUTOR_SALES_OPS_SHARE and eng < config.PEOPLE_VOTE_DISTRIBUTOR_MAX_ENG_SHARE:
        return "distributor"
    return None


def buyer_type(kw: str | None, ppl: str | None) -> str:
    """Both votes must agree; one vote alone also decides; conflict or silence -> unclear (both branches scored)."""
    if kw and ppl:
        return kw if kw == ppl else "unclear"
    return kw or ppl or "unclear"
