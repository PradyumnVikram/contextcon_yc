"""Folder-based mailbox (task B3). Inbox/outbox are directories of .eml files.

The demo's "compose test email" panel writes into the inbox; the poller picks up files it has not seen.
"""
from __future__ import annotations

import sqlite3
import uuid
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

from clearance import config
from clearance.models import Email, utcnow

COMPLIANCE_ADDRESS = "compliance@exporter.example"


class Mailbox:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or config.MAILBOX_DIR)
        self.inbox = self.root / "inbox"
        self.outbox = self.root / "outbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)

    # --- files --------------------------------------------------------------
    @staticmethod
    def _to_eml(e: Email) -> bytes:
        m = EmailMessage()
        m["Message-ID"] = e.msg_id
        m["From"] = e.from_addr
        m["To"] = e.to_addr
        m["Subject"] = e.subject
        m["Date"] = format_datetime(e.received_at)
        if e.in_reply_to:
            m["In-Reply-To"] = e.in_reply_to
        m.set_content(e.body)
        return m.as_bytes(policy=policy.SMTP)

    @staticmethod
    def read_eml(path: Path) -> Email:
        m = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body_part = m.get_body(preferencelist=("plain",))
        body = body_part.get_content() if body_part else ""
        date = m["Date"]
        return Email(
            msg_id=str(m["Message-ID"] or f"<{path.stem}@local>").strip(),
            from_addr=str(m["From"] or ""),
            to_addr=str(m["To"] or ""),
            subject=str(m["Subject"] or ""),
            body=body.strip(),
            in_reply_to=str(m["In-Reply-To"]).strip() if m["In-Reply-To"] else None,
            received_at=parsedate_to_datetime(date) if date else utcnow(),
        )

    def _write(self, folder: Path, e: Email) -> Path:
        stamp = e.received_at.strftime("%Y%m%dT%H%M%S%f")
        path = folder / f"{stamp}-{uuid.uuid4().hex[:6]}.eml"
        path.write_bytes(self._to_eml(e))
        return path

    # --- public API ---------------------------------------------------------
    def compose(self, from_addr: str, subject: str, body: str, in_reply_to: str | None = None) -> Email:
        """Simulate an incoming email (demo panel / tests)."""
        e = Email(msg_id=f"<{uuid.uuid4().hex}@buyer.example>", from_addr=from_addr, to_addr=COMPLIANCE_ADDRESS,
                  subject=subject, body=body, in_reply_to=in_reply_to)
        self._write(self.inbox, e)
        return e

    def send(self, to_addr: str, subject: str, body: str, in_reply_to: str | None = None) -> Email:
        """'Send' an email by writing it to the outbox."""
        e = Email(msg_id=f"<{uuid.uuid4().hex}@exporter.example>", from_addr=COMPLIANCE_ADDRESS, to_addr=to_addr,
                  subject=subject, body=body, in_reply_to=in_reply_to)
        self._write(self.outbox, e)
        return e

    def poll(self, conn: sqlite3.Connection) -> list[Email]:
        """Inbox emails not yet recorded in the `emails` table, oldest first."""
        seen = {r["msg_id"] for r in conn.execute("SELECT msg_id FROM emails WHERE direction='in'")}
        new = []
        for path in sorted(self.inbox.glob("*.eml")):
            e = self.read_eml(path)
            if e.msg_id not in seen:
                new.append(e)
                seen.add(e.msg_id)
        return new

    def outbox_messages(self) -> list[Email]:
        return [self.read_eml(p) for p in sorted(self.outbox.glob("*.eml"))]
