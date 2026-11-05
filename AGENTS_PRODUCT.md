# AGENTS_PRODUCT.md: Clearance, Person B (agent, LLM and product)

> **Who reads this:** Person B and any coding agent working on the **`product`** branch.
> **Your scope:** the Claude client, the mail module, the end-use loop and its eval set, decision rules, explanations and the audit file, the pipeline state machine, and the Streamlit UI.
> **The other half:** Person A builds the Crustdata client, catalog, screening, capability engine and watcher, and their brief is `AGENTS_DATA.md`. §1–§15 are identical in both files. If you change anything in §1–§15, make the same change in both files in the same commit.
> Read this whole file before writing code.

## ★ Your job (Person B: agent, LLM and product, branch `product`)

**Your job is to build the agent the compliance officer actually uses.** It:
- reads order emails and replies to buyers;
- runs the end-use loop;
- applies the decision table;
- writes the cited explanation and audit file;
- drives each order through its states;
- gives the officer the screens to sign, resolve exceptions and override.

You call Person A's modules for every data signal. You never compute screening or capability yourself.

**Do these tasks, in this order** (full details in §16):
1. **S1–S5** (shared, with Person A, on `dev`): scaffold, contracts, storage, fixtures, stubs.
2. **B1–B2**: Claude client, prompts, evidence-ID validator.
3. **B3**: mail module (inbox, order parsing, missing-details auto-reply, reply matching).
4. **B4–B5**: end-use loop and the hand-written eval set.
5. **B6–B7**: decision rules, explanation and audit, pipeline state machine.
6. **B8–B9**: Streamlit UI, tests.
7. **I1–I3** (with Person A): integration, acceptance cases, rehearsal.

**You deliver** `clearance/llm/`, `clearance/mail/`, `clearance/enduse/`, `clearance/decision/`, `clearance/pipeline.py`, `app.py`, `mailbox/`, `eval/`, and their tests.

**You do NOT do:** any A-task (Crustdata, catalog, screening, capability scoring, buyer type, watcher). Don't edit Person A's folders (§17). Until their modules land, use the S5 stubs.

**Definition of done for your job:** `pytest` passes offline for all your modules, acceptance cases 1–9 (§4.9) produce the expected recommendation through `pipeline`, and the demo script (§12) runs from the UI.

## 1. What we are building

**Clearance** is an autonomous export-compliance agent for Indian electronics exporters and distributors. It does the job of a trade compliance officer. An order for sensitive electronic parts arrives by email, and the agent gathers the evidence and recommends one of **RELEASE, LICENCE_REQUIRED, HOLD or BLOCK**. It writes an audit file that cites the evidence behind every step. A compliance officer resolves the exceptions and signs every RELEASE and BLOCK.

Built for the ContextCon hackathon (Crustdata), theme **"Services, Replaced"**. Time budget: **8 hours**.

### The problem
- Dual-use electronics (certain RF parts, ADCs, FPGAs, semiconductors) exported from India must clear **India's SCOMET controls** (administered by DGFT). If a part is US-origin, **US re-export rules (EAR)** also apply, including in-country transfers inside India.
- Indian companies have been added to US restricted lists for diverting US-origin electronics to restricted end users.
- India also has **catch-all controls**: even an unlisted item needs authorisation if the exporter has reason to believe it may be misused.
- Most Indian component distributors are SMEs with no compliance team. Today the checks are manual, name-based, or skipped.

### The core insight
List screening only catches buyers whose names are already listed, and shell companies used for diversion aren't on any list. Clearance also asks: **is this buyer capable of using what it is buying?** A buyer of mmWave power amplifiers should employ RF engineers. A 5-person trading company with no engineers and a young domain, ordering hundreds of controlled parts, is a mismatch. Crustdata provides the evidence: headcount by function, employees' titles, skills and past employers, company age, traffic, and similar companies to compare against. This matches DGFT's own SCOMET criteria: the credentials of the end user and the credibility of the declared end use.

## 2. Non-negotiable design rules

