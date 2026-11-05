"""Score Claude's end-use extraction against hand-written expectations (task B5).

Usage: python eval/score.py [path/to/replies.jsonl]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from clearance import config, store
from clearance.enduse import extract, is_vague
from clearance.evidence import Ledger
from clearance.llm import LLMUnavailable, make_llm
from clearance.models import Classification, Email

FIELDS = ["end_user_name", "end_user_country", "evasive", "use_specific"]


def _norm(v):
    return v.strip().lower() if isinstance(v, str) else v


def main(path: str) -> int:
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    llm = make_llm(store.connect(config.DB_PATH))
    hits = {f: 0 for f in FIELDS}
    misses, errors = [], 0
    for r in rows:
        cls = [Classification(part_number="EVAL", found=True, needs=r["parts_needs"])]
        try:
            c = extract(Email(msg_id=f"<eval-{r['id']}>", from_addr="", to_addr="", subject="", body=r["reply"]),
                        cls, llm, Ledger())
        except LLMUnavailable as e:
            errors += 1
            print(f"{r['id']}: LLM unavailable ({e})")
            continue
        got = {"end_user_name": c.end_user_name, "end_user_country": c.end_user_country, "evasive": c.evasive,
               "use_specific": not is_vague(c.claimed_use) and bool(c.mapped_needs)}
        for f in FIELDS:
            if _norm(got[f]) == _norm(r["expected"][f]):
                hits[f] += 1
            else:
                misses.append((r["id"], f, r["expected"][f], got[f]))
    n = len(rows) - errors
    model = config.OLLAMA_MODEL if config.LLM_PROVIDER == "ollama" else config.LLM_MODEL
    print(f"\n{n} scored, {errors} errors, {config.LLM_PROVIDER}:{model}")
    for f in FIELDS:
        print(f"  {f:18s} {hits[f]}/{n}  ({100 * hits[f] / n:.0f}%)" if n else f"  {f}: n/a")
    for m in misses:
        print(f"  MISS {m[0]} {m[1]}: expected {m[2]!r}, got {m[3]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("replies.jsonl"))))
