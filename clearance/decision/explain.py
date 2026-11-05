"""Cited explanation (task B6). Claude writes sentences citing evidence IDs; code validates them.
Any failure (Claude unavailable, unknown IDs, uncited sentence) falls back to a deterministic template."""
from __future__ import annotations

import json
import logging

from clearance.decision.rules import RULES_BY_ID
from clearance.evidence import Ledger
from clearance.llm import LLM, LLMUnavailable, validate
from clearance.llm.schemas import ExplanationOut
from clearance.models import Decision, ExplanationSentence

log = logging.getLogger(__name__)


def _short(value) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s if len(s) <= 200 else s[:197] + "..."


def template(decision: Decision) -> list[ExplanationSentence]:
    rule = RULES_BY_ID.get(decision.rule_fired)
    label = rule.label if rule else decision.rule_fired
    ids = [e.id for e in decision.evidence][:5]
    return [ExplanationSentence(text=f"Recommendation: {decision.outcome}. {label}.", evidence_ids=ids)]


def explain(decision: Decision, ledger: Ledger, llm: LLM) -> list[ExplanationSentence]:
    if not decision.evidence:
        return template(decision)
    rule = RULES_BY_ID.get(decision.rule_fired)
    payload = {
        "decision": {"outcome": decision.outcome, "rule": decision.rule_fired, "rule_label": rule.label if rule else "",
                     "capability_rules_triggered": decision.rules_triggered},
        # Values are given so the model doesn't guess; the validator rejects any number it writes (design rule 3).
        "evidence": [{"id": e.id, "claim": e.claim, "value": _short(e.value), "source": e.source.split(":")[0]}
                     for e in decision.evidence],
    }
    try:
        out = llm.structured("explain", ExplanationOut, payload)
        sentences = [ExplanationSentence(text=s.text, evidence_ids=s.evidence_ids) for s in out.sentences]
        validate.check(sentences, ledger)
        return sentences
    except (LLMUnavailable, validate.ExplanationRejected) as e:
        log.warning("explanation fell back to template: %s", e)
        return template(decision)
