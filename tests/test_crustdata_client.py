"""A1: Crustdata client caching, retry, headers, fixture fallback. No network (httpx MockTransport)."""
import httpx
import pytest

from clearance import store
from clearance.crustdata_client import CrustdataClient, CrustdataError, Fixtures, norm_key


def _client(handler, fixtures=None):
    return CrustdataClient(store.connect(":memory:"), api_key="k", transport=httpx.MockTransport(handler),
                           fixtures=fixtures or Fixtures(root=__import__("pathlib").Path("/nonexistent")))


def test_enrich_live_is_cached_and_sends_headers():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=[{"matched_on": "acme.example", "matches": [
            {"confidence_score": 1, "company_data": {"basic_info": {"name": "Acme"}}}]}])

    c = _client(handler)
    assert c.enrich_company("https://www.Acme.example/about")["basic_info"]["name"] == "Acme"
    assert c.enrich_company("acme.example")["basic_info"]["name"] == "Acme"
    assert len(calls) == 1
    req = calls[0]
    assert req.headers["authorization"] == "Bearer k" and req.headers["x-api-version"] == "2025-11-01"
    body = __import__("json").loads(req.content)
    assert body["domains"] == ["acme.example"] and "headcount" in body["fields"]


def test_no_match_returns_none_and_retries_on_429(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    seq = [httpx.Response(429, headers={"retry-after": "1"}), httpx.Response(200, json=[{"matches": []}])]
    c = _client(lambda req: seq.pop(0))
    assert c.enrich_company("nobody.example") is None


def test_http_error_raises():
    c = _client(lambda req: httpx.Response(400, json={"error": {"type": "invalid_request"}}))
    with pytest.raises(CrustdataError):
        c.search_companies({"field": "x", "type": "=", "value": 1})


def test_network_timeout_is_retried_then_reported(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    seq = [httpx.ReadTimeout("slow"), httpx.Response(200, json=[{"matches": []}])]

    def handler(req):
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    assert _client(handler).enrich_company("slow.example") is None

    def always(req):
        raise httpx.ConnectTimeout("down")
    with pytest.raises(CrustdataError):
        _client(always).enrich_company("down.example")


def test_cached_answer_older_than_max_age_is_fetched_again():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=[{"matches": [{"company_data": {"basic_info": {"name": "Acme"}}}]}])
    c = _client(handler)
    c.enrich_company("acme.example")
    c.conn.execute("UPDATE api_cache SET fetched_at='2020-01-01T00:00:00+00:00'")
    c.enrich_company("acme.example")
    assert len(calls) == 2
    c.enrich_company("acme.example")
    assert len(calls) == 2 and c.fetched_at["/company/enrich"].year >= 2026


def test_offline_uses_fixtures_and_unknown_is_none():
    c = CrustdataClient(store.connect(":memory:"), api_key="")
    assert c.enrich_company("Synthetic Radar Systems")["basic_info"]["primary_domain"] == "synthetic-radar.example"
    assert len(c.search_people("synthetic-radar.example")) == 25
    assert c.enrich_company("Totally Unknown Pvt Ltd") is None
    assert c.search_people("Totally Unknown") is None


def test_norm_key():
    assert norm_key("https://www.X.com/a") == "x.com" and norm_key("Acme, Trading Co") == "acme trading"


def test_company_name_lookup_ignores_legal_suffixes():
    c = CrustdataClient(store.connect(":memory:"), api_key="")
    for name in ["Synthetic Radar Systems Pvt Ltd", "SYNTHETIC RADAR SYSTEMS PRIVATE LIMITED", "Synthetic Radar Systems, Ltd."]:
        assert c.enrich_company(name)["basic_info"]["primary_domain"] == "synthetic-radar.example", name
    assert norm_key("Acme Pvt. Ltd") == "acme" and norm_key("acme.example") == "acme.example"
