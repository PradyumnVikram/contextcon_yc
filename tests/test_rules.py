"""B6: decision table on all 9 acceptance cases (using Person A's stubs), explanation and audit."""
import pytest

from clearance import capability, catalog, screening
from clearance.decision import RULES, audit_html, decide, explain
from clearance.enduse import check
from clearance.evidence import Ledger
from clearance.llm import FakeLLM
from clearance.models import OrderResults
from tests.fixtures.cases import CASES


def build_results(case, led):
    o = case.order
    cls = [catalog.classify(l.part_number, led) for l in o.lines]
    r = OrderResults(
        classifications=cls,
        licences=[catalog.licence(c, o.ship_to_country, led) for c in cls if c.found],
        screenings=[screening.screen(p, led) for p in o.parties],
        buyer_capability=capability.assess(o.buyer, cls, o.lines, o.ship_to_country, led),
    )
    if case.end_use:
        r.end_use = check(case.end_use, o, cls, screening.screen, capability.assess, led)
    return r


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_acceptance_case_outcome(case):
    led = Ledger()
    d = decide(case.order, build_results(case, led), led)
    assert d.outcome == case.expected, d.rule_fired
    assert all(led.has(e.id) for e in d.evidence)


def test_rule_ids_are_unique_and_end_with_release():
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids)) and ids[-1] == "R12_release"


def test_llm_unavailable_holds_instead_of_asking():
    led = Ledger()
    r = build_results(CASES[5], led)  # shell -> would be AWAITING_END_USE
    r.llm_unavailable = True
    assert decide(CASES[5].order, r, led).rule_fired == "R10_llm_unavailable"


def test_licence_documents_listed():
    led = Ledger()
    d = decide(CASES[1].order, build_results(CASES[1], led), led)
    assert d.outcome == "LICENCE_REQUIRED" and d.licence_documents


def test_explain_validates_and_falls_back():
    led = Ledger()
    d = decide(CASES[7].order, build_results(CASES[7], led), led)  # BLOCK
    good_id = d.evidence[0].id
    good = FakeLLM({"explain": {"sentences": [{"text": "The buyer matches a listed entity.", "evidence_ids": [good_id]}]}})
    assert explain(d, led, good)[0].evidence_ids == [good_id]
    bad = FakeLLM({"explain": {"sentences": [{"text": "Made up.", "evidence_ids": ["E999"]}]}})
    fallback = explain(d, led, bad)
    assert fallback[0].text.startswith("Block:") and all(led.has(i) for i in fallback[0].evidence_ids)


def test_audit_html_contains_everything():
    led = Ledger()
    case = CASES[8]
    d = decide(case.order, build_results(case, led), led)
    d.explanation = explain(d, led, FakeLLM())
    html = audit_html(case.order, d, led)
    assert "R3_fuzzy_list_hit" in html and case.order.buyer.name in html
    assert all(e.id in html for e in led.items)
