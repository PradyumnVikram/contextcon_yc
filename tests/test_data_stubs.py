"""Person A stubs honour the §5.2 contracts (task S5). Replace with real tests in A12."""
from clearance import capability, catalog, screening
from clearance.evidence import Ledger
from clearance.models import CapabilityResult, Classification, LicenceResult, Party, ScreeningResult
from tests.fixtures.cases import CASES


def test_catalog_contract():
    led = Ledger()
    known = catalog.classify("PA-77G-HE", led)
    unknown = catalog.classify("NOPE-1", led)
    assert isinstance(known, Classification) and known.found and known.needs
    assert not unknown.found and unknown.evidence_ids
    lic = catalog.licence(known, "DE", led)
    assert isinstance(lic, LicenceResult) and lic.required and lic.documents
    assert not catalog.licence(known, "IN", led).required


def test_screening_contract():
    led = Ledger()
    exact = screening.screen(Party(role="buyer", name="Listed Electronics Trading", country="AE"), led)
    fuzzy = screening.screen(Party(role="buyer", name="Listed Electronic Tradng", country="AE"), led)
    clear = screening.screen(Party(role="buyer", name="Synthetic Radar Systems", country="IN"), led)
    fwd = screening.screen(Party(role="end_user", name="Quick Freight Logistics", country="AE"), led)
    assert isinstance(exact, ScreeningResult)
    assert (exact.status, fuzzy.status, clear.status) == ("exact_hit", "fuzzy_hit", "clear")
    assert fuzzy.matches and fuzzy.matches[0].breakdown
    assert fwd.is_forwarder
    assert all(led.has(i) for r in (exact, fuzzy, clear) for i in r.evidence_ids)


def test_capability_contract():
    led = Ledger()
    for c in CASES:
        cls = [catalog.classify(l.part_number, led) for l in c.order.lines]
        res = capability.assess(c.order.buyer, cls, c.order.lines, c.order.ship_to_country, led)
        assert isinstance(res, CapabilityResult)
        assert res.evidence_ids and all(led.has(i) for i in res.evidence_ids)
    shell = capability.assess(Party(role="buyer", name="x shell y"), [], [], "AE", led)
    nodata = capability.assess(Party(role="buyer", name="x nodata y"), [], [], "IN", led)
    assert shell.tier == "high_risk" and nodata.coverage == "missing" and nodata.tier == "no_data"
