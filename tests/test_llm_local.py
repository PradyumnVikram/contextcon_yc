"""Local LLM (Ollama) adapter behind the same LLM.structured seam. No network: httpx MockTransport."""
import json

import httpx
import pytest

from clearance import config, store
from clearance.llm import LLMUnavailable, make_llm
from clearance.llm.local import OllamaLLM
from clearance.llm.schemas import DraftOut


def _llm(handler):
    return OllamaLLM(store.connect(":memory:"), transport=httpx.MockTransport(handler))


def _ok(content):
    return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(content)}, "done": True})


def test_returns_schema_object_and_caches():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return _ok({"subject": "[CLR-1] Details", "body": "Please reply."})

    llm = _llm(handler)
    a = llm.structured("draft_email", DraftOut, {"kind": "x"})
    b = llm.structured("draft_email", DraftOut, {"kind": "x"})
    assert a == b == DraftOut(subject="[CLR-1] Details", body="Please reply.")
    assert len(seen) == 1
    req = seen[0]
    assert req["model"] == config.OLLAMA_MODEL and req["stream"] is False and req["think"] is False
    assert req["format"]["properties"].keys() == {"subject", "body"}
    assert req["messages"][0]["role"] == "system" and req["messages"][1]["role"] == "user"


def test_invalid_json_is_retried_once_then_unavailable():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={"message": {"content": "not json"}})

    with pytest.raises(LLMUnavailable):
        _llm(handler).structured("draft_email", DraftOut, {"kind": "x"})
    assert len(calls) == 2


def test_server_down_is_unavailable():
    def handler(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMUnavailable):
        _llm(handler).structured("draft_email", DraftOut, {"kind": "x"})


def test_factory_picks_provider(monkeypatch):
    conn = store.connect(":memory:")
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    assert type(make_llm(conn)).__name__ == "OllamaLLM"
    monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
    assert type(make_llm(conn)).__name__ == "ClaudeLLM"
