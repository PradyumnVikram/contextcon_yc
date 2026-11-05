"""Capability engine (task A9). OWNER: Person A.

assess() answers "can this party actually use what it is buying?" from Crustdata evidence:
coverage (§4.3) -> people background check + buyer type (§4.4) -> peer percentiles (§4.5) -> points (§4.6) -> tier.
Deterministic: no LLM. Every feature that feeds a rule is recorded in the ledger with its source.
"""
from __future__ import annotations

from datetime import datetime, timezone

from clearance import config, crustdata_client
from clearance.capability.people import background_check, buyer_type, keyword_vote, people_vote
from clearance.capability.peers import peer_percentiles, peer_set
from clearance.capability.profile import parse_company
from clearance.evidence import Ledger
from clearance.models import CapabilityResult, Classification, OrderLine, Party

PTS = config.CAPABILITY_POINTS


def _tier(score: float) -> str:
    return "high_risk" if score >= config.TIER_HIGH_MIN else "medium_risk" if score >= config.TIER_MEDIUM_MIN else "consistent"


def assess(party: Party, classifications: list[Classification], lines: list[OrderLine],
           ship_to_country: str, ledger: Ledger) -> CapabilityResult:
    client = crustdata_client.get_client()
    conn = client.conn
    key = party.domain or party.name
    src = "crustdata-fixture" if client.fixtures.company(key) is not None else "crustdata"
    now = datetime.now(timezone.utc)
    ids: list[str] = []

    def ev(claim, value, path):
        ids.append(ledger.add(claim, value, f"{src}:{path}", now))

    cd = client.enrich_company(key)
    pc = background_check(client, conn, key) if cd is not None else None

    # ---- coverage -----------------------------------------------------------
    if cd is None:
        ev(f"No Crustdata company record for '{party.name}'", None, "/company/enrich#no_match")
        return CapabilityResult(party_name=party.name, coverage="missing", buyer_type="unclear", tier="no_data",
                                evidence_ids=ids)
    prof = parse_company(cd)
    if not prof.description and not prof.headcount and not (pc and pc.n):
        ev(f"Crustdata record for '{party.name}' has no description, headcount or people", None, "/company/enrich#thin")
        return CapabilityResult(party_name=party.name, coverage="thin", buyer_type="unclear", tier="no_data",
                                evidence_ids=ids)

    # ---- features -----------------------------------------------------------
    age = (now.year - prof.year_founded) if prof.year_founded else None
    needs = sorted({n for c in classifications for n in c.needs})
    matching = pc.matching(needs) if pc and needs else []
    kw, pv = keyword_vote(prof), people_vote(pc)
    btype = buyer_type(kw, pv)
    peers = peer_set(client, conn, prof)
    pcts, n_peers = peer_percentiles(prof, peers)

    feats = {"headcount": prof.headcount, "age_years": age, "headcount_growth_yoy_pct": prof.growth_yoy_pct,
             "monthly_visitors": prof.monthly_visitors,
             "engineering_share": round(prof.engineering_share, 3) if prof.engineering_share is not None else None,
             "people_sampled": pc.n if pc else 0, "matching_people": len(matching) if needs else None,
             "function_mix": pc.function_mix() if pc else {}, "technical_share": pc.technical_share() if pc else None,
             "past_employer_profile": pc.past_employer_profile() if pc else {},
             "buyer_type_keyword_vote": kw, "buyer_type_people_vote": pv, "peer_count": n_peers}

    ev(f"Company profile of '{prof.name}'", {"industry": prof.industry, "country": prof.country,
                                              "description": (prof.description or "")[:160]}, "/company/enrich#basic_info")
    ev("Total headcount", prof.headcount, "/company/enrich#headcount.total")
    ev("Company age in years", age, "/company/enrich#basic_info.year_founded")
    ev("Headcount change over 12 months (%)", prof.growth_yoy_pct, "/company/enrich#headcount.growth_percent.yoy")
    ev("Monthly web visitors", prof.monthly_visitors, "/company/enrich#web_traffic")
    ev("Engineering share of headcount", feats["engineering_share"], "/company/enrich#headcount.by_role_absolute")
    if pc:
        ev(f"Employee background check ({pc.n} people sampled): function mix", feats["function_mix"],
           "/person/search#function_category")
        ev("Past employers of sampled staff", feats["past_employer_profile"], "/person/search#employment_details.past")
        if needs:
            ev(f"Employees whose title/skills match {needs}", [f"{p.name}: {p.title}" for p in matching][:10] or 0,
               "/person/search#title,skills")
    ev("Buyer type (keyword vote + people vote)", {"type": btype, "keyword": kw, "people": pv}, "derived:buyer_type")
    if pcts:
        ev(f"Peer percentiles vs {n_peers} similar companies", pcts, "/company/search#peers")

    # ---- rules --------------------------------------------------------------
    def manufacturer_rules() -> list[str]:
        r = []
        if needs and len(matching) == 0:
            r.append("C1_no_matching_people")
        if pcts.get("engineering_share") is not None and pcts["engineering_share"] < config.LOW_PERCENTILE:
            r.append("C2_low_engineering_share")
        if age is not None and age < config.YOUNG_COMPANY_YEARS:
            r.append("C3_young_company")
        if prof.growth_yoy_pct is not None and prof.growth_yoy_pct < -config.HEADCOUNT_DECLINE_PCT:
            r.append("C4_headcount_decline")
        if pcts.get("monthly_visitors") is not None and pcts["monthly_visitors"] < config.LOW_PERCENTILE:
            r.append("C5_low_traffic")
        if needs:
            for line in lines:
                c = next((c for c in classifications if c.part_number.upper() == line.part_number.upper()), None)
                if c and c.max_units_per_engineer and line.quantity / max(len(matching), 1e-9) > c.max_units_per_engineer:
                    r.append("O1_units_per_engineer")
                    break
        return r

    def distributor_rules() -> list[str]:
        r = []
        if age is not None and age < config.YOUNG_DISTRIBUTOR_YEARS:
            r.append("D1_young_distributor")
        if pcts.get("headcount") is not None and pcts["headcount"] < config.LOW_PERCENTILE:
            r.append("D2_small_distributor")
        if pcts.get("monthly_visitors") is not None and pcts["monthly_visitors"] < config.LOW_PERCENTILE:
            r.append("D3_low_traffic_distributor")
        small = prof.headcount is not None and prof.headcount < config.SMALL_DISTRIBUTOR_HEADCOUNT
        for line in lines:
            c = next((c for c in classifications if c.part_number.upper() == line.part_number.upper()), None)
            if small and c and c.max_units_distributor_small and line.quantity > c.max_units_distributor_small:
                r.append("D4_large_order_small_distributor")
                break
        return r

    ship_rules = []
    buyer_country = (party.country or "").upper()
    dest = (ship_to_country or "").upper()
    if dest and buyer_country and dest != buyer_country:
        ship_rules.append("O2_transshipment_hub" if dest in config.TRANSSHIPMENT_HUBS else "O3_ship_to_mismatch")

    score = lambda rules: sum(PTS[r] for r in rules)
    if btype == "manufacturer":
        triggered = manufacturer_rules() + ship_rules
    elif btype == "distributor":
        triggered = distributor_rules() + ship_rules
    else:
        m, d = manufacturer_rules() + ship_rules, distributor_rules() + ship_rules
        triggered = m if score(m) >= score(d) else d
    total = score(triggered)
    tier = _tier(total)
    ev(f"Capability score {total} -> {tier}", {"rules": triggered, "buyer_type": btype}, "derived:capability_score")

    return CapabilityResult(party_name=party.name, coverage="rich", buyer_type=btype, features=feats, percentiles=pcts,
                            triggered_rules=triggered, mismatch_score=float(total), tier=tier, evidence_ids=ids)
