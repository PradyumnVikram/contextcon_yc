"""HTML audit file (task B6): everything a reviewer needs to reconstruct the recommendation."""
from __future__ import annotations

import json
from html import escape

from clearance.decision.rules import RULES_BY_ID
from clearance.evidence import Ledger
from clearance.llm import validate
from clearance.models import Decision, Order

_CSS = """
body{font:14px/1.5 system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1d1d1f}
h1{font-size:22px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #ddd}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}
.o{display:inline-block;padding:2px 10px;border-radius:4px;font-weight:600;background:#eee}
.RELEASE{background:#d7f5dd}.HOLD{background:#fff1c2}.BLOCK{background:#ffd6d6}.LICENCE_REQUIRED{background:#dbe8ff}
code{font-size:12px}small{color:#666}
"""


def _v(value) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return escape(s if len(s) <= 300 else s[:297] + "...")


def audit_html(order: Order, decision: Decision, ledger: Ledger) -> str:
    rule = RULES_BY_ID.get(decision.rule_fired)
    cited = {e.id for e in decision.evidence}
    rows = []
    rows.append(f"<h1>Clearance audit: order {escape(order.order_id)}</h1>")
    rows.append(f"<p><span class='o {decision.outcome}'>{decision.outcome}</span> "
                f"<code>{escape(decision.rule_fired)}</code> {escape(rule.label if rule else '')}</p>")
    if decision.signature:
        rows.append(f"<p>Signed by <b>{escape(decision.signature.by)}</b> at {decision.signature.at:%Y-%m-%d %H:%M} UTC</p>")
    if ov := decision.override:
        rows.append(f"<p><b>Override</b> by {escape(ov.by)} at {ov.at:%Y-%m-%d %H:%M} UTC: "
                    f"{ov.original_outcome} ({escape(ov.original_rule)}) → <b>{ov.new_outcome}</b>. "
                    f"Reason: {escape(ov.reason)}</p>")

    rows.append("<h2>Explanation</h2><ul>")
    try:
        rendered = validate.render(decision.explanation, ledger)
    except KeyError:
        rendered = [s.text for s in decision.explanation]
    rows += [f"<li>{escape(s)}</li>" for s in rendered]
    rows.append("</ul>")

    rows.append("<h2>Order</h2><table><tr><th>Role</th><th>Name</th><th>Country</th><th>Address</th></tr>")
    rows += [f"<tr><td>{p.role}</td><td>{escape(p.name)}</td><td>{p.country or ''}</td><td>{escape(p.address or '')}</td></tr>"
             for p in order.parties]
    rows.append("</table><table><tr><th>Part</th><th>Qty</th></tr>")
    rows += [f"<tr><td>{escape(l.part_number)}</td><td>{l.quantity}</td></tr>" for l in order.lines]
    rows.append(f"</table><p>Destination: {order.ship_to_country}. Stated purpose: {escape(order.stated_purpose or '-')}</p>")

    if decision.licence_documents:
        rows.append("<h2>Licence documents to collect</h2><ul>"
                    + "".join(f"<li>{escape(d)}</li>" for d in decision.licence_documents) + "</ul>")
    if decision.rules_triggered:
        rows.append("<h2>Capability rules triggered</h2><p>"
                    + ", ".join(f"<code>{escape(r)}</code>" for r in decision.rules_triggered) + "</p>")

    rows.append("<h2>State history</h2><table><tr><th>State</th><th>At (UTC)</th></tr>")
    rows += [f"<tr><td>{s.value}</td><td>{at:%Y-%m-%d %H:%M:%S}</td></tr>" for s, at in decision.state_history]
    rows.append("</table>")

    rows.append("<h2>Evidence</h2><table><tr><th>ID</th><th>Claim</th><th>Value</th><th>Source</th><th>Fetched</th></tr>")
    for e in ledger.items:
        mark = " <b>★</b>" if e.id in cited else ""
        rows.append(f"<tr><td>{e.id}{mark}</td><td>{escape(e.claim)}</td><td>{_v(e.value)}</td>"
                    f"<td><code>{escape(e.source)}</code></td><td>{e.fetched_at:%Y-%m-%d %H:%M}</td></tr>"
                    if e.fetched_at else
                    f"<tr><td>{e.id}{mark}</td><td>{escape(e.claim)}</td><td>{_v(e.value)}</td>"
                    f"<td><code>{escape(e.source)}</code></td><td></td></tr>")
    rows.append("</table><p><small>★ cited by the recommendation. Clearance is a prototype and not legal advice; "
                "a qualified person signs every release and block.</small></p>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Audit {escape(order.order_id)}</title>"
            f"<style>{_CSS}</style></head><body>{''.join(rows)}</body></html>")
