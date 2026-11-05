"""Order-email parsing, missing-details merge, reply matching (task B3).

Claude extracts fields; code decides what is missing. Nothing is guessed: a missing or ambiguous
required field produces `Incomplete`, which triggers one auto-reply to the buyer.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from clearance.evidence import Ledger
from clearance.llm import LLM, LLMUnavailable
from clearance.llm.schemas import DraftOut, ParsedOrder
from clearance.models import Email, Incomplete, Order, OrderLine, Party

TAG_RE = re.compile(r"\[CLR-([A-Za-z0-9_-]+)\]")
REQUIRED = ("buyer_name", "buyer_country", "ship_to_country", "lines")
_COUNTRY_FIELDS = ("buyer_country", "ship_to_country", "middleman_country", "shipper_country")

FIELD_LABELS = {
    "buyer_name": "your company's registered name",
    "buyer_country": "your company's country",
    "ship_to_country": "the destination country for delivery",
    "lines": "the part numbers and quantities you need",
}


FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com",
             "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "rediffmail.com", "zoho.com",
             "yandex.com", "mail.com", "gmx.com", "example.com"}


def sender_domain(from_addr: str) -> str | None:
    """Corporate domain of the sender ("Procurement <p@astramwp.com>" -> "astramwp.com"); None for free-mail."""
    m = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", from_addr or "")
    dom = m.group(1).lower() if m else None
    return dom if dom and dom not in FREE_MAIL else None


def tag(order_id: str) -> str:
    return f"[CLR-{order_id}]"


def finalize_subject(subject: str, order_tag: str, fallback: str) -> str:
    """The subject must start with the tag AND say what the email is about (a bare tag is easy to miss)."""
    s = (subject or "").strip()
    rest = s[len(order_tag):].strip(" :-–") if s.startswith(order_tag) else ""
    return f"{order_tag} {rest}" if len(rest) >= 3 else f"{order_tag} {fallback}"


def match_reply(email: Email, conn: sqlite3.Connection | None = None) -> str | None:
    """Order id from the [CLR-id] subject tag, else from In-Reply-To pointing at one of our sent emails."""
    if m := TAG_RE.search(email.subject):
        return m.group(1)
    if conn is not None and email.in_reply_to:
        row = conn.execute("SELECT order_id FROM emails WHERE msg_id=?", (email.in_reply_to,)).fetchone()
        if row and row["order_id"]:
            return row["order_id"]
    return None


def _clean(p: ParsedOrder) -> dict[str, Any]:
    d = p.model_dump()
    for f in _COUNTRY_FIELDS:
        v = (d.get(f) or "").strip().upper()
        d[f] = v if re.fullmatch(r"[A-Z]{2}", v) else None
    d["lines"] = [l for l in d["lines"] if l["part_number"].strip() and l["quantity"] > 0]
    return d


def _missing(d: dict[str, Any]) -> list[str]:
    missing = [f for f in REQUIRED if not d.get(f)]
    missing += [f for f in d.get("ambiguous_fields", []) if f in REQUIRED and f not in missing]
    return missing


def _build(order_id: str, email_id: str, d: dict[str, Any]) -> Order:
    parties = [Party(role="buyer", name=d["buyer_name"], country=d["buyer_country"],
                     address=d.get("buyer_address"), domain=d.get("buyer_website")),
               Party(role="ship_to", name=d.get("ship_to_name") or d["buyer_name"],
                     country=d["ship_to_country"], address=d.get("ship_to_address"))]
    if d.get("middleman_name"):
        parties.append(Party(role="middleman", name=d["middleman_name"], country=d.get("middleman_country")))
    if d.get("shipper_name"):
        parties.append(Party(role="shipper", name=d["shipper_name"], country=d.get("shipper_country")))
    return Order(order_id=order_id, source_email_id=email_id, parties=parties, ship_to_country=d["ship_to_country"],
                 lines=[OrderLine(**l) for l in d["lines"]], stated_purpose=d.get("stated_purpose"))


def _record(ledger: Ledger, d: dict[str, Any], email: Email) -> None:
    src = f"email:{email.msg_id}"
    for k, v in d.items():
        if k != "ambiguous_fields" and v not in (None, [], ""):
            ledger.add(f"Order field '{k}' from email", v, src, email.received_at)


def _finish(order_id: str, email: Email, d: dict[str, Any], ledger: Ledger, sender: str | None = None) -> Order | Incomplete:
    _record(ledger, d, email)
    if not d.get("buyer_website") and (dom := sender_domain(sender or email.from_addr)):
        # a corporate sender address identifies the company for Crustdata (a website in the email still wins)
        d["buyer_website"] = dom
        ledger.add("Buyer domain taken from sender address", dom, f"email:{email.msg_id}#from", email.received_at)
    if missing := _missing(d):
        return Incomplete(order_id=order_id, missing_fields=missing, partial=d)
    return _build(order_id, email.msg_id, d)


def parse_order(email: Email, order_id: str, llm: LLM, ledger: Ledger) -> Order | Incomplete:
    """Raises LLMUnavailable if Claude cannot parse; the pipeline turns that into a HOLD."""
    parsed = llm.structured("parse_order", ParsedOrder,
                            {"email": {"subject": email.subject, "body": email.body, "from": email.from_addr}})
    return _finish(order_id, email, _clean(parsed), ledger)


def merge_details(partial: dict[str, Any], reply: Email, order_id: str, llm: LLM, ledger: Ledger) -> Order | Incomplete:
    """Parse the buyer's reply and fill in the fields that were missing."""
    parsed = _clean(llm.structured("parse_order", ParsedOrder,
                                   {"email": {"subject": reply.subject, "body": reply.body, "from": reply.from_addr}}))
    merged = dict(partial)
    for k, v in parsed.items():
        if k == "ambiguous_fields":
            merged[k] = v
        elif v not in (None, [], "") and not merged.get(k):
            merged[k] = v
    return _finish(order_id, reply, merged, ledger, sender=reply.from_addr)


def missing_details_email(order_id: str, missing: list[str], llm: LLM) -> DraftOut:
    ask = [FIELD_LABELS.get(f, f) for f in missing]
    try:
        d = llm.structured("draft_email", DraftOut, {"kind": "missing_details", "tag": tag(order_id), "ask_for": ask})
        if d.body.strip():
            return DraftOut(subject=finalize_subject(d.subject, tag(order_id), "Additional order details needed"),
                            body=d.body)
    except LLMUnavailable:
        pass
    body = ("Thank you for your order. Before we can process it, please reply with:\n- "
            + "\n- ".join(ask) + "\n\nCompliance Desk")
    return DraftOut(subject=f"{tag(order_id)} Additional order details needed", body=body)
