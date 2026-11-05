"""Capability engine. OWNER: Person A (tasks A6-A9).

STUB (S5): decides by keywords in the party name so the pipeline can be
exercised: "shell" -> high_risk, "nodata" -> missing coverage,
"distributor" -> distributor. Replace with the real engine. Keep the signature.
"""
from __future__ import annotations

from clearance.evidence import Ledger
from clearance.models import CapabilityResult, Classification, OrderLine, Party

STUB = True


def assess(party: Party, classifications: list[Classification], lines: list[OrderLine],
           ship_to_country: str, ledger: Ledger) -> CapabilityResult:
    name = party.name.lower()
    if "nodata" in name:
        eid = ledger.add(f"No Crustdata record for '{party.name}'", None, "crustdata:/company/enrich#miss")
        return CapabilityResult(party_name=party.name, coverage="missing", buyer_type="unclear",
                                tier="no_data", evidence_ids=[eid])
    if "shell" in name:
        e1 = ledger.add("0 employees match the part's needs", 0, "crustdata:stub#people")
        e2 = ledger.add("Company age (years)", 1, "crustdata:stub#founded")
        return CapabilityResult(party_name=party.name, coverage="rich", buyer_type="unclear",
                                features={"matching_people": 0, "age_years": 1},
                                triggered_rules=["C1_no_matching_people", "C3_young_company", "O1_units_per_engineer"],
                                mismatch_score=75, tier="high_risk", evidence_ids=[e1, e2])
    buyer_type = "distributor" if "distributor" in name else "manufacturer"
    eid = ledger.add(f"Capability profile of '{party.name}' is consistent", {"buyer_type": buyer_type}, "crustdata:stub")
    return CapabilityResult(party_name=party.name, coverage="rich", buyer_type=buyer_type,
                            features={"matching_people": 12}, mismatch_score=0, tier="consistent", evidence_ids=[eid])