1. **The LLM never makes a decision.** Every recommendation comes from deterministic rules over computed features. Claude only extracts, maps, drafts emails, and explains.
2. **Every claim cites evidence.** Each evidence item has an ID (`E1`, `E2`, …), a source (Crustdata endpoint and fetch time, CSL entry ID, catalog row, email message ID), and a value.
3. **The LLM cites evidence IDs only, never raw numbers.** Code checks that every cited ID exists and renders the real values. An explanation that cites an unknown ID is rejected.
4. **Missing data is a risk signal, never a pass.** No Crustdata record, or only a thin one, means HOLD plus an end-use request.
5. **Unknown parts escalate.** A part not in the catalog means HOLD. Never guess a classification.
6. **Cache every external response** (Crustdata and Claude) in SQLite, keyed by endpoint and normalized request. Never make the same call twice. Tests never touch the network.
7. **Send the LLM only what the task needs.** Claude (through the Anthropic API) is the only LLM. Each call gets only the fields its task needs, never the whole order record or any secrets.
8. **A human signs every RELEASE and BLOCK.** A HOLD takes effect immediately on its own. The officer can override any outcome, and every override is logged.
9. **Ethics:** never present a real company that is *not* on a restricted list as suspicious, in the demo or in test data. Use synthetic companies or entities that are already listed.

## 3. User and interaction

**User:** a dedicated compliance officer. They want full evidence detail, score breakdowns, rule traces, and the power to override any decision with a logged note.

**Entry point: a simulated email inbox.** The mailbox is local: `mailbox/inbox/*.eml` and `mailbox/outbox/*.eml`. A poller picks up new inbox files. For the demo, a "compose test email" panel in the UI writes into the inbox.

**Flow:**
1. **An order email arrives.** Claude extracts `{buyer_name, buyer_website, buyer_country, ship_to_address, ship_to_country, middleman?, shipper?, lines[part_number, qty], stated_purpose?}` using structured outputs. Each field becomes evidence sourced to `email:<msg-id>`.
2. **Missing or unclear fields:** Clearance auto-replies to the buyer asking for exactly those fields (state `AWAITING_ORDER_DETAILS`). If the reply is still incomplete after one round, the order goes to HOLD. Nothing is guessed.
3. **Classify, screen and check capability** with no human involved.
4. **End-use loop** (when needed): Claude drafts the request, which goes to `outbox/` with the subject `[CLR-<order_id>] End-use statement request`. If the first reply is vague or evasive, one targeted follow-up is sent. The named end user is screened and capability-checked the same way as the buyer.
5. **Reply matching:** a reply is matched to its order by the `[CLR-<order_id>]` tag in the subject (or `In-Reply-To`). A reply that can't be matched goes to Exceptions.
6. **Recommendation:** an outcome comes out of the rules table, and the officer then acts on it.

**Screens (Streamlit):**
| Screen | Purpose |
|---|---|
| Inbox | Raw emails and parse status, plus the "compose test email" panel |
| Orders | All orders by state |
| Ready to sign | Recommended RELEASE and BLOCK orders, each signed in one click with the evidence shown |
| Exceptions | HOLD orders: fuzzy matches shown side by side, capability mismatches, evasive replies, no data, freight-forwarder end users, unmatched replies |
| Order detail | State timeline, every evidence item and its source, rule trace, screening score breakdown, capability feature table with peer percentiles, audit download, override with note |
| Customers | Watched buyers and their tiers, plus a "simulate event" button |

**Order states:**
`EMAIL_RECEIVED → PARSED → [AWAITING_ORDER_DETAILS] → CLASSIFIED → SCREENED → CAPABILITY_CHECKED → [AWAITING_END_USE] → RECOMMENDED → SIGNED`

A HOLD is final at `RECOMMENDED` until the officer resolves it. Every transition appends to the state history and the audit log.

**Watcher:** each released buyer becomes an approved customer, and a Crustdata watcher is registered on it. An event recomputes the buyer's capability features and peer percentiles and re-tiers the customer. Their **next** order gets a full review, and already-released orders are not re-opened.

## 4. Flagging basis

These are starting values. Tune them on the test companies and record every change in **both** agent files. All weights and thresholds live in `clearance/config.py`.

### 4.1 Catalog (per part)
`known_part`, `controlled`, `scomet_category`, `eccn`, `us_origin`, `part_class` (`commodity | high_end`), `needs` (capability tags such as `rf`, `antenna`, `fpga`, `radar`, `test_lab`), `max_units_per_engineer`, `max_units_distributor_small`, and `source_url`.

