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


def test_shell_is_medium_from_age_and_order_size_only():
    r, _ = _assess("Synthetic shell Traders", "PA-77G-HE", 100, dest="AE")
    assert r.buyer_type == "distributor" and r.tier == "medium_risk"
    assert {"D1_small_staff", "D4_large_order_small_distributor"} <= set(r.triggered_rules)
    assert "D2_small_distributor" not in r.triggered_rules
    assert "D3_low_traffic_distributor" not in r.triggered_rules
    assert r.features["ship_note"] == "transshipment_hub"
    assert any(t["code"] == "D2_small_distributor" and "median" in t and t["peer_count"] >= 20
               for t in r.features["tracked"])


def test_units_per_engineer_rule():
    r, _ = _assess("Synthetic Hardware Works", "FPGA-RH-X", 100)   # high-end: 3 per engineer allowed
    assert "O1_quantity_vs_technical_staff" in r.triggered_rules
    assert r.features["technical_headcount"] == 3
    assert r.features["reasonable_quantity"] == 9


def test_no_record_is_no_data():
    r, led = _assess("Synthetic nodata Enterprises", "ADC-12G-HE", 10)
    assert (r.coverage, r.tier) == ("missing", "no_data") and r.evidence_ids


def test_real_company_never_gets_synthetic_peers():
    import json as _json

    import httpx

    from clearance import store
    from clearance.capability.peers import peer_set
    from clearance.capability.profile import parse_company
    from clearance.crustdata_client import CrustdataClient

    sent = []

    def handler(req):
        sent.append(_json.loads(req.content))
        return httpx.Response(200, json={"companies": [{"basic_info": {"name": f"Real peer {i}"},
                                                        "headcount": {"total": 100 + i}} for i in range(25)]})

    client = CrustdataClient(store.connect(":memory:"), api_key="k", transport=httpx.MockTransport(handler))
    real = parse_company({"basic_info": {"name": "Real Defence Co", "primary_domain": "realdefence.example"},
                          "taxonomy": {"professional_network_industry": "Defense and Space Manufacturing"},
                          "headcount": {"total": 1500}, "locations": {"country": "IND"}})
    peers = peer_set(client, client.conn, real)
    assert len(sent) == 1 and len(peers) == 25 and peers[0].name == "Real peer 0"
    conds = {c["field"]: c["value"] for c in sent[0]["filters"]["conditions"]}
    assert conds["taxonomy.professional_network_industry"] == ["Defense and Space Manufacturing"]


def _live_client(handler):
    import httpx

    from clearance import store
    from clearance.crustdata_client import CrustdataClient
    return CrustdataClient(store.connect(":memory:"), api_key="k", transport=httpx.MockTransport(handler))


REAL = {"basic_info": {"name": "Real Defence Co", "primary_domain": "realdefence.example",
                       "description": "Designs radar systems"},
        "taxonomy": {"professional_network_industry": "Defense and Space Manufacturing"},
        "headcount": {"total": 1500, "by_role_absolute": {"Engineering": 900, "Sales": 600}},
        "locations": {"country": "IND"}}


def test_peers_are_batch_enriched_for_engineering_share_and_traffic():
    import json as _json

    import httpx

    from clearance.capability.peers import peer_set
    from clearance.capability.profile import parse_company
    calls = []

    def handler(req):
        body = _json.loads(req.content)
        calls.append((req.url.path, body))
        if req.url.path == "/company/search":
            return httpx.Response(200, json={"companies": [
                {"basic_info": {"name": f"P{i}", "primary_domain": f"p{i}.example"}, "headcount": {"total": 100}}
                for i in range(25)]})
        return httpx.Response(200, json=[{"matched_on": d, "matches": [{"company_data": {
            "basic_info": {"name": d, "primary_domain": d}, "headcount": {"total": 100, "by_role_absolute": {"Engineering": 40, "Sales": 60}},
            "web_traffic": {"domain_traffic": {d: {"monthly_visitors": 1000}}}}}]} for d in body["domains"]])

    client = _live_client(handler)
    peers = peer_set(client, client.conn, parse_company(REAL))
    paths = [p for p, _ in calls]
    assert paths == ["/company/search", "/company/enrich"]           # one search + ONE batched enrich
    assert "web_traffic" not in calls[0][1]["fields"]                # search rejects web_traffic
    assert len(calls[1][1]["domains"]) == 20                          # capped
    enriched = [p for p in peers if p.monthly_visitors is not None]
    assert len(enriched) == 20 and enriched[0].engineering_share == 0.4


def test_crustdata_error_degrades_instead_of_crashing(offline, monkeypatch):
    import httpx

    from clearance import crustdata_client
    from clearance.capability import assess
    from clearance.evidence import Ledger
    from clearance.models import Party

    def handler(req):
        if req.url.path == "/company/enrich":
            return httpx.Response(200, json=[{"matches": [{"company_data": REAL}]}])
        return httpx.Response(400, json={"error": {"type": "invalid_request"}})   # people + peers fail

    crustdata_client.set_client(_live_client(handler))
    led = Ledger()
    r = assess(Party(role="buyer", name="Real Defence Co", domain="realdefence.example", country="IN"), [], [], "IN", led)
    assert r.coverage == "rich" and r.percentiles == {}
    assert any("unavailable" in e.claim for e in led.items)
