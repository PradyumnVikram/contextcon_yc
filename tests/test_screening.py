"""A5: CSL screening (sample list + synthetic demo list)."""
from clearance import screening
from clearance.evidence import Ledger
from clearance.models import Party
from clearance.screening import csl


def _s(name, country=None, role="buyer", address=None):
    return screening.screen(Party(role=role, name=name, country=country, address=address), Ledger())


def test_exact_fuzzy_clear():
    assert _s("Listed Electronics Trading", "AE").status == "exact_hit"
    fz = _s("Listed Electronic Tradng", "AE")
    assert fz.status == "fuzzy_hit" and fz.matches[0].breakdown["token_set"] > 85
    assert _s("Synthetic Radar Systems", "IN").status == "clear"


def test_exact_needs_same_country_and_suffixes_are_ignored():
    assert _s("Sample Radio Components Co., Ltd.", "CN").status == "exact_hit"
    assert _s("Sample Radio Components", "IN").status == "fuzzy_hit"   # same name, other country -> human review
    assert _s("SAMPLE RADIO COMPONENT", "CN").status == "exact_hit"    # alt name


def test_transliteration_and_forwarder():
    assert _s("Sampel Avionix", "RU").status in ("fuzzy_hit", "exact_hit")
    fwd = _s("Fast Freight Logistics LLC", "AE", role="end_user")
    assert fwd.is_forwarder and len(fwd.evidence_ids) == 2


def test_normalize():
    assert screening.normalize("ACME Pvt. Ltd.") == "acme"
    assert screening.normalize("Ünïcode & Sons Private Limited") == "unicode and sons"


def test_convert_raw_csl(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text('_id,source,type,name,addresses,alt_names\n'
                   '"1","EL","Entity","X CORP","1 Rd, Delhi, IN; 2 Rd, Dubai, AE","XC"\n'
                   '"2","SDN","Individual","JOHN DOE","Moscow, RU",""\n')
    out = tmp_path / "csl.csv"
    assert csl.convert(raw, out) == 1
    [e] = csl._read(out)
    assert e.countries == {"AE", "IN"} and e.alt_names == ["XC"]