The demo catalog has about 8–10 parts across RF/microwave, high-speed ADC/DAC and FPGA, with one controlled part and one uncontrolled look-alike per category. Destinations: India (domestic buyer), UAE, Hong Kong, Türkiye, Singapore, Germany, US, Russia, China.

**Licence:** required if a part is SCOMET-controlled and the destination is not India, **or** the part is US-origin and `licence_rules.csv` lists an EAR requirement for the destination (this includes in-country transfer within India). The audit lists the documents to collect. Clearance never files a licence.

### 4.2 Screening (US Consolidated Screening List only)
Parties screened: **buyer, ship-to party, middleman, shipper/forwarder, and end user**.
- **Normalize:** lowercase; strip `pvt ltd`, `private limited`, `llc`, `co`, `limited` and punctuation; normalize transliteration variants.
- **Block:** compare only against entries with the same country or the same first word.
- **Score:** `score = 0.60·token_set + 0.25·jaro_winkler + 0.15·address_sim` (0–100), using `rapidfuzz`.
- `exact_hit`: the normalized name is identical (or score ≥ 97) **and** the country matches. `fuzzy_hit`: score ≥ 85. Otherwise `clear`.
- Keep the CSL entry ID and the score breakdown as evidence.
- `forwarder_is_end_user`: the named end user is a freight or logistics company.

### 4.3 Crustdata coverage
`missing` = no company record. `thin` = a record, but with no description, no headcount and no people. `rich` = anything else.

### 4.4 Employee background check (cached once per company, reused everywhere)
- Crustdata person search runs **once per company**, capped at about 25 people (senior people and founders first). Raw results go into the `people` table: `company_key, person_id, name, title, function, skills, past_employers, fetched_at`.
- **Computed from the cache:**
  - `function_mix`: shares of engineering, sales/procurement, operations/logistics, and other.
  - `matching_people`: people whose title, function or skills hit the part's `needs`.
  - `technical_share`: share of people in engineering functions.
  - `past_employer_profile`: share of past employers that are electronics/defence/telecom firms vs trading firms.
- **`buyer_type`** comes from two votes, with no LLM involved:
  - **Keyword vote** on the description and industry fields: trading/wholesale/distribution → distributor; manufacturer/laboratory/design/radar/telecom equipment → manufacturer.
  - **People vote:** engineering share ≥ 30% → manufacturer; sales+ops ≥ 60% and engineering < 10% → distributor.
  - If the votes agree, use that type. If they conflict, or neither votes, the type is `unclear`.
- **Reuse:** the same cache feeds rule C1, the end-user check, and the watcher recompute. A company's people are fetched again only after a watcher event. Each person becomes evidence `crustdata:/person/search#<person_id>`.

### 4.5 Peer comparison
`company/search` pulls 20–50 companies with the same industry, size band and region, and caches them per buyer. Features are scored as percentiles against these peers, so evidence reads like "engineering share is at the 3rd percentile of 40 peers".

### 4.6 Capability scoring (points add up to `mismatch_score`)

**Manufacturer branch**
| Rule | Condition | Pts |
|---|---|---|
| C1 | `matching_people` = 0 for the part's `needs` | 40 |
| C2 | Engineering share < 10th percentile of peers | 20 |
| C3 | Company age < 2 years | 15 |
| C4 | Headcount fell > 20% in 12 months | 10 |
| C5 | Web traffic < 10th percentile of peers | 10 |
| O1 | Units ÷ `matching_people` > part's `max_units_per_engineer` | 20 |
| O2 | Ship-to is a transshipment hub (UAE, HK, Türkiye, Singapore) and ≠ buyer country | 15 |
| O3 | Ship-to country ≠ buyer country (not a hub) | 5 |

**Distributor branch** (replaces C1, C2 and O1)
| Rule | Condition | Pts |
|---|---|---|
| D1 | Operating < 3 years | 25 |
| D2 | Headcount < 10th percentile of distributor peers | 15 |
| D3 | Web traffic < 10th percentile of distributor peers | 15 |
| D4 | Quantity > part's `max_units_distributor_small` and headcount < 20 | 15 |
| O2 / O3 | Same as above | 15 / 5 |

