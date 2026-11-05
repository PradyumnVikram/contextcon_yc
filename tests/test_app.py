"""B8: the two demo windows. Clearance (app.py) processes mail on its own; the buyer client (buyer_app.py)
sends into Clearance's inbox and shows Clearance's replies. Offline: LLM faked, Crustdata fixtures."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from clearance import config  # noqa: E402
from clearance.llm import client as llm_client  # noqa: E402
from clearance.mail import Mailbox  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RADAR = {"buyer_name": "Synthetic Radar Systems", "buyer_country": "IN", "ship_to_country": "IN",
         "lines": [{"part_number": "PA-77G-HE", "quantity": 4}]}
SHELL = {"buyer_name": "Synthetic shell Traders", "buyer_country": "IN", "ship_to_country": "AE",
         "lines": [{"part_number": "PA-77G-HE", "quantity": 100}]}
EVASIVE = {"claimed_use": "civilian use", "mapped_needs": [], "end_user_name": None, "end_user_country": None,
           "evasive": True}


def _parse(payload):
    return SHELL if "shell" in payload["email"]["body"].lower() else RADAR


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "MAILBOX_DIR", tmp_path / "mailbox")
    fake = llm_client.FakeLLM({"parse_order": _parse, "extract_end_use": [EVASIVE, EVASIVE]})
    monkeypatch.setattr("clearance.llm.make_llm", lambda conn: fake)
    return Mailbox(tmp_path / "mailbox")


def _service(env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception
    return at


def test_service_starts_empty_with_auto_processing_on(env):
    at = _service(env)
    assert at.sidebar.toggle(key="auto").value is True
    assert any("No orders yet" in i.value for i in at.info)


def test_mail_is_processed_without_clicks_and_signed(env):
    env.compose("Procurement <procurement@synthetic-radar.example>", "PO 4411", "4 pcs PA-77G-HE, Pune, India")
    at = _service(env)                                   # auto-processing picks the email up on its own
    at.sidebar.text_input(key="officer").set_value("A. Officer").run()
    next(b for b in at.button if b.label.startswith("Sign")).click().run()
    assert not at.exception
    assert any("Signed by A. Officer" in s.value for s in at.success)


def test_buyer_window_sends_and_receives(env):
    buyer = AppTest.from_file(str(ROOT / "buyer_app.py"), default_timeout=30)
    buyer.run()
    buyer.selectbox(key="b_identity").set_value("Synthetic shell Traders (demo, suspicious)").run()
    next(b for b in buyer.button if b.label == "Send").click().run()
    assert not buyer.exception and len(list(env.inbox.glob("*.eml"))) == 1

    service = _service(env)                              # Clearance processes it and emails an end-use request
    assert service.session_state["sel"] == "O0001"
    from clearance import store
    assert store.load_decision(store.connect(config.DB_PATH), "O0001").outcome == "AWAITING_END_USE"
    buyer.run()
    reply = next(b for b in buyer.button if b.label == "Reply")   # the request arrived in the buyer's inbox
    reply.click().run()
    assert buyer.text_input(key="b_subj").value.startswith("Re: [CLR-O0001]")
    buyer.selectbox(key="b_reply_tpl").set_value("Evasive: 'civilian use only'").run()
    next(b for b in buyer.button if b.label == "Send").click().run()
    service.run()                                        # evasive reply -> one follow-up, still waiting
    buyer.run()
    assert sum(b.label == "Reply" for b in buyer.button) == 2


def test_buyer_inbox_shows_replies_even_after_switching_identity(env):
    env.send("Procurement <procurement@astramwp.com>", "[CLR-O0001] Additional order details needed", "Destination?")
    buyer = AppTest.from_file(str(ROOT / "buyer_app.py"), default_timeout=30)
    buyer.run()
    buyer.selectbox(key="b_identity").set_value("Synthetic shell Traders (demo, suspicious)").run()
    assert any("Additional order details needed" in m.value for m in buyer.markdown)   # not hidden by the switch
    next(b for b in buyer.button if b.label == "Reply").click().run()
    assert buyer.text_input(key="b_from").value == "Procurement <procurement@astramwp.com>"  # replies as the addressee
