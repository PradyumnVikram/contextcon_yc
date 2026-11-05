"""Shared contracts. SHARED FILE, FROZEN: any change needs both teammates and its own commit on main.

Every module returns these models, never raw API JSON. See AGENTS_*.md §5.1.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Enums / literals ---------------------------------------------------------
PartyRole = Literal["buyer", "ship_to", "middleman", "shipper", "end_user"]
ScreenStatus = Literal["clear", "fuzzy_hit", "exact_hit"]
Coverage = Literal["missing", "thin", "rich"]
BuyerType = Literal["manufacturer", "distributor", "unclear"]
Tier = Literal["consistent", "medium_risk", "high_risk", "no_data"]
Outcome = Literal["RELEASE", "HOLD", "LICENCE_REQUIRED", "BLOCK", "AWAITING_END_USE"]


class OrderState(str, Enum):
    EMAIL_RECEIVED = "EMAIL_RECEIVED"
    PARSED = "PARSED"
    AWAITING_ORDER_DETAILS = "AWAITING_ORDER_DETAILS"
    CLASSIFIED = "CLASSIFIED"
    SCREENED = "SCREENED"
    CAPABILITY_CHECKED = "CAPABILITY_CHECKED"
    AWAITING_END_USE = "AWAITING_END_USE"
    RECOMMENDED = "RECOMMENDED"
    SIGNED = "SIGNED"


# --- Evidence -----------------------------------------------------------------
class Evidence(BaseModel):
    id: str                              # "E1"
    claim: str                           # "Buyer has 0 employees with RF skills"
    value: Any = None
    source: str                          # "crustdata:/company/enrich#headcount" | "csl:entry/123" | "catalog:row/7" | "email:<msg-id>"
    fetched_at: datetime | None = None


# --- Email & order ------------------------------------------------------------
class Email(BaseModel):
    msg_id: str
    from_addr: str
    to_addr: str
    subject: str
    body: str
    in_reply_to: str | None = None
    received_at: datetime = Field(default_factory=utcnow)


class OrderLine(BaseModel):
    part_number: str
    quantity: int


class Party(BaseModel):
    role: PartyRole
    name: str
    country: str | None = None           # ISO-3166 alpha-2
    address: str | None = None
    domain: str | None = None


class Order(BaseModel):
    order_id: str
    source_email_id: str | None = None
    parties: list[Party]
    lines: list[OrderLine]
    ship_to_country: str
    stated_purpose: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    def party(self, role: PartyRole) -> Party | None:
        return next((p for p in self.parties if p.role == role), None)

    @property
    def buyer(self) -> Party:
        b = self.party("buyer")
        if b is None:
            raise ValueError(f"order {self.order_id} has no buyer")
        return b


class Incomplete(BaseModel):
    """Returned by mail.parse_order when required fields are missing."""
    order_id: str
    missing_fields: list[str]
    partial: dict[str, Any] = Field(default_factory=dict)


# --- Person A results ---------------------------------------------------------
class Classification(BaseModel):
    part_number: str
    found: bool
    controlled: bool = False
    scomet_category: str | None = None
    eccn: str | None = None
    us_origin: bool = False
    part_class: Literal["commodity", "high_end"] | None = None
    needs: list[str] = Field(default_factory=list)
    max_units_per_engineer: int | None = None
    max_units_distributor_small: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class LicenceResult(BaseModel):
    part_number: str
    required: bool
    reason: str
    documents: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class Match(BaseModel):
    csl_entry_id: str
    listed_name: str
    score: float
    breakdown: dict[str, float] = Field(default_factory=dict)
    listed_record: dict[str, Any] = Field(default_factory=dict)


class ScreeningResult(BaseModel):
    party_role: PartyRole
    party_name: str
    status: ScreenStatus
    matches: list[Match] = Field(default_factory=list)
    is_forwarder: bool = False
    evidence_ids: list[str] = Field(default_factory=list)


class CapabilityResult(BaseModel):
    party_name: str
    coverage: Coverage
    buyer_type: BuyerType
    features: dict[str, Any] = Field(default_factory=dict)
    percentiles: dict[str, float] = Field(default_factory=dict)
    triggered_rules: list[str] = Field(default_factory=list)
    mismatch_score: float = 0.0
    tier: Tier
    evidence_ids: list[str] = Field(default_factory=list)


# --- Person B results ---------------------------------------------------------
class EndUseClaim(BaseModel):
    claimed_use: str
    mapped_needs: list[str] = Field(default_factory=list)
    end_user_name: str | None = None
    end_user_country: str | None = None
    evasive: bool = False


class EndUseResult(BaseModel):
    claim: EndUseClaim
    end_user_screening: ScreeningResult | None = None
    end_user_capability: CapabilityResult | None = None
    consistent: bool
    reasons: list[str] = Field(default_factory=list)
    followups_sent: int = 0
    evidence_ids: list[str] = Field(default_factory=list)


class OrderResults(BaseModel):
    """Everything decision.decide() needs. Built by pipeline from module outputs."""
    classifications: list[Classification] = Field(default_factory=list)
    licences: list[LicenceResult] = Field(default_factory=list)
    screenings: list[ScreeningResult] = Field(default_factory=list)
    buyer_capability: CapabilityResult | None = None
    end_use: EndUseResult | None = None
    end_use_requested: bool = False
    order_incomplete: bool = False
    llm_unavailable: bool = False


class ExplanationSentence(BaseModel):
    text: str
    evidence_ids: list[str]


class Signature(BaseModel):
    by: str
    at: datetime = Field(default_factory=utcnow)


class Override(BaseModel):
    by: str
    at: datetime = Field(default_factory=utcnow)
    original_outcome: Outcome
    original_rule: str
    new_outcome: Outcome
    reason: str


class Decision(BaseModel):
    order_id: str
    outcome: Outcome
    rule_fired: str
    rules_triggered: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    explanation: list[ExplanationSentence] = Field(default_factory=list)
    licence_documents: list[str] = Field(default_factory=list)
    needs_human: bool = True
    signature: Signature | None = None
    override: Override | None = None
    state_history: list[tuple[OrderState, datetime]] = Field(default_factory=list)
