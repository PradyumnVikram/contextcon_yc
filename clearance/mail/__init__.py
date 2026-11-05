"""Folder mailbox, order-email parsing, reply matching. OWNER: Person B (task B3)."""
from clearance.mail.mailbox import COMPLIANCE_ADDRESS, Mailbox
from clearance.mail.parse import match_reply, merge_details, missing_details_email, parse_order, tag

__all__ = ["COMPLIANCE_ADDRESS", "Mailbox", "match_reply", "merge_details", "missing_details_email",
           "parse_order", "tag"]
