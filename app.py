"""Clearance officer UI (task B8). Run: streamlit run app.py

Screens: Inbox · Orders · Ready to sign · Exceptions · Order detail · Customers.
Every screen reads from SQLite through store.py and acts through pipeline.Pipeline.
"""
from __future__ import annotations

import json
from html import escape

import httpx
import pandas as pd
import streamlit as st

from clearance import config, store, watch
from clearance.decision.rules import RULES_BY_ID
from clearance.evidence import Ledger
from clearance.llm import make_llm
from clearance.mail import Mailbox
from clearance.models import OrderState, Party
from clearance.pipeline import Pipeline

st.set_page_config(page_title="Clearance", page_icon="🛃", layout="wide")

# --------------------------------------------------------------------------- look & feel
OUTCOME = {  # label, colour, background
    "RELEASE": ("Release", "#0f6b2f", "#dcf5e3"),
    "HOLD": ("Hold", "#8a5300", "#fff0cc"),
    "BLOCK": ("Block", "#9b1c1c", "#fde0e0"),
    "LICENCE_REQUIRED": ("Licence required", "#1e40af", "#dde7ff"),
    "AWAITING_END_USE": ("Awaiting end-use", "#6b21a8", "#efe1fc"),
}
STATE_LABEL = {
    "EMAIL_RECEIVED": "Email received", "PARSED": "Parsed", "AWAITING_ORDER_DETAILS": "Waiting for buyer details",
    "CLASSIFIED": "Parts classified", "SCREENED": "Parties screened", "CAPABILITY_CHECKED": "Capability checked",
    "AWAITING_END_USE": "Waiting for end-use reply", "RECOMMENDED": "Recommended", "SIGNED": "Signed",
}
TIER_LABEL = {"consistent": "Consistent", "medium_risk": "Medium risk", "high_risk": "High risk", "no_data": "No data"}

st.markdown("""
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 1.6rem; max-width: 1200px;}
h1, h2, h3 {letter-spacing: -0.01em;}
.pill {display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.78rem; font-weight:600;
       line-height:1.5; white-space:nowrap; vertical-align:middle;}
.muted {color:#6b7280; font-size:0.85rem;}
.order-head {font-size:1.02rem; font-weight:600;}
.route {font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.85rem; color:#374151;}
.cite {display:inline-block; margin-left:4px; padding:0 6px; border-radius:6px; background:#eef2f7; color:#334155;
       font-size:0.72rem; font-family: ui-monospace, monospace; cursor:help; border:1px solid #d9e1ea;}
.expl {margin:0.15rem 0 0.35rem 0; line-height:1.55;}
.status-row {display:flex; justify-content:space-between; font-size:0.82rem; margin:2px 0;}
.dot-ok {color:#15803d;} .dot-warn {color:#b45309;} .dot-off {color:#b91c1c;}
.party {border:1px solid #e5e7eb; border-radius:10px; padding:10px 12px; background:#fafafa;}
</style>
""", unsafe_allow_html=True)

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


def pill(outcome: str | None) -> str:
    label, fg, bg = OUTCOME.get(outcome or "", (outcome or "Pending", "#374151", "#eceff3"))
    return f"<span class='pill' style='color:{fg};background:{bg}'>{escape(label)}</span>"


def rule_label(rule_id: str) -> str:
    r = RULES_BY_ID.get(rule_id)
    return r.label if r else rule_id


# --------------------------------------------------------------------------- wiring
def pipeline() -> Pipeline:
    conn = store.connect(config.DB_PATH)  # per rerun: sqlite connections are not shared across threads
    return Pipeline(conn, make_llm(conn), Mailbox(config.MAILBOX_DIR))


P = pipeline()
conn = P.conn


@st.cache_data(ttl=30, show_spinner=False)
def llm_status() -> tuple[str, str]:
    if config.LLM_PROVIDER == "claude":
        return ("ok", f"Claude · {config.LLM_MODEL}") if config.ANTHROPIC_API_KEY else ("off", "Claude · no API key")
    try:
        tags = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=1.5).json()
        names = {m["name"] for m in tags.get("models", [])}
        return ("ok", f"Local · {config.OLLAMA_MODEL}") if config.OLLAMA_MODEL in names else \
               ("warn", f"{config.OLLAMA_MODEL} not pulled")
    except Exception:
        return ("off", "Ollama not running")


@st.cache_data(ttl=300, show_spinner=False)
def csl_size() -> int:
    from clearance.screening import csl
    return len(csl.load())


