"""A4: catalog lookup and licence rules."""
from clearance import catalog
from clearance.evidence import Ledger


def test_known_and_unknown_parts():
    led = Ledger()
    c = catalog.classify("pa-77g-he", led)
    assert c.found and c.controlled and c.us_origin and c.part_class == "high_end" and "radar" in c.needs
    assert led.get(c.evidence_ids[0]).source.startswith("catalog:row/")
    miss = catalog.classify("NOT-A-PART", led)
    assert not miss.found and led.get(miss.evidence_ids[0]).source == "catalog:miss"


def test_licence_rules():
    led = Ledger()
    pa = catalog.classify("PA-77G-HE", led)
    india = catalog.licence(pa, "IN", led)
    assert not india.required and "in-country transfer" in india.reason
    de = catalog.licence(pa, "DE", led)
    assert de.required and "SCOMET authorisation application (DGFT)" in de.documents
    cn = catalog.licence(pa, "CN", led)
    assert cn.required and "EAR" in cn.reason and "SCOMET" in cn.reason
    assert not catalog.licence(catalog.classify("FPGA-C10", led), "DE", led).required
    indian = catalog.classify("RF-TRX-IN", led)
    assert catalog.licence(indian, "AE", led).required and "EAR" not in catalog.licence(indian, "AE", led).reason