If `buyer_type` is `unclear`, score both branches and take the higher score.
**Tiers:** 0–29 `consistent` · 30–59 `medium_risk` · ≥ 60 `high_risk`. When coverage is `missing` or `thin`, the tier is `no_data`.

### 4.7 End-use consistency
Claude extracts `{claimed_use, end_user_name, end_user_country, evasive}` and maps `claimed_use` onto the catalog's `needs` vocabulary. A reply is **consistent** only if all of these hold:
- the mapped needs overlap the part's `needs`;
- the claimed use is not blank and not just "civilian use";
- the end user screens `clear` and is not a freight forwarder;
- the end user's tier is ≤ `medium_risk`;
- the reply is not `evasive`.

### 4.8 Decision table (first match wins)
| # | Condition | Recommendation |
|---|---|---|
| 1 | Any party is an `exact_hit` | **BLOCK** → officer signs |
| 2 | Any part is not in the catalog | **HOLD** |
| 3 | Any party is a `fuzzy_hit` | **HOLD** (side by side) |
| 4 | The end user is a freight forwarder | **HOLD** |
| 5 | Order details still incomplete after the auto-reply round | **HOLD** |
| 6 | `coverage` is `missing` or `thin` | **HOLD**, and send the end-use request. The reply goes to the officer, never to auto-release |
| 7 | Tier is `medium_risk` or `high_risk`, and the end-use loop hasn't run yet | **AWAITING_END_USE** |
| 8 | End-use reply inconsistent after the follow-up | **HOLD** (catch-all concern) |
| 9 | End-use reply consistent but the buyer's tier is `high_risk` | **HOLD** |
| 10 | Claude unavailable and no cached response | **HOLD** |
| 11 | Licence required | **LICENCE_REQUIRED** (lists the documents to collect) |
| 12 | Otherwise | **RELEASE** → officer signs |

The officer may replace any outcome. The audit keeps the original rule, the new outcome, who changed it, when, and why.

### 4.9 Acceptance cases (`tests/test_cases.py`, from the original add-on)
1. A known radar firm with engineers whose skills match, a small quantity, clear lists and no licence → **RELEASE**, then signature.
2. The same firm, but the destination needs a licence → **LICENCE_REQUIRED**, with the documents listed.
3. A real distributor with no engineers, plus a named end user who has the engineers → **RELEASE** through the distributor branch.
4. A distributor who won't name the end user → **HOLD**.
5. A real hardware firm with three engineers and a hundred commodity FPGAs → **RELEASE**: within `max_units_per_engineer` for a commodity part.
6. Three engineers and a hundred high-end FPGAs or controlled RF amplifiers, with nothing in the profile matching → **HOLD**, and ask who the parts are for.
7. No Crustdata record → **HOLD**, and ask. Don't ship and don't block.
8. A name already on the list → **BLOCK**, then signature.
9. A close spelling of a listed name → **HOLD**, with the two names shown side by side.

## 5. Architecture

```
                 ┌──────────── Streamlit app.py ─────────────┐
                 │ inbox · orders · ready-to-sign · exceptions│
                 │ order detail · customers                   │
                 └──────────────────┬─────────────────────────┘
                                    │
   mailbox/ ◄──► mail/ ──► clearance/pipeline.py (state machine, the only orchestrator)
              ┌──────────┬──────────┬───┴──────┬──────────┬──────────┐
           catalog/  screening/ capability/  enduse/   decision/   watch/ (FastAPI)
              │          │          │           │          │          │
              │          │  crustdata_client  llm/client llm/validate crustdata_client
              └──────────┴──── evidence.Ledger ──┴──── store.py (SQLite) ┘
```

- **Modules never call each other.** Only `pipeline.py` calls modules. `enduse.check` gets `screen` and `assess` passed in as callables.
- Every module function takes a `Ledger`, records evidence through it, and returns a typed result that refers to evidence IDs.
- Every external call goes through a cached client.

