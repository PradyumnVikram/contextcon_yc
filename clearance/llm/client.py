"""Claude client (task B1). The only place in the codebase that talks to the Anthropic API.

- One model (config.LLM_MODEL), structured outputs into pydantic schemas, explicit effort per task.
- Every successful response is cached in store.api_cache (key = model + task + prompt version + payload),
  so a repeated call never hits the network and the demo can replay offline.
- Any failure (network, auth, refusal, max_tokens, unparseable output) raises LLMUnavailable.
  The pipeline maps that to decision rule R10 (HOLD). Never guess.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from clearance import config, store
from clearance.llm import prompts

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """Claude could not produce a valid answer and nothing is cached."""


class LLM(Protocol):
    def structured(self, task: str, schema: type[T], payload: dict[str, Any]) -> T: ...


def _cache_request(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"model": config.LLM_MODEL, "task": task, "prompt_version": prompts.PROMPT_VERSION, "payload": payload}


class ClaudeLLM:
    """Production client. `sdk` can be injected for tests (anything with .messages.parse)."""

    def __init__(self, conn: sqlite3.Connection, sdk: Any | None = None) -> None:
        self.conn = conn
        self._sdk = sdk

    @property
    def sdk(self) -> Any:
        if self._sdk is None:
            import anthropic  # imported lazily so modules that never call Claude don't need it
            self._sdk = anthropic.Anthropic(max_retries=2, timeout=120.0)
        return self._sdk

    def structured(self, task: str, schema: type[T], payload: dict[str, Any]) -> T:
        endpoint = f"llm:{task}"
        req = _cache_request(task, payload)
        cached = store.cache_get(self.conn, endpoint, req)
        if cached is not None:
            try:
                return schema.model_validate(cached)
            except ValidationError:
                log.warning("cached %s response no longer matches schema; refetching", task)

        result = self._call(task, schema, payload)
        store.cache_put(self.conn, endpoint, req, result.model_dump(mode="json"))
        return result

    def _call(self, task: str, schema: type[T], payload: dict[str, Any]) -> T:
        import anthropic

        kwargs: dict[str, Any] = dict(
            model=config.LLM_MODEL,
            max_tokens=config.LLM_MAX_TOKENS,
            # Fixed system prompt first so prompt caching applies; per-order data goes last.
            system=[{"type": "text", "text": prompts.SYSTEM[task], "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": json.dumps(payload, sort_keys=True, ensure_ascii=False)}],
            output_config={"effort": config.LLM_EFFORT[task]},
            output_format=schema,
        )
        if config.LLM_SERVER_FALLBACK:
            kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
            kwargs["extra_body"] = {"fallbacks": "default"}
        try:
            resp = self.sdk.messages.parse(**kwargs)
        except anthropic.APIConnectionError as e:
            raise LLMUnavailable(f"{task}: connection error: {e}") from e
        except anthropic.APIStatusError as e:  # auth, 4xx, 5xx after SDK retries
            raise LLMUnavailable(f"{task}: API error {e.status_code}: {e.message}") from e

        if resp.stop_reason == "refusal":
            category = getattr(getattr(resp, "stop_details", None), "category", None)
            raise LLMUnavailable(f"{task}: refused (category={category})")
        if resp.stop_reason == "max_tokens":
            raise LLMUnavailable(f"{task}: hit max_tokens")
        parsed = getattr(resp, "parsed_output", None)
        if parsed is None:
            raise LLMUnavailable(f"{task}: no parsed output")
        return parsed


class FakeLLM:
    """Test/demo double: returns canned outputs per task, or raises LLMUnavailable if none."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def structured(self, task: str, schema: type[T], payload: dict[str, Any]) -> T:
        self.calls.append((task, payload))
        r = self.responses.get(task)
        if callable(r):
            r = r(payload)
        if isinstance(r, list):  # queue of responses for repeated calls
            r = r.pop(0) if r else None
        if r is None:
            raise LLMUnavailable(f"FakeLLM has no response for {task}")
        return r if isinstance(r, schema) else schema.model_validate(r)
