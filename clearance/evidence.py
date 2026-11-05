"""Evidence ledger: the only way modules record facts. SHARED FILE."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from clearance.models import Evidence


class Ledger:
    """Issues sequential evidence IDs (E1, E2, ...) for one order."""

    def __init__(self, items: Iterable[Evidence] = ()) -> None:
        self._items: dict[str, Evidence] = {}
        for ev in items:
            self._items[ev.id] = ev
        self._next = len(self._items) + 1

    def add(self, claim: str, value: Any, source: str, fetched_at: datetime | None = None) -> str:
        eid = f"E{self._next}"
        self._next += 1
        self._items[eid] = Evidence(id=eid, claim=claim, value=value, source=source, fetched_at=fetched_at)
        return eid

    def get(self, eid: str) -> Evidence:
        return self._items[eid]

    def has(self, eid: str) -> bool:
        return eid in self._items

    def unknown_ids(self, ids: Iterable[str]) -> list[str]:
        return [i for i in ids if i not in self._items]

    @property
    def items(self) -> list[Evidence]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
