"""A11: customer registration, re-tier on webhook event, signature check, demo simulate."""
import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from clearance import config, store, watch
from clearance.models import Party
from clearance.watch import webhook

RADAR = Party(role="buyer", name="Synthetic Radar Systems", country="IN", domain="synthetic-radar.example")
EVENT = {"metadata": {"watch_id": 1, "kind": "entity", "dataset": "company"},
         "results": [{"changes": [{"field": "headcount.total", "type": "changed", "from": 180, "to": 120}],
                      "record": {"basic_info": {"name": "Synthetic Radar Systems",
                                                "primary_domain": "synthetic-radar.example"}}}]}


def _tier(conn):
    return conn.execute("SELECT tier FROM customers").fetchone()["tier"]


def test_register_and_simulate():
    conn = store.connect(":memory:")
    watch.register(conn, RADAR, "consistent")
    assert _tier(conn) == "consistent"
    watch.simulate_event(conn, RADAR, "high_risk")
    assert _tier(conn) == "high_risk"
    assert watch.simulate_event(conn, RADAR) == "consistent"   # real re-tier from (fixture) data


def test_handle_event_only_touches_known_customers():
    conn = store.connect(":memory:")
    assert watch.handle_event(conn, EVENT) == []
    watch.register(conn, RADAR, "high_risk")
    [u] = watch.handle_event(conn, EVENT)
    assert u["tier"] == "consistent" and "headcount.total" in u["changes"]


def test_webhook_endpoint_and_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "w.db")
    watch.register(store.connect(config.DB_PATH), RADAR, "high_risk")
    client = TestClient(webhook.app)
    assert client.post("/webhook/crustdata", json=EVENT).json()["updated"][0]["tier"] == "consistent"

    monkeypatch.setattr(config, "CRUSTDATA_API_KEY", "secret")
    body = json.dumps(EVENT).encode()
    sig = hmac.new(b"secret", b"123." + body, hashlib.sha256).hexdigest()
    assert client.post("/webhook/crustdata", content=body, headers={"x-crustdata-signature": "t=123,v1=bad"}).status_code == 401
    ok = client.post("/webhook/crustdata", content=body, headers={"x-crustdata-signature": f"t=123,v1={sig}",
                                                                   "content-type": "application/json"})
    assert ok.status_code == 200
