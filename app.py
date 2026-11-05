"""Clearance officer workspace (task B8). Run: streamlit run app.py --server.port 8501

Pair it with the buyer mail client (streamlit run buyer_app.py --server.port 8502): emails sent there land
in this inbox and are processed automatically; Clearance's replies show up in the buyer's window.

Three panes, one order at a time:
  1. Inbox       - every order and its email conversation
  2. Processing  - Checks (steps, order, parts, screening, end-use) · Crustdata (what was retrieved) · Evidence
  3. Action      - recommendation, cited explanation, sign / override, audit file, work queues
Styling comes from .streamlit/config.toml and native elements only (Streamlit skill guidelines).
"""
from __future__ import annotations

import httpx
import pandas as pd
import streamlit as st

from clearance import config, crustdata_client, store
from clearance.decision.rules import RULES_BY_ID
from clearance.evidence import Ledger
from clearance.llm import make_llm
from clearance.mail import Mailbox
from clearance.models import OrderState
from clearance.pipeline import Pipeline
from clearance.ui import (crustdata_snapshot, crustdata_summary, evidence_groups, function_label, md_escape,
                          network_dot, network_summary, readable_value)

st.set_page_config(page_title="Clearance", page_icon=":material/verified_user:", layout="wide")

OUTCOME = {  # label, badge colour, icon
    "RELEASE": ("Release", "green", ":material/check_circle:"),
    "HOLD": ("Hold", "orange", ":material/pause_circle:"),
    "BLOCK": ("Block", "red", ":material/block:"),
    "LICENCE_REQUIRED": ("Licence required", "blue", ":material/assignment:"),
    "AWAITING_END_USE": ("Awaiting end-use", "violet", ":material/hourglass_top:"),
}
STATE_LABEL = {
    "EMAIL_RECEIVED": "Email received", "PARSED": "Order read", "AWAITING_ORDER_DETAILS": "Waiting for buyer details",
    "CLASSIFIED": "Parts classified", "SCREENED": "Parties screened", "CAPABILITY_CHECKED": "Capability checked",
    "AWAITING_END_USE": "Waiting for end-use reply", "RECOMMENDED": "Recommendation ready", "SIGNED": "Signed",
}
TIER = {"consistent": ("Consistent", "green"), "medium_risk": ("Medium risk", "orange"),
        "high_risk": ("High risk", "red"), "no_data": ("No data", "gray")}
SCREEN = {"clear": ("Clear", "green"), "fuzzy_hit": ("Close match", "orange"), "exact_hit": ("Exact match", "red")}
AUTO_POLL_S = 4


def badge_md(outcome: str | None) -> str:
    label, color, _ = OUTCOME.get(outcome or "", ("Pending", "gray", ""))
    return f":{color}-badge[{label}]"


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
        return ("green", f"Claude {config.LLM_MODEL}") if config.ANTHROPIC_API_KEY else ("red", "Claude: no API key")
    try:
        names = {m["name"] for m in httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=1.5).json().get("models", [])}
        return ("green", f"Local {config.OLLAMA_MODEL}") if config.OLLAMA_MODEL in names else \
               ("orange", f"{config.OLLAMA_MODEL} not pulled")
    except Exception:
        return ("red", "Ollama not running")


@st.cache_data(ttl=300, show_spinner=False)
def csl_size() -> int:
    from clearance.screening import csl
    return len(csl.load())


def rows(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args)]


def all_orders() -> list[dict]:
    import json
    out = []
    for r in rows("SELECT order_id, order_json, state, decision_json FROM orders ORDER BY order_id DESC"):
        o = json.loads(r["order_json"])
        d = json.loads(r["decision_json"]) if r["decision_json"] else {}
        buyer = next((p for p in o["parties"] if p["role"] == "buyer"), {})
        out.append({"order": r["order_id"], "buyer": buyer.get("name", ""),
                    "route": f"{buyer.get('country') or '?'} → {o['ship_to_country'] or '?'}",
                    "parts": ", ".join(f'{l["quantity"]} × {l["part_number"]}' for l in o["lines"]) or "no parts yet",
                    "state": r["state"], "recommendation": d.get("outcome", ""), "rule": d.get("rule_fired", "")})
    return out


