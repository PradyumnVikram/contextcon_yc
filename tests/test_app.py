"""B8: the Streamlit app renders every screen and processes an order end to end (offline, Claude faked)."""
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from clearance import config  # noqa: E402
from clearance.llm import client as llm_client  # noqa: E402
from pathlib import Path  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "app.py"

PARSED = {"buyer_name": "Synthetic Radar Systems", "buyer_country": "IN", "ship_to_country": "IN",
          "lines": [{"part_number": "PA-77G-HE", "quantity": 4}]}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "MAILBOX_DIR", tmp_path / "mailbox")
    fake = llm_client.FakeLLM({"parse_order": PARSED})
    monkeypatch.setattr("clearance.llm.ClaudeLLM", lambda conn: fake)
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception
    return at


def test_every_screen_renders(app):
    for label in app.sidebar.radio[0].options:
        app.sidebar.radio[0].set_value(label).run()
        assert not app.exception, label


def test_compose_process_sign(app):
    app.sidebar.text_input[0].set_value("A. Officer").run()
    app.selectbox[0].set_value("Radar firm order (clean)").run()
    next(b for b in app.button if b.label == "Drop into inbox").click().run()
    next(b for b in app.sidebar.button if "Process inbox" in b.label).click().run()
    assert not app.exception
    app.sidebar.radio[0].set_value(next(o for o in app.sidebar.radio[0].options if o.startswith("Ready"))).run()
    sign = next(b for b in app.button if b.label.startswith("✍️ Sign RELEASE"))
    sign.click().run()
    assert not app.exception
    app.sidebar.radio[0].set_value("Customers").run()
    assert "Synthetic Radar Systems" in app.dataframe[0].value.to_string()
