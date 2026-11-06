"""Throttled, cached Crustdata REST client (task A1). OWNER: Person A.

Endpoints and shapes are from docs.crustdata.com (API version 2025-11-01); see AGENTS_DATA.md §5.5.
- Every request is cached in store.api_cache (key = endpoint + request body); a repeat never hits the network.
- Client-side throttle per endpoint (enrich 15/min, search 30/min, watch 10/min) + retry with backoff on 429/5xx.
- Demo companies are synthetic (ethics rule), so they are served from data/demo_crustdata/*.json fixtures.
  Live calls happen only when CRUSTDATA_API_KEY is set; with no key, unknown companies return None (= no data).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clearance import config, store

log = logging.getLogger(__name__)

FIXTURES_DIR = config.DATA_DIR / "demo_crustdata"

ENRICH_FIELDS = ["basic_info", "headcount", "taxonomy", "locations", "web_traffic", "hiring", "news"]
PEER_FIELDS = ["basic_info", "headcount", "taxonomy", "locations"]   # /company/search rejects web_traffic (live, 2026-11-06)
PEER_ENRICH_FIELDS = ["basic_info", "headcount", "web_traffic"]
PERSON_FIELDS = [
    "crustdata_person_id",
    "basic_profile.name",
    "basic_profile.current_title",
    "experience.employment_details.current.function_category",
    "experience.employment_details.current.seniority_level",
    "experience.employment_details.past",
    "skills.professional_network_skills",
]

RATE_PER_MIN = {"/company/enrich": 15, "/company/search": 30, "/person/search": 30, "/watch/company": 10}


class CrustdataError(RuntimeError):
    pass


_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


_LEGAL_SUFFIX_RE = re.compile(
    r"\b(pvt|private|ltd|limited|llc|inc|incorporated|co|company|corp|corporation|plc|gmbh|fze|fzco|llp|lp)\b")


def norm_key(s: str) -> str:
    """Normalised company key: bare lowercase domain, or lowercase alphanumeric name without legal suffixes
    ("Acme Pvt. Ltd" and "ACME PRIVATE LIMITED" both -> "acme")."""
    s = s.strip().lower()
    d = re.sub(r"^https?://", "", s).removeprefix("www.").split("/")[0]
    if _DOMAIN_RE.match(d):
        return d
    name = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(_LEGAL_SUFFIX_RE.sub(" ", name).split()) or " ".join(name.split())


def is_domain(key: str) -> bool:
    return bool(_DOMAIN_RE.match(key))


class _Throttle:
    def __init__(self) -> None:
        self._calls: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def wait(self, endpoint: str) -> None:
        limit = RATE_PER_MIN.get(endpoint, 10)
        with self._lock:
            q = self._calls.setdefault(endpoint, deque())
            now = time.monotonic()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                sleep = 60 - (now - q[0]) + 0.05
                log.info("throttling %s for %.1fs", endpoint, sleep)
                time.sleep(sleep)
            q.append(time.monotonic())


class Fixtures:
    """Synthetic demo data in Crustdata's response shapes."""

    def __init__(self, root: Path = FIXTURES_DIR) -> None:
        load = lambda n: json.loads((root / n).read_text()) if (root / n).exists() else {}
        companies = load("companies.json")
        self.companies: dict[str, dict] = {}
        for c in companies.values():
            bi = c.get("basic_info", {})
            for k in [bi.get("primary_domain"), bi.get("name")]:
                if k:
                    self.companies[norm_key(k)] = c
        self.people: dict[str, list[dict]] = {norm_key(k): v for k, v in load("people.json").items()}
        self.peers: dict[str, list[dict]] = load("peers.json")

    def company(self, key: str) -> dict | None:
        return self.companies.get(norm_key(key))

    def company_people(self, key: str) -> list[dict] | None:
        c = self.company(key)
        if c is None:
            return None
        dom = norm_key(c["basic_info"].get("primary_domain") or c["basic_info"]["name"])
        return self.people.get(dom, [])

    def peer_set(self, industry: str | None) -> list[dict] | None:
        return self.peers.get(industry or "")


