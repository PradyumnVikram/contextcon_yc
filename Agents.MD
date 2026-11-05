# AGENTS.md — Clearance

> Status: **initial planning**. This file is the source of truth for coding agents and teammates working on this repo. Read it fully before writing code. When a decision here changes, update this file in the same commit.

## 1. What we are building

**Clearance** is an autonomous export-compliance agent for Indian electronics exporters and distributors. It does the whole job of a trade compliance officer: an order for sensitive electronic parts comes in, and the order ends up **released, held for a human, flagged as licence-required, or blocked**, with an audit file that cites the evidence behind every decision.

Built for the ContextCon hackathon (Crustdata), theme **"Services, Replaced"**: pick a job people do today, build the agents that do all of it, bring in a human only for exceptions, and make every decision cite its reasons. Time budget: **8 hours**.

### The problem

- Dual-use electronics (certain RF parts, ADCs, FPGAs, semiconductors) exported from India must clear **India's SCOMET controls** (administered by DGFT). If a part is US-origin, **US re-export rules (EAR)** also apply.
- Indian companies have been added to US restricted lists for diverting US-origin electronics to restricted end users. Getting listed cuts a company off from US technology.
- India also has **catch-all controls**: even an unlisted item needs authorisation if the exporter has reason to believe it may be misused.
- Most Indian component distributors are SMEs with no compliance team. Today the checks are manual, name-based, or skipped.

### The core insight

List screening only catches buyers whose names are already listed. Shell companies used for diversion are not on any list. Clearance also asks: **is this buyer capable of using what it is buying?** A buyer ordering mmWave power amplifiers should employ RF engineers and hire for radar or antenna work. A 5-person trading company with no engineers and a young domain ordering hundreds of controlled parts is a mismatch. Crustdata provides the evidence: headcount by function, people's titles and skills, job postings, company age, traffic, and funding.

This also maps onto DGFT's own evaluation criteria for SCOMET authorisations: credentials of the end user and credibility of the declared end use.

## 2. The end-to-end workflow

```
Order in ─► Classify ─► Screen lists ─► Capability check ─► Decide
                                               │                │
                                    (medium risk)               ├─ RELEASE
                                               ▼                ├─ HOLD → human
                                    End-use statement loop      ├─ LICENCE_REQUIRED
                                    (parse reply → screen +     └─ BLOCK
                                     capability-check the
                                     named end user)
                                                         Every step ─► Audit file
Approved customers ─► Crustdata watcher ─► webhook ─► re-tier risk
```

Each order is a **state machine**:
`RECEIVED → CLASSIFIED → SCREENED → CAPABILITY_CHECKED → [AWAITING_END_USE] → DECIDED`

Every state transition appends evidence to the order's audit log.

### Where humans come in (only these)

1. Fuzzy (non-exact) matches against a restricted-party list.
2. Capability mismatches still unresolved after the end-use loop.
3. Signing licence applications.
4. Final sign-off on any BLOCK.

## 3. Non-negotiable design rules

1. **The LLM never makes a decision.** Release, hold, licence, and block decisions come from deterministic rules over computed features. The LLM extracts, classifies, and explains.
2. **Every claim cites evidence.** Each evidence item has an ID (`E1`, `E2`, …), a source (Crustdata field and fetch time, list entry ID, catalog row, or URL), and a value.
3. **The LLM cites evidence IDs only, never raw numbers.** Code verifies that every cited ID exists and renders the real values. An explanation citing a nonexistent ID is rejected.
4. **Missing data is a risk signal, never a pass.** "No Crustdata profile" triggers the end-use loop.
5. **Unknown parts escalate.** If a part is not in the catalog, the order goes to HOLD. Never guess a classification.
6. **Cache every Crustdata response** (SQLite, keyed by endpoint plus normalized request). Never call the same request twice during development.
7. **Data stays local.** Inference runs on a local model. No order data, end-use statements, or customer data is sent to third-party LLM APIs at runtime.
8. **Ethics:** never present a real company that is *not* on a restricted list as suspicious in the demo or the test data. Use synthetic companies or already-listed entities for the suspicious cases.

## 4. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | Single codebase |
| Env / deps | `uv` (or `pip` + `requirements.txt`) | Pin versions |
| UI | **Streamlit** | No separate frontend in 8 hours |
| Webhook receiver | **FastAPI** + `uvicorn` | Only for Crustdata watcher callbacks |
| Tunnel | `ngrok` | Exposes the webhook during the hackathon |
| HTTP client | `httpx` | With retry and backoff for rate limits |
| Data models | `pydantic` v2 | All module inputs and outputs are typed |
| Storage / cache | SQLite (`sqlite3` or `sqlmodel`) | Orders, evidence, Crustdata cache |
| Tabular data | `pandas` | Screening list and catalog loading |
| Fuzzy matching | `rapidfuzz` | Token-set ratio, Jaro-Winkler |
| Data provider | **Crustdata REST API** | Direct calls, not MCP, at runtime (see §6) |
| Local LLM runtime | **Ollama** (llama.cpp / GGUF underneath) | JSON-schema constrained output |
| Base model | Small open model, 3–8B (Qwen or Llama family) | **TBD** after hardware check |
| Fine-tuning | **Unsloth** or Hugging Face **TRL + PEFT** (LoRA/QLoRA) | One cloud GPU |
| Teacher model | Large model via API | Offline only: generates synthetic training data. Never used at runtime |
| Testing | `pytest` | Unit tests for matcher, rules, evidence validation |
| Config | `.env` + `python-dotenv` | Secrets never committed |

