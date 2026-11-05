"""B7: end-to-end pipeline runs: email in -> states -> emails out -> recommendation -> sign/override.
Claude is faked; Person A's modules are their stubs."""
import pytest

from clearance import store
from clearance.llm import FakeLLM
from clearance.mail import Mailbox
from clearance.models import OrderState
from clearance.pipeline import Pipeline

ORDERS = {
    "PO radar": {"buyer_name": "Synthetic Radar Systems", "buyer_country": "IN", "ship_to_country": "IN",
                 "lines": [{"part_number": "PA-77G-HE", "quantity": 4}]},
    "PO shell": {"buyer_name": "Synthetic shell Traders", "buyer_country": "IN", "ship_to_country": "AE",
                 "lines": [{"part_number": "PA-77G-HE", "quantity": 100}]},
    "PO nodata": {"buyer_name": "Synthetic nodata Enterprises", "buyer_country": "IN", "ship_to_country": "IN",
                  "lines": [{"part_number": "ADC-12G-HE", "quantity": 10}]},
    "PO partial": {"buyer_name": "Synthetic Radar Systems", "buyer_country": "IN", "ship_to_country": None,
                   "lines": [{"part_number": "PA-77G-HE", "quantity": 4}]},
    "details": {"ship_to_country": "IN"},
}
EVASIVE = {"claimed_use": "civilian use", "mapped_needs": [], "end_user_name": None, "end_user_country": None,
           "evasive": True}
GOOD = {"claimed_use": "77 GHz automotive radar", "mapped_needs": ["radar", "rf"],
        "end_user_name": "Synthetic Radar Systems", "end_user_country": "IN", "evasive": False}


def _parse(payload):
    subj = payload["email"]["subject"]
    return next(v for k, v in ORDERS.items() if k in subj)


def make(tmp_path, extract=None, parse=_parse):
    llm = FakeLLM({"parse_order": parse, "extract_end_use": extract or []})
    conn = store.connect(":memory:")
    mb = Mailbox(tmp_path)
    return Pipeline(conn, llm, mb), mb, conn


def test_clean_order_releases_and_signing_registers_customer(tmp_path):
    p, mb, conn = make(tmp_path)
    mb.compose("buyer@radar.example", "PO radar", "4 pcs PA-77G-HE")
    [oid] = p.process_inbox()
    d = store.load_decision(conn, oid)
    assert d.outcome == "RELEASE" and store.get_state(conn, oid) is OrderState.RECOMMENDED
    states = [s for s, _ in d.state_history]
    assert states[:5] == [OrderState.EMAIL_RECEIVED, OrderState.PARSED, OrderState.CLASSIFIED,
                          OrderState.SCREENED, OrderState.CAPABILITY_CHECKED]
    p.sign(oid, "A. Officer")
    assert store.get_state(conn, oid) is OrderState.SIGNED
    assert conn.execute("SELECT tier FROM customers").fetchone()["tier"] == "consistent"
    assert "A. Officer" in p.audit(oid)


def test_shell_end_use_loop_with_one_followup_then_hold(tmp_path):
    p, mb, conn = make(tmp_path, extract=[EVASIVE, EVASIVE])
    mb.compose("x@shell.example", "PO shell", "100 pcs")
    [oid] = p.process_inbox()
    assert store.get_state(conn, oid) is OrderState.AWAITING_END_USE
    [req] = mb.outbox_messages()
    assert req.subject.startswith(f"[CLR-{oid}]")

    mb.compose("x@shell.example", f"Re: {req.subject}", "civilian use only")
    p.process_inbox()
    assert store.get_state(conn, oid) is OrderState.AWAITING_END_USE   # follow-up sent, still waiting
    assert len(mb.outbox_messages()) == 2

    mb.compose("x@shell.example", f"Re: {req.subject}", "as said, civilian")
    p.process_inbox()
    d = store.load_decision(conn, oid)
    assert (d.outcome, d.rule_fired) == ("HOLD", "R8_end_use_inconsistent")
    assert len(mb.outbox_messages()) == 2   # no third email


def test_shell_with_good_end_use_still_needs_a_licence(tmp_path):
    p, mb, conn = make(tmp_path, extract=[GOOD])
    mb.compose("x@shell.example", "PO shell", "100 pcs")
    [oid] = p.process_inbox()
    req = mb.outbox_messages()[0]
    mb.compose("x@shell.example", f"Re: {req.subject}", "radar")
    p.process_inbox()
    d = store.load_decision(conn, oid)
    assert (d.outcome, d.rule_fired) == ("HOLD", "R9b_buyer_cannot_use_quantity")


def test_no_data_holds_and_asks_and_never_auto_releases(tmp_path):
    p, mb, conn = make(tmp_path, extract=[GOOD])
    mb.compose("n@nodata.example", "PO nodata", "10 pcs")
    [oid] = p.process_inbox()
    d = store.load_decision(conn, oid)
    assert (d.outcome, d.rule_fired) == ("HOLD", "R6_no_or_thin_coverage")
    req = mb.outbox_messages()[0]
    mb.compose("n@nodata.example", f"Re: {req.subject}", "radar for Synthetic Radar Systems")
    p.process_inbox()
    d = store.load_decision(conn, oid)
    assert d.outcome == "HOLD" and any(e.source.startswith("email:") for e in d.evidence)


def test_missing_details_round_trip(tmp_path):
    p, mb, conn = make(tmp_path)
    mb.compose("buyer@radar.example", "PO partial", "4 pcs, destination TBD")
    [oid] = p.process_inbox()
    assert store.get_state(conn, oid) is OrderState.AWAITING_ORDER_DETAILS
    ask = mb.outbox_messages()[0]
    mb.compose("buyer@radar.example", f"Re: {ask.subject} details", "Deliver in India")
    p.process_inbox()
    assert store.load_order(conn, oid).ship_to_country == "IN"
    assert store.load_decision(conn, oid).outcome == "RELEASE"


def test_llm_down_holds(tmp_path):
    p, mb, conn = make(tmp_path, parse=None)
    mb.compose("b@x.example", "PO radar", "...")
    [oid] = p.process_inbox()
    assert store.load_decision(conn, oid).rule_fired == "R10_llm_unavailable"


def test_override_needs_reason_and_is_audited(tmp_path):
    p, mb, conn = make(tmp_path)
    mb.compose("b@x.example", "PO nodata", "...")
    [oid] = p.process_inbox()
    with pytest.raises(ValueError):
        p.override(oid, "RELEASE", "A. Officer", "")
    d = p.override(oid, "RELEASE", "A. Officer", "Known customer, verified offline")
    assert d.override.original_rule == "R6_no_or_thin_coverage" and d.outcome == "RELEASE"
    with pytest.raises(ValueError):
        p.sign("nonexistent", "x")
    p.sign(oid, "A. Officer")
    assert "Known customer" in p.audit(oid)


def test_unmatched_tagged_reply_is_kept(tmp_path):
    p, mb, conn = make(tmp_path)
    mb.compose("b@x.example", "Re: [CLR-O9999] hello", "...")
    assert p.process_inbox() == []
    assert conn.execute("SELECT COUNT(*) n FROM emails WHERE order_id IS NULL").fetchone()["n"] == 1
