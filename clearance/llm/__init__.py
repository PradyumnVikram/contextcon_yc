"""LLM layer. OWNER: Person B (tasks B1-B2).

Default provider is a LOCAL model through Ollama (config.LLM_PROVIDER = "ollama"); ClaudeLLM stays available
with CLEARANCE_LLM=claude. Every caller depends only on the LLM.structured(task, schema, payload) seam.
"""
from __future__ import annotations

import sqlite3

from clearance import config
from clearance.llm.client import LLM, ClaudeLLM, FakeLLM, LLMUnavailable


def make_llm(conn: sqlite3.Connection) -> LLM:
    if config.LLM_PROVIDER == "claude":
        return ClaudeLLM(conn)
    from clearance.llm.local import OllamaLLM
    return OllamaLLM(conn)


__all__ = ["LLM", "ClaudeLLM", "FakeLLM", "LLMUnavailable", "make_llm"]
