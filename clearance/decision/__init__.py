"""Decision table, explanation, audit. OWNER: Person B (task B6)."""
from __future__ import annotations

from clearance.decision.audit import audit_html
from clearance.decision.explain import explain
from clearance.decision.rules import RULES, RULES_BY_ID, first_match
from clearance.evidence import Ledger
from clearance.models import Decision, Order, OrderResults


def decide(order: Order, results: OrderResults, ledger: Ledger) -> Decision:
    rule, ids = first_match(order, results)
    docs = sorted({d for l in results.licences if l.required for d in l.documents}) if rule.outcome == "LICENCE_REQUIRED" else []
    return Decision(
        order_id=order.order_id,
        outcome=rule.outcome,
        rule_fired=rule.id,
        rules_triggered=list(results.buyer_capability.triggered_rules) if results.buyer_capability else [],
        evidence=[ledger.get(i) for i in ids if ledger.has(i)],
        licence_documents=docs,
        needs_human=rule.outcome != "AWAITING_END_USE",
    )


__all__ = ["RULES", "RULES_BY_ID", "audit_html", "decide", "explain", "first_match"]