### 5.1 Shared contracts: `clearance/models.py` (pydantic v2; frozen after S2)
```python
class OrderLine:         part_number: str; quantity: int
class Party:             role: Literal["buyer","ship_to","middleman","shipper","end_user"]
                         name: str; country: str | None; address: str | None; domain: str | None
class Order:             order_id; source_email_id; parties: list[Party]; lines: list[OrderLine]
                         ship_to_country; stated_purpose: str | None; created_at
class Evidence:          id: str  # "E1"
                         claim: str; value: Any; source: str; fetched_at: datetime | None
class Ledger:            add(claim, value, source, fetched_at=None) -> str; get(id); items
class Classification:    part_number; found: bool; controlled; scomet_category; eccn; us_origin
                         part_class: Literal["commodity","high_end"]; needs: list[str]
                         max_units_per_engineer: int; max_units_distributor_small: int; evidence_ids
class LicenceResult:     required: bool; reason: str; documents: list[str]; evidence_ids
class Match:             csl_entry_id; listed_name; score; breakdown: dict; listed_record: dict
class ScreeningResult:   party_role; status: Literal["clear","fuzzy_hit","exact_hit"]
                         matches: list[Match]; is_forwarder: bool; evidence_ids
class CapabilityResult:  coverage: Literal["missing","thin","rich"]
                         buyer_type: Literal["manufacturer","distributor","unclear"]
                         features: dict; percentiles: dict; triggered_rules: list[str]
                         mismatch_score: float
                         tier: Literal["consistent","medium_risk","high_risk","no_data"]; evidence_ids
class EndUseClaim:       claimed_use; mapped_needs: list[str]; end_user_name | None
                         end_user_country | None; evasive: bool
class EndUseResult:      claim; end_user_screening; end_user_capability; consistent: bool
                         reasons: list[str]; evidence_ids
class ExplanationSentence: text: str; evidence_ids: list[str]
class Signature:         by: str; at: datetime
class Override:          by; at; original_outcome; original_rule; new_outcome; reason
class Decision:          order_id; outcome: Literal["RELEASE","HOLD","LICENCE_REQUIRED","BLOCK","AWAITING_END_USE"]
                         rule_fired: str; rules_triggered: list[str]; evidence: list[Evidence]
                         explanation: list[ExplanationSentence]; needs_human: bool
                         signature: Signature | None; override: Override | None
                         state_history: list[tuple[str, datetime]]
```

### 5.2 Module signatures
| Module | Owner | Functions |
|---|---|---|
| `catalog` | A | `classify(part_number, ledger) -> Classification`, `licence(cls, dest_country, ledger) -> LicenceResult` |
| `screening` | A | `screen(party: Party, ledger) -> ScreeningResult` |
| `capability` | A | `assess(party: Party, classifications, lines, ship_to_country, ledger) -> CapabilityResult` |
| `watch` | A | FastAPI `POST /webhook/crustdata`, `register(company)`, `simulate_event(company)` |
| `crustdata_client` | A | `enrich_company`, `search_companies`, `search_people`, `watch_company` (all cached) |
| `llm` | B | `client.structured(task, schema, input) -> model`, `validate.check(sentences, ledger)`, `validate.render(...)` |
| `mail` | B | `poll() -> list[Email]`, `parse_order(email, ledger) -> Order \| Incomplete`, `send(to, subject, body)`, `match_reply(email) -> order_id \| None` |
| `enduse` | B | `draft_request(order)`, `extract(reply, ledger) -> EndUseClaim`, `check(claim, classifications, screen, assess, ledger) -> EndUseResult` |
| `decision` | B | `decide(order, results, ledger) -> Decision`, `explain(decision, ledger) -> list[ExplanationSentence]`, `audit_html(decision) -> str` |
| `pipeline` | B | `ingest(email)`, `run(order_id)`, `on_reply(email)`, `sign(order_id, by)`, `override(order_id, outcome, by, reason)` |

### 5.3 Storage: `clearance/store.py` (one SQLite file, `clearance.db`)
Tables:
- `api_cache(key, endpoint, request_json, response_json, fetched_at)`
- `people(company_key, person_id, name, title, function, skills, past_employers, fetched_at)`
- `peers(company_key, peer_set_json, fetched_at)`
- `orders(order_id, order_json, state, decision_json)`
- `state_history(order_id, state, at)`
- `evidence(order_id, id, claim, value_json, source, fetched_at)`
- `emails(msg_id, direction, order_id, subject, body, received_at)`
- `customers(company_key, name, tier, watcher_id, updated_at)`

