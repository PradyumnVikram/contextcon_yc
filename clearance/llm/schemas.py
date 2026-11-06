"""Output schemas Claude must fill (structured outputs). Internal to Person B's modules."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LineOut(BaseModel):
    part_number: str
    quantity: int


class ParsedOrder(BaseModel):
    is_order: bool = Field(True, description="False if the email is not about buying parts at all (spam, jokes, "
                                             "unrelated questions)")
    buyer_name: str | None = None
    buyer_website: str | None = None
    buyer_country: str | None = Field(None, description="ISO-3166 alpha-2, e.g. IN")
    buyer_address: str | None = None
    ship_to_name: str | None = None
    ship_to_address: str | None = None
    ship_to_country: str | None = Field(None, description="ISO-3166 alpha-2")
    middleman_name: str | None = None
    middleman_country: str | None = None
    shipper_name: str | None = None
    shipper_country: str | None = None
    lines: list[LineOut] = Field(default_factory=list)
    stated_purpose: str | None = None
    ambiguous_fields: list[str] = Field(default_factory=list,
                                        description="Field names whose value the email states unclearly")


class EndUseOut(BaseModel):
    claimed_use: str = Field(description="The use the buyer states, in their words; empty string if none")
    mapped_needs: list[str] = Field(default_factory=list, description="Subset of the given needs vocabulary")
    end_user_name: str | None = None
    end_user_country: str | None = Field(None, description="ISO-3166 alpha-2")
    evasive: bool = Field(description="True if the reply avoids naming the end user or the use")


class DraftOut(BaseModel):
    subject: str
    body: str


class SentenceOut(BaseModel):
    text: str
    evidence_ids: list[str]


class ExplanationOut(BaseModel):
    sentences: list[SentenceOut]
