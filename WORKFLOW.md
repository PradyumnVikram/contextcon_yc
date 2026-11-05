# WORKFLOW.md: how Clearance is structured and how it flows

This file covers the **project mechanics**: how code is laid out, how an order moves through it, which files are shared, and how the two of us keep `main` working while building in parallel. What each person builds lives in `AGENTS_DATA.md` (Person A) and `AGENTS_PRODUCT.md` (Person B).

---

## 1. The system in one picture

```
 mailbox/inbox/*.eml
        │
        ▼
 ┌──────────────┐   Order / Incomplete    ┌───────────────────────────────────────────────┐
 │ mail/   (B)  │ ──────────────────────► │ pipeline.py (B): the only orchestrator         │
 │ parse, reply │ ◄────── emails out ──── │ state machine, persistence, sign/override      │
 └──────────────┘                         └───┬─────────┬──────────┬─────────┬────────┬────┘
                                              │         │          │         │        │
                         ┌────────────────────┘         │          │         │        └──────────┐
                         ▼                              ▼          ▼         ▼                   ▼
                  catalog/ (A)                   screening/ (A) capability/ (A)  enduse/ (B)   decision/ (B)
                  classify, licence              screen         assess          extract,      decide, explain,
                                                                  │              check         audit_html
                                                                  ▼                │              │
                                                     crustdata_client.py (A)   llm/ (B) ◄─────────┘
                                                                  │               │
                         ┌────────────────────────────────────────┴───────────────┴─────────┐
                         │ SHARED: models.py · evidence.py (Ledger) · store.py (SQLite) · config.py │
                         └──────────────────────────────────────────────────────────────────┘
 app.py (B): Streamlit screens read store.py and call pipeline.py
 watch/ (A): FastAPI webhook → re-runs capability → updates customers table
```

**Three rules hold everywhere:**
1. **Only `pipeline.py` calls modules.** Modules never import each other. `enduse.check` receives `screening.screen` and `capability.assess` as function arguments.
2. **Every module records facts through the `Ledger`** and returns a model from `models.py`, never raw JSON.
3. **Every external call is cached** in `store.api_cache`. Tests never touch the network.

## 2. How one order flows

| Step | State after | Who runs it | Function | Output |
|---|---|---|---|---|
| 1. Email lands in `mailbox/inbox` | `EMAIL_RECEIVED` | B | `mail.poll()` | `Email` |
| 2. Parse order | `PARSED` or `AWAITING_ORDER_DETAILS` | B | `mail.parse_order(email, ledger)` | `Order` or `Incomplete`. If incomplete, one auto-reply goes out, then the order holds |
| 3. Classify parts and check licences | `CLASSIFIED` | A | `catalog.classify`, `catalog.licence` | `Classification`, `LicenceResult` per line |
| 4. Screen all parties | `SCREENED` | A | `screening.screen(party, ledger)` | `ScreeningResult` per party (buyer, ship-to, middleman, shipper) |
| 5. Capability check on the buyer | `CAPABILITY_CHECKED` | A | `capability.assess(...)` | `CapabilityResult` (coverage, buyer type, score, tier) |
| 6. Decide | `RECOMMENDED` or `AWAITING_END_USE` | B | `decision.decide(order, OrderResults, ledger)` | `Decision` |
| 7. End-use loop (if rule 6 or 7 fired) | `AWAITING_END_USE` | B | `enduse.draft_request` → email out → reply → `enduse.extract` → `enduse.check(…, screen, assess, …)` | `EndUseResult`. Back to step 6 with `end_use` filled in |
| 8. Explain and audit | `RECOMMENDED` | B | `decision.explain`, `decision.audit_html` | Cited sentences (IDs checked), HTML audit |
| 9. Officer acts | `SIGNED` | B (UI) | `pipeline.sign` / `pipeline.override` | Signature or override recorded. A signed RELEASE calls `watch.register` |
| 10. Monitoring | (customer tier) | A | `watch` webhook / `simulate_event` | Re-tiered customer. Their next order gets a full review |

`OrderResults` (in `models.py`) is the single bundle passed from steps 3–7 into `decide`, so B's decision code only depends on models, not on A's modules.

## 3. Repo layout

```
contextcon_yc/
├── WORKFLOW.md                 this file (shared)
├── AGENTS_DATA.md              Person A brief
├── AGENTS_PRODUCT.md           Person B brief
├── README.md  pyproject.toml  .env.example  .gitignore            SHARED
├── clearance/
│   ├── models.py               SHARED, frozen contracts
│   ├── evidence.py             SHARED, Ledger
│   ├── store.py                SHARED, SQLite schema + helpers
│   ├── config.py               SHARED, every weight, threshold, model id
│   ├── crustdata_client.py     A
│   ├── catalog/                A
│   ├── screening/              A
│   ├── capability/             A
│   ├── watch/                  A
│   ├── llm/                    B
│   ├── mail/                   B
│   ├── enduse/                 B
│   ├── decision/               B
│   └── pipeline.py             B (not created yet)
├── app.py                      B (not created yet)
├── data/                       A: catalog.csv, licence_rules.csv, csl.csv, test_companies.csv
├── mailbox/inbox, outbox/      B: simulated email (.eml files are git-ignored)
├── eval/                       B: hand-written end-use replies + scorer
└── tests/
    ├── fixtures/cases.py       SHARED: the 9 acceptance cases as orders
    ├── test_shared.py          SHARED: models, ledger, store
    ├── test_data_stubs.py      A: contract tests for A's modules (replaced by real tests in A12)
    └── test_*.py               one file per module, owned by that module's owner
```