class CrustdataClient:
    @classmethod
    def open(cls, path: str | Path, **kw) -> "CrustdataClient":
        """Own connection usable from any thread (Streamlit and FastAPI call from worker threads)."""
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(store.SCHEMA)
        return cls(conn, **kw)

    def __init__(self, conn: sqlite3.Connection, api_key: str | None = None, transport: Any = None,
                 fixtures: Fixtures | None = None, max_retries: int = 3) -> None:
        self.conn = conn
        self.api_key = config.CRUSTDATA_API_KEY if api_key is None else api_key
        self.fixtures = fixtures if fixtures is not None else Fixtures()
        self.max_retries = max_retries
        self._transport = transport
        self._http = None
        self._throttle = _Throttle()
        self.fetched_at: dict[str, datetime | None] = {}   # endpoint -> when the last answer was fetched

    @property
    def live(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------ HTTP
    def _client(self):
        if self._http is None:
            import httpx
            self._http = httpx.Client(
                base_url=config.CRUSTDATA_BASE_URL, timeout=60.0, transport=self._transport,
                headers={"authorization": f"Bearer {self.api_key}", "x-api-version": config.CRUSTDATA_API_VERSION,
                         "content-type": "application/json"})
        return self._http

    def post(self, endpoint: str, body: dict[str, Any], cache: bool = True) -> Any:
        if cache and (hit := store.cache_get(self.conn, endpoint, body, config.CRUSTDATA_MAX_AGE_DAYS)) is not None:
            self.fetched_at[endpoint] = store.cache_fetched_at(self.conn, endpoint, body)
            return hit
        self.fetched_at[endpoint] = datetime.now(timezone.utc)
        if not self.live:
            raise CrustdataError("CRUSTDATA_API_KEY not set")
        import httpx
        resp = None
        for attempt in range(self.max_retries + 1):
            self._throttle.wait(endpoint.split("/{")[0] if "{" in endpoint else endpoint)
            try:
                resp = self._client().post(endpoint, json=body)
            except httpx.TransportError as e:   # timeout, DNS, connection reset: retried, then reported
                resp = None
                log.warning("crustdata %s -> %s (attempt %d)", endpoint, type(e).__name__, attempt + 1)
                if attempt == self.max_retries:
                    raise CrustdataError(f"{endpoint} -> network error after {attempt + 1} tries: {e}") from e
                time.sleep(min(2 ** attempt, 10))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = float(resp.headers.get("retry-after") or 2 ** attempt)
                log.warning("crustdata %s -> %s, retry in %.0fs", endpoint, resp.status_code, delay)
                time.sleep(min(delay, 60))
                continue
            break
        if resp.status_code == 404:
            data: Any = None
        elif resp.status_code >= 400:
            raise CrustdataError(f"{endpoint} -> {resp.status_code}: {resp.text[:300]}")
        else:
            data = resp.json()
        if cache:
            store.cache_put(self.conn, endpoint, body, data)
        return data

    # ------------------------------------------------------------------ endpoints
    def enrich_company(self, key: str, fields: list[str] = ENRICH_FIELDS) -> dict | None:
        """company_data dict for a domain or name, or None when Crustdata has no record."""
        if (fx := self.fixtures.company(key)) is not None:
            return fx
        if not self.live:
            return None
        k = norm_key(key)
        body = {"domains" if is_domain(k) else "names": [k], "fields": fields}
        data = self.post("/company/enrich", body)
        if not data:
            return None
        matches = (data[0] or {}).get("matches") or []
        return matches[0]["company_data"] if matches else None

    def enrich_companies(self, domains: list[str], fields: list[str] = PEER_ENRICH_FIELDS) -> dict[str, dict]:
        """ONE batched enrich request for several domains -> {domain: company_data}. Missing ones are left out."""
        doms = sorted({norm_key(d) for d in domains if d and is_domain(norm_key(d))})
        if not doms or not self.live:
            return {}
        data = self.post("/company/enrich", {"domains": doms, "fields": fields}) or []
        out = {}
        for entry in data:
            matches = (entry or {}).get("matches") or []
            if matches:
                cd = matches[0]["company_data"]
                out[norm_key((cd.get("basic_info") or {}).get("primary_domain") or entry.get("matched_on") or "")] = cd
        return out

    def search_companies(self, filters: dict[str, Any], fields: list[str] = PEER_FIELDS, limit: int = 50,
                         fixture_industry: str | None = None) -> list[dict]:
        if fixture_industry is not None and (fx := self.fixtures.peer_set(fixture_industry)) is not None:
            return fx[:limit]
        if not self.live:
            return []
        data = self.post("/company/search", {"filters": filters, "fields": fields, "limit": limit}) or {}
        return data.get("companies", [])

    def search_people(self, company_key: str, fields: list[str] = PERSON_FIELDS, limit: int = 25) -> list[dict] | None:
        """Up to `limit` current employees. None = company unknown to the source."""
        fx = self.fixtures.company_people(company_key)
        if fx is not None:
            return fx[:limit]
        if not self.live:
            return None
        k = norm_key(company_key)
        field = ("experience.employment_details.current.company_website_domain" if is_domain(k)
                 else "experience.employment_details.current.company_name")
        # seniority_level is filterable but not a legal sort; sending it makes the live call 400.
        body = {"filters": {"field": field, "type": "=", "value": k}, "fields": fields, "limit": limit}
        data = self.post("/person/search", body) or {}
        return data.get("profiles", [])

    def watch_company(self, domain: str, webhook_url: str) -> str | None:
        if not self.live or not webhook_url:
            return None
        body = {"entities": {"domains": [norm_key(domain)]},
                "track": {"op": "or", "conditions": [{"field": "headcount.total", "type": "changed"},
                                                     {"field": "basic_info.name", "type": "changed"},
                                                     {"field": "locations.country", "type": "changed"}]},
                "config": {"trigger": {"type": "interval", "every_hours": 24}},
                "fields": ENRICH_FIELDS,
                "notifications": [{"type": "webhook", "url": webhook_url}]}
        data = self.post("/watch/company", body, cache=False) or {}
        return str(data.get("id")) if data.get("id") is not None else None

    def invalidate(self, company_key: str) -> None:
        """Forget cached data for one company (after a watcher event)."""
        k = norm_key(company_key)
        self.conn.execute("DELETE FROM people WHERE company_key=?", (k,))
        self.conn.execute("DELETE FROM peers WHERE company_key=?", (k,))
        self.conn.execute("DELETE FROM api_cache WHERE endpoint IN ('/company/enrich','/person/search') "
                          "AND request_json LIKE ?", (f"%{k}%",))
        self.conn.commit()


_default: CrustdataClient | None = None


def get_client() -> CrustdataClient:
    global _default
    if _default is None:
        _default = CrustdataClient.open(config.DB_PATH)
    return _default


def set_client(client: CrustdataClient | None) -> None:
    """Tests and the watcher can swap the module-wide client."""
    global _default
    _default = client


def _check(domain: str = "stripe.com") -> int:
    """`python -m clearance.crustdata_client [domain]`: verify the key, show credits, make ONE cached enrich (~2 credits)."""
    import httpx
    c = get_client()
    if not c.live:
        print("CRUSTDATA_API_KEY is not set (check .env). Only synthetic demo fixtures are available.")
        return 1
    h = {"authorization": f"Bearer {c.api_key}", "x-api-version": config.CRUSTDATA_API_VERSION}
    r = httpx.get(config.CRUSTDATA_BASE_URL + "/account/credits", headers=h, timeout=30)
    if r.status_code != 200:
        print(f"key rejected: /account/credits -> {r.status_code} {r.text[:200]}")
        return 1
    print(f"key OK. credits: {r.json()['account']['credits']:,.0f}")
    from clearance.capability.profile import parse_company
    cd = c.enrich_company(domain)
    if cd is None:
        print(f"enrich {domain}: no match")
        return 1
    p = parse_company(cd)
    print(f"enrich {domain}: {p.name} | {p.industry} | {p.country} | founded {p.year_founded} | "
          f"headcount {p.headcount} | engineering share {p.engineering_share} | visitors/month {p.monthly_visitors}")
    print("(cached: running this again costs nothing)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_check(*sys.argv[1:2]))
