"""Simulated buyer mail client: the "other side" of the demo.  Run:  streamlit run buyer_app.py --server.port 8502

Write an email as any buyer (use a real company address such as procurement@astramwp.com so Crustdata looks
the company up), hit Send, and it lands in Clearance's inbox (the other window). Whatever Clearance sends back
to that address (missing-details requests, end-use requests, follow-ups) appears here; reply from here.
Both windows share the mailbox/ folders (config.MAILBOX_DIR).
"""
from __future__ import annotations

from email.utils import parseaddr
import streamlit as st

from clearance import config
from clearance.mail import COMPLIANCE_ADDRESS, Mailbox
from clearance.ui import md_escape

st.set_page_config(page_title="Buyer mail", page_icon=":material/mail:", layout="wide")
REFRESH_S = 3

# Real companies only in clean scenarios (ethics rule); suspicious buyers stay synthetic.
IDENTITIES = {
    "Astra Microwave (REAL, live Crustdata)": "Procurement <procurement@astramwp.com>",
    "Data Patterns (REAL, live Crustdata)": "Purchase Team <purchase@datapatternsindia.com>",
    "Synthetic Radar Systems (demo)": "Procurement <procurement@synthetic-radar.example>",
    "Synthetic shell Traders (demo, suspicious)": "Orders <orders@synthetic-shell.example>",
    "Synthetic nodata Enterprises (demo, unknown)": "Buyer <buy@synthetic-nodata.example>",
    "Listed Electronic Tradng (demo, near a listed name)": "Info <info@listed-tradng.example>",
    "Ring 1 · Synthetic Orbit Electronics (demo network)": "Purchasing <purchasing@orbit-electronics.example>",
    "Ring 2 · Synthetic Nimbus Instruments (demo network)": "Stores <stores@nimbus-instruments.example>",
    "Ring 3 · Synthetic Delta Systems (demo network)": "Projects <projects@delta-systems.example>",
    "Synthetic Apex Components (demo, staff from a listed entity)": "MD Office <md@apex-components.example>",
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
    # The ring: each order is small and routine on its own (licence paperwork only). Send all three, in order.
    "Ring 1 · Synthetic Orbit Electronics (demo network)": (
        "PO 3307: amplifiers for calibration bench",
        "Hello,\nPlease supply 6 pcs PA-77G-HE for our calibration bench.\nShip via Gulf Swift Cargo FZE to "
        "Warehouse 14, Jebel Ali Free Zone, Dubai, UAE.\n\nSynthetic Orbit Electronics, Pune, India"),
    "Ring 2 · Synthetic Nimbus Instruments (demo network)": (
        "Spares order: LNA-77G-HE",
        "Dear team,\nWe need 6 x LNA-77G-HE as instrument spares.\nShip via Gulf Swift Cargo FZE to "
        "Warehouse 14, Jebel Ali Free Zone, Dubai, UAE.\n\nSynthetic Nimbus Instruments, Mumbai, India"),
    "Ring 3 · Synthetic Delta Systems (demo network)": (
        "PO D-118: high-speed ADCs",
        "Hi,\nPlease send 8 x ADC-12G-HE for a client design project.\nDelivery to Warehouse 14, Jebel Ali Free "
        "Zone, Dubai, UAE, via Gulf Swift Cargo FZE.\n\nSynthetic Delta Systems, Delhi, India"),
    "Synthetic Apex Components (demo, staff from a listed entity)": (
        "PO AX-52: FPGAs",
        "Please supply 20 x FPGA-C10 for our motor-drive controllers. Deliver to our Bengaluru plant.\n\n"
        "Synthetic Apex Components, Bengaluru, India"),
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
    """Reply as the buyer the message was addressed to (not whoever is in the compose box)."""
    ss.update(b_from=e.to_addr, b_subj=e.subject if e.subject.lower().startswith("re:") else f"Re: {e.subject}",
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


st.title("Buyer mail", icon=":material/mail:")
st.caption(f"You are writing to {COMPLIANCE_ADDRESS}, the exporter's compliance desk (the Clearance window). "
           "Real company addresses are looked up live in Crustdata by their email domain.")

left, right = st.columns([1, 1], gap="large")

with left:
    with st.container(border=True):
        replying = ss["b_reply_to"]
        st.subheader("Reply" if replying else "New message", icon=":material/reply:" if replying else ":material/edit_square:")
        if not replying:
            st.selectbox("Write as", list(IDENTITIES), key="b_identity", on_change=_pick_identity)
        st.text_input("From", key="b_from")
        st.markdown(f"**To:** {COMPLIANCE_ADDRESS}")
        st.text_input("Subject", key="b_subj")
        if replying:
            st.selectbox("Quick answer", list(REPLIES), key="b_reply_tpl", on_change=_reply_tpl)
        st.text_area("Message", key="b_body", height=220)
        with st.container(horizontal=True):
            st.button("Send", type="primary", icon=":material/send:", on_click=_send)
            if replying:
                st.button("Cancel reply", icon=":material/close:",
                          on_click=lambda: ss.update(b_reply_to=None, b_subj="", b_body=""))
        if err := ss.pop("b_error", None):
            st.error(err, icon=":material/error:")
        if sent := ss.pop("b_sent", None):
            st.success(f"Sent “{sent}”. Watch the Clearance window.", icon=":material/check_circle:")


@st.fragment(run_every=f"{REFRESH_S}s")
def inbox() -> None:
    """Every buyer's mail from the compliance desk, independent of the compose box; optional per-address filter."""
    received = mb.outbox_messages()
    addresses = sorted({addr(e.to_addr) for e in received})
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.subheader("Inbox", icon=":material/inbox:")
        show = st.selectbox("Show mail for", ["All buyers"] + addresses, key="b_filter")
    if show != "All buyers":
        received = [e for e in received if addr(e.to_addr) == show]
    seen = ss.setdefault("b_seen", set())
    if not received:
        st.caption("Nothing yet. Replies from the compliance desk appear here automatically.")
    for e in reversed(received):
        new = e.msg_id not in seen
        with st.container(border=True, gap="small"):
            st.markdown(f"**{md_escape(e.subject)}**" + (" :blue-badge[New]" if new else ""))
            st.caption(f"To {md_escape(e.to_addr)} · from {e.from_addr} · {e.received_at:%d %b %H:%M}")
            st.markdown(md_escape(e.body).replace("\n", "  \n"))
            st.button("Reply", key=f"r-{e.msg_id}", on_click=_reply, args=(e,), icon=":material/reply:")
        seen.add(e.msg_id)
    sent = [m for path in sorted(mb.inbox.glob("*.eml")) if (m := mb.read_eml(path))]
    with st.expander(f"Sent to the compliance desk ({len(sent)})", icon=":material/outbox:"):
        for m in reversed(sent):
            st.markdown(f"**{md_escape(m.subject)}**  \n{md_escape(m.from_addr)} · {m.received_at:%d %b %H:%M}")
    st.caption(f":material/schedule: Refreshes every {REFRESH_S}s")


with right:
    inbox()
