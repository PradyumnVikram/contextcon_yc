"""Restricted-party screening against the US CSL. OWNER: Person A (task A5).

STUB (S5): a three-entry fake list and difflib scoring. Replace with the CSL
loader, normaliser, blocking and rapidfuzz scorer. Keep the signature.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from clearance import config
from clearance.evidence import Ledger
from clearance.models import Match, Party, ScreeningResult

STUB = True

_FAKE_LIST = [
    {"id": "stub-1", "name": "Listed Electronics Trading", "country": "AE"},
    {"id": "stub-2", "name": "Prohibited Microwave Systems", "country": "IN"},
]


def _norm(name: str) -> str:
    n = name.lower()
    for s in config.NAME_SUFFIXES:
        n = n.replace(s, "")
    return " ".join(n.replace(".", " ").replace(",", " ").split())


def screen(party: Party, ledger: Ledger) -> ScreeningResult:
    best: Match | None = None
    for entry in _FAKE_LIST:
        score = 100 * SequenceMatcher(None, _norm(party.name), _norm(entry["name"])).ratio()
        if best is None or score > best.score:
            best = Match(csl_entry_id=entry["id"], listed_name=entry["name"], score=round(score, 1),
                         breakdown={"name": round(score, 1)}, listed_record=entry)
    status = "clear"
    if best and best.score >= config.SCREEN_EXACT_SCORE and best.listed_record.get("country") == party.country:
        status = "exact_hit"
    elif best and best.score >= config.SCREEN_FUZZY_SCORE:
        status = "fuzzy_hit"
    is_forwarder = any(k in party.name.lower() for k in config.FORWARDER_KEYWORDS)
    matches = [best] if best and status != "clear" else []
    eid = ledger.add(f"CSL screening of {party.role} '{party.name}': {status}",
                     best.model_dump() if matches else None, f"csl:{best.csl_entry_id}" if matches else "csl:none")
    return ScreeningResult(party_role=party.role, party_name=party.name, status=status, matches=matches,
                           is_forwarder=is_forwarder, evidence_ids=[eid])
