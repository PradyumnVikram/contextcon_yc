"""Simulated buyer mail client: the "other side" of the demo.  Run:  streamlit run buyer_app.py --server.port 8502

Write an email as any buyer (use a real company address such as procurement@astramwp.com so Crustdata looks
the company up), hit Send, and it lands in Clearance's inbox (the other window). Whatever Clearance sends back
to that address (missing-details requests, end-use requests, follow-ups) appears here; reply from here.
Both windows share the mailbox/ folders (config.MAILBOX_DIR).
"""
from __future__ import annotations

from email.utils import parseaddr
from html import escape

import streamlit as st

from clearance import config
from clearance.mail import COMPLIANCE_ADDRESS, Mailbox

st.set_page_config(page_title="Buyer mail", page_icon="✉️", layout="wide")
REFRESH_S = 3

st.markdown("""
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 1.2rem; max-width: 1150px;}
.mail {border:1px solid #e5e7eb; border-radius:10px; padding:10px 13px; margin-bottom:8px; background:#fff;}
.mail.new {border-color:#6366f1; box-shadow:0 0 0 2px #e0e7ff;}
.from {font-size:0.8rem; color:#6b7280;}
.subj {font-weight:650; margin:2px 0 4px;}
.body {white-space:pre-wrap; font-size:0.9rem; line-height:1.5;}
.tag {display:inline-block; font-size:0.7rem; padding:0 7px; border-radius:999px; background:#eef2ff; color:#4338ca;}
</style>
""", unsafe_allow_html=True)

# Real companies only in clean scenarios (ethics rule); suspicious buyers stay synthetic.
IDENTITIES = {
    "Astra Microwave (REAL, live Crustdata)": "Procurement <procurement@astramwp.com>",
    "Data Patterns (REAL, live Crustdata)": "Purchase Team <purchase@datapatternsindia.com>",
    "Synthetic Radar Systems (demo)": "Procurement <procurement@synthetic-radar.example>",
    "Synthetic shell Traders (demo, suspicious)": "Orders <orders@synthetic-shell.example>",
    "Synthetic nodata Enterprises (demo, unknown)": "Buyer <buy@synthetic-nodata.example>",
    "Listed Electronic Tradng (demo, near a listed name)": "Info <info@listed-tradng.example>",
    "Custom address…": "",
}
TEMPLATES = {
    "Astra Microwave (REAL, live Crustdata)": (
        "PO AMP-2291: PA-77G-HE",
        "Dear Sir/Madam,\n\nPlease supply 4 pcs PA-77G-HE for our radar front-end test bench.\n"
        "Delivery to our Hyderabad facility.\n\nRegards,\nProcurement\nAstra Microwave Products Limited\nHyderabad, India"),
    "Data Patterns (REAL, live Crustdata)": (
        "Order DP-7710: ADC-12G-HE for Germany",
        "Hello,\n\nWe need 10 x ADC-12G-HE delivered to our partner's integration lab in Munich, Germany.\n\n"
        "Purchase Team\nData Patterns (India) Limited\nChennai, India"),
    "Synthetic Radar Systems (demo)": (
        "PO 4411: mmWave amplifiers",
        "Hello,\n\nPlease supply 4 pcs PA-77G-HE for our radar test bench.\n"
        "Synthetic Radar Systems Pvt Ltd, Pune, India. Deliver to our Pune lab.\n\nRegards, Procurement"),
    "Synthetic shell Traders (demo, suspicious)": (
        "Urgent order PA-77G-HE",
        "Need 100 pcs PA-77G-HE asap. Synthetic shell Traders, Mumbai, India.\n"
        "Deliver to our warehouse in Dubai, UAE. Pay advance."),
    "Synthetic nodata Enterprises (demo, unknown)": (
        "Enquiry + PO ADC-12G-HE",
        "Please send 10 x ADC-12G-HE. Synthetic nodata Enterprises, Delhi, India. Deliver Delhi."),
    "Listed Electronic Tradng (demo, near a listed name)": (
        "PO ADC", "10 x ADC-12G-HE please. Listed Electronic Tradng LLC, Dubai, UAE. Deliver Dubai."),
}
REPLIES = {
    "(write my own)": "",
    "Evasive: 'civilian use only'": "Dear sir, the goods are for civilian use only. Our customer will collect from "
                                    "Jebel Ali. Kindly dispatch at the earliest.",
    "Still vague": "As already told, civilian purpose. Please ship urgently, payment is ready.",
    "Names a capable end user (REAL)": "The parts are for Astra Microwave Products Limited, Hyderabad, India, "
                                       "for their radar front-end test bench.",
    "Names a freight forwarder": "Please consign the parts to Fast Freight Logistics LLC, Dubai, UAE, who will handle "
                                 "onward delivery to our customer.",
    "Gives the missing destination": "The delivery destination is India: our Hyderabad facility.",
}

