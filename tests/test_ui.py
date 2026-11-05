"""Presentation helpers: human-readable evidence and the cached Crustdata snapshot shown in the UI."""
from clearance import ui
from clearance.models import Evidence, Party


def test_readable_values():
    assert ui.readable_value(None) == "—"
    assert ui.readable_value(True) == "Yes"
    assert ui.readable_value(16694) == "16,694"
    assert ui.readable_value(0.4865) == "0.49"
    assert ui.readable_value(130128790.0) == "130,128,790"
    assert ui.readable_value(["rf", "radar"]) == "rf, radar"
    assert ui.readable_value({"buyer_type": "manufacturer", "keyword": None}) == "Buyer type: manufacturer · Keyword: —"
    assert ui.readable_value([]) == "none"


def test_friendly_sources_and_groups():
    assert ui.friendly_source("crustdata:/company/enrich#headcount.total") == "Crustdata · company record (live)"
    assert ui.friendly_source("crustdata-fixture:/person/search#title,skills") == "Crustdata · employee search (demo data)"
    assert ui.friendly_source("csl:entry/12345") == "US screening list · entry 12345"
    assert ui.friendly_source("email:<abc@x>") == "Order email"
    assert ui.friendly_source("catalog:row/3") == "Parts catalog · row 3"
    assert ui.group_of("crustdata:/company/search#peers") == "Crustdata"
    assert ui.group_of("licence_rules:row/2") == "Parts & licence"
    assert ui.group_of("derived:capability_score") == "Analysis"


def test_evidence_rows_are_grouped_in_a_fixed_order():
    items = [Evidence(id="E2", claim="Total headcount", value=180, source="crustdata:/company/enrich#headcount.total"),
             Evidence(id="E1", claim="Order field 'buyer_name' from email", value="Acme", source="email:<m>")]
    groups = ui.evidence_groups(items, cited={"E2"})
    assert list(groups) == ["Order email", "Crustdata"]
    assert groups["Crustdata"][0] == {"ID": "E2", "Cited": True, "What": "Total headcount", "Value": "180",
                                      "Source": "Crustdata · company record (live)"}
    assert groups["Order email"][0]["What"] == "Buyer name (from the email)"


def test_crustdata_snapshot_reads_cache_and_fixtures_only(offline):
    snap = ui.crustdata_snapshot(offline, Party(role="buyer", name="Synthetic Radar Systems", domain="synthetic-radar.example"))
    assert snap["source"] == "demo data" and snap["profile"]["Headcount"] == "180"
    assert snap["by_function"]["Engineering"] == 95
    unknown = ui.crustdata_snapshot(offline, Party(role="buyer", name="Nobody Ltd"))
    assert unknown["profile"] is None


def test_md_escape_keeps_text_literal():
    assert ui.md_escape("2 * 3 = [six]") == "2 \\* 3 = \\[six\\]"


def test_crustdata_summary_reads_like_a_report(offline):
    from clearance import capability, catalog
    from clearance.evidence import Ledger
    from clearance.models import OrderLine
    party = Party(role="buyer", name="Synthetic Radar Systems", domain="synthetic-radar.example", country="IN")
    led = Ledger()
    cap = capability.assess(party, [catalog.classify("PA-77G-HE", led)], [OrderLine(part_number="PA-77G-HE", quantity=4)],
                            "IN", led)
    lines = ui.crustdata_summary(ui.crustdata_snapshot(offline, party), cap)
    text = " ".join(t for _, t in lines)
    assert [h for h, _ in lines] == ["Company record", "Employees", "Peer comparison", "Verdict"]
    assert "founded in 2009" in text and "180 employees" in text and "115 in engineering and research (64%)" in text
    assert "25 employee profiles" in text and "16 have skills matching" in text
    assert "30 similar companies" in text and "percentile" in text
    assert "Consistent" in text


def test_crustdata_summary_when_nothing_found(offline):
    lines = ui.crustdata_summary(ui.crustdata_snapshot(offline, Party(role="buyer", name="Nobody Ltd")), None)
    assert lines == [("Company record", "Crustdata returned no record for this company. Clearance treats missing data as a "
                                        "risk signal, never a pass, and asks the buyer for an end-use statement.")]


def test_every_capability_rule_has_plain_english_text():
    from clearance import config
    assert set(ui.RULE_TEXT) == set(config.CAPABILITY_POINTS)
