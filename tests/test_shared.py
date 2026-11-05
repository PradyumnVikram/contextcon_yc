"""Shared layer: models, ledger, store (tasks S2-S4)."""
from clearance import store
from clearance.evidence import Ledger
from clearance.models import Decision, Email, OrderState
from tests.fixtures.cases import CASES


def test_ledger_issues_sequential_ids_and_flags_unknown():
    led = Ledger()
    a = led.add("x", 1, "test:a")
    b = led.add("y", 2, "test:b")
    assert (a, b) == ("E1", "E2")
    assert led.get("E2").value == 2
    assert led.unknown_ids(["E1", "E9"]) == ["E9"]


def test_all_acceptance_cases_are_valid_orders():
    assert len(CASES) == 9
    for c in CASES:
        assert c.order.buyer.name
        assert c.expected in {"RELEASE", "HOLD", "LICENCE_REQUIRED", "BLOCK", "AWAITING_END_USE"}


def test_store_roundtrip():
    conn = store.connect(":memory:")
    order = CASES[0].order
    store.save_order(conn, order, OrderState.PARSED)
    store.set_state(conn, order.order_id, OrderState.CLASSIFIED)
    assert store.load_order(conn, order.order_id) == order
    assert store.get_state(conn, order.order_id) is OrderState.CLASSIFIED
    assert [s for s, _ in store.get_state_history(conn, order.order_id)] == [OrderState.PARSED, OrderState.CLASSIFIED]

    led = Ledger()
    led.add("claim", {"k": 1}, "test:src")
    store.save_evidence(conn, order.order_id, led.items)
    assert store.load_evidence(conn, order.order_id)[0].value == {"k": 1}

    dec = Decision(order_id=order.order_id, outcome="HOLD", rule_fired="R2_unknown_part")
    store.save_decision(conn, dec)
    assert store.load_decision(conn, order.order_id).outcome == "HOLD"

    store.save_email(conn, Email(msg_id="m1", from_addr="a@x", to_addr="b@y", subject="s", body="b"), "in")


def test_api_cache_hit_and_miss():
    conn = store.connect(":memory:")
    assert store.cache_get(conn, "/company/enrich", {"domain": "x.com"}) is None
    store.cache_put(conn, "/company/enrich", {"domain": "x.com"}, {"headcount": 5})
    assert store.cache_get(conn, "/company/enrich", {"domain": "x.com"}) == {"headcount": 5}
    # key is order-independent
    assert store.cache_key("e", {"a": 1, "b": 2}) == store.cache_key("e", {"b": 2, "a": 1})
