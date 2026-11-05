"""B1-B2: Claude client caching/failure handling and the evidence-ID validator. No network."""
from types import SimpleNamespace

import pytest

from clearance import store
from clearance.evidence import Ledger
from clearance.llm import ClaudeLLM, FakeLLM, LLMUnavailable
from clearance.llm import validate
from clearance.llm.schemas import DraftOut
from clearance.models import ExplanationSentence


class FakeSDK:
    """Mimics anthropic.Anthropic().messages.parse."""

    def __init__(self, stop_reason="end_turn", parsed=None):
        self.calls = []
        self.stop_reason = stop_reason
        self.parsed = parsed
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, stop_details=None, parsed_output=self.parsed)


def test_claude_client_caches_successful_calls():
    conn = store.connect(":memory:")
    sdk = FakeSDK(parsed=DraftOut(subject="[CLR-1] hi", body="b"))
    llm = ClaudeLLM(conn, sdk=sdk)
    a = llm.structured("draft_email", DraftOut, {"kind": "x"})
    b = llm.structured("draft_email", DraftOut, {"kind": "x"})
    assert a == b and len(sdk.calls) == 1
    call = sdk.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "medium"}
    assert call["output_format"] is DraftOut
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_claude_client_bad_stop_reason_raises(stop_reason):
    llm = ClaudeLLM(store.connect(":memory:"), sdk=FakeSDK(stop_reason=stop_reason, parsed=None))
    with pytest.raises(LLMUnavailable):
        llm.structured("draft_email", DraftOut, {"kind": "x"})


def test_fake_llm_without_response_is_unavailable():
    with pytest.raises(LLMUnavailable):
        FakeLLM().structured("explain", DraftOut, {})


def test_validator_rejects_unknown_and_uncited():
    led = Ledger()
    e1 = led.add("Buyer headcount", 4, "crustdata:test")
    ok = [ExplanationSentence(text="Small company.", evidence_ids=[e1])]
    validate.check(ok, led)
    assert validate.render(ok, led) == ["Small company. [E1: Buyer headcount = 4]"]
    with pytest.raises(validate.ExplanationRejected):
        validate.check([ExplanationSentence(text="x", evidence_ids=["E9"])], led)
    with pytest.raises(validate.ExplanationRejected):
        validate.check([ExplanationSentence(text="x", evidence_ids=[])], led)
