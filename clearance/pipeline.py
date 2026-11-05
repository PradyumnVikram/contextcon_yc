"""Order state machine (task B7). The ONLY module that calls other modules.

EMAIL_RECEIVED → PARSED → [AWAITING_ORDER_DETAILS] → CLASSIFIED → SCREENED → CAPABILITY_CHECKED
→ [AWAITING_END_USE] → RECOMMENDED → SIGNED

Person A's modules are injected (defaults: the real packages), so stubs or fakes can be swapped in.
Per-order working state (buyer address, partial order, results so far, follow-up counts) lives in
`order_context`, a table private to this module; shared tables in store.py are used as defined.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from types import ModuleType
from typing import Any

from pydantic import BaseModel, Field

from clearance import capability as _capability
from clearance import catalog as _catalog
from clearance import config, store
from clearance import screening as _screening
from clearance import watch as _watch
from clearance import decision as dec
from clearance import enduse, network
from clearance.evidence import Ledger
from clearance.llm import LLM, LLMUnavailable
from clearance.mail import Mailbox, match_reply, merge_details, missing_details_email, parse_order
from clearance.models import (Decision, Email, Incomplete, Order, OrderResults, OrderState, Outcome, Override,
                              Party, Signature)

log = logging.getLogger(__name__)

_CTX_SCHEMA = "CREATE TABLE IF NOT EXISTS order_context (order_id TEXT PRIMARY KEY, context_json TEXT)"
SIGNABLE = ("RELEASE", "BLOCK")


class OrderContext(BaseModel):
    buyer_email: str = ""
    partial: dict[str, Any] | None = None
    details_rounds: int = 0
    results: OrderResults | None = None
    end_use_requested: bool = False
    followups_sent: int = 0
    last_end_use_reasons: list[str] = Field(default_factory=list)
    network_alerts: list[str] = Field(default_factory=list)     # later orders that re-flagged this one


class Pipeline:
    def __init__(self, conn: sqlite3.Connection, llm: LLM, mailbox: Mailbox, *,
                 catalog: ModuleType = _catalog, screening: ModuleType = _screening,
                 capability: ModuleType = _capability, watch: ModuleType = _watch) -> None:
        self.conn, self.llm, self.mailbox = conn, llm, mailbox
        self.catalog, self.screening, self.capability, self.watch = catalog, screening, capability, watch
        conn.execute(_CTX_SCHEMA)
        conn.commit()

    # ------------------------------------------------------------------ context / persistence
    def _ctx(self, oid: str) -> OrderContext:
        row = self.conn.execute("SELECT context_json FROM order_context WHERE order_id=?", (oid,)).fetchone()
        return OrderContext.model_validate_json(row["context_json"]) if row else OrderContext()

    def _save_ctx(self, oid: str, ctx: OrderContext) -> None:
        self.conn.execute("INSERT OR REPLACE INTO order_context VALUES (?,?)", (oid, ctx.model_dump_json()))
        self.conn.commit()

    def _ledger(self, oid: str) -> Ledger:
        return Ledger(store.load_evidence(self.conn, oid))

    def _save_ledger(self, oid: str, ledger: Ledger) -> None:
        store.save_evidence(self.conn, oid, ledger.items)

    def _new_order_id(self) -> str:
        n = self.conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
        return f"O{n + 1:04d}"

    def _send(self, oid: str, subject: str, body: str, in_reply_to: str | None = None) -> Email:
        to = self._ctx(oid).buyer_email or "buyer@unknown.example"
        e = self.mailbox.send(to, subject, body, in_reply_to=in_reply_to)
        store.save_email(self.conn, e, "out", order_id=oid)
        return e

    # ------------------------------------------------------------------ entry points
    def process_inbox(self) -> list[str]:
        """Poll the mailbox and ingest every new email. Returns the order ids touched."""
        return [oid for e in self.mailbox.poll(self.conn) if (oid := self.ingest(e))]

    def ingest(self, email: Email) -> str | None:
        oid = match_reply(email, self.conn)
        if oid and self.conn.execute("SELECT 1 FROM orders WHERE order_id=?", (oid,)).fetchone():
            store.save_email(self.conn, email, "in", order_id=oid)
            self.on_reply(oid, email)
            return oid
        if oid:  # tagged reply for an order we don't know: keep it for the Exceptions screen
            store.save_email(self.conn, email, "in", order_id=None)
            log.warning("unmatched reply %s (tag %s)", email.msg_id, oid)
            return None
        return self._new_order(email)

    def _new_order(self, email: Email) -> str:
        oid = self._new_order_id()
        store.save_email(self.conn, email, "in", order_id=oid)
        ctx = OrderContext(buyer_email=email.from_addr)
        ledger = Ledger()
        try:
            parsed = parse_order(email, oid, self.llm, ledger)
        except LLMUnavailable as e:
            log.warning("parse failed for %s: %s", oid, e)
            order = self._placeholder(oid, email, {})
            store.save_order(self.conn, order, OrderState.EMAIL_RECEIVED)
            ctx.results = OrderResults(llm_unavailable=True)
            self._save_ctx(oid, ctx)
            self._save_ledger(oid, ledger)
            self._finish(oid, order, ledger, ctx)
            return oid

        if isinstance(parsed, Incomplete):
            order = self._placeholder(oid, email, parsed.partial)
            store.save_order(self.conn, order, OrderState.EMAIL_RECEIVED)
            ctx.partial, ctx.details_rounds = parsed.partial, 1
            self._save_ctx(oid, ctx)
            self._save_ledger(oid, ledger)
            draft = missing_details_email(oid, parsed.missing_fields, self.llm)
            self._send(oid, draft.subject, draft.body, in_reply_to=email.msg_id)
            store.set_state(self.conn, oid, OrderState.AWAITING_ORDER_DETAILS)
            return oid

        store.save_order(self.conn, parsed, OrderState.EMAIL_RECEIVED)
        store.set_state(self.conn, oid, OrderState.PARSED)
        self._save_ctx(oid, ctx)
        self._assess(oid, parsed, ledger, ctx)
        return oid

    @staticmethod
    def _placeholder(oid: str, email: Email, partial: dict[str, Any]) -> Order:
        name = partial.get("buyer_name") or email.from_addr or "(unknown buyer)"
        return Order(order_id=oid, source_email_id=email.msg_id,
                     parties=[Party(role="buyer", name=name, country=partial.get("buyer_country"))],
                     lines=[], ship_to_country=partial.get("ship_to_country") or "")

    # ------------------------------------------------------------------ assessment
    def _assess(self, oid: str, order: Order, ledger: Ledger, ctx: OrderContext) -> None:
        cls = [self.catalog.classify(l.part_number, ledger, l.description) for l in order.lines]
        lic = [self.catalog.licence(c, order.ship_to_country, ledger) for c in cls if c.found]
        store.set_state(self.conn, oid, OrderState.CLASSIFIED)
        scr = [self.screening.screen(p, ledger) for p in order.parties]
        store.set_state(self.conn, oid, OrderState.SCREENED)
        cap = self.capability.assess(order.buyer, cls, order.lines, order.ship_to_country, ledger)
        store.set_state(self.conn, oid, OrderState.CAPABILITY_CHECKED)
        ctx.results = OrderResults(classifications=cls, licences=lic, screenings=scr, buyer_capability=cap)
        # memory across orders: leave this order's identifiers behind, then look at the buyer's network
        email_text = ""
        if order.source_email_id:
            row = self.conn.execute("SELECT body FROM emails WHERE msg_id=?", (order.source_email_id,)).fetchone()
            email_text = row["body"] if row else ""
        network.record(self.conn, order, cls, email_text)
        ctx.results.network = network.analyse(self.conn, order, self.screening.screen, ledger)
        self._save_ledger(oid, ledger)
        self._finish(oid, order, ledger, ctx)
        self._recheck_linked(oid, ctx.results.network)

    def _recheck_linked(self, oid: str, net) -> None:
        """When this order completes a controlled set, re-examine the earlier orders that supplied it."""
        for finding in [s for s in (net.systems if net else []) if s.flagged]:
            for other in finding.orders:
                if other == oid:
                    continue
                ctx2 = self._ctx(other)
                if ctx2.results is None or oid in ctx2.network_alerts:
                    continue
                order2, ledger2 = store.load_order(self.conn, other), self._ledger(other)
                ctx2.results.network = network.analyse(self.conn, order2, self.screening.screen, ledger2)
                ledger2.add(f"Network alert: order {oid} completed a {finding.system} together with this order",
                            {"orders": finding.orders, "companies": finding.companies}, f"network:alert/{oid}")
                ctx2.network_alerts.append(oid)
                if store.get_state(self.conn, other) == OrderState.SIGNED:
                    # never silently undo a signature: the alert goes on the file for the officer
                    self._save_ledger(other, ledger2)
                    self._save_ctx(other, ctx2)
                else:
                    self._finish(other, order2, ledger2, ctx2)

    def _finish(self, oid: str, order: Order, ledger: Ledger, ctx: OrderContext) -> Decision:
        """Decide, send any end-use request the decision calls for, explain, persist."""
        results = ctx.results or OrderResults()
        d = dec.decide(order, results, ledger)

        wants_end_use = d.outcome == "AWAITING_END_USE" or (d.rule_fired == "R6_no_or_thin_coverage" and results.end_use is None)
        if wants_end_use and not ctx.end_use_requested:
            draft = enduse.draft_request(order, self.llm)
            self._send(oid, draft.subject, draft.body, in_reply_to=order.source_email_id)
            ctx.end_use_requested = True
            ledger.add("End-use statement requested from buyer", draft.subject, f"pipeline:{oid}")

        if d.outcome == "AWAITING_END_USE":
            store.set_state(self.conn, oid, OrderState.AWAITING_END_USE)
            d.explanation = dec.explain(d, ledger, _NoLLM())  # template only while waiting; saves a call
        else:
            store.set_state(self.conn, oid, OrderState.RECOMMENDED)
            d.explanation = dec.explain(d, ledger, self.llm)

        d.state_history = store.get_state_history(self.conn, oid)
        self._save_ledger(oid, ledger)
        self._save_ctx(oid, ctx)
        store.save_decision(self.conn, d)
        return d

    # ------------------------------------------------------------------ replies
    def on_reply(self, oid: str, email: Email) -> None:
        state = store.get_state(self.conn, oid)
        ctx, ledger = self._ctx(oid), self._ledger(oid)
        order = store.load_order(self.conn, oid)

        if state == OrderState.AWAITING_ORDER_DETAILS:
            try:
                res = merge_details(ctx.partial or {}, email, oid, self.llm, ledger)
            except LLMUnavailable:
                ctx.results = OrderResults(llm_unavailable=True)
                self._finish(oid, order, ledger, ctx)
                return
            if isinstance(res, Incomplete):
                if ctx.details_rounds >= config.ORDER_DETAILS_MAX_ROUNDS:
                    ctx.partial = res.partial
                    ctx.results = OrderResults(order_incomplete=True)
                    self._finish(oid, order, ledger, ctx)
                    return
                ctx.partial, ctx.details_rounds = res.partial, ctx.details_rounds + 1
                self._save_ctx(oid, ctx)
                self._save_ledger(oid, ledger)
                draft = missing_details_email(oid, res.missing_fields, self.llm)
                self._send(oid, draft.subject, draft.body, in_reply_to=email.msg_id)
                return
            store.save_order(self.conn, res, OrderState.PARSED)
            store.set_state(self.conn, oid, OrderState.PARSED)
            ctx.partial = None
            self._assess(oid, res, ledger, ctx)
            return

        if ctx.end_use_requested and ctx.results is not None and ctx.results.end_use is None:
            self._on_end_use_reply(oid, order, email, ctx, ledger, state)
            return

        log.info("reply for %s in state %s recorded without action", oid, state.value)

    def _on_end_use_reply(self, oid, order, email, ctx, ledger, state) -> None:
        results = ctx.results
        before = {e.id for e in ledger.items}
        try:
            claim = enduse.extract(email, results.classifications, self.llm, ledger)
        except LLMUnavailable:
            results.llm_unavailable = True
            self._finish(oid, order, ledger, ctx)
            return
        reply_ids = [e.id for e in ledger.items if e.id not in before]  # the reply's own fields, cited too
        res = enduse.check(claim, order, results.classifications, self.screening.screen, self.capability.assess, ledger)
        res.evidence_ids = reply_ids + res.evidence_ids
        if not res.consistent and ctx.followups_sent < config.END_USE_MAX_FOLLOWUPS and state == OrderState.AWAITING_END_USE:
            ctx.followups_sent += 1
            ctx.last_end_use_reasons = res.reasons
            draft = enduse.draft_followup(order, res.reasons, self.llm)
            self._send(oid, draft.subject, draft.body, in_reply_to=email.msg_id)
            ledger.add("End-use follow-up sent", res.reasons, f"pipeline:{oid}")
            self._save_ledger(oid, ledger)
            self._save_ctx(oid, ctx)
            return
        res.followups_sent = ctx.followups_sent
        results.end_use = res
        self._finish(oid, order, ledger, ctx)

    # ------------------------------------------------------------------ officer actions
    def sign(self, oid: str, by: str) -> Decision:
        d = store.load_decision(self.conn, oid)
        if d is None or d.outcome not in SIGNABLE:
            raise ValueError(f"order {oid}: only RELEASE or BLOCK recommendations are signed")
        if not by.strip():
            raise ValueError("signer name required")
        d.signature = Signature(by=by.strip())
        store.set_state(self.conn, oid, OrderState.SIGNED)
        d.state_history = store.get_state_history(self.conn, oid)
        store.save_decision(self.conn, d)
        if d.outcome == "RELEASE":
            ctx = self._ctx(oid)
            tier = ctx.results.buyer_capability.tier if ctx.results and ctx.results.buyer_capability else "no_data"
            self.watch.register(self.conn, store.load_order(self.conn, oid).buyer, tier)
        return d

    def override(self, oid: str, new_outcome: Outcome, by: str, reason: str) -> Decision:
        if not reason.strip() or not by.strip():
            raise ValueError("override needs the officer's name and a reason")
        d = store.load_decision(self.conn, oid)
        if d is None:
            raise ValueError(f"order {oid} has no recommendation yet")
        d.override = Override(by=by.strip(), original_outcome=d.outcome, original_rule=d.rule_fired,
                              new_outcome=new_outcome, reason=reason.strip())
        d.outcome, d.signature = new_outcome, None
        ledger = self._ledger(oid)
        ledger.add(f"Officer override to {new_outcome}", reason.strip(), f"officer:{by.strip()}")
        self._save_ledger(oid, ledger)
        if store.get_state(self.conn, oid) == OrderState.SIGNED:
            store.set_state(self.conn, oid, OrderState.RECOMMENDED)
        d.state_history = store.get_state_history(self.conn, oid)
        store.save_decision(self.conn, d)
        return d

    # ------------------------------------------------------------------ read helpers for the UI
    def audit(self, oid: str) -> str:
        return dec.audit_html(store.load_order(self.conn, oid), store.load_decision(self.conn, oid), self._ledger(oid))

    def context(self, oid: str) -> OrderContext:
        return self._ctx(oid)


class _NoLLM:
    def structured(self, task, schema, payload):
        raise LLMUnavailable("not used while awaiting end-use")
