"""A6-A9: background check, buyer type, peers, scoring on the synthetic demo companies."""
from clearance import capability, catalog
from clearance.capability.people import background_check, buyer_type
from clearance.evidence import Ledger
from clearance.models import OrderLine, Party


def _assess(name, part, qty, dest="IN", country="IN"):
    led = Ledger()
    cls = [catalog.classify(part, led)]
    r = capability.assess(Party(role="buyer", name=name, country=country), cls,
                          [OrderLine(part_number=part, quantity=qty)], dest, led)
    return r, led


def test_people_fetched_once_and_cached(offline):
    calls = []
    orig = offline.search_people
    offline.search_people = lambda *a, **k: calls.append(1) or orig(*a, **k)
    first = background_check(offline, offline.conn, "Synthetic Radar Systems")
    again = background_check(offline, offline.conn, "Synthetic Radar Systems")
    assert len(calls) == 1 and first.n == again.n == 25 and again.source == "people-cache"
    assert first.function_mix()["engineering"] > 0.5
    assert len(first.matching(["radar", "rf"])) == 16


def test_buyer_type_votes():
    assert buyer_type("manufacturer", "manufacturer") == "manufacturer"
    assert buyer_type("distributor", "manufacturer") == "unclear"
    assert buyer_type(None, "distributor") == "distributor"
    assert buyer_type(None, None) == "unclear"


def test_radar_firm_consistent_with_peer_evidence():
    r, led = _assess("Synthetic Radar Systems", "PA-77G-HE", 4)
    assert (r.coverage, r.buyer_type, r.tier) == ("rich", "manufacturer", "consistent")
    assert r.features["matching_people"] == 16 and r.features["peer_count"] == 30
    assert "engineering_share" in r.percentiles
    assert all(led.has(i) for i in r.evidence_ids)
    assert any("Peer percentiles" in led.get(i).claim for i in r.evidence_ids)


def test_distributor_branch_and_small_hardware_firm_pass():
    assert _assess("Synthetic Components distributor", "FPGA-C10", 200)[0].tier == "consistent"
    hw, _ = _assess("Synthetic Hardware Works", "FPGA-C10", 100)   # 3 engineers, commodity part
    assert hw.tier == "consistent" and hw.features["matching_people"] == 3


def test_shell_is_high_risk():
    r, _ = _assess("Synthetic shell Traders", "PA-77G-HE", 100, dest="AE")
    assert r.buyer_type == "distributor" and r.tier == "high_risk"
    assert {"D1_young_distributor", "D4_large_order_small_distributor", "O2_transshipment_hub"} <= set(r.triggered_rules)


def test_units_per_engineer_rule():
    r, _ = _assess("Synthetic Hardware Works", "FPGA-RH-X", 100)   # high-end: 3 per engineer allowed
    assert "O1_units_per_engineer" in r.triggered_rules


def test_no_record_is_no_data():
    r, led = _assess("Synthetic nodata Enterprises", "ADC-12G-HE", 10)
    assert (r.coverage, r.tier) == ("missing", "no_data") and r.evidence_ids