def rows(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args)]


def all_orders() -> list[dict]:
    out = []
    for r in rows("SELECT order_id, order_json, state, decision_json FROM orders ORDER BY order_id DESC"):
        o = json.loads(r["order_json"])
        d = json.loads(r["decision_json"]) if r["decision_json"] else {}
        parties = {p["role"]: p for p in o["parties"]}
        buyer = parties.get("buyer", {})
        out.append({"order": r["order_id"], "buyer": buyer.get("name", ""),
                    "route": f"{buyer.get('country') or '?'} → {o['ship_to_country'] or '?'}",
                    "parts": ", ".join(f'{l["quantity"]}× {l["part_number"]}' for l in o["lines"]) or "—",
                    "state": r["state"], "recommendation": d.get("outcome", ""), "rule": d.get("rule_fired", ""),
                    "signed": (d.get("signature") or {}).get("by", "")})
    return out


def explanation_html(oid: str, decision) -> str:
    ledger = Ledger(store.load_evidence(conn, oid))
    parts = []
    for s in decision.explanation:
        chips = []
        for eid in s.evidence_ids:
            if ledger.has(eid):
                ev = ledger.get(eid)
                val = ev.value if isinstance(ev.value, str) else json.dumps(ev.value, default=str)
                tip = escape(f"{ev.claim}: {val[:180]}", quote=True)
                chips.append(f"<span class='cite' title='{tip}'>{eid}</span>")
        parts.append(f"<div class='expl'>{escape(s.text)}{''.join(chips)}</div>")
    return "".join(parts) or "<div class='muted'>No explanation recorded.</div>"


def open_detail(oid: str) -> None:
    st.session_state.update(detail=oid, screen="Order detail")


# --------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## 🛃 Clearance")
    st.caption("Export-compliance agent")
    officer = st.text_input("Officer name", value=st.session_state.get("officer", ""), key="officer",
                            placeholder="Required to sign or override")
    if st.button("📥 Process inbox", type="primary", width="stretch"):
        with st.spinner("Reading new emails and running checks…"):
            touched = P.process_inbox()
        st.toast(f"Processed {len(touched)} email(s)" if touched else "No new emails")

    # counts are computed after processing so the navigation labels are current
    orders = all_orders()
    todo_sign = [o for o in orders if o["recommendation"] in ("RELEASE", "BLOCK") and o["state"] == "RECOMMENDED"]
    holds = [o for o in orders if o["recommendation"] == "HOLD" and o["state"] != "SIGNED"]
    waiting = [o for o in orders if o["state"] in ("AWAITING_END_USE", "AWAITING_ORDER_DETAILS")]
    nav_label = {"Inbox": "📨 Inbox", "Orders": "📋 Orders", "Ready": f"✍️ Ready to sign ({len(todo_sign)})",
                 "Exceptions": f"⚠️ Exceptions ({len(holds)})", "Order detail": "🔎 Order detail",
                 "Customers": "👁️ Customers"}
    # stable option values (labels carry the live counts), so signing an order doesn't reset the selection
    screen = st.radio("Navigate", list(nav_label), format_func=nav_label.get, key="screen",
                      label_visibility="collapsed")
    st.divider()
    lvl, txt = llm_status()
    crust = ("ok", "Live API") if config.CRUSTDATA_API_KEY else ("warn", "Demo fixtures only")
    n_csl = csl_size()
    csl_st = ("ok", f"{n_csl:,} entries") if n_csl > 100 else ("warn", "Demo list only: run csl download")
    dot = {"ok": "dot-ok", "warn": "dot-warn", "off": "dot-off"}
    st.markdown("".join(f"<div class='status-row'><span>{k}</span><span class='{dot[l]}'>● {escape(v)}</span></div>"
                        for k, (l, v) in {"LLM": (lvl, txt), "Crustdata": crust, "Screening list": csl_st}.items()),
                unsafe_allow_html=True)
    st.caption("Prototype · not legal advice. An officer signs every release and block.")


# --------------------------------------------------------------------------- screens
def metrics_row():
    c = st.columns(4)
    c[0].metric("Orders", len(orders))
    c[1].metric("Ready to sign", len(todo_sign))
    c[2].metric("Exceptions", len(holds))
    c[3].metric("Waiting on buyer", len(waiting))