### 5.4 Claude usage (owned by B, consumed by nobody else)
- One SDK client in `clearance/llm/client.py`. The model is `claude-opus-5-5`, set once in `config.py`. Every task uses structured outputs into a pydantic schema.
- Effort is set explicitly per task: `low` for order parsing, extraction and needs mapping; `medium` for explanations and drafting emails.
- Check `stop_reason` before reading content (handle `refusal` and `max_tokens`), and enable the server-side refusal fallback.
- Fixed system prompts and few-shot examples go first so prompt caching applies. Per-order data goes last.
- **Claude's tasks:**
  - parse order emails
  - extract end-use replies
  - map `claimed_use` onto `needs`
  - draft emails (missing details, end-use request, follow-up)
  - write explanations as `[{text, evidence_ids}]`
- Claude never decides `buyer_type`.
- Responses are cached in `api_cache`, keyed by model, prompt version and input. If the API fails and nothing is cached, the order goes to HOLD (rule 10).

### 5.5 Crustdata integration notes (owned by A)
- Base URL `https://api.crustdata.com`. Headers: `authorization: Bearer $CRUSTDATA_API_KEY` and `x-api-version: 2025-11-01`.
- Confirmed endpoints: `POST /company/enrich`, `POST /company/search`, `POST /company/identify`, `POST /watch/company/search`, `POST /watch/person/search`.
- **Check in the docs before use:** the person search path, the company watcher path, and the exact `fields` names for headcount-by-function, past employers and traffic. Record findings in §5.5 of both files.
- **Rate limit:** company enrich allows 15 requests/min. Throttle on our side and rely on the cache.
- Always pass `fields`. Budget about 30 credits per deep screening and 1,000–1,500 in total.
- Use the Crustdata MCP server only for exploring data during preparation. The product makes fixed, cached API calls.

## 6. Tech stack
| Layer | Choice |
|---|---|
| Language | Python 3.10+ (we may move to 3.11 via `uv`; open item) |
| Deps | `pyproject.toml`, pinned |
| UI | Streamlit |
| Webhook | FastAPI + uvicorn, exposed with ngrok |
| HTTP | `httpx`, with retry and backoff |
| Models | pydantic v2 |
| Storage | SQLite |
| Tabular | pandas |
| Fuzzy matching | rapidfuzz |
| Data | Crustdata REST API |
| LLM | Claude API via the `anthropic` SDK, model `claude-opus-5-5` |
| Email | Python `email` stdlib, folder mailbox |
| Tests | pytest |
| Config | `.env` + python-dotenv (never committed) |

## 7. Repo layout (owner in brackets)
```
contextcon_yc/
├── AGENTS_DATA.md  AGENTS_PRODUCT.md                 [S]  one brief per teammate
├── README.md  pyproject.toml  .env.example           [S]
├── app.py                                            [B]  Streamlit UI
├── mailbox/inbox/  mailbox/outbox/                   [B]  simulated email (.eml)
├── data/
│   ├── catalog.csv  licence_rules.csv                [A]
│   ├── csl.csv                                       [A]  US Consolidated Screening List
│   └── test_companies.csv                            [A]
├── clearance/
│   ├── models.py  evidence.py  store.py  config.py   [S]  frozen contracts
│   ├── pipeline.py                                   [B]
│   ├── crustdata_client.py                           [A]
│   ├── catalog/  screening/  capability/  watch/     [A]
│   └── mail/  enduse/  decision/  llm/               [B]
├── eval/                                             [B]  hand-written end-use replies + scorer
└── tests/
    ├── fixtures/  test_cases.py  test_pipeline_stub.py   [S]
    ├── test_catalog.py  test_screening.py  test_capability.py  test_watch.py   [A]
    └── test_llm_validate.py  test_mail.py  test_enduse.py  test_rules.py       [B]
```

