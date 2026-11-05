"""B4: end-use extraction and consistency rules, with Person A's stub screen/assess injected."""
from clearance import capability, catalog, screening
from clearance.enduse import check, draft_followup, draft_request, extract
from clearance.evidence import Ledger
from clearance.llm import FakeLLM
from clearance.models import Email, EndUseClaim
from tests.fixtures.cases import CASES

ORDER = CASES[5].order  # shell, 100 x high-end RF amplifier


def _cls(led):
    return [catalog.classify(l.part_number, led) for l in ORDER.lines]


def _check(claim, led=None):
    led = led or Ledger()
    return check(claim, ORDER, _cls(led), screening.screen, capability.assess, led)


def test_extract_filters_needs_to_vocab_and_records_evidence():
    led = Ledger()
    llm = FakeLLM({"extract_end_use": {"claimed_use": "radar front-end", "mapped_needs": ["radar", "made_up"],
                                       "end_user_name": "Synthetic Radar Systems", "end_user_country": "in",
                                       "evasive": False}})
    claim = extract(Email(msg_id="<r>", from_addr="", to_addr="", subject="", body="..."), _cls(led), llm, led)
    assert claim.mapped_needs == ["radar"] and claim.end_user_country == "IN"
    assert any(e.source == "email:<r>" for e in led.items)


def test_consistent_reply():
    res = _check(EndUseClaim(claimed_use="77 GHz automotive radar", mapped_needs=["radar", "rf"],
                             end_user_name="Synthetic Radar Systems", end_user_country="IN"))
    assert res.consistent, res.reasons


def test_vague_evasive_and_listed_end_user_are_inconsistent():
    assert not _check(EndUseClaim(claimed_use="civilian use", evasive=True)).consistent
    listed = _check(EndUseClaim(claimed_use="radar", mapped_needs=["radar"],
                                end_user_name="Listed Electronics Trading", end_user_country="AE"))
    assert not listed.consistent and any("exact_hit" in r for r in listed.reasons)
    fwd = _check(EndUseClaim(claimed_use="radar", mapped_needs=["radar"], end_user_name="Fast Freight Logistics"))
    assert any("forwarder" in r for r in fwd.reasons)


def test_drafts_carry_tag_with_template_fallback():
    req = draft_request(ORDER, FakeLLM())
    fol = draft_followup(ORDER, ["no end user named"], FakeLLM())
    assert req.subject.startswith("[CLR-C6]") and fol.subject.startswith("[CLR-C6]")
    assert "organisation that will use the parts" in fol.body


def test_vague_use_with_filler_words_is_still_vague():
    res = _check(EndUseClaim(claimed_use="Civilian use only", mapped_needs=[], end_user_name="Synthetic Radar Systems",
                             end_user_country="IN"))
    assert "claimed use is blank or vague" in res.reasons


def test_generic_end_user_placeholder_counts_as_not_named():
    led = Ledger()
    llm = FakeLLM({"extract_end_use": {"claimed_use": "civilian use only", "mapped_needs": [],
                                       "end_user_name": "our customer", "end_user_country": "", "evasive": False}})
    claim = extract(Email(msg_id="<r>", from_addr="", to_addr="", subject="", body="..."), _cls(led), llm, led)
    assert claim.end_user_name is None and claim.end_user_country is None
    assert "no end user named" in _check(claim).reasons


def test_end_use_request_subject_is_never_just_the_tag():
    bare = FakeLLM({"draft_email": {"subject": "[CLR-C6]", "body": "Please describe the end use."}})
    req = draft_request(ORDER, bare)
    assert req.subject.startswith("[CLR-C6] ") and "end-use" in req.subject.lower()
