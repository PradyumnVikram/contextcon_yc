"""Clearance officer UI (task B8). Run: streamlit run app.py

Screens: Inbox · Orders · Ready to sign · Exceptions · Order detail · Customers.
Every screen reads from SQLite through store.py and acts through pipeline.Pipeline.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from clearance import config, store, watch
from clearance.decision.rules import RULES_BY_ID
from clearance.evidence import Ledger
from clearance.llm import ClaudeLLM, validate
from clearance.mail import Mailbox
from clearance.models import OrderState, Party
from clearance.pipeline import Pipeline

st.set_page_config(page_title="Clearance", page_icon="🛃", layout="wide")

OUTCOME_COLOR = {"RELEASE": "green", "HOLD": "orange", "BLOCK": "red", "LICENCE_REQUIRED": "blue",
                 "AWAITING_END_USE": "violet"}

PRESETS = {
    "Radar firm order (clean)": ("procurement@synthetic-radar.example", "PO 4411: mmWave amplifiers",
                                 "Hello,\nPlease supply 4 pcs PA-77G-HE for our radar test bench.\n"
                                 "Synthetic Radar Systems Pvt Ltd, Pune, India. Deliver to our Pune lab.\n\nRegards, Procurement"),
    "Shell trader order (capability mismatch)": ("orders@synthetic-shell.example", "Urgent order PA-77G-HE",
                                                 "Need 100 pcs PA-77G-HE asap. Synthetic shell Traders, Mumbai, India.\n"
                                                 "Deliver to our warehouse in Dubai, UAE. Pay advance."),
    "Unknown company (no data)": ("buy@synthetic-nodata.example", "Enquiry + PO ADC-12G-HE",
                                  "Please send 10 x ADC-12G-HE. Synthetic nodata Enterprises, Delhi, India. Deliver Delhi."),
    "Close spelling of a listed name": ("info@listed-tradng.example", "PO ADC",
                                        "10 x ADC-12G-HE please. Listed Electronic Tradng LLC, Dubai, UAE. Deliver Dubai."),
    "Order with missing destination": ("procurement@synthetic-radar.example", "PO 4412",
                                       "Please supply 4 pcs PA-77G-HE. Synthetic Radar Systems, India."),
}


# --------------------------------------------------------------------------- wiring
def pipeline() -> Pipeline:
    conn = store.connect(config.DB_PATH)  # per rerun: sqlite connections are not shared across threads
    return Pipeline(conn, ClaudeLLM(conn), Mailbox(config.MAILBOX_DIR))


P = pipeline()
conn = P.conn


def rows(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args)]


def all_orders() -> list[dict]:
    out = []
    for r in rows("SELECT order_id, order_json, state, decision_json FROM orders ORDER BY order_id DESC"):
        o = json.loads(r["order_json"])
        d = json.loads(r["decision_json"]) if r["decision_json"] else {}
        buyer = next((p["name"] for p in o["parties"] if p["role"] == "buyer"), "")
        out.append({"order": r["order_id"], "buyer": buyer, "destination": o["ship_to_country"],
                    "parts": ", ".join(f'{l["quantity"]}×{l["part_number"]}' for l in o["lines"]),
                    "state": r["state"], "recommendation": d.get("outcome", ""), "rule": d.get("rule_fired", ""),
                    "signed": (d.get("signature") or {}).get("by", "")})
    return out


def badge(outcome: str) -> str:
    return f":{OUTCOME_COLOR.get(outcome, 'gray')}-background[{outcome}]"


def explanation_lines(oid: str, decision) -> list[str]:
    try:
        return validate.render(decision.explanation, Ledger(store.load_evidence(conn, oid)))
    except KeyError:
        return [s.text for s in decision.explanation]


# --------------------------------------------------------------------------- sidebar
st.sidebar.title("🛃 Clearance")
officer = st.sidebar.text_input("Officer name", value=st.session_state.get("officer", ""), key="officer")
if not config.ANTHROPIC_API_KEY:
    st.sidebar.warning("ANTHROPIC_API_KEY is not set. Claude steps use cached responses only; "
                       "uncached ones HOLD (rule R10).")
if st.sidebar.button("📥 Process inbox", type="primary", use_container_width=True):
    with st.spinner("Processing new emails…"):
        touched = P.process_inbox()
    st.sidebar.success(f"Processed {len(touched)} email(s)" if touched else "No new emails")

orders = all_orders()
n_sign = sum(1 for o in orders if o["recommendation"] in ("RELEASE", "BLOCK") and o["state"] == "RECOMMENDED")
n_exc = sum(1 for o in orders if o["recommendation"] == "HOLD")
screen = st.sidebar.radio("Screen", ["Inbox", "Orders", f"Ready to sign ({n_sign})", f"Exceptions ({n_exc})",
                                     "Order detail", "Customers"], key="screen")
st.sidebar.caption("Prototype. Not legal advice. A person signs every release and block.")


# --------------------------------------------------------------------------- screens
def screen_inbox():
    st.header("Inbox")
    with st.expander("✉️ Compose test email (simulates a buyer)", expanded=not orders):
        preset = st.selectbox("Preset", ["(blank)"] + list(PRESETS))
        f, s, b = PRESETS.get(preset, ("buyer@example.com", "", ""))
        frm = st.text_input("From", f, key=f"from-{preset}")
        subj = st.text_input("Subject (keep the [CLR-…] tag when replying)", s, key=f"subj-{preset}")
        body = st.text_area("Body", b, height=160, key=f"body-{preset}")
        if st.button("Drop into inbox"):
            P.mailbox.compose(frm, subj, body)
            st.success("Email written to mailbox/inbox. Click **Process inbox** in the sidebar.")
    pending = P.mailbox.poll(conn)
    st.subheader(f"Unprocessed ({len(pending)})")
    for e in pending:
        st.markdown(f"- **{e.subject}** from {e.from_addr}")
    st.subheader("Mail log")
    log = rows("SELECT direction, order_id, subject, received_at FROM emails ORDER BY received_at DESC")
    st.dataframe(pd.DataFrame(log), use_container_width=True, hide_index=True) if log else st.info("No mail yet.")
    out = P.mailbox.outbox_messages()
    if out:
        st.subheader("Sent by Clearance (outbox)")
        for e in reversed(out[-10:]):
            with st.expander(f"→ {e.to_addr}: {e.subject}"):
                st.text(e.body)


def screen_orders():
    st.header("Orders")
    st.dataframe(pd.DataFrame(orders), use_container_width=True, hide_index=True) if orders else st.info("No orders yet.")


def _order_card(o: dict, actions: bool):
    d = store.load_decision(conn, o["order"])
    with st.container(border=True):
        st.markdown(f"**{o['order']}** · {o['buyer']} → {o['destination']} · {o['parts']}  {badge(d.outcome)}")
        rule = RULES_BY_ID.get(d.rule_fired)
        st.caption(f"{d.rule_fired}: {rule.label if rule else ''}")
        for line in explanation_lines(o["order"], d):
            st.markdown(f"- {line}")
        if actions:
            c1, c2 = st.columns([1, 3])
            if c1.button(f"✍️ Sign {d.outcome}", key=f"sign-{o['order']}", disabled=not officer):
                P.sign(o["order"], officer)
                st.rerun()
            c2.button("Open detail", key=f"open-{o['order']}",
                      on_click=lambda oid=o["order"]: st.session_state.update(detail=oid, screen="Order detail"))


def screen_sign():
    st.header("Ready to sign")
    st.caption("Recommended RELEASE and BLOCK orders. Nothing ships or is refused until an officer signs.")
    if not officer:
        st.warning("Enter your officer name in the sidebar to sign.")
    todo = [o for o in orders if o["recommendation"] in ("RELEASE", "BLOCK") and o["state"] == "RECOMMENDED"]
    for o in todo:
        _order_card(o, actions=True)
    if not todo:
        st.info("Nothing waiting for a signature.")


def screen_exceptions():
    st.header("Exceptions")
    holds = [o for o in orders if o["recommendation"] == "HOLD"]
    for o in holds:
        _order_card(o, actions=False)
        st.button("Open detail", key=f"exc-{o['order']}",
                  on_click=lambda oid=o["order"]: st.session_state.update(detail=oid, screen="Order detail"))
    unmatched = rows("SELECT subject, msg_id, received_at FROM emails WHERE direction='in' AND order_id IS NULL")
    if unmatched:
        st.subheader("Replies that matched no order")
        st.dataframe(pd.DataFrame(unmatched), use_container_width=True, hide_index=True)
    if not holds and not unmatched:
        st.info("No exceptions.")


def screen_detail():
    st.header("Order detail")
    ids = [o["order"] for o in orders]
    if not ids:
        st.info("No orders yet.")
        return
    default = ids.index(st.session_state["detail"]) if st.session_state.get("detail") in ids else 0
    oid = st.selectbox("Order", ids, index=default)
    order, d, ctx = store.load_order(conn, oid), store.load_decision(conn, oid), P.context(oid)
    ledger = Ledger(store.load_evidence(conn, oid))
    if d is None:
        st.info(f"State: {store.get_state(conn, oid).value}. No recommendation yet.")
        return

    st.markdown(f"### {badge(d.outcome)} `{d.rule_fired}`")
    if d.signature:
        st.success(f"Signed by {d.signature.by} at {d.signature.at:%Y-%m-%d %H:%M} UTC")
    if d.override:
        st.warning(f"Override by {d.override.by}: {d.override.original_outcome} → {d.override.new_outcome}. "
                   f"Reason: {d.override.reason}")
    for line in explanation_lines(oid, d):
        st.markdown(f"- {line}")
    if d.licence_documents:
        st.info("Documents to collect: " + ", ".join(d.licence_documents))

    t1, t2, t3, t4, t5 = st.tabs(["Timeline", "Screening", "Capability", "End-use", "Evidence"])
    with t1:
        st.dataframe(pd.DataFrame([{"state": s.value, "at (UTC)": f"{at:%Y-%m-%d %H:%M:%S}"} for s, at in d.state_history]),
                     hide_index=True, use_container_width=True)
        st.write("Parties:", [f"{p.role}: {p.name} ({p.country or '?'})" for p in order.parties])
    res = ctx.results
    with t2:
        for s in (res.screenings if res else []):
            st.markdown(f"**{s.party_role}** {s.party_name}: `{s.status}`" + (" · freight forwarder" if s.is_forwarder else ""))
            for m in s.matches:
                c1, c2 = st.columns(2)
                c1.markdown(f"**Order party**\n\n{s.party_name}")
                c2.markdown(f"**Listed entry {m.csl_entry_id}** (score {m.score})\n\n{m.listed_name}")
                st.json(m.breakdown, expanded=False)
    with t3:
        cap = res.buyer_capability if res else None
        if cap:
            st.markdown(f"Coverage `{cap.coverage}` · buyer type `{cap.buyer_type}` · score **{cap.mismatch_score:g}** · tier `{cap.tier}`")
            st.write("Rules triggered:", cap.triggered_rules or "none")
            if cap.features:
                st.dataframe(pd.DataFrame([{"feature": k, "value": str(v), "peer percentile": cap.percentiles.get(k, "")}
                                           for k, v in cap.features.items()]), hide_index=True, use_container_width=True)
    with t4:
        st.write(f"End-use requested: {ctx.end_use_requested} · follow-ups sent: {ctx.followups_sent}")
        if res and res.end_use:
            eu = res.end_use
            st.write({"claimed_use": eu.claim.claimed_use, "mapped_needs": eu.claim.mapped_needs,
                      "end_user": eu.claim.end_user_name, "country": eu.claim.end_user_country,
                      "evasive": eu.claim.evasive, "consistent": eu.consistent, "reasons": eu.reasons})
    with t5:
        cited = {e.id for e in d.evidence}
        st.dataframe(pd.DataFrame([{"id": e.id, "cited": "★" if e.id in cited else "", "claim": e.claim,
                                    "value": json.dumps(e.value, default=str)[:200], "source": e.source}
                                   for e in ledger.items]), hide_index=True, use_container_width=True)

    st.download_button("⬇️ Download audit (HTML)", P.audit(oid), file_name=f"audit-{oid}.html", mime="text/html")

    st.subheader("Officer actions")
    c1, c2 = st.columns(2)
    with c1:
        can_sign = d.outcome in ("RELEASE", "BLOCK") and store.get_state(conn, oid) != OrderState.SIGNED
        if st.button(f"✍️ Sign {d.outcome}", disabled=not (officer and can_sign)):
            P.sign(oid, officer)
            st.rerun()
    with c2:
        with st.form(f"override-{oid}"):
            new = st.selectbox("Override to", ["RELEASE", "HOLD", "LICENCE_REQUIRED", "BLOCK"])
            reason = st.text_area("Reason (required, goes into the audit)")
            if st.form_submit_button("Override", disabled=not officer):
                try:
                    P.override(oid, new, officer, reason)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def screen_customers():
    st.header("Customers (watched)")
    cust = rows("SELECT company_key, name, tier, watcher_id, updated_at FROM customers ORDER BY updated_at DESC")
    if not cust:
        st.info("A buyer becomes a watched customer when an officer signs its RELEASE.")
        return
    st.dataframe(pd.DataFrame(cust), hide_index=True, use_container_width=True)
    with st.form("simulate"):
        by_name = {c["name"]: c["company_key"] for c in cust}
        name = st.selectbox("Customer", list(by_name))
        tier = st.selectbox("New tier reported", ["medium_risk", "high_risk", "consistent"])
        if st.form_submit_button("Simulate Crustdata event"):
            watch.simulate_event(conn, Party(role="buyer", name=name, domain=by_name[name]), tier)
            st.rerun()


SCREENS = {"Inbox": screen_inbox, "Orders": screen_orders, "Ready": screen_sign, "Exceptions": screen_exceptions,
           "Order detail": screen_detail, "Customers": screen_customers}
next(fn for k, fn in SCREENS.items() if screen.startswith(k))()
