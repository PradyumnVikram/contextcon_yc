"""The §4.8 decision table as data (task B6). First rule whose predicate fires wins.

Each predicate returns the evidence IDs that justify it (a non-empty list, or [] for "fires with no specific
evidence"), or None when the rule does not apply. Thresholds live in config.py / Person A's modules;
this table only reads their typed results.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from clearance.models import Order, OrderResults, Outcome, ScreeningResult


@dataclass(frozen=True)
class Rule:
    id: str
    outcome: Outcome
    label: str
    when: Callable[[Order, OrderResults], list[str] | None]


def _all_screens(r: OrderResults) -> list[ScreeningResult]:
    s = list(r.screenings)
    if r.end_use and r.end_use.end_user_screening:
        s.append(r.end_use.end_user_screening)
    return s


def _ids(items) -> list[str]:
    return [i for it in items for i in it.evidence_ids]


def _some(items) -> list[str] | None:
    return _ids(items) if items else None


def _cap_ids(r: OrderResults) -> list[str]:
    return list(r.buyer_capability.evidence_ids) if r.buyer_capability else []


_CANNOT_USE = {"O1_quantity_vs_technical_staff", "D4_large_order_small_distributor", "C1_not_a_technical_business"}


def _diversion(r: OrderResults) -> list[str] | None:
    """A controlled quantity the buyer cannot use stays a hold after the letter."""
    cap = r.buyer_capability
    if not cap or not r.end_use or not r.end_use.consistent:
        return None
    if not any(c.controlled for c in r.classifications):
        return None
    if not _CANNOT_USE.intersection(cap.triggered_rules):
        return None
    return _cap_ids(r) + r.end_use.evidence_ids


def _order_red_flag(o: Order) -> bool:
    buyer = o.buyer.country or ""
    payer = (o.payer_country or "").upper()
    return bool(o.unusual_premium or o.virtual_or_residential_ship_to or (payer and payer != buyer.upper()))


RULES: list[Rule] = [
    Rule("R1_exact_list_hit", "BLOCK", "A party exactly matches the US Consolidated Screening List",
         lambda o, r: _some([s for s in _all_screens(r) if s.status == "exact_hit"])),
    Rule("R2_unknown_part", "HOLD", "A part is not in the catalog, so it cannot be classified",
         lambda o, r: _some([c for c in r.classifications if not c.found])),
    Rule("R3_fuzzy_list_hit", "HOLD", "A party closely resembles a listed entity",
         lambda o, r: _some([s for s in _all_screens(r) if s.status == "fuzzy_hit"])),
    Rule("R4_forwarder_end_user", "HOLD", "The named end user is a freight forwarder",
         lambda o, r: _some([s for s in _all_screens(r) if s.party_role == "end_user" and s.is_forwarder])),
    Rule("R5_order_incomplete", "HOLD", "Order details are still incomplete after asking the buyer",
         lambda o, r: [] if r.order_incomplete else None),
    Rule("R5b_order_red_flags", "HOLD", "The order itself has a red flag the data cannot clear",
         lambda o, r: [] if _order_red_flag(o) else None),
    Rule("R6_no_or_thin_coverage", "HOLD", "No or thin company data: end-use statement requested, officer decides",
         lambda o, r: (_cap_ids(r) + (r.end_use.evidence_ids if r.end_use else []))
         if r.buyer_capability and r.buyer_capability.coverage in ("missing", "thin") else None),
    Rule("R7_end_use_needed", "AWAITING_END_USE", "Capability risk: an end-use statement is required",
         lambda o, r: _cap_ids(r) if (r.buyer_capability and r.buyer_capability.tier in ("medium_risk", "high_risk")
                                     and r.end_use is None and not r.llm_unavailable) else None),
    Rule("R8_end_use_inconsistent", "HOLD", "The end-use statement is inconsistent, vague or evasive",
         lambda o, r: r.end_use.evidence_ids if r.end_use and not r.end_use.consistent else None),
    Rule("R9_high_risk_despite_end_use", "HOLD", "End-use is consistent but the buyer remains high risk",
         lambda o, r: _cap_ids(r) + r.end_use.evidence_ids
         if r.end_use and r.buyer_capability and r.buyer_capability.tier == "high_risk" else None),
    Rule("R9b_buyer_cannot_use_quantity", "HOLD",
         "The buyer is not equipped for this controlled quantity; naming a use does not clear it",
         lambda o, r: _diversion(r)),
    Rule("R10_llm_unavailable", "HOLD", "Claude was unavailable for a required step",
         lambda o, r: [] if r.llm_unavailable else None),
    Rule("R11_licence_required", "LICENCE_REQUIRED", "An export licence is required for this destination",
         lambda o, r: _some([l for l in r.licences if l.required])),
    Rule("R12_release", "RELEASE", "All checks passed",
         lambda o, r: _ids(r.classifications) + _ids(r.screenings) + _cap_ids(r)
         + (r.end_use.evidence_ids if r.end_use else [])),
]

RULES_BY_ID = {r.id: r for r in RULES}


def first_match(order: Order, results: OrderResults) -> tuple[Rule, list[str]]:
    for rule in RULES:
        ids = rule.when(order, results)
        if ids is not None:
            return rule, list(dict.fromkeys(ids))
    raise AssertionError("R12 always matches")  # pragma: no cover
