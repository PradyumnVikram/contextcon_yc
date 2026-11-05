"""Capability engine (task A9). OWNER: Person A.

assess() answers "can this party actually use what it is buying?" from Crustdata evidence:
coverage (§4.3) -> people background check + buyer type (§4.4) -> peer percentiles (§4.5) -> points (§4.6) -> tier.
Deterministic: no LLM. Every feature that feeds a rule is recorded in the ledger with its source.
"""
from __future__ import annotations

from datetime import datetime, timezone

from clearance import config, crustdata_client
from clearance.capability.people import background_check, decide_buyer, domain_evidence, keyword_vote, people_vote
from clearance.capability.peers import comparison, fade_points, peer_percentiles, peer_set
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
    # identify the company by domain first (exact), then by name; the first key with data is used throughout
    keys = [k for k in (party.domain, party.name) if k]
    key = next((k for k in keys if client.fixtures.company(k) is not None), keys[0] if keys else party.name)
    src = "crustdata-fixture" if client.fixtures.company(key) is not None else "crustdata"
    now = datetime.now(timezone.utc)
    ids: list[str] = []

    def ev(claim, value, path):
        ids.append(ledger.add(claim, value, f"{src}:{path}", now))

    try:
        cd = client.enrich_company(key)
        if cd is None and len(keys) > 1 and key != keys[-1]:
            key = keys[-1]
            cd = client.enrich_company(key)
    except crustdata_client.CrustdataError as e:
        ev(f"Crustdata company lookup unavailable for '{party.name}'", str(e)[:200], "/company/enrich#error")
        return CapabilityResult(party_name=party.name, coverage="missing", buyer_type="unclear", tier="no_data",
                                evidence_ids=ids)
    pc = None
    if cd is not None:
        try:
            pc = background_check(client, conn, key)
        except crustdata_client.CrustdataError as e:
            ev("Employee background check unavailable", str(e)[:200], "/person/search#error")

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
    btype, buyer_basis = decide_buyer(prof, pc)
    try:
        peers = peer_set(client, conn, prof)
    except crustdata_client.CrustdataError as e:
        peers = []
        ev("Peer comparison unavailable", str(e)[:200], "/company/search#error")
    pcts, n_peers = peer_percentiles(prof, peers)

    feats = {"headcount": prof.headcount, "age_years": age, "headcount_growth_yoy_pct": prof.growth_yoy_pct,
             "monthly_visitors": prof.monthly_visitors,
             "engineering_share": round(prof.engineering_share, 3) if prof.engineering_share is not None else None,
             "people_sampled": pc.n if pc else 0, "matching_people": len(matching) if needs else None,
             "function_mix": pc.function_mix() if pc else {}, "technical_share": pc.technical_share() if pc else None,
             "past_employer_profile": pc.past_employer_profile() if pc else {},
             "buyer_type_keyword_vote": kw, "buyer_type_people_vote": pv,
             "buyer_type_basis": buyer_basis, "peer_count": n_peers}

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
    ev("Buyer type", {"type": btype, "basis": buyer_basis, "description_hint": kw,
                      "employee_sample": pv, "workforce_engineering_share": feats["engineering_share"]},
       "derived:buyer_type")
    if pcts:
        ev(f"Peer percentiles vs {n_peers} similar companies", pcts, "/company/search#peers")

    def track(code: str, label: str, value: float | None, attr: str) -> None:
        detail = comparison(value, peers, attr)
        if detail is None:
            return
        detail["code"] = code
        detail["against"] = {"industry": prof.industry, "country": prof.country}
        tracked.append(detail)
        ev(f"{label} is {detail['value']} against {detail['peer_count']} peers "
           f"in {prof.industry or 'the same industry'} ({prof.country or 'any country'}). "
           f"Peer median {detail['median']}, range {detail['low']}–{detail['high']}, "
           f"percentile {detail['percentile']}. Not scored.",
           detail, "derived:tracked")

    tracked: list[dict] = []
    track("D2_small_distributor", "Headcount", float(prof.headcount) if prof.headcount is not None else None, "headcount")
    track("C5_D3_traffic", "Monthly visitors", prof.monthly_visitors, "monthly_visitors")

    # ---- rules --------------------------------------------------------------
    evidence = domain_evidence(prof, pc, needs)
    tech = prof.technical_headcount
    sampled = pc.n if pc else 0
    feats["domain_evidence"] = evidence
    feats["technical_headcount"] = None if tech is None else round(tech, 1)
    feats["sample_covers_staff"] = bool(prof.headcount and sampled >= config.SMALL_STAFF_SAMPLE_COVERS * prof.headcount)

    def small_staff_points(full: float) -> float:
        hc = prof.headcount
        if not hc or hc >= config.SMALL_STAFF_FADE_AT:
            return 0
        base = full * (config.SMALL_STAFF_FADE_AT - hc) / config.SMALL_STAFF_FADE_AT
        if feats["sample_covers_staff"]:
            base *= 1.35
        return round(min(full * 1.35, base), 1)

    def over_order_points(qty: int, staff: float, per_person: int, full: float) -> tuple[float, float]:
        """0 at a reasonable order, full points at OVER_ORDER_FULL_AT times that.

        10,000 high-end parts at 5 per technical person is a normal buy only for
        about 2,000 engineers. 10,000 commodity FPGAs at 50 per person is normal
        for about 200. A handful of engineers ordering 10,000 is not.
        """
        reasonable = max(per_person, (staff or 0) * per_person)
        if qty <= reasonable:
            return 0, reasonable
        ratio = qty / reasonable
        span = config.OVER_ORDER_FULL_AT - 1
        return round(min(full, full * (ratio - 1) / span), 1), reasonable

    def manufacturer_rules() -> list[tuple[str, float]]:
        r = []
        eng = prof.engineering_share or 0
        if needs and not evidence and eng < config.TECHNICAL_SHARE_CLEAR:
            c1 = round(PTS["C1_not_a_technical_business"] * (1 - eng / config.TECHNICAL_SHARE_CLEAR), 1)
            if c1:
                r.append(("C1_not_a_technical_business", c1))
        c2 = fade_points(pcts.get("engineering_share"), PTS["C2_low_engineering_share"], config.C2_FADE_UNTIL)
        if c2:
            r.append(("C2_low_engineering_share", c2))
        small = small_staff_points(PTS["C3_small_staff"])
        if small:
            r.append(("C3_small_staff", small))
        if prof.growth_yoy_pct is not None and prof.growth_yoy_pct < -config.HEADCOUNT_DECLINE_PCT:
            r.append(("C4_headcount_decline", PTS["C4_headcount_decline"]))
        for line in lines:
            c = next((c for c in classifications if c.part_number.upper() == line.part_number.upper()), None)
            if not c or not c.max_units_per_engineer:
                continue
            pts, reasonable = over_order_points(line.quantity, tech or 0, c.max_units_per_engineer,
                                                PTS["O1_quantity_vs_technical_staff"])
            feats["reasonable_quantity"] = reasonable
            feats["ordered_quantity"] = line.quantity
            if pts:
                r.append(("O1_quantity_vs_technical_staff", pts))
                break
        return r

    def distributor_rules() -> list[tuple[str, float]]:
        r = []
        small = small_staff_points(PTS["D1_small_staff"])
        if small:
            r.append(("D1_small_staff", small))
        staff = float(prof.headcount or 0)
        for line in lines:
            c = next((c for c in classifications if c.part_number.upper() == line.part_number.upper()), None)
            if not c or not c.max_units_distributor_small:
                continue
            # The catalog cap is what a 5-person reseller can move. Bigger staff scales it up.
            per_person = max(1, c.max_units_distributor_small / 5)
            pts, reasonable = over_order_points(line.quantity, staff, int(per_person),
                                                PTS["D4_large_order_small_distributor"])
            feats["reasonable_quantity"] = reasonable
            feats["ordered_quantity"] = line.quantity
            if pts:
                r.append(("D4_large_order_small_distributor", pts))
                break
        return r

    buyer_country = (party.country or "").upper()
    dest = (ship_to_country or "").upper()
    ship_note = None
    if dest and buyer_country and dest != buyer_country:
        ship_note = "transshipment_hub" if dest in config.TRANSSHIPMENT_HUBS else "different_country"
    feats["buyer_country"] = buyer_country or None
    feats["ship_to_country"] = dest or None
    feats["ship_note"] = ship_note
    if ship_note:
        ev(f"Ship-to country {dest} is not the buyer's country {buyer_country}",
           {"note": ship_note, "hubs": sorted(config.TRANSSHIPMENT_HUBS)}, "order:ship_to")

    def point_sum(rules: list[tuple[str, float]]) -> float:
        return sum(pts for _, pts in rules)

    if btype == "manufacturer":
        awarded = manufacturer_rules()
    elif btype == "distributor":
        awarded = distributor_rules()
    else:
        m, d = manufacturer_rules(), distributor_rules()
        awarded = m if point_sum(m) >= point_sum(d) else d
    triggered = [name for name, pts in awarded if pts > 0]
    total = point_sum(awarded)
    tier = _tier(total)
    feats["tracked"] = tracked
    feats["rule_points"] = {name: pts for name, pts in awarded}
    ev(f"Capability score {total} -> {tier}", {"rules": feats["rule_points"], "buyer_type": btype}, "derived:capability_score")

    return CapabilityResult(party_name=party.name, coverage="rich", buyer_type=btype, features=feats, percentiles=pcts,
                            triggered_rules=triggered, mismatch_score=float(total), tier=tier, evidence_ids=ids)