## 4. What exists today (shared foundation on `main`)

| File | Status |
|---|---|
| `models.py`, `evidence.py`, `store.py`, `config.py` | **Done.** Shared contracts, ledger, all SQLite tables, all tunables |
| `tests/fixtures/cases.py`, `tests/test_shared.py` | **Done.** 9 acceptance cases, shared-layer tests |
| `catalog/`, `screening/`, `capability/`, `watch/`, `crustdata_client.py` | **Stubs** (`STUB = True`). Correct signatures and fake data; A replaces them |
| `llm/`, `mail/`, `enduse/`, `decision/` | **Empty packages.** B writes their stubs and real code |
| `pipeline.py`, `app.py` | **Not created.** B creates them (B7, B8) |

A module's stub keeps the exact function signature from AGENTS §5.2. When the real implementation lands, delete `STUB = True`.

## 5. Setup (both)

```bash
git clone https://github.com/PradyumnVikram/contextcon_yc.git && cd contextcon_yc
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # shared layer + pytest
pip install -e ".[data]"           # Person A extras (httpx, pandas, rapidfuzz, fastapi, uvicorn)
pip install -e ".[product]"        # Person B extras (anthropic, streamlit)
cp .env.example .env               # fill in keys, never commit
pytest                             # must be green before every merge
```

If a system install adds its own pytest plugins (for example ROS through `PYTHONPATH`), run `env -u PYTHONPATH pytest`.

## 6. Branches and keeping `main` working

| Branch | Who | Purpose |
|---|---|---|
| `main` | both | **Integration branch. Always green.** The shared foundation lives here, and every finished feature lands here |
| `dev` | Person A | A's working branch |
| `dev2` | Person B | B's working branch |

**Feature loop (both people, every finished task):**
1. Finish a task on your branch, with its tests.
2. `git fetch origin && git merge origin/main` into your branch, then fix any conflicts.
3. `pytest` must pass, including everyone's tests.
4. Open a PR into `main` (or merge directly if you're both online and agree). Title: `[A6] employee background check`.
5. Tell your teammate. They run `git pull origin main` into their branch straight away.

**Shared files** (`models.py`, `evidence.py`, `store.py`, `config.py`, `pyproject.toml`, `tests/fixtures/`, `WORKFLOW.md`, §1–§15 of both AGENTS files):
- Change them only after both people agree.
- Put the change in a commit of its own with nothing else in it, and get it to `main` first.
- Adding a new `config.py` key that only your module reads is fine without asking. Renaming or removing a key is not.

**Never:** force-push `main`, commit `.env` or `clearance.db`, or edit the other person's folders (use stubs instead).

## 7. Checkpoints (verify after each feature)

Each checkpoint is a command you can run plus what you should see. Person A's checkpoints, in task order:

| # | After | Run | Expect |
|---|---|---|---|
| CP0 | Shared foundation | `pytest` | 7 passed |
| CP1 | A1 Crustdata client | `pytest tests/test_crustdata_client.py`, then one live `enrich_company` called twice | Second call served from `api_cache` (no HTTP) |
| CP2 | A2–A3 coverage | `python -m clearance.capability.coverage_report` | `missing/thin/rich` for 5 companies, go/no-go recorded |
| CP3 | A4 catalog | `pytest tests/test_catalog.py` | Unknown part → `found=False`. India + US-origin part → EAR reason |
| CP4 | A5 screening | `pytest tests/test_screening.py` | Exact / fuzzy (with breakdown) / clear / forwarder |
| CP5 | A6–A7 background check, buyer type | `pytest tests/test_capability.py -k people` | One person-search per company. Buyer-type votes correct |
| CP6 | A8 peers | `pytest tests/test_capability.py -k peers` | Percentiles with peer count in evidence |
| CP7 | A9 capability scoring | `pytest tests/test_capability.py` | Radar `consistent`, distributor `consistent`, shell `high_risk`, no record `no_data` |
| CP8 | A10–A12 | `pytest` | All green. Every acceptance case has a buyer in `data/test_companies.csv` |
| CP9 | I1–I2 integration | `pytest tests/test_cases.py` | 9/9 acceptance cases produce the §4.8 recommendation |

Person B defines their checkpoints in `AGENTS_PRODUCT.md` §16 as they go.
