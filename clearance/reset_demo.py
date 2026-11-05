"""Reset the demo: clear orders, mail and customers, but KEEP the paid Crustdata/LLM caches.

    python -m clearance.reset_demo
"""
from __future__ import annotations

from clearance import config, store

CLEARED = ["orders", "state_history", "evidence", "emails", "customers", "order_context"]


def main() -> int:
    conn = store.connect(config.DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS order_context (order_id TEXT PRIMARY KEY, context_json TEXT)")
    for t in CLEARED:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    removed = 0
    for folder in ("inbox", "outbox"):
        for f in (config.MAILBOX_DIR / folder).glob("*.eml"):
            f.unlink()
            removed += 1
    kept = conn.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0]
    print(f"cleared {', '.join(CLEARED)} and {removed} emails; kept {kept} cached API responses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