## 8. Branching and collaboration
- `main`: stable. Receives `dev` by pull request when a feature is complete.
- `dev`: the integration branch. The shared tasks (S1–S5) are done together here.
- `data`: Person A's branch. `product`: Person B's branch. Both are cut from `dev`.
- **Merge often:** after every finished task with tests passing, rebase on `dev`, then merge into `dev`. Pull `dev` into your branch at least every hour.
- **Contract changes** (`models.py`, `store.py` schema, `config.py` keys) need agreement from both people, go to `dev` in their own commit, and both branches pull immediately.
- **Stay in your own folders** (see §7). If you need something from the other side, use the stub and fixtures, and don't edit their module.
- Every module ships with pytest tests that run against fixtures with no network. `pytest` must pass before any merge.
- Secrets live only in `.env`. Never commit keys, `clearance.db`, or real customer data.

## 9. Shared tasks (pair, about 1 hour, on `dev`)
| ID | Task | Done when |
|---|---|---|
| S1 | Scaffold: `pyproject.toml`, `.env.example` (`ANTHROPIC_API_KEY`, `CRUSTDATA_API_KEY`), package folders, pytest config | `pip install -e .` works and `pytest` runs |
| S2 | `clearance/models.py` with every contract in §5.1 | Both people sign off. Frozen |
| S3 | `evidence.py` (Ledger), `store.py` (all tables in §5.3), `config.py` (all weights and thresholds in §4) | Unit tests for the Ledger and store pass |
| S4 | `tests/fixtures/`: fake results for every module, plus the 9 acceptance cases (§4.9) as orders | Fixtures load into the models without errors |
| S5 | Stub for each module returning fixture data. `pipeline.run(fake_order)` works end to end | `tests/test_pipeline_stub.py` passes |

## 10. Integration tasks (both)
| ID | Task | Done when |
|---|---|---|
| I1 | Replace the stubs with real modules in `pipeline` | `pytest` passes with real modules and cached data |
| I2 | The 9 acceptance cases pass end to end | `tests/test_cases.py` passes |
| I3 | Pre-warm the Crustdata and Claude caches for the demo buyers, run 3 rehearsals, feature freeze at 6:45 | Three clean rehearsals |

## 11. Timeline (8 hours)
| Time | Person A | Person B |
|---|---|---|
| 0:00–1:00 | S1–S5 together | S1–S5 together |
| 1:00–1:45 | A1, A2, A3 (**coverage go/no-go**) | B1, B2 |
| 1:45–3:00 | A4, A5 | B3 |
| 3:00–4:45 | A6, A7, A8, A9 | B4, B6 |
| 4:45–5:30 | A10, A12 | B5, B7 |
| 5:30–6:45 | A11, then I1 and I2 together | B8, then I1 and I2 together |
| 6:45 | **Feature freeze** | |
| 7:00–8:00 | I3: rehearsals and slides | I3 |

If coverage turns out poor at the go/no-go, switch the demo buyers to well-covered companies, and make "no data → HOLD and ask" a visible behaviour.

## 12. Demo script (about 3 minutes)
1. **Legitimate radar firm**, controlled RF part → RELEASE recommended. The evidence is shown and the officer signs.
2. **Large distributor** with a named end user who has the engineers → RELEASE through the distributor branch.
3. **Shell trading company** (synthetic, or an already-listed entity) → capability mismatch, end-use email sent, reply arrives, end user extracted and checked → HOLD with the full evidence trail.
4. **Misspelled listed name** → HOLD, with the two records side by side.
5. Optional: a simulated watcher event re-tiers an approved customer.
6. Close: "The agent does all of the evidence work. The officer signs a clean release in one click and only digs into exceptions. The model explains; the rules decide."

## 13. Out of scope
Real ERP or email integration · full SCOMET and EAR coverage · UN and EU lists (stretch) · filing licence applications · multi-user auth · job postings (stretch).

## 14. Open questions
- [ ] Python 3.10 with venv, or `uv` with 3.11.
- [ ] Whether the Crustdata and Anthropic keys are available, and what the $4,560 in credits covers.
- [ ] Exact Crustdata field names (A2).
- [ ] Final part catalog (A4).

## 15. Disclaimer
Clearance is a hackathon prototype that automates a compliance workflow. It is not legal advice. In any real deployment, a qualified person reviews and signs all decisions and licence applications.

---

## 16. Your tasks (Person B, branch `product`)

Do S1–S5 with Person A first (§9). "→" marks a dependency.

