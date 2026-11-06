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


def test_extra_sanctions_list_is_screened(tmp_path, monkeypatch):
    extra = tmp_path / "extra.csv"
    extra.write_text(
        "id,source,name,alt_names,addresses,countries\n"
        'UN-1,UN Security Council Consolidated List,ACME SANCTIONED TRADING,,"Dubai, AE",AE\n'
    )
    monkeypatch.setattr(csl, "EXTRA_CSV", extra)
    screening.reload()
    assert _s("Acme Sanctioned Trading LLC", "AE").status == "exact_hit"


def test_listed_address_is_its_own_hit():
    # a specific listed address (with its office number) is a hit even under a new name, but an address alone
    # is a close match for the officer to compare, never an exact hit (exact needs the name, per AGENTS §4.2)
    hit = _s("Independent Buyer", "AE", address="Office 12, Demo Tower, Dubai")
    assert hit.status == "fuzzy_hit"
    assert hit.matches[0].listed_record.get("address_match")


def test_a_generic_area_address_does_not_match_every_buyer_there():
    # the listed entry's address is only "Jebel Ali Free Zone, Dubai": thousands of real companies are there
    for addr in ["Warehouse 14, Jebel Ali Free Zone, Dubai, UAE", "Plot S10, Jebel Ali Free Zone, Dubai"]:
        assert _s("Independent Buyer", "AE", address=addr).status == "clear", addr


def test_a_different_unit_number_is_not_the_same_address():
    assert _s("Independent Buyer", "AE", address="Office 47, Demo Tower, Dubai").status == "clear"


def test_indian_buyer_records_that_iec_was_not_checked():
    led = Ledger()
    screening.screen(Party(role="buyer", name="Synthetic Radar Systems", country="IN"), led)
    assert any(e.source == "dgft:iec" for e in led.items)


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


def test_one_word_listed_name_does_not_flag_longer_company_names():
    # a listed entity called just "NOVA" must not flag every company with "Nova" in its name
    assert _s("Nova Microwave Products Limited", "IN").status == "clear"
    assert _s("Nova", "RU").status == "exact_hit"