def select(oid: str) -> None:
    st.session_state["sel"] = oid


@st.fragment(run_every=f"{AUTO_POLL_S}s")
def auto_poll() -> None:
    """Own timer; fresh pipeline per tick so SQLite stays on one thread. Full rerun only when something changed."""
    c = store.connect(config.DB_PATH)
    touched = Pipeline(c, make_llm(c), Mailbox(config.MAILBOX_DIR)).process_inbox()
    st.caption(f":material/schedule: Checking the inbox every {AUTO_POLL_S}s")
    if touched:
        st.session_state["sel"] = touched[-1]
        st.toast(f"Processed {', '.join(touched)}", icon=":material/mark_email_read:")
        st.rerun(scope="app")


# --------------------------------------------------------------------------- sidebar
st.session_state.setdefault("auto", True)   # the service processes mail on its own; the toggle can pause it

with st.sidebar:
    st.subheader("Clearance", icon=":material/verified_user:")
    st.caption("Export-compliance agent")
    officer = st.text_input("Officer name", key="officer", placeholder="Required to sign or override")
    if st.button("Process inbox now", type="primary", icon=":material/move_to_inbox:", width="stretch"):
        with st.spinner("Reading new emails and running every check…"):
            touched = P.process_inbox()
        if touched:
            st.session_state["sel"] = touched[-1]
        st.toast(f"Processed {', '.join(touched)}" if touched else "No new emails", icon=":material/mark_email_read:")
    st.toggle("Auto-process inbox", key="auto", help="Poll the inbox and process new mail automatically.")
    if st.session_state.get("auto"):
        auto_poll()

    st.markdown("**System status**")
    lvl, txt = llm_status()
    n_csl = csl_size()
    st.badge(f"LLM · {txt}", color=lvl, icon=":material/smart_toy:")
    st.badge("Crustdata · live API" if config.CRUSTDATA_API_KEY else "Crustdata · demo data only",
             color="green" if config.CRUSTDATA_API_KEY else "orange", icon=":material/apartment:")
    st.badge(f"Screening list · {n_csl:,} entries" if n_csl > 100 else "Screening list · demo only",
             color="green" if n_csl > 100 else "orange", icon=":material/gpp_good:")

    cust = rows("SELECT company_key, name, tier FROM customers ORDER BY updated_at DESC")
    with st.expander(f"Watched customers ({len(cust)})", icon=":material/visibility:"):
        if not cust:
            st.caption("A buyer is watched once its release is signed.")
        else:
            st.table({c["name"]: f":{TIER.get(c['tier'], ('', 'gray'))[1]}-badge[{TIER.get(c['tier'], (c['tier'],))[0]}]"
                      for c in cust}, border="horizontal", alt="Watched customers and their risk tier")
            st.caption("Re-rated automatically when Crustdata reports a change.")
    st.caption("Prototype, not legal advice. An officer signs every release and block.")

orders = all_orders()
ids = [o["order"] for o in orders]
if st.session_state.get("sel") not in ids:
    st.session_state["sel"] = ids[0] if ids else None
sel = st.session_state["sel"]

p1, p2, p3 = st.columns([1.0, 1.7, 1.1], gap="medium")

# --------------------------------------------------------------------------- pane 1: inbox
with p1:
    st.subheader("Inbox", icon=":material/inbox:")
    st.caption("Mail from buyers, processed automatically")
    pending = P.mailbox.poll(conn)
    if pending:
        st.caption(f":material/pending: {len(pending)} new email(s) waiting to be processed")
    if not orders:
        st.info("No orders yet. Send an email from the buyer window "
                "(`streamlit run buyer_app.py --server.port 8502`).", icon=":material/mail:")
    for o in orders:
        with st.container(border=True, gap="small"):
            st.markdown(f"**{md_escape(o['buyer'])}** {badge_md(o['recommendation'] or None)}")
            st.caption(f"{o['order']} · {o['route']} · {md_escape(o['parts'])}  \n{STATE_LABEL.get(o['state'], o['state'])}")
            is_sel = o["order"] == sel
            st.button("Selected" if is_sel else "Open", key=f"open-{o['order']}", on_click=select, args=(o["order"],),
                      disabled=is_sel, icon=":material/radio_button_checked:" if is_sel else ":material/open_in_new:",
                      type="tertiary")

    if sel:
        st.markdown(f"**Conversation · {sel}**")
        thread = rows("SELECT direction, subject, body, received_at FROM emails WHERE order_id=? ORDER BY received_at",
                      (sel,))
        for m in thread:
            outgoing = m["direction"] == "out"
            with st.chat_message("assistant" if outgoing else "user",
                                 avatar=":material/verified_user:" if outgoing else ":material/storefront:"):
                st.caption(f"{'Clearance → buyer' if outgoing else 'Buyer → Clearance'} · {m['received_at'][11:16]}")
                st.markdown(f"**{md_escape(m['subject'])}**")
                st.markdown(md_escape(m["body"]).replace("\n", "  \n"))