## 5. Modules

### A. `catalog/` — part classification
- Hand-built CSV of ~8–15 parts: `part_number, manufacturer, origin_country, eccn, scomet_category, controlled, required_capability, source_url`.
- `required_capability` is a list of engineering functions or skills a legitimate user needs (for example `["rf_microwave", "antenna_radar", "test_lab"]`).
- Classification is a catalog lookup. A miss goes to HOLD.
- Licence determination (MVP): small rules table over `(scomet_category / eccn, destination_country)` for ~8 destinations. Output: `licence_required: bool` plus a reason.

### B. `screening/` — restricted-party screening
- MVP list: **US Consolidated Screening List** (CSV, downloaded in advance). UN and EU lists are a stretch goal.
- Pipeline: normalize (lowercase; strip `pvt ltd`, `private limited`, `llc`, `co`, `limited`, punctuation; normalize transliteration variants), then block by country and first tokens, then score (token-set ratio, Jaro-Winkler, address similarity), then threshold.
- Output: `exact_hit` → BLOCK, `fuzzy_hit` → HOLD (show both records side by side), `clear`.
- Keep the list entry ID and score breakdown as evidence.

### C. `capability/` — the core engine
- Crustdata inputs: company enrich (headcount, funding, hiring fields), person search scoped to the buyer company with relevant titles and skills, and job postings (stretch).
- Features: `total_headcount`, `headcount_trend`, `engineering_share`, `matching_skill_count`, `relevant_postings`, `company_age_years`, `web_traffic`, `buyer_type`.
- `buyer_type` (manufacturer / distributor / unclear) comes from the local LLM, using the company description and industry fields.
- **Reseller branch:** if the buyer is a distributor, apply a distributor-legitimacy test instead (years operating, size, traffic, high-risk transshipment location).
- Scoring: weighted rules giving a `mismatch_score` and a list of triggered rules. Thresholds give `consistent`, `medium_risk`, or `high_risk`.

### D. `enduse/` — end-use statement loop
- MVP: the "customer reply" is pasted into a text box in the UI (no real email).
- The local LLM extracts `{claimed_use, end_user_name, end_user_country, evasive}` with JSON-schema constrained output.
- The named end user goes back through **B** and **C**.
- Consistency check: does the claimed use fit the part's `required_capability`, and does it fit the end user's capability?

### E. `decision/` — rules, audit, explanation
- Rules table maps screening, capability, and end-use results plus `licence_required` to one of `RELEASE | HOLD | LICENCE_REQUIRED | BLOCK`.
- Audit file: rendered HTML (PDF is a stretch) listing every evidence item, every rule triggered, and the final decision with timestamp.
- Explanation: the local LLM writes prose citing `[E#]` IDs. A validator rejects unknown IDs, and the renderer substitutes real values.

### F. `watch/` — continuous monitoring
- Register a Crustdata company watcher on approved customers, delivering to the FastAPI webhook.
- On an event: recompute capability features and re-tier the customer. The customer's next order gets a full review.
- Demo: a "simulate event" button posts a payload of the same shape, since a real event is unlikely during the demo window.

## 6. Crustdata integration notes

- Base URL: `https://api.crustdata.com`
- Every request needs headers `authorization: Bearer $CRUSTDATA_API_KEY` and `x-api-version: 2025-11-01`.
- Confirmed endpoints: `POST /company/enrich`, `POST /company/search`, `POST /company/identify`, `POST /watch/company/search`, `POST /watch/person/search`.
- **Verify in the docs before use:** person search path, job postings search path, company entity watcher path, and the exact names in `fields` for headcount-by-function and hiring data.
- **Rate limit:** company enrich is limited to 15 requests per minute. Throttle client-side and rely on the cache.
- Always pass `fields` explicitly. Omitting it returns very large payloads.
- Budget: ~30 credits per deep screening; plan for ~1,000–1,500 credits total for the hackathon. Enrich people only when company-level data is ambiguous.
- **MCP vs API:** use the Crustdata MCP server only during preparation, to explore data interactively. The product uses direct, fixed API calls, which are deterministic, cacheable, and auditable. A small local model should not choose tools on its own.

## 7. Local LLM plan

