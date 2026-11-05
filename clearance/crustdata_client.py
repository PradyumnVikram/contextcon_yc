"""Throttled, cached Crustdata REST client. OWNER: Person A (task A1).

STUB (S5): signatures only. Every call must go through store.cache_get/cache_put
and always pass explicit `fields`. See AGENTS_DATA.md §5.5.
"""
from __future__ import annotations

from typing import Any

STUB = True


def enrich_company(domain_or_name: str, fields: list[str]) -> dict[str, Any] | None:
    raise NotImplementedError("A1: implement Crustdata /company/enrich")


def search_companies(filters: dict[str, Any], fields: list[str], limit: int = 50) -> list[dict[str, Any]]:
    raise NotImplementedError("A1/A8: implement Crustdata /company/search")


def search_people(company: str, fields: list[str], limit: int = 25) -> list[dict[str, Any]]:
    raise NotImplementedError("A1/A6: implement Crustdata person search (path to confirm in A2)")


def watch_company(company: str, webhook_url: str) -> str:
    raise NotImplementedError("A11: implement Crustdata company watcher")