# --------------------------------------------------------------------------- pane 2: processing
with p2:
    st.subheader("Processing", icon=":material/fact_check:")
    if not sel:
        st.caption("Select an order in the inbox.")
    else:
        order, d, ctx = store.load_order(conn, sel), store.load_decision(conn, sel), P.context(sel)
        ledger = Ledger(store.load_evidence(conn, sel))
        res = ctx.results
        history = store.get_state_history(conn, sel)
        when = {s.value: at for s, at in history}
        net = res.network if res else None
        net_flag = bool(net and (net.listed_staff or any(s.flagged for s in net.systems)))
        t_checks, t_crust, t_net, t_ev = st.tabs([":material/checklist: Checks", ":material/apartment: Crustdata",
                                                  (":material/hub: Network · alert" if net_flag else ":material/hub: Network"),
                                                  f":material/receipt_long: Evidence ({len(ledger)})"])

        with t_checks:
            steps = ["EMAIL_RECEIVED", "PARSED", "CLASSIFIED", "SCREENED", "CAPABILITY_CHECKED", "RECOMMENDED", "SIGNED"]
            if "AWAITING_ORDER_DETAILS" in when:
                steps.insert(2, "AWAITING_ORDER_DETAILS")
            if "AWAITING_END_USE" in when or ctx.end_use_requested:
                steps.insert(steps.index("RECOMMENDED"), "AWAITING_END_USE")
            with st.container(border=True, gap=None):
                for s in steps:
                    done = s in when
                    st.markdown(f"{':green[:material/check_circle:]' if done else ':gray[:material/radio_button_unchecked:]'} "
                                f"{STATE_LABEL[s]}" + (f" :gray[· {when[s]:%H:%M:%S}]" if done else ""))

            with st.expander("Order, as read from the email", icon=":material/description:"):
                facts = {f":material/person: {p.role.replace('_', ' ').capitalize()}":
                         f"**{md_escape(p.name)}** {p.country or ''}" + (f" · {p.domain}" if p.domain else "")
                         for p in order.parties}
                facts[":material/inventory_2: Parts"] = ", ".join(f"{l.quantity} × `{l.part_number}`" for l in order.lines) or "—"
                facts[":material/flight_takeoff: Destination"] = order.ship_to_country or "—"
                st.table(facts, border="horizontal", alt="Order details extracted from the email")

            if res and res.classifications:
                with st.expander("Parts and licence", icon=":material/inventory_2:"):
                    for c in res.classifications:
                        lic = next((l for l in res.licences if l.part_number == c.part_number), None)
                        with st.container(border=True, gap="small"):
                            if not c.found:
                                st.markdown(f"`{c.part_number}` :red-badge[Not in catalog]")
                                st.caption("Unknown parts are never guessed: the order is held.")
                                continue
                            st.markdown(f"`{c.part_number}` "
                                        + (":orange-badge[Controlled]" if c.controlled else ":green-badge[Not controlled]")
                                        + f" :gray-badge[{c.part_class or ''}] :gray-badge[ECCN {c.eccn or '—'}]")
                            st.caption(f"Engineering capability needed: {', '.join(c.needs)}")
                            if lic:
                                st.markdown((":blue-badge[Licence required] " if lic.required else ":green-badge[No licence] ")
                                            + md_escape(lic.reason))

            if res and res.screenings:
                hits = [s for s in res.screenings if s.status != "clear"]
                with st.expander("Restricted-list screening" + (f" · {len(hits)} match(es)" if hits else " · all clear"),
                                 icon=":material/gpp_maybe:" if hits else ":material/gpp_good:", expanded=bool(hits)):
                    st.dataframe(pd.DataFrame([{
                        "Party": s.party_role.replace("_", " ").capitalize(), "Name": s.party_name,
                        "Result": SCREEN[s.status][0] + (" · freight forwarder" if s.is_forwarder else ""),
                        "Closest listed name": s.matches[0].listed_name if s.matches else "—",
                        "Score": s.matches[0].score if s.matches else None,
                        "List": str(s.matches[0].listed_record.get("source", ""))[:60] if s.matches else "—"}
                        for s in res.screenings]), hide_index=True, alt="Screening result for each party",
                        column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f")})

            if ctx.end_use_requested or (res and res.end_use):
                eu = res.end_use if res else None
                with st.expander("End-use statement", icon=":material/assignment_ind:", expanded=bool(eu)):
                    if not eu:
                        st.caption(f"Requested from the buyer · follow-ups sent: {ctx.followups_sent}. Waiting for a reply.")
                    else:
                        st.table({":material/target: Claimed use": md_escape(eu.claim.claimed_use or "—"),
                                  ":material/domain: End user": md_escape(eu.claim.end_user_name or "not named")
                                  + f" {eu.claim.end_user_country or ''}",
                                  ":material/rule: Consistent": ":green-badge[Yes]" if eu.consistent else ":red-badge[No]",
                                  ":material/forward_to_inbox: Follow-ups sent": str(ctx.followups_sent)},
                                 border="horizontal", alt="End-use statement as extracted from the reply")
                        for r in eu.reasons:
                            st.markdown(f":orange[:material/error:] {md_escape(r)}")

        with t_crust:
            cap = res.buyer_capability if res else None
            snap = crustdata_snapshot(crustdata_client.get_client(), order.buyer)
            if cap is None:
                st.caption("The capability check has not run yet for this order.")
            else:
                with st.container(border=True):
                    st.markdown("**What Crustdata returned**" + (f" :{'green' if snap['source'] == 'live Crustdata' else 'gray'}"
                                                                f"-badge[{snap['source']}]" if snap["source"] else ""))
                    icons = {"Company record": ":material/apartment:", "Employees": ":material/groups:",
                             "Peer comparison": ":material/compare_arrows:", "Verdict": ":material/gavel:"}
                    for heading, sentence in crustdata_summary(snap, cap):
                        st.markdown(f"{icons.get(heading, '')} **{heading}.** {sentence}")
            if cap:
                tier_label, tier_color = TIER.get(cap.tier, (cap.tier, "gray"))
                m1, m2 = st.columns(2)
                m3, m4 = st.columns(2)
                m1.metric("Risk tier", tier_label, border=True)
                m2.metric("Score", f"{cap.mismatch_score:g}", border=True,
                          help="Points from the capability rules. 0–29 consistent, 30–59 medium, 60+ high.")
                m3.metric("Buyer type", cap.buyer_type.capitalize(), border=True)
                m4.metric("Coverage", cap.coverage.capitalize(), border=True)
                st.markdown("**Rules triggered:** " + (" ".join(f":orange-badge[{r}]" for r in cap.triggered_rules)
                                                      or ":green-badge[None]"))
            if snap["profile"]:
                st.markdown("**Company record**")
                st.table(snap["profile"], border="horizontal", alt="Company record retrieved from Crustdata")
                if snap["description"]:
                    st.caption(md_escape(snap["description"][:400]))
                if snap["by_function"]:
                    st.markdown("**Headcount by function**")
                    st.bar_chart(pd.DataFrame({"Function": list(snap["by_function"]), "Employees": list(snap["by_function"].values())}),
                                 x="Function", y="Employees", horizontal=True, height=260,
                                 alt="Number of employees in each function at the buyer")
                f = cap.features if cap else {}
                if snap["people"]:
                    st.markdown(f"**Employees sampled** · {len(snap['people'])} · "
                                f"{f.get('matching_people', '—')} match what the parts need")
                    st.dataframe(pd.DataFrame(snap["people"]), hide_index=True, height=min(320, 36 * (len(snap["people"]) + 1) + 4),
                                 alt="Employees retrieved for the background check",
                                 column_config={"Skills": st.column_config.ListColumn(),
                                                "Past employers": st.column_config.ListColumn()})
                if snap["peers"]:
                    st.markdown(f"**Peer companies** · {len(snap['peers'])}")
                    if cap and cap.percentiles:
                        st.caption("Where this buyer ranks among them: " + " · ".join(
                            f"{k.replace('_', ' ')} {v:.0f}th percentile" for k, v in cap.percentiles.items()))
                    st.dataframe(pd.DataFrame([snap["self"], *snap["peers"]]), hide_index=True,
                                 height=min(320, 36 * (len(snap["peers"]) + 2) + 4),
                                 alt="Similar companies used for the peer comparison",
                                 column_config={"Engineering share": st.column_config.ProgressColumn(
                                     min_value=0, max_value=1, format="percent"),
                                     "Headcount": st.column_config.NumberColumn(format="localized"),
                                     "Monthly visitors": st.column_config.NumberColumn(format="compact")})
            if snap["profile"]:
                with st.expander("Raw Crustdata response (company record)", icon=":material/data_object:"):
                    st.json(snap["company_data"], expanded=1)

        with t_net:
            if net is None:
                st.caption("The network check runs after the capability check.")
            else:
                with st.container(border=True):
                    st.markdown("**Across orders and buyers**")
                    icons = {"Linked buyers": ":material/hub:", "Parts across orders": ":material/memory:",
                             "Staff background": ":material/badge:"}
                    for heading, sentence in network_summary(net):
                        st.markdown(f"{icons.get(heading, '')} **{heading}.** {sentence}")
                    for alert_from in ctx.network_alerts:
                        st.markdown(f":orange[:material/notifications_active:] **Alert.** Order {alert_from}, received "
                                    f"later, completed a set together with this order.")
                if net.links:
                    st.markdown("**How the buyers are linked**")
                    st.graphviz_chart(network_dot(net), alt="Diagram of buyers linked by shared people, addresses "
                                                            "or forwarders")
                for f in net.systems:
                    with st.container(border=True):
                        st.markdown(f"**{f.system}** " + (":red-badge[Not explained by their business]" if f.flagged
                                                          else ":green-badge[Fits their business]"))
                        st.progress(f.coverage, text=f"{len(f.functions_present)} of "
                                                     f"{len(f.functions_present) + len(f.functions_missing)} functions present")
                        st.markdown(" ".join(f":blue-badge[{function_label(x)}]" for x in f.functions_present)
                                    + " " + " ".join(f":gray-badge[missing: {function_label(x)}]" for x in f.functions_missing))
                        st.caption(f"Concern: {f.concern}. Orders {', '.join(f.orders)}.")
                if net.cluster_orders:
                    marks = ",".join("?" * len(net.cluster_orders))
                    rows_ = rows(f"SELECT order_id AS 'Order', company_name AS 'Buyer', part_number AS 'Part', function, "
                                 f"quantity AS 'Qty', substr(created_at,1,16) AS 'Received' FROM network_orders "
                                 f"WHERE order_id IN ({marks}) ORDER BY created_at", tuple(net.cluster_orders))
                    for r_ in rows_:
                        r_["What it does"] = function_label(r_.pop("function") or "") or "—"
                    st.markdown("**Orders from this buyer and its linked buyers (last 180 days)**")
                    st.dataframe(pd.DataFrame(rows_), hide_index=True, alt="Recent orders across the linked buyers")

        with t_ev:
            cited = {e.id for e in d.evidence} if d else set()
            st.caption("Every fact Clearance recorded, grouped by where it came from. "
                       ":blue[:material/check:] marks the facts the recommendation cites.")
            for group, items in evidence_groups(ledger.items, cited).items():
                with st.expander(f"{group} · {len(items)}", expanded=group in ("Crustdata", "Screening", "End-use")):
                    st.table(pd.DataFrame([{"": ":blue[:material/check:]" if i["Cited"] else "", "ID": i["ID"],
                                            "What": md_escape(i["What"]), "Value": md_escape(i["Value"]),
                                            "Source": md_escape(i["Source"])} for i in items]),
                             hide_index=True, border="horizontal", alt=f"Evidence from {group.lower()}")

# --------------------------------------------------------------------------- pane 3: action
with p3:
    st.subheader("Action", icon=":material/gavel:")
    if sel:
        d = store.load_decision(conn, sel)
        state = store.get_state(conn, sel).value
        ledger = Ledger(store.load_evidence(conn, sel))
        with st.container(border=True):
            if d is None:
                st.badge(STATE_LABEL.get(state, state), color="gray", icon=":material/hourglass_top:")
                st.caption("No recommendation yet: Clearance is waiting for the buyer.")
            else:
                label, color, icon = OUTCOME[d.outcome]
                st.badge(label, color=color, icon=icon)
                st.markdown(f"**{md_escape(rule_label(d.rule_fired))}**")
                for s in d.explanation:
                    if rule_label(d.rule_fired).lower().rstrip(".") not in s.text.lower():
                        st.markdown(md_escape(s.text))
                    cites = [ledger.get(i) for i in s.evidence_ids if ledger.has(i)]
                    if cites:
                        st.caption("  \n".join(f"{e.id} · {md_escape(e.claim)}: {md_escape(readable_value(e.value))}"
                                               for e in cites[:4]))
                if d.licence_documents:
                    st.info("**Documents to collect:** " + ", ".join(d.licence_documents), icon=":material/assignment:")
                if d.signature:
                    st.success(f"Signed by {d.signature.by} · {d.signature.at:%d %b %H:%M} UTC", icon=":material/draw:")
                if d.override:
                    st.warning(f"Override by {d.override.by}: {d.override.original_outcome} → {d.override.new_outcome}. "
                               f"{d.override.reason}", icon=":material/edit_note:")
                if d.outcome == "AWAITING_END_USE":
                    st.caption("No action needed: Clearance has emailed the buyer and continues when they reply.")
                if d.outcome in ("RELEASE", "BLOCK") and state != OrderState.SIGNED.value:
                    if st.button(f"Sign {label.lower()}", type="primary", icon=":material/draw:", width="stretch",
                                 disabled=not officer, key="sign-sel"):
                        P.sign(sel, officer)
                        st.rerun()
                    if not officer:
                        st.caption("Enter your officer name in the sidebar to sign.")
                with st.container(horizontal=True):
                    with st.popover("Override", icon=":material/edit_note:", disabled=not officer):
                        new = st.selectbox("New outcome", ["RELEASE", "HOLD", "LICENCE_REQUIRED", "BLOCK"],
                                           format_func=lambda o: OUTCOME[o][0], key="ov_outcome")
                        reason = st.text_area("Reason (required, recorded in the audit)", key="ov_reason")
                        if st.button("Apply override", key="ov_apply", type="primary"):
                            try:
                                P.override(sel, new, officer, reason)
                                st.rerun()
                            except ValueError as e:
                                st.error(str(e))
                    st.download_button("Audit file", P.audit(sel), file_name=f"audit-{sel}.html", mime="text/html",
                                       icon=":material/download:")

    todo = [o for o in orders if o["recommendation"] in ("RELEASE", "BLOCK") and o["state"] == "RECOMMENDED"]
    holds = [o for o in orders if o["recommendation"] == "HOLD" and o["state"] != "SIGNED"]
    waiting = [o for o in orders if o["state"] in ("AWAITING_END_USE", "AWAITING_ORDER_DETAILS")]
    for title, icon, items in [("Ready to sign", ":material/draw:", todo), ("Exceptions", ":material/report:", holds),
                               ("Waiting on buyer", ":material/schedule_send:", waiting)]:
        with st.expander(f"{title} ({len(items)})", icon=icon, expanded=bool(items) and title != "Waiting on buyer"):
            if not items:
                st.caption("None.")
            for o in items:
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.markdown(f"{badge_md(o['recommendation'] or None)} {md_escape(o['buyer'][:28])}")
                    st.button("Open", key=f"q-{title}-{o['order']}", on_click=select, args=(o["order"],),
                              disabled=o["order"] == sel, type="tertiary", icon=":material/open_in_new:")
