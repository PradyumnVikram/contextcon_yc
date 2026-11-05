"""Evidence-ID validator and renderer (task B2). Design rule 3: the LLM cites IDs only; code supplies values."""
from __future__ import annotations

import json

from clearance.evidence import Ledger
from clearance.models import ExplanationSentence


class ExplanationRejected(ValueError):
    pass


def unknown_ids(sentences: list[ExplanationSentence], ledger: Ledger) -> list[str]:
    bad: list[str] = []
    for s in sentences:
        bad.extend(ledger.unknown_ids(s.evidence_ids))
    return bad


def check(sentences: list[ExplanationSentence], ledger: Ledger) -> None:
    """Raise if any sentence is uncited or cites an ID that is not in the ledger."""
    if not sentences:
        raise ExplanationRejected("empty explanation")
    if any(not s.evidence_ids for s in sentences):
        raise ExplanationRejected("a sentence cites no evidence")
    if bad := unknown_ids(sentences, ledger):
        raise ExplanationRejected(f"unknown evidence IDs: {sorted(set(bad))}")


def _fmt(value) -> str:
    if isinstance(value, (dict, list)):
        s = json.dumps(value, default=str)
        return s if len(s) <= 120 else s[:117] + "..."
    return str(value)


def render(sentences: list[ExplanationSentence], ledger: Ledger) -> list[str]:
    """Each sentence followed by its citations with the real recorded values, e.g. 'text [E3: headcount = 4]'."""
    out = []
    for s in sentences:
        cites = "; ".join(f"{i}: {ledger.get(i).claim} = {_fmt(ledger.get(i).value)}" for i in s.evidence_ids)
        out.append(f"{s.text} [{cites}]")
    return out