| ID | Task | Depends on | Done when |
|---|---|---|---|
| B1 | `clearance/llm/client.py`: `anthropic` SDK client, `claude-opus-5-5` from config, `structured(task, schema, input)` using structured outputs, explicit effort per task (§5.4), `stop_reason` handling (`refusal`, `max_tokens`), server-side refusal fallback, response cache in `api_cache` (key = model + prompt version + input). Raises `LLMUnavailable` when the API fails and nothing is cached | S3 | A cached call makes no API request. A mocked refusal raises `LLMUnavailable` |
| B2 | `clearance/llm/prompts.py` (fixed system prompts plus few-shot examples per task, versioned) and `clearance/llm/validate.py` (`check` rejects unknown evidence IDs, `render` substitutes the real values) | B1 | An unknown ID is rejected, and rendering shows the ledger values |
| B3 | `clearance/mail/`: folder mailbox (`mailbox/inbox`, `mailbox/outbox`, `.eml` via stdlib `email`), `poll()`, `parse_order` (Claude → `Order` or `Incomplete(missing_fields)`, each field recorded as evidence), auto-reply for missing details (one round), `send`, and `match_reply` by the `[CLR-<id>]` subject tag or `In-Reply-To` | B1 | A complete email gives an Order. A missing ship-to country sends one auto-reply and the reply merges in. An unmatched reply goes to Exceptions |
| B4 | `clearance/enduse/`: `draft_request`, one targeted follow-up, `extract` (Claude → `EndUseClaim`, including `mapped_needs` and `evasive`), and `check` (calls the injected `screen` and `assess` on the end user, applying the consistency rules in §4.7, including blank or "civilian use" → not consistent) | B1 | A vague first reply triggers one follow-up. An evasive second reply is inconsistent. A good reply naming a listed end user is inconsistent |
| B5 | `eval/`: 30–40 **hand-written** end-use replies (honest, vague, evasive, forwarded chains, transliterated names, mixed-language) with expected fields, plus `eval/score.py` reporting field-level accuracy | B4 | Accuracy reported. Only measured numbers are shown |
| B6 | `clearance/decision/`: `rules.py` (the 12-row table in §4.8 as data, thresholds from config), `decide()`, `explain()` (Claude → `[ExplanationSentence]`, validated by B2), `audit_html()` (state timeline, every evidence item with its source, rule trace, score breakdowns, licence documents, signature, override) | B2 | Every acceptance case in §4.9 gets the expected outcome from fixture inputs |
| B7 | `clearance/pipeline.py`: the state machine (§3), persistence in `orders`/`state_history`/`evidence`/`emails`, `ingest`, `run`, `on_reply`, `sign` (RELEASE/BLOCK only; on a RELEASE signature call A's `watch.register`), `override` (note required). Catches `LLMUnavailable` → rule 10 | B6 | `test_pipeline_stub.py` and the state-transition tests pass |
| B8 | `app.py`: the six screens in §3. The compose-test-email panel, one-click sign, side-by-side fuzzy view, capability feature and percentile table, audit download, override form, and the Customers screen with the simulate-event button (calls A's `watch.simulate_event`) | B7 | All demo scenarios in §12 run from the UI |
| B9 | Tests: `test_llm_validate.py`, `test_mail.py`, `test_enduse.py`, `test_rules.py`. Claude is mocked or served from recorded responses in `tests/fixtures/llm/` | All of the above | `pytest` passes offline |

Then I1–I3 with Person A (§10).

## 17. Your boundaries
- **You own:** `clearance/llm/`, `clearance/mail/`, `clearance/enduse/`, `clearance/decision/`, `clearance/pipeline.py`, `app.py`, `mailbox/`, `eval/`, and your test files.
- **Don't edit:** `crustdata_client.py`, `catalog/`, `screening/`, `capability/`, `watch/`, `data/`. Until A's modules land, use the S5 stubs and fixtures.
- **You are the only caller** of A's modules, through the signatures in §5.2. Don't reach into their internals or the Crustdata cache.
- **Claude never decides anything.** Your Claude calls only parse, extract, map, draft and explain. `buyer_type` is A's deterministic rule, so never ask Claude for it.
- Send Claude only the fields each task needs (§2.7). Never send API keys, the whole order record, or the evidence ledger beyond what is being explained.