**Tasks for the model** (narrow on purpose):
1. End-use reply extraction (primary fine-tuning target).
2. Buyer-type classification.
3. Evidence-ID-only explanations.

**Distillation pipeline:**
1. The teacher model generates ~500–1,000 labelled synthetic end-use replies (honest, vague, evasive, forwarded chains, transliterated names, mixed-language) plus buyer-type examples. Store them in `training/data/`.
2. A **hand-written** test set of 30–40 examples, never teacher-generated, goes in `training/eval/`.
3. LoRA/QLoRA fine-tune on one cloud GPU, then export to GGUF and load into Ollama.
4. Report base vs fine-tuned field accuracy on the hand-written test set. Only show measured numbers.

**Fallback (must always work):** base model with few-shot prompts and JSON-schema constrained output. The demo must never depend on the fine-tune succeeding.

## 8. Core data shapes (sketch)

```python
class Evidence(BaseModel):
    id: str                 # "E1"
    claim: str              # "Buyer has 0 employees with RF/microwave skills"
    value: Any
    source: str             # "crustdata:/company/enrich#headcount" | "csl:entry/12345" | "catalog:row/7"
    fetched_at: datetime | None

class Decision(BaseModel):
    order_id: str
    outcome: Literal["RELEASE", "HOLD", "LICENCE_REQUIRED", "BLOCK"]
    rules_triggered: list[str]
    evidence: list[Evidence]
    explanation: str        # cites [E#] only; validated
    needs_human: bool
    state_history: list[tuple[str, datetime]]
```

Agree on these shapes before parallel work starts. The UI is built against fake data of exactly this shape.

## 9. Proposed repo layout

```
clearance/
├── AGENTS.md
├── README.md
├── .env.example
├── data/
│   ├── catalog.csv
│   ├── csl.csv                # US Consolidated Screening List
│   └── test_companies.csv
├── clearance/
│   ├── models.py              # pydantic shapes (§8)
│   ├── crustdata_client.py    # throttled, cached client
│   ├── catalog/
│   ├── screening/
│   ├── capability/
│   ├── enduse/
│   ├── decision/
│   ├── watch/                 # FastAPI webhook
│   └── llm/                   # Ollama client, prompts, schemas, ID validator
├── app.py                     # Streamlit UI
├── training/
│   ├── generate_data.py
│   ├── finetune.py
│   ├── data/
│   └── eval/
└── tests/
```

## 10. Eight-hour build plan

| Time | Work | Done when |
|---|---|---|
| 0:00–0:45 | Crustdata client with throttling and cache; enrich 5 test companies | Data shape known. **Go/no-go on coverage** |
| 0:45–1:45 | Screening matcher on CSL | Misspelled listed entity is caught |
| 1:45–3:45 | Capability engine plus reseller branch | Radar firm passes, distributor passes, shell flagged |
| 3:45–4:30 | Decision rules plus evidence plus audit | `decide(order) -> Decision` works |
| 4:30–5:30 | End-use loop with local LLM extraction | Suspicious order: request, reply parsed, end user checked, HOLD |
| 5:30–6:45 | Streamlit UI | Demo-ready |
| 6:45 | **Feature freeze** | — |
| 7:00–8:00 | Three full demo rehearsals, bug fixes only, slides | Rehearsed |

**Parallel fine-tune track** (if a teammate or background GPU is available): data generation from 0:45, training from about 2:00, evaluation at about 5:00.

**If coverage is poor at 0:45:** switch the demo buyers to well-covered companies and make "no data → end-use request" a visible behaviour.

## 11. Demo script (about 3 minutes)

1. **Legitimate radar firm**, controlled RF part: auto-RELEASE, evidence shown.
2. **Large distributor**: low engineering headcount but RELEASE via the reseller branch.
3. **Shell trading company** (synthetic or already listed): capability mismatch, end-use request, reply pasted, end user extracted and checked, HOLD with full evidence trail.
4. Optional: simulated watcher event re-tiers an approved customer.
5. Close: "Every decision cites its reasons. A human only sees the exceptions. All inference runs locally."

## 12. Out of scope for the hackathon

- Real ERP or email integration
- Full SCOMET and EAR classification coverage
- UN and EU lists (stretch)
- Real licence application filing
- Multi-user auth

## 13. Open questions

- [ ] Base model choice and size: depends on venue hardware and GPU access.
- [ ] What the $4,560 credits cover (Crustdata, model API, or cloud GPU): decides the teacher model and training setup.
- [ ] Do hackathon rules allow pre-generated data or a pre-trained adapter?
- [ ] Exact Crustdata field names for headcount-by-function and hiring data.
- [ ] Final part catalog and destination list.
- [ ] Team size and who owns which module.

## 14. Disclaimer

Clearance is a hackathon prototype that automates a compliance workflow. It is not legal advice. In any real deployment, a qualified person reviews and signs all denials and licence applications.
