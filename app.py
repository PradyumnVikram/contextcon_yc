"""Clearance officer workspace (task B8). Run: streamlit run app.py

Pair it with the buyer mail client (streamlit run buyer_app.py --server.port 8502): emails sent there land
in this inbox and are processed automatically; Clearance's replies show up in the buyer's window.

Three panes, one order at a time:
  1. Inbox       - incoming orders and replies, the conversation per order
  2. Processing  - everything Clearance checked: parsed order, parts and licence, list screening,
                   Crustdata company + employee data and peer comparison, end-use statement
  3. Action      - the recommendation, cited explanation, sign / override, audit file, work queues
Sidebar: officer name, process / auto-process inbox, system status, watched customers.
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
    "EMAIL_RECEIVED": "Email received", "PARSED": "Order parsed", "AWAITING_ORDER_DETAILS": "Waiting for buyer details",
    "CLASSIFIED": "Parts classified", "SCREENED": "Parties screened", "CAPABILITY_CHECKED": "Capability checked",
    "AWAITING_END_USE": "Waiting for end-use reply", "RECOMMENDED": "Recommendation ready", "SIGNED": "Signed",
}
TIER_LABEL = {"consistent": "Consistent", "medium_risk": "Medium risk", "high_risk": "High risk", "no_data": "No data"}
AUTO_POLL_S = 4

st.markdown("""
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 1.2rem; padding-left: 1.4rem; padding-right: 1.4rem; max-width: 100%;}
.pane-title {font-size:1.05rem; font-weight:700; margin:0 0 0.4rem 0; letter-spacing:-0.01em;}
.pane-sub {color:#6b7280; font-size:0.8rem; margin-top:-0.3rem; margin-bottom:0.6rem;}
.pill {display:inline-block; padding:1px 9px; border-radius:999px; font-size:0.74rem; font-weight:600;
       line-height:1.55; white-space:nowrap; vertical-align:middle;}
.muted {color:#6b7280; font-size:0.82rem;}
.small {font-size:0.82rem;}
.mono {font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.8rem;}
.cite {display:inline-block; margin-left:4px; padding:0 6px; border-radius:6px; background:#eef2f7; color:#334155;
       font-size:0.7rem; font-family: ui-monospace, monospace; cursor:help; border:1px solid #d9e1ea;}
.expl {margin:0.15rem 0 0.4rem 0; line-height:1.55; font-size:0.92rem;}
.row {display:flex; justify-content:space-between; gap:8px; font-size:0.82rem; margin:2px 0;}
.ok {color:#15803d;} .warn {color:#b45309;} .off {color:#b91c1c;} .todo {color:#9ca3af;}
.card {border:1px solid #e5e7eb; border-radius:10px; padding:8px 11px; background:#fafafa; margin-bottom:6px;}
.mail-in {border-left:3px solid #94a3b8; padding:4px 0 4px 9px; margin:6px 0;}
.mail-out {border-left:3px solid #6366f1; padding:4px 0 4px 9px; margin:6px 0;}
.big {font-size:1.15rem; font-weight:700;}
</style>
""", unsafe_allow_html=True)

def pill(outcome: str | None) -> str:
    label, fg, bg = OUTCOME.get(outcome or "", (outcome or "Pending", "#374151", "#eceff3"))
    return f"<span class='pill' style='color:{fg};background:{bg}'>{escape(label)}</span>"


def rule_label(rule_id: str) -> str:
    r = RULES_BY_ID.get(rule_id)
    return r.label if r else rule_id


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


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
        return ("ok", f"local {config.OLLAMA_MODEL}") if config.OLLAMA_MODEL in names else \
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
        buyer = next((p for p in o["parties"] if p["role"] == "buyer"), {})
        out.append({"order": r["order_id"], "buyer": buyer.get("name", ""),
                    "route": f"{buyer.get('country') or '?'} → {o['ship_to_country'] or '?'}",
                    "parts": ", ".join(f'{l["quantity"]}× {l["part_number"]}' for l in o["lines"]) or "—",
                    "state": r["state"], "recommendation": d.get("outcome", ""), "rule": d.get("rule_fired", "")})
    return out


def explanation_html(ledger: Ledger, decision) -> str:
    parts = []
    for s in decision.explanation:
        chips = []
        for eid in s.evidence_ids:
            if ledger.has(eid):
                ev = ledger.get(eid)
                val = ev.value if isinstance(ev.value, str) else json.dumps(ev.value, default=str)
                chips.append(f"<span class='cite' title='{escape(f'{ev.claim}: {val[:180]}', quote=True)}'>{eid}</span>")
        parts.append(f"<div class='expl'>{escape(s.text)}{''.join(chips)}</div>")
    return "".join(parts) or "<div class='muted'>No explanation recorded.</div>"


def select(oid: str) -> None:
    st.session_state["sel"] = oid


@st.fragment(run_every=f"{AUTO_POLL_S}s")
def auto_poll() -> None:
    """Own timer; fresh pipeline per tick so SQLite stays on one thread. Full rerun only when something changed."""
    c = store.connect(config.DB_PATH)
    touched = Pipeline(c, make_llm(c), Mailbox(config.MAILBOX_DIR)).process_inbox()
    st.caption(f"⏱️ checking the inbox every {AUTO_POLL_S}s")
    if touched:
        st.session_state["sel"] = touched[-1]
        st.toast(f"Processed {', '.join(touched)}")
        st.rerun(scope="app")


# --------------------------------------------------------------------------- sidebar
st.session_state.setdefault("auto", True)   # the service processes mail on its own; the toggle can pause it

with st.sidebar:
    html("<div class='big'>🛃 Clearance</div><div class='muted'>Export-compliance agent</div>")
    officer = st.text_input("Officer name", key="officer", placeholder="Required to sign or override")
    if st.button("📥 Process inbox", type="primary", width="stretch"):
        with st.spinner("Reading new emails and running every check…"):
            touched = P.process_inbox()
        if touched:
            st.session_state["sel"] = touched[-1]
        st.toast(f"Processed {', '.join(touched)}" if touched else "No new emails")
    st.toggle("Auto-process inbox", key="auto", help="Poll the inbox and process new mail automatically.")
    if st.session_state.get("auto"):
        auto_poll()
    st.divider()
    lvl, txt = llm_status()
    n_csl = csl_size()
    status = {"LLM": (lvl, txt),
              "Crustdata": ("ok", "live API") if config.CRUSTDATA_API_KEY else ("warn", "demo data only"),
              "Screening list": ("ok", f"{n_csl:,} entries") if n_csl > 100 else ("warn", "demo list only")}
    html("".join(f"<div class='row'><span>{k}</span><span class='{l}'>● {escape(v)}</span></div>"
                 for k, (l, v) in status.items()))
    st.divider()
    cust = rows("SELECT company_key, name, tier, updated_at FROM customers ORDER BY updated_at DESC")
    with st.expander(f"👁️ Watched customers ({len(cust)})"):
        if not cust:
            st.caption("A buyer is watched once its release is signed.")
        for c in cust:
            html(f"<div class='row'><span>{escape(c['name'])}</span><span>{TIER_LABEL.get(c['tier'], c['tier'])}</span></div>")
        if cust:
            by_name = {c["name"]: c["company_key"] for c in cust}
            name = st.selectbox("Customer", list(by_name), key="sim_customer")
            tier = st.selectbox("Crustdata reports", ["medium_risk", "high_risk", "consistent"],
                                format_func=TIER_LABEL.get, key="sim_tier")
            if st.button("Simulate watcher event", width="stretch"):
                watch.simulate_event(conn, Party(role="buyer", name=name, domain=by_name[name]), tier)
                st.rerun()
    st.caption("Prototype · not legal advice. An officer signs every release and block.")

orders = all_orders()
ids = [o["order"] for o in orders]
if st.session_state.get("sel") not in ids:
    st.session_state["sel"] = ids[0] if ids else None
sel = st.session_state["sel"]

p1, p2, p3 = st.columns([1.05, 1.55, 1.15], gap="medium")

# --------------------------------------------------------------------------- pane 1: inbox
with p1:
    html("<div class='pane-title'>📨 Inbox</div><div class='pane-sub'>Mail from buyers, processed automatically · one conversation per order</div>")
    pending = P.mailbox.poll(conn)
    if pending:
        html(f"<div class='muted' style='margin:6px 0'>⏳ {len(pending)} unprocessed: "
             + ", ".join(escape(e.subject[:30]) for e in pending) + "</div>")

    if not orders:
        st.info("No orders yet. Send an email from the buyer window (`streamlit run buyer_app.py --server.port 8502`).")
    for o in orders:
        is_sel = o["order"] == sel
        with st.container(border=True):
            html(f"<div class='row'><b>{escape(o['buyer'][:34])}</b>{pill(o['recommendation'] or None)}</div>"
                 f"<div class='muted'>{o['order']} · {escape(o['route'])} · {escape(o['parts'][:40])}</div>"
                 f"<div class='muted'>{STATE_LABEL.get(o['state'], o['state'])}</div>")
            st.button("● Selected" if is_sel else "Open", key=f"open-{o['order']}", on_click=select, args=(o["order"],),
                      disabled=is_sel, width="stretch")

    if sel:
        thread = rows("SELECT msg_id, direction, subject, body, received_at FROM emails WHERE order_id=? "
                      "ORDER BY received_at", (sel,))
        html(f"<div class='pane-title' style='margin-top:10px'>Conversation · {sel}</div>")
        for m in thread:
            cls = "mail-out" if m["direction"] == "out" else "mail-in"
            who = "Clearance → buyer" if m["direction"] == "out" else "Buyer"
            html(f"<div class='{cls}'><div class='muted'>{who} · {m['received_at'][11:16]}</div>"
                 f"<div class='small'><b>{escape(m['subject'])}</b></div></div>")
            with st.expander("Show message", expanded=False):
                st.text(m["body"])

# --------------------------------------------------------------------------- pane 2: processing
with p2:
    html("<div class='pane-title'>🔍 Processing</div>"
         "<div class='pane-sub'>Everything Clearance checked, with the evidence it recorded</div>")
    if not sel:
        st.caption("Select an order in the inbox.")
    else:
        order, d, ctx = store.load_order(conn, sel), store.load_decision(conn, sel), P.context(sel)
        ledger = Ledger(store.load_evidence(conn, sel))
        res = ctx.results
        history = store.get_state_history(conn, sel)
        reached = {s.value for s, _ in history}
        when = {s.value: at for s, at in history}

        with st.container(border=True):
            steps = ["EMAIL_RECEIVED", "PARSED", "CLASSIFIED", "SCREENED", "CAPABILITY_CHECKED", "RECOMMENDED", "SIGNED"]
            if "AWAITING_ORDER_DETAILS" in reached:
                steps.insert(2, "AWAITING_ORDER_DETAILS")
            if "AWAITING_END_USE" in reached or ctx.end_use_requested:
                steps.insert(steps.index("RECOMMENDED"), "AWAITING_END_USE")
            html("".join(
                f"<div class='row'><span class='ok'>✓ {STATE_LABEL[s]}</span><span class='muted'>{when[s]:%H:%M:%S}</span></div>"
                if s in when else f"<div class='row'><span class='todo'>○ {STATE_LABEL[s]}</span><span></span></div>"
                for s in steps))

        with st.expander("🧾 Order (extracted from the email)", expanded=False):
            for p in order.parties:
                html(f"<div class='row'><span class='muted'>{p.role.replace('_', ' ')}</span>"
                     f"<span><b>{escape(p.name)}</b> {p.country or ''}</span></div>")
            html("<div class='row'><span class='muted'>parts</span><span>"
                 + ", ".join(f"{l.quantity}× <span class='mono'>{escape(l.part_number)}</span>" for l in order.lines)
                 + f"</span></div><div class='row'><span class='muted'>destination</span><span>{order.ship_to_country}</span></div>")

        if res and res.classifications:
            with st.expander("📦 Parts & licence", expanded=False):
                for c in res.classifications:
                    lic = next((l for l in res.licences if l.part_number == c.part_number), None)
                    if not c.found:
                        html(f"<div class='card'><b class='mono'>{escape(c.part_number)}</b> "
                             f"<span class='off'>not in catalog → hold</span></div>")
                        continue
                    html(f"<div class='card'><b class='mono'>{c.part_number}</b> · {c.part_class or ''} · "
                         f"{'controlled' if c.controlled else 'not controlled'} · ECCN {c.eccn or '—'}"
                         f"<div class='muted'>needs: {', '.join(c.needs)}</div>"
                         + (f"<div class='small'>{'🔐 licence required' if lic.required else '✓ no licence'}: "
                            f"{escape(lic.reason)}</div>" if lic else "") + "</div>")

        if res and res.screenings:
            hits = [s for s in res.screenings if s.status != "clear"]
            label = f"⚠️ {len(hits)} match(es)" if hits else "✓ all clear"
            with st.expander(f"🛡️ Restricted-list screening · {label}", expanded=bool(hits)):
                for s in res.screenings:
                    mark = {"clear": "<span class='ok'>✓ clear</span>", "fuzzy_hit": "<span class='warn'>⚠ close match</span>",
                            "exact_hit": "<span class='off'>⛔ exact match</span>"}[s.status]
                    html(f"<div class='row'><span>{s.party_role.replace('_', ' ')} · {escape(s.party_name)}"
                         f"{' · 🚚 forwarder' if s.is_forwarder else ''}</span>{mark}</div>")
                    for m in s.matches:
                        html(f"<div class='card small'>Listed: <b>{escape(m.listed_name)}</b> · score {m.score}"
                             f"<div class='muted'>{escape(str(m.listed_record.get('source', ''))[:70])} · "
                             f"{', '.join(f'{k} {v}' for k, v in m.breakdown.items())}</div></div>")

        cap = res.buyer_capability if res else None
        if cap:
            src = next((ledger.get(i).source for i in cap.evidence_ids if ledger.has(i)), "")
            badge = "demo data" if src.startswith("crustdata-fixture") else "live Crustdata"
            with st.expander(f"🏢 Crustdata capability check · {TIER_LABEL.get(cap.tier, cap.tier)} ({badge})",
                             expanded=True):
                m = st.columns(4)
                m[0].metric("Tier", TIER_LABEL.get(cap.tier, cap.tier))
                m[1].metric("Score", f"{cap.mismatch_score:g}")
                m[2].metric("Buyer type", cap.buyer_type.title())
                m[3].metric("Coverage", cap.coverage.title())
                f = cap.features
                if f:
                    html("<div class='small'>"
                         f"<b>Company:</b> headcount {f.get('headcount', '—')} · age {f.get('age_years', '—')} yrs · "
                         f"12-month change {f.get('headcount_growth_yoy_pct', '—')}% · visitors/month {f.get('monthly_visitors', '—')}"
                         f"<br><b>People ({f.get('people_sampled', 0)} sampled):</b> matching the parts' needs "
                         f"{f.get('matching_people', '—')} · mix {f.get('function_mix', {})}"
                         f"<br><b>Buyer type votes:</b> keywords {f.get('buyer_type_keyword_vote') or '—'} · "
                         f"people {f.get('buyer_type_people_vote') or '—'}</div>")
                    if cap.percentiles:
                        st.dataframe(pd.DataFrame([{"vs peers": k.replace("_", " "), "percentile": v}
                                                   for k, v in cap.percentiles.items()]), hide_index=True, width="stretch",
                                     column_config={"percentile": st.column_config.ProgressColumn(
                                         min_value=0, max_value=100, format="%.0f")})
                        st.caption(f"Compared with {f.get('peer_count', 0)} similar companies.")
                html("<div class='small'><b>Rules triggered:</b> "
                     + (" · ".join(f"<span class='mono'>{r}</span>" for r in cap.triggered_rules) or "none") + "</div>")

        if ctx.end_use_requested or (res and res.end_use):
            eu = res.end_use if res else None
            with st.expander("📝 End-use statement", expanded=bool(eu)):
                html(f"<div class='small'>Requested: <b>yes</b> · follow-ups sent: <b>{ctx.followups_sent}</b></div>")
                if eu:
                    html(f"<div class='small'><b>Claimed use:</b> {escape(eu.claim.claimed_use or '—')}<br>"
                         f"<b>End user:</b> {escape(eu.claim.end_user_name or 'not named')} {eu.claim.end_user_country or ''}<br>"
                         f"<b>Consistent:</b> {'<span class=ok>yes</span>' if eu.consistent else '<span class=off>no</span>'}"
                         + "".join(f"<br>• {escape(r)}" for r in eu.reasons) + "</div>")
                else:
                    st.caption("Waiting for the buyer's reply.")

        with st.expander(f"🔗 All evidence ({len(ledger)})", expanded=False):
            cited = {e.id for e in d.evidence} if d else set()
            st.dataframe(pd.DataFrame([{"ID": e.id, "★": "★" if e.id in cited else "", "Claim": e.claim,
                                        "Value": json.dumps(e.value, default=str)[:160], "Source": e.source}
                                       for e in ledger.items]), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- pane 3: action
with p3:
    html("<div class='pane-title'>✍️ Action</div><div class='pane-sub'>Recommendation and the officer's decision</div>")
    if sel:
        d = store.load_decision(conn, sel)
        state = store.get_state(conn, sel).value
        ledger = Ledger(store.load_evidence(conn, sel))
        with st.container(border=True):
            if d is None:
                html(f"<div class='big'>{STATE_LABEL.get(state, state)}</div>"
                     "<div class='muted'>No recommendation yet: Clearance is waiting for the buyer.</div>")
            else:
                html(f"<div class='big'>{pill(d.outcome)}</div>"
                     f"<div class='small' style='margin:4px 0 8px'><b>{escape(rule_label(d.rule_fired))}</b> "
                     f"<span class='muted mono'>{d.rule_fired}</span></div>")
                html(explanation_html(ledger, d))
                st.caption("Hover a grey tag to see the evidence value.")
                if d.licence_documents:
                    st.info("**Documents to collect:** " + " · ".join(d.licence_documents))
                if d.signature:
                    st.success(f"Signed by {d.signature.by} · {d.signature.at:%d %b %H:%M} UTC")
                if d.override:
                    st.warning(f"Override by {d.override.by}: {d.override.original_outcome} → "
                               f"{d.override.new_outcome}. {d.override.reason}")
                if d.outcome == "AWAITING_END_USE":
                    st.caption("No action needed: Clearance has emailed the buyer and continues when they reply.")
                if d.outcome in ("RELEASE", "BLOCK") and state != OrderState.SIGNED.value:
                    if st.button(f"✍️ Sign {OUTCOME[d.outcome][0].lower()}", type="primary", width="stretch",
                                 disabled=not officer, key="sign-sel"):
                        P.sign(sel, officer)
                        st.rerun()
                    if not officer:
                        st.caption("Enter your officer name in the sidebar to sign.")
                with st.popover("Override recommendation", width="stretch", disabled=not officer):
                    new = st.selectbox("New outcome", ["RELEASE", "HOLD", "LICENCE_REQUIRED", "BLOCK"],
                                       format_func=lambda o: OUTCOME[o][0], key="ov_outcome")
                    reason = st.text_area("Reason (required, recorded in the audit)", key="ov_reason")
                    if st.button("Apply override", key="ov_apply"):
                        try:
                            P.override(sel, new, officer, reason)
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                st.download_button("⬇️ Audit file (HTML)", P.audit(sel), file_name=f"audit-{sel}.html",
                                   mime="text/html", width="stretch")

    todo = [o for o in orders if o["recommendation"] in ("RELEASE", "BLOCK") and o["state"] == "RECOMMENDED"]
    holds = [o for o in orders if o["recommendation"] == "HOLD" and o["state"] != "SIGNED"]
    waiting = [o for o in orders if o["state"] in ("AWAITING_END_USE", "AWAITING_ORDER_DETAILS")]
    for title, items in [("Ready to sign", todo), ("Exceptions", holds), ("Waiting on buyer", waiting)]:
        html(f"<div class='pane-title' style='margin-top:12px'>{title} · {len(items)}</div>")
        if not items:
            html("<div class='muted'>None.</div>")
        for o in items:
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"{pill(o['recommendation'] or None)} <span class='small'>{escape(o['buyer'][:26])}</span>",
                        unsafe_allow_html=True)
            c2.button("Open", key=f"q-{title}-{o['order']}", on_click=select, args=(o["order"],),
                      disabled=o["order"] == sel)