mb = Mailbox(config.MAILBOX_DIR)
ss = st.session_state
for k, v in {"b_from": IDENTITIES[next(iter(IDENTITIES))], "b_subj": "", "b_body": "", "b_reply_to": None,
             "b_identity": next(iter(IDENTITIES))}.items():
    ss.setdefault(k, v)


def addr(s: str) -> str:
    return parseaddr(s or "")[1].lower()


def _pick_identity() -> None:
    who = ss["b_identity"]
    if IDENTITIES[who]:
        ss["b_from"] = IDENTITIES[who]
    subj, body = TEMPLATES.get(who, ("", ""))
    ss.update(b_subj=subj, b_body=body, b_reply_to=None)


def _reply(e) -> None:
    ss.update(b_subj=e.subject if e.subject.lower().startswith("re:") else f"Re: {e.subject}",
              b_body="", b_reply_to=e.msg_id, b_reply_tpl="(write my own)")


def _reply_tpl() -> None:
    ss["b_body"] = REPLIES[ss["b_reply_tpl"]]


def _send() -> None:
    if not ss["b_subj"].strip() or not ss["b_body"].strip():
        ss["b_error"] = "Subject and message are required."
        return
    mb.compose(ss["b_from"], ss["b_subj"], ss["b_body"], in_reply_to=ss["b_reply_to"])
    ss["b_sent"] = ss["b_subj"]
    ss.update(b_subj="", b_body="", b_reply_to=None)


st.markdown("### ✉️ Buyer mail")
st.caption(f"You are writing to **{COMPLIANCE_ADDRESS}**, the exporter's compliance desk (the Clearance window).")

left, right = st.columns([1, 1], gap="large")

with left:
    with st.container(border=True):
        replying = ss["b_reply_to"]
        st.markdown("**↩️ Reply**" if replying else "**New message**")
        if not replying:
            st.selectbox("Write as", list(IDENTITIES), key="b_identity", on_change=_pick_identity,
                         help="REAL companies are looked up live in Crustdata by their email domain.")
        st.text_input("From", key="b_from")
        st.text_input("To", COMPLIANCE_ADDRESS, disabled=True)
        st.text_input("Subject", key="b_subj")
        if replying:
            st.selectbox("Quick answer", list(REPLIES), key="b_reply_tpl", on_change=_reply_tpl)
        st.text_area("Message", key="b_body", height=220)
        c1, c2 = st.columns([1, 1])
        c1.button("Send ➤", type="primary", on_click=_send, width="stretch")
        if replying:
            c2.button("Cancel reply", on_click=lambda: ss.update(b_reply_to=None, b_subj="", b_body=""), width="stretch")
        if err := ss.pop("b_error", None):
            st.error(err)
        if sent := ss.pop("b_sent", None):
            st.success(f"Sent “{sent}”. Watch the Clearance window.")


@st.fragment(run_every=f"{REFRESH_S}s")
def inbox() -> None:
    me = addr(ss["b_from"])
    received = [e for e in mb.outbox_messages() if addr(e.to_addr) == me]
    sent = [m for path in sorted(mb.inbox.glob("*.eml")) if addr((m := mb.read_eml(path)).from_addr) == me]
    seen = ss.setdefault("b_seen", set())
    st.markdown(f"**Inbox · {escape(me) or 'no address'}** · {len(received)}")
    if not received:
        st.caption("Nothing yet. Replies from the compliance desk appear here automatically.")
    for e in reversed(received):
        new = e.msg_id not in seen
        st.markdown(f"<div class='mail{' new' if new else ''}'><div class='from'>From {escape(e.from_addr)} · "
                    f"{e.received_at:%d %b %H:%M}{' · <span class=tag>new</span>' if new else ''}</div>"
                    f"<div class='subj'>{escape(e.subject)}</div><div class='body'>{escape(e.body)}</div></div>",
                    unsafe_allow_html=True)
        st.button("↩️ Reply", key=f"r-{e.msg_id}", on_click=_reply, args=(e,))
        seen.add(e.msg_id)
    with st.expander(f"Sent ({len(sent)})"):
        for e in reversed(sent):
            st.markdown(f"<div class='from'>{e.received_at:%d %b %H:%M}</div><div class='subj'>{escape(e.subject)}</div>",
                        unsafe_allow_html=True)
    st.caption(f"⏱️ refreshes every {REFRESH_S}s")


with right:
    inbox()
