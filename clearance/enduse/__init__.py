"""End-use statement loop. OWNER: Person B (tasks B4-B5).

Flow: draft_request -> (buyer reply) -> extract -> check. If the first reply fails `check`,
the pipeline sends ONE draft_followup; a second failure is final (decision rule R8).
`screen` and `assess` are Person A's functions, injected by the pipeline (modules never import each other).
"""
from __future__ import annotations

from typing import Callable

from clearance import config
from clearance.evidence import Ledger
from clearance.llm import LLM, LLMUnavailable
from clearance.llm.schemas import DraftOut, EndUseOut
from clearance.mail import tag
from clearance.models import (CapabilityResult, Classification, Email, EndUseClaim, EndUseResult, Order,
                              OrderLine, Party, ScreeningResult)

ScreenFn = Callable[[Party, Ledger], ScreeningResult]
AssessFn = Callable[[Party, list[Classification], list[OrderLine], str, Ledger], CapabilityResult]

BASE_NEEDS = ["rf", "antenna", "radar", "fpga", "mixed_signal", "test_lab", "telecom", "satellite", "defence",
              "industrial_control", "consumer_electronics", "research"]

REQUEST_ASKS = ["the name and country of the final end user of the parts",
                "the specific intended use (application) of the parts",
                "the product or system the parts will be built into"]


def needs_vocabulary(classifications: list[Classification]) -> list[str]:
    return sorted(set(BASE_NEEDS) | {n for c in classifications for n in c.needs})


def _draft(kind: str, order: Order, ask_for: list[str], llm: LLM, fallback_subject: str, fallback_intro: str) -> DraftOut:
    t = tag(order.order_id)
    parts = ", ".join(f"{l.quantity} x {l.part_number}" for l in order.lines)
    try:
        d = llm.structured("draft_email", DraftOut, {"kind": kind, "tag": t, "ask_for": ask_for, "order_parts": parts})
        if d.subject.startswith(t):
            return d
    except LLMUnavailable:
        pass
    body = f"{fallback_intro} ({parts}). Please reply with:\n- " + "\n- ".join(ask_for) + "\n\nCompliance Desk"
    return DraftOut(subject=f"{t} {fallback_subject}", body=body)


def draft_request(order: Order, llm: LLM) -> DraftOut:
    return _draft("end_use_request", order, REQUEST_ASKS, llm, "End-use statement request",
                  "Export regulations require an end-use statement for your order")


def draft_followup(order: Order, reasons: list[str], llm: LLM) -> DraftOut:
    asks = []
    if any("end user" in r for r in reasons):
        asks.append("the full legal name and country of the organisation that will use the parts")
    if any("use" in r and "end user" not in r for r in reasons):
        asks.append("a specific description of the application (a general phrase such as 'civilian use' is not sufficient)")
    asks = asks or REQUEST_ASKS
    return _draft("end_use_followup", order, asks, llm, "End-use statement: more detail needed",
                  "Thank you for your reply. We need a little more detail about your order")


def extract(reply: Email, classifications: list[Classification], llm: LLM, ledger: Ledger) -> EndUseClaim:
    """Raises LLMUnavailable when Claude cannot extract (pipeline -> HOLD)."""
    vocab = needs_vocabulary(classifications)
    out = llm.structured("extract_end_use", EndUseOut, {"reply": reply.body, "needs_vocabulary": vocab})
    claim = EndUseClaim(
        claimed_use=out.claimed_use.strip(),
        mapped_needs=[n for n in out.mapped_needs if n in vocab],
        end_user_name=(out.end_user_name or "").strip() or None,
        end_user_country=(out.end_user_country or "").strip().upper()[:2] or None,
        evasive=out.evasive,
    )
    src = f"email:{reply.msg_id}"
    ledger.add("End-use reply: claimed use", claim.claimed_use, src, reply.received_at)
    ledger.add("End-use reply: needs implied by claimed use", claim.mapped_needs, src, reply.received_at)
    ledger.add("End-use reply: named end user", claim.end_user_name, src, reply.received_at)
    ledger.add("End-use reply judged evasive", claim.evasive, src, reply.received_at)
    return claim


def check(claim: EndUseClaim, order: Order, classifications: list[Classification],
          screen: ScreenFn, assess: AssessFn, ledger: Ledger) -> EndUseResult:
    """§4.7: consistent only if use matches the parts' needs, is specific, the end user is named, clear on the
    list, not a forwarder, at most medium risk, and the reply is not evasive."""
    reasons: list[str] = []
    part_needs = {n for c in classifications for n in c.needs}
    if claim.claimed_use.strip().lower() in config.VAGUE_USE_PHRASES:
        reasons.append("claimed use is blank or vague")
    elif part_needs and not part_needs.intersection(claim.mapped_needs):
        reasons.append("claimed use does not match what the parts are for")
    if claim.evasive:
        reasons.append("reply is evasive")

    scr = cap = None
    if claim.end_user_name:
        eu = Party(role="end_user", name=claim.end_user_name, country=claim.end_user_country)
        scr = screen(eu, ledger)
        cap = assess(eu, classifications, order.lines, order.ship_to_country, ledger)
        if scr.status != "clear":
            reasons.append(f"end user list screening: {scr.status}")
        if scr.is_forwarder:
            reasons.append("end user is a freight forwarder")
        if cap.tier in ("high_risk", "no_data"):
            reasons.append(f"end user capability: {cap.tier}")
    else:
        reasons.append("no end user named")

    eid = ledger.add("End-use consistency check", {"consistent": not reasons, "reasons": reasons}, "enduse:check")
    ids = [eid] + (scr.evidence_ids if scr else []) + (cap.evidence_ids if cap else [])
    return EndUseResult(claim=claim, end_user_screening=scr, end_user_capability=cap,
                        consistent=not reasons, reasons=reasons, evidence_ids=ids)
