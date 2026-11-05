"""Headless inbox worker (Person B): processes new mail continuously, no clicks needed.

    python -m clearance.worker              # poll mailbox/inbox every 3 s, print what happened
    python -m clearance.worker --once       # process what's there now and exit

Replies are linked to their order automatically by the [CLR-<id>] subject tag or by In-Reply-To.
The Streamlit app has the same behaviour behind its "Auto-process inbox" toggle.
"""
from __future__ import annotations

import argparse
import logging
import time

from clearance import config, store
from clearance.llm import make_llm
from clearance.mail import Mailbox
from clearance.pipeline import Pipeline

log = logging.getLogger("clearance.worker")


def run_once(p: Pipeline) -> list[str]:
    """Process every new inbox email once. Returns the order ids touched."""
    return p.process_inbox()


def describe(p: Pipeline, oid: str) -> str:
    d = store.load_decision(p.conn, oid)
    state = store.get_state(p.conn, oid).value
    return f"{oid}: {state}" + (f" -> {d.outcome} ({d.rule_fired})" if d else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    conn = store.connect(config.DB_PATH)
    p = Pipeline(conn, make_llm(conn), Mailbox(config.MAILBOX_DIR))
    log.info("watching %s (LLM: %s)", p.mailbox.inbox, config.LLM_PROVIDER)
    while True:
        for oid in run_once(p):
            log.info(describe(p, oid))
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