def screen_inbox():
    st.title("Inbox")
    st.caption("Orders and replies arrive here as emails. Clearance reads them, runs every check, and drafts replies.")
    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**✉️ Compose a test email** <span class='muted'>(simulates a buyer)</span>",
                        unsafe_allow_html=True)
            preset = st.selectbox("Preset", ["(blank)"] + list(PRESETS))
            f, s, b = PRESETS.get(preset, ("buyer@example.com", "", ""))
            frm = st.text_input("From", f, key=f"from-{preset}")
            subj = st.text_input("Subject", s, key=f"subj-{preset}",
                                 help="When replying to Clearance, keep the [CLR-…] tag so the reply is matched.")
            body = st.text_area("Body", b, height=150, key=f"body-{preset}")
            if st.button("Drop into inbox"):
                P.mailbox.compose(frm, subj, body)
                st.success("Email delivered to the inbox. Click **📥 Process inbox** in the sidebar.")
    with right:
        pending = P.mailbox.poll(conn)
        st.markdown(f"**Unprocessed** · {len(pending)}")
        if pending:
            for e in pending:
                st.markdown(f"<div class='muted'>• <b>{escape(e.subject)}</b> — {escape(e.from_addr)}</div>",
                            unsafe_allow_html=True)
        else:
            st.markdown("<div class='muted'>Nothing waiting.</div>", unsafe_allow_html=True)
        out = P.mailbox.outbox_messages()
        st.markdown(f"**Sent by Clearance** · {len(out)}")
        for e in reversed(out[-8:]):
            with st.expander(e.subject, expanded=False):
                st.caption(f"To {e.to_addr} · {e.received_at:%d %b %H:%M}")
                st.text(e.body)
    log = rows("SELECT received_at AS time, direction, order_id AS order_, subject FROM emails ORDER BY received_at DESC")
    with st.expander(f"Mail log ({len(log)})"):
        if log:
            st.dataframe(pd.DataFrame(log).rename(columns={"order_": "order"}), width="stretch", hide_index=True)
        else:
            st.caption("No mail yet.")


def screen_orders():
    st.title("Orders")
    metrics_row()
    if not orders:
        st.info("No orders yet. Compose a test email in the Inbox, then click **Process inbox**.")
        return
    df = pd.DataFrame([{
        "Order": o["order"], "Buyer": o["buyer"], "Route": o["route"], "Parts": o["parts"],
        "Recommendation": OUTCOME.get(o["recommendation"], (o["recommendation"] or "—",))[0],
        "Why": rule_label(o["rule"]) if o["rule"] else "—",
        "Status": STATE_LABEL.get(o["state"], o["state"]), "Signed by": o["signed"] or "—"} for o in orders])
    st.dataframe(df, width="stretch", hide_index=True,
                 column_config={"Why": st.column_config.TextColumn(width="large")})


def _order_card(o: dict, actions: bool, key: str):
    d = store.load_decision(conn, o["order"])
    with st.container(border=True):
        st.markdown(f"<div class='order-head'>{pill(d.outcome)} &nbsp;{escape(o['buyer'])} "
                    f"<span class='muted'>· {o['order']}</span></div>"
                    f"<div class='route'>{escape(o['route'])} &nbsp;·&nbsp; {escape(o['parts'])}</div>",
                    unsafe_allow_html=True)
        st.markdown(f"<div class='muted' style='margin-top:6px'>{escape(rule_label(d.rule_fired))}</div>",
                    unsafe_allow_html=True)
        st.markdown(explanation_html(o["order"], d), unsafe_allow_html=True)
        c1, c2, _ = st.columns([1.3, 1, 3])
        if actions and c1.button(f"✍️ Sign {d.outcome}", key=f"sign-{key}", disabled=not officer, type="primary"):
            P.sign(o["order"], officer)
            st.rerun()
        c2.button("Open detail", key=f"open-{key}", on_click=open_detail, args=(o["order"],))


def screen_sign():
    st.title("Ready to sign")
    st.caption("Recommended releases and blocks. Nothing ships, and nothing is refused, until an officer signs.")
    if not officer:
        st.warning("Enter your officer name in the sidebar to sign.")
    for o in todo_sign:
        _order_card(o, actions=True, key=o["order"])
    if not todo_sign:
        st.info("Nothing waiting for a signature.")


