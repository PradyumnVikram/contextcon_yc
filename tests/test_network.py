"""Cross-order network: linked buyers, what they build together, and staff from listed entities. Offline (fixtures)."""
from datetime import timedelta

from clearance import capability, catalog, network, screening, store
from clearance.evidence import Ledger
from clearance.models import Order, OrderLine, Party, utcnow

RING = [("Synthetic Orbit Electronics", "orbit-electronics.example", "PA-77G-HE"),
        ("Synthetic Nimbus Instruments", "nimbus-instruments.example", "LNA-77G-HE"),
        ("Synthetic Delta Systems", "delta-systems.example", "ADC-12G-HE")]


def _order(oid, name, domain, part, qty=6, ship_to="AE", shipper=None, created=None):
    parties = [Party(role="buyer", name=name, country="IN", domain=domain),
               Party(role="ship_to", name=name, country=ship_to)]
    if shipper:
        parties.append(Party(role="shipper", name=shipper, country="AE"))
    o = Order(order_id=oid, parties=parties, lines=[OrderLine(part_number=part, quantity=qty)], ship_to_country=ship_to)
    if created:
        o.created_at = created
    return o


def _run(conn, order, body=""):
    """What the pipeline does: capability (fills the people cache), then record + analyse."""
    led = Ledger()
    cls = [catalog.classify(l.part_number, led) for l in order.lines]
    capability.assess(order.buyer, cls, order.lines, order.ship_to_country, led)
    network.record(conn, order, cls, body)
    return network.analyse(conn, order, screening.screen, led), led


def test_ring_is_linked_by_a_shared_director_and_caught_on_the_third_order(offline):
    conn = offline.conn
    results = [_run(conn, _order(f"R{i}", n, d, p))[0] for i, (n, d, p) in enumerate(RING, 1)]
    first, second, third = results
    assert not any(s.flagged for s in first.systems + second.systems)          # nothing visible yet
    assert set(third.linked_companies) == {"Synthetic Orbit Electronics", "Synthetic Nimbus Instruments"}
    assert {l.kind for l in third.links} == {"person"} and "Rakesh Varma" in third.links[0].value
    [seeker] = [s for s in third.systems if s.system == "Radar seeker front-end"]
    assert seeker.flagged and not seeker.fits_business
    assert seeker.coverage == 0.75 and seeker.functions_missing == ["fpga|rad_hard_fpga"]
    assert set(seeker.orders) == {"R1", "R2", "R3"}


def test_known_radar_maker_buying_the_same_set_is_not_flagged(offline):
    conn = offline.conn
    for i, part in enumerate(["PA-77G-HE", "LNA-77G-HE", "ADC-12G-HE"], 1):
        res, _ = _run(conn, _order(f"S{i}", "Synthetic Radar Systems", "synthetic-radar.example", part, qty=4, ship_to="IN"))
    [seeker] = [s for s in res.systems if s.system == "Radar seeker front-end"]
    assert seeker.fits_business and not seeker.flagged


def test_a_common_forwarder_does_not_link_unrelated_buyers(offline):
    conn = offline.conn
    names = ["Alpha Optics", "Beta Motors", "Gamma Labs", "Delta Foods", "Epsilon Textiles", "Zeta Pumps"]
    for i, n in enumerate(names):
        res, _ = _run(conn, _order(f"F{i}", n, None, "FPGA-C10", qty=10, shipper="DHL Express"))
    assert res.linked_companies == []


def test_two_buyers_sharing_a_small_forwarder_and_address_are_linked(offline):
    conn = offline.conn
    for i, n in enumerate(["Kappa Traders", "Lambda Exports"]):
        o = _order(f"K{i}", n, None, "FPGA-C10", qty=10, shipper="Swift Cargo FZE")
        o.parties[1].address = "Warehouse 14, Jebel Ali Free Zone, Dubai"
        res, _ = _run(conn, o, body="Call +971 50 123 4567")
    assert res.linked_companies == ["Kappa Traders"]
    assert {l.kind for l in res.links} == {"forwarder", "address", "phone"}
    assert {l.value for l in res.links if l.kind == "forwarder"} == {"Swift Cargo FZE"}   # shown as written


def test_old_orders_outside_the_window_do_not_count(offline):
    conn = offline.conn
    old = utcnow() - timedelta(days=400)
    _run(conn, _order("O1", *RING[0][:2], RING[0][2], created=old))
    _run(conn, _order("O2", *RING[1][:2], RING[1][2], created=old))
    res, _ = _run(conn, _order("O3", *RING[2][:2], RING[2][2]))
    assert not any(s.flagged for s in res.systems)


def test_staff_from_a_listed_entity_is_found(offline):
    res, led = _run(offline.conn, _order("A1", "Synthetic Apex Components", "apex-components.example", "FPGA-C10", ship_to="IN"))
    [hit] = res.listed_staff
    assert hit.person == "Imran Qureshi" and "PROHIBITED MICROWAVE" in hit.listed_name.upper()
    assert all(led.has(i) for i in res.evidence_ids)
