"""B3: mailbox round-trip, order parsing, missing-details merge, reply matching."""
from clearance import store
from clearance.evidence import Ledger
from clearance.llm import FakeLLM
from clearance.mail import Mailbox, match_reply, merge_details, missing_details_email, parse_order, tag
from clearance.models import Email, Incomplete, Order

FULL = {"buyer_name": "Synthetic Radar Systems", "buyer_country": "in", "ship_to_country": "IN",
        "lines": [{"part_number": "PA-77G-HE", "quantity": 4}], "stated_purpose": "radar test bench"}


def test_mailbox_roundtrip_and_poll(tmp_path):
    mb = Mailbox(tmp_path)
    conn = store.connect(":memory:")
    sent = mb.compose("buyer@x.example", "PO 17", "Need 4 pcs PA-77G-HE")
    new = mb.poll(conn)
    assert [e.msg_id for e in new] == [sent.msg_id]
    assert new[0].body == "Need 4 pcs PA-77G-HE"
    store.save_email(conn, new[0], "in")
    assert mb.poll(conn) == []
    out = mb.send("buyer@x.example", f"{tag('7')} hello", "body", in_reply_to=sent.msg_id)
    assert mb.outbox_messages()[0].in_reply_to == sent.msg_id == out.in_reply_to


def test_parse_complete_order_records_evidence():
    led = Ledger()
    email = Email(msg_id="<m1>", from_addr="b@x", to_addr="c@y", subject="PO", body="...")
    order = parse_order(email, "7", FakeLLM({"parse_order": FULL}), led)
    assert isinstance(order, Order)
    assert order.buyer.country == "IN"  # normalised to upper case
    assert order.party("ship_to").name == "Synthetic Radar Systems"
    assert all(e.source == "email:<m1>" for e in led.items) and len(led) >= 4


def test_missing_fields_then_merge_from_reply():
    led = Ledger()
    partial_resp = {**FULL, "ship_to_country": None}
    email = Email(msg_id="<m1>", from_addr="b@x", to_addr="c@y", subject="PO", body="...")
    res = parse_order(email, "7", FakeLLM({"parse_order": partial_resp}), led)
    assert isinstance(res, Incomplete) and res.missing_fields == ["ship_to_country"]

    draft = missing_details_email("7", res.missing_fields, FakeLLM())  # LLM down -> template
    assert draft.subject.startswith("[CLR-7]") and "destination country" in draft.body

    reply = Email(msg_id="<m2>", from_addr="b@x", to_addr="c@y", subject="Re: [CLR-7] details", body="Ship to UAE")
    merged = merge_details(res.partial, reply, "7", FakeLLM({"parse_order": {"ship_to_country": "AE"}}), led)
    assert isinstance(merged, Order) and merged.ship_to_country == "AE"


def test_ambiguous_required_field_counts_as_missing():
    res = parse_order(Email(msg_id="<m>", from_addr="", to_addr="", subject="", body=""), "8",
                      FakeLLM({"parse_order": {**FULL, "ambiguous_fields": ["lines"]}}), Ledger())
    assert isinstance(res, Incomplete) and res.missing_fields == ["lines"]


def test_match_reply_by_tag_and_in_reply_to():
    conn = store.connect(":memory:")
    assert match_reply(Email(msg_id="a", from_addr="", to_addr="", subject="Re: [CLR-C6] End-use", body="")) == "C6"
    ours = Email(msg_id="<ours>", from_addr="", to_addr="", subject="no tag", body="")
    store.save_email(conn, ours, "out", order_id="C9")
    reply = Email(msg_id="<r>", from_addr="", to_addr="", subject="Re: hello", body="", in_reply_to="<ours>")
    assert match_reply(reply, conn) == "C9"
    assert match_reply(Email(msg_id="z", from_addr="", to_addr="", subject="hi", body=""), conn) is None


def test_sender_corporate_domain_identifies_buyer_when_no_website_given():
    led = Ledger()
    corp = Email(msg_id="<m>", from_addr="Procurement <procurement@astramwp.com>", to_addr="c@y", subject="PO", body="...")
    order = parse_order(corp, "9", FakeLLM({"parse_order": FULL}), led)
    assert order.buyer.domain == "astramwp.com"
    assert any(e.claim.startswith("Buyer domain taken from sender address") for e in led.items)

    free = Email(msg_id="<n>", from_addr="someone@gmail.com", to_addr="c@y", subject="PO", body="...")
    assert parse_order(free, "10", FakeLLM({"parse_order": FULL}), Ledger()).buyer.domain is None

    stated = Email(msg_id="<o>", from_addr="a@astramwp.com", to_addr="c@y", subject="PO", body="...")
    o = parse_order(stated, "11", FakeLLM({"parse_order": {**FULL, "buyer_website": "www.other.example"}}), Ledger())
    assert o.buyer.domain == "www.other.example"     # a website stated in the email wins


def test_drafted_subject_is_never_just_the_tag():
    bare = FakeLLM({"draft_email": {"subject": "[CLR-7]", "body": "Please send the destination country."}})
    d = missing_details_email("7", ["ship_to_country"], bare)
    assert d.subject.startswith("[CLR-7] ") and len(d.subject) > len("[CLR-7] ") + 5
    assert d.body == "Please send the destination country."      # the model's body is kept


def test_relative_paths_in_env_resolve_to_the_repo(monkeypatch):
    import importlib

    from clearance import config
    monkeypatch.setenv("CLEARANCE_MAILBOX", "mailbox")
    monkeypatch.setenv("CLEARANCE_DB", "clearance.db")
    cfg = importlib.reload(config)
    try:
        assert cfg.MAILBOX_DIR.is_absolute() and cfg.MAILBOX_DIR == cfg.ROOT / "mailbox"
        assert cfg.DB_PATH.is_absolute() and cfg.DB_PATH == cfg.ROOT / "clearance.db"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
