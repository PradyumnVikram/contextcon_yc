"""Local LLM via Ollama (default provider). Same seam as ClaudeLLM: structured(task, schema, payload) -> schema.

- POST {OLLAMA_URL}/api/chat with `format` = the pydantic JSON schema (Ollama structured outputs),
  `think: false` (qwen3 thinking off: extraction tasks don't need it and it doubles latency), temperature 0.
- Cached in store.api_cache like every other external call (key = provider + model + task + prompt version + payload).
- Invalid JSON / schema mismatch is retried once; any remaining failure raises LLMUnavailable -> HOLD (R10).
Nothing leaves the machine: order data and end-use replies stay local.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from clearance import config, store
from clearance.llm import prompts
from clearance.llm.client import LLMUnavailable

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_JSON_RULE = "\n\nRespond with a single JSON object that matches the required schema. No prose, no markdown."


class OllamaLLM:
    def __init__(self, conn: sqlite3.Connection, transport: httpx.BaseTransport | None = None,
                 model: str | None = None, base_url: str | None = None) -> None:
        self.conn = conn
        self.model = model or config.OLLAMA_MODEL
        self._http = httpx.Client(base_url=base_url or config.OLLAMA_URL, timeout=config.OLLAMA_TIMEOUT_S,
                                  transport=transport)

    def structured(self, task: str, schema: type[T], payload: dict[str, Any]) -> T:
        endpoint = f"llm:{task}"
        req = {"provider": "ollama", "model": self.model, "task": task,
               "prompt_version": prompts.PROMPT_VERSION, "payload": payload}
        if (cached := store.cache_get(self.conn, endpoint, req)) is not None:
            try:
                return schema.model_validate(cached)
            except ValidationError:
                log.warning("cached %s response no longer matches schema; refetching", task)
        result = self._call(task, schema, payload)
        store.cache_put(self.conn, endpoint, req, result.model_dump(mode="json"))
        return result

    def _call(self, task: str, schema: type[T], payload: dict[str, Any]) -> T:
        body = {
            "model": self.model, "stream": False, "think": False,
            "options": {"temperature": 0, "num_ctx": config.OLLAMA_NUM_CTX},
            "format": schema.model_json_schema(),
            "messages": [{"role": "system", "content": prompts.SYSTEM[task] + _JSON_RULE},
                         {"role": "user", "content": json.dumps(payload, sort_keys=True, ensure_ascii=False)}],
        }
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                r = self._http.post("/api/chat", json=body)
                r.raise_for_status()
                content = r.json()["message"]["content"]
                return schema.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError, KeyError) as e:
                last_err = e
                log.warning("ollama %s returned invalid output (attempt %d): %s", task, attempt + 1, e)
            except httpx.HTTPError as e:
                raise LLMUnavailable(f"{task}: Ollama unreachable at {config.OLLAMA_URL}: {e}") from e
        raise LLMUnavailable(f"{task}: invalid structured output from {self.model}: {last_err}")
