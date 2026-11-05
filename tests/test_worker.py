"""Inbox worker: processes new mail without any clicks, and replies link back to their order."""
from clearance import store
from clearance.llm import FakeLLM
from clearance.mail import Mailbox
from clearance.models import OrderState
from clearance.pipeline import Pipeline
from clearance.worker import run_once

SHELL = {"buyer_name": "Synthetic shell Traders", "buyer_country": "IN", "ship_to_country": "AE",
         "lines": [{"part_number": "PA-77G-HE", "quantity": 100}]}
EVASIVE = {"claimed_use": "civilian use", "mapped_needs": [], "end_user_name": None, "end_user_country": None,
           "evasive": True}


def test_worker_runs_whole_end_use_loop_from_mail_alone(tmp_path):
    conn = store.connect(":memory:")
    mb = Mailbox(tmp_path)
    p = Pipeline(conn, FakeLLM({"parse_order": SHELL, "extract_end_use": [EVASIVE, EVASIVE]}), mb)

    mb.compose("x@shell.example", "Urgent order", "100 pcs PA-77G-HE")
    [oid] = run_once(p)
    assert store.get_state(conn, oid) is OrderState.AWAITING_END_USE
    assert run_once(p) == []                       # nothing new -> nothing done

    req = mb.outbox_messages()[-1]                 # buyer replies to OUR email: plain "Re:" subject + In-Reply-To
    mb.compose("x@shell.example", "Re: your email", "civilian use only", in_reply_to=req.msg_id)
    assert run_once(p) == [oid]                    # linked by In-Reply-To, follow-up sent
    followup = mb.outbox_messages()[-1]
    mb.compose("x@shell.example", f"Re: {followup.subject}", "civilian, ship fast")   # linked by [CLR-id] tag
    assert run_once(p) == [oid]
    assert store.load_decision(conn, oid).rule_fired == "R8_end_use_inconsistent"