def screen_exceptions():
    st.title("Exceptions")
    st.caption("Held orders. A hold takes effect immediately; resolve it from the order detail page.")
    for o in holds:
        _order_card(o, actions=False, key=f"exc-{o['order']}")
    unmatched = rows("SELECT subject, msg_id, received_at FROM emails WHERE direction='in' AND order_id IS NULL")
    if unmatched:
        st.subheader("Replies that matched no order")
        st.dataframe(pd.DataFrame(unmatched), width="stretch", hide_index=True)
    if not holds and not unmatched:
        st.info("No exceptions.")


def screen_detail():
    st.title("Order detail")
    ids = [o["order"] for o in orders]
    if not ids:
        st.info("No orders yet.")
        return
    labels = {o["order"]: f"{o['order']} · {o['buyer']}" for o in orders}
    default = ids.index(st.session_state["detail"]) if st.session_state.get("detail") in ids else 0
    oid = st.selectbox("Order", ids, index=default, format_func=labels.get)
    order, d, ctx = store.load_order(conn, oid), store.load_decision(conn, oid), P.context(oid)
    ledger = Ledger(store.load_evidence(conn, oid))
    state = store.get_state(conn, oid).value
    if d is None:
        st.info(f"{STATE_LABEL.get(state, state)}. No recommendation yet.")
        return

    head, side = st.columns([3, 1])
    with head:
        st.markdown(f"<div style='font-size:1.25rem;font-weight:650'>{pill(d.outcome)} &nbsp;"
                    f"{escape(rule_label(d.rule_fired))}</div>"
                    f"<div class='muted'>{STATE_LABEL.get(state, state)} · rule <code>{d.rule_fired}</code></div>",
                    unsafe_allow_html=True)
    with side:
        st.download_button("⬇️ Audit file (HTML)", P.audit(oid), file_name=f"audit-{oid}.html", mime="text/html",
                           width="stretch")
    if d.signature:
        st.success(f"Signed by {d.signature.by} · {d.signature.at:%d %b %Y %H:%M} UTC")
    if d.override:
        st.warning(f"Override by {d.override.by}: {d.override.original_outcome} → {d.override.new_outcome}. "
                   f"Reason: {d.override.reason}")
    with st.container(border=True):
        st.markdown(explanation_html(oid, d), unsafe_allow_html=True)
        st.caption("Hover a grey evidence tag to see the recorded value.")
    if d.licence_documents:
        st.info("**Documents to collect:** " + " · ".join(d.licence_documents))

    res = ctx.results
    t1, t2, t3, t4, t5 = st.tabs(["Timeline", "Screening", "Capability", "End-use", f"Evidence ({len(ledger)})"])
    with t1:
        c1, c2 = st.columns([1, 1], gap="large")
        with c1:
            for s, at in d.state_history:
                st.markdown(f"<div class='status-row'><span>{STATE_LABEL.get(s.value, s.value)}</span>"
                            f"<span class='muted'>{at:%d %b %H:%M:%S}</span></div>", unsafe_allow_html=True)
        with c2:
            for p in order.parties:
                st.markdown(f"<div class='muted'>{p.role.replace('_', ' ')}</div><b>{escape(p.name)}</b> "
                            f"<span class='muted'>{p.country or ''}</span>", unsafe_allow_html=True)
            st.markdown(f"<div class='muted' style='margin-top:8px'>parts</div>"
                        + "<br>".join(f"{l.quantity}× <code>{escape(l.part_number)}</code>" for l in order.lines),
                        unsafe_allow_html=True)
    with t2:
        if not res or not res.screenings:
            st.caption("Not screened yet.")
        for s in (res.screenings if res else []):
            status = {"clear": "✅ clear", "fuzzy_hit": "⚠️ close match", "exact_hit": "⛔ exact match"}[s.status]
            st.markdown(f"**{s.party_role.replace('_', ' ').title()}** · {escape(s.party_name)} — {status}"
                        + (" · 🚚 freight forwarder" if s.is_forwarder else ""), unsafe_allow_html=True)
            for m in s.matches:
                a, b = st.columns(2)
                a.markdown(f"<div class='party'><div class='muted'>Order party</div><b>{escape(s.party_name)}</b></div>",
                           unsafe_allow_html=True)
                b.markdown(f"<div class='party'><div class='muted'>Listed · {escape(m.listed_record.get('source', ''))[:60]}"
                           f"</div><b>{escape(m.listed_name)}</b><div class='muted'>score {m.score} · "
                           f"{', '.join(f'{k} {v}' for k, v in m.breakdown.items())}</div></div>", unsafe_allow_html=True)
    with t3:
        cap = res.buyer_capability if res else None
        if not cap:
            st.caption("No capability check yet.")
        else:
            c = st.columns(4)
            c[0].metric("Tier", TIER_LABEL.get(cap.tier, cap.tier))
            c[1].metric("Mismatch score", f"{cap.mismatch_score:g}")
            c[2].metric("Buyer type", cap.buyer_type.title())
            c[3].metric("Data coverage", cap.coverage.title())
            if cap.triggered_rules:
                st.markdown("**Rules triggered:** " + " · ".join(f"`{r}`" for r in cap.triggered_rules))
            if cap.features:
                st.dataframe(pd.DataFrame([{"Feature": k.replace("_", " "), "Value": str(v),
                                            "Peer percentile": cap.percentiles.get(k)} for k, v in cap.features.items()]),
                             hide_index=True, width="stretch",
                             column_config={"Peer percentile": st.column_config.ProgressColumn(
                                 min_value=0, max_value=100, format="%.0f")})
    with t4:
        st.markdown(f"End-use requested: **{'yes' if ctx.end_use_requested else 'no'}** · "
                    f"follow-ups sent: **{ctx.followups_sent}**")
        if res and res.end_use:
            eu = res.end_use
            c1, c2 = st.columns(2)
            c1.markdown(f"**Claimed use**  \n{escape(eu.claim.claimed_use or '—')}  \n"
                        f"**End user**  \n{escape(eu.claim.end_user_name or 'not named')} {eu.claim.end_user_country or ''}")
            c2.markdown(f"**Consistent:** {'✅ yes' if eu.consistent else '❌ no'}  \n"
                        + ("  \n".join(f"• {escape(r)}" for r in eu.reasons) if eu.reasons else ""))
    with t5:
        cited = {e.id for e in d.evidence}
        st.dataframe(pd.DataFrame([{"ID": e.id, "Cited": "★" if e.id in cited else "", "Claim": e.claim,
                                    "Value": json.dumps(e.value, default=str)[:200], "Source": e.source}
                                   for e in ledger.items]), hide_index=True, width="stretch",
                     column_config={"Claim": st.column_config.TextColumn(width="large")})

    st.subheader("Officer actions")
    c1, c2 = st.columns([1, 2], gap="large")
    with c1:
        can_sign = d.outcome in ("RELEASE", "BLOCK") and state != OrderState.SIGNED.value
        if st.button(f"✍️ Sign {d.outcome}", disabled=not (officer and can_sign), type="primary",
                     width="stretch"):
            P.sign(oid, officer)
            st.rerun()
        if not officer:
            st.caption("Enter your officer name in the sidebar.")
    with c2:
        with st.form(f"override-{oid}"):
            new = st.selectbox("Override to", ["RELEASE", "HOLD", "LICENCE_REQUIRED", "BLOCK"],
                               format_func=lambda o: OUTCOME[o][0])
            reason = st.text_area("Reason (required, recorded in the audit)", height=80)
            if st.form_submit_button("Override", disabled=not officer):
                try:
                    P.override(oid, new, officer, reason)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def screen_customers():
    st.title("Customers")
    st.caption("Buyers whose release was signed are watched through Crustdata and re-rated when their data changes.")
    cust = rows("SELECT company_key, name, tier, watcher_id, updated_at FROM customers ORDER BY updated_at DESC")
    if not cust:
        st.info("A buyer becomes a watched customer when an officer signs its release.")
        return
    st.dataframe(pd.DataFrame([{"Customer": c["name"], "Risk tier": TIER_LABEL.get(c["tier"], c["tier"]),
                                "Watcher": c["watcher_id"], "Updated": c["updated_at"][:16].replace("T", " "),
                                "Key": c["company_key"]} for c in cust]), hide_index=True, width="stretch")
    with st.form("simulate"):
        st.markdown("**Simulate a Crustdata watcher event**")
        by_name = {c["name"]: c["company_key"] for c in cust}
        name = st.selectbox("Customer", list(by_name))
        tier = st.selectbox("New tier reported", ["medium_risk", "high_risk", "consistent"], format_func=TIER_LABEL.get)
        if st.form_submit_button("Simulate Crustdata event"):
            watch.simulate_event(conn, Party(role="buyer", name=name, domain=by_name[name]), tier)
            st.rerun()


SCREENS = {"Inbox": screen_inbox, "Orders": screen_orders, "Ready": screen_sign, "Exceptions": screen_exceptions,
           "Order detail": screen_detail, "Customers": screen_customers}
SCREENS[screen]()
