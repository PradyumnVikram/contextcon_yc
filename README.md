# Clearance

**An autonomous export-compliance agent for Indian electronics exporters.** Built for the ContextCon hackathon (Crustdata), theme *"Services, Replaced"*.

An order for sensitive electronic parts arrives by email. Clearance:
1. reads the order;
2. classifies each part against SCOMET and EAR controls;
3. screens every party against the US Consolidated Screening List;
4. checks whether the buyer can actually use what it's buying, using Crustdata company and employee data.

If the risk is unclear, it emails the buyer for an end-use statement. It then recommends **RELEASE**, **LICENCE_REQUIRED**, **HOLD** or **BLOCK**, and every recommendation cites the evidence behind it. A compliance officer handles the exceptions and signs every release and block.

> **Design rules:** the LLM never decides anything. Fixed rules decide, and the LLM only reads emails, drafts replies and explains. By default the LLM runs **locally** (Ollama), so customer data never leaves the machine.

---

## How it works

```
 email in ─► parse order ─► classify parts ─► screen parties ─► capability check ─► decide ─► officer signs
 (mailbox/)   (local LLM)    (catalog.csv)     (US CSL)          (Crustdata data)    (12 rules)  (Streamlit)
                  │                                                    │
                  └─ missing details? ask the buyer        risky? ─► end-use email loop (one follow-up)
```

Every step records evidence (`E1`, `E2`, …) with its source. The audit file for each order lists all of it. For the full flow, module map and order states, see [`WORKFLOW.md`](WORKFLOW.md).

---

## Requirements

| What | Version / notes |
|---|---|
| Python | 3.10 or newer |
| [Ollama](https://ollama.com) | Runs the local LLM. Default model `qwen3:8b`: about 5 GB, and fits an 8 GB GPU (it also runs on CPU, more slowly) |
| Git, `gh` (optional) | For the team workflow |
| Crustdata API key | Optional. Without it, the synthetic demo companies are served from fixtures |
| Anthropic API key | Optional. Only if you switch the LLM to Claude |

---

## Setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/PradyumnVikram/contextcon_yc.git
cd contextcon_yc

# 2. Virtual environment and dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[data,product,dev]"

# 3. Local LLM
ollama pull qwen3:8b            # once; then make sure the Ollama service is running
curl -s localhost:11434/api/version

# 4. Configuration
cp .env.example .env            # defaults work offline; add keys only if you have them

# 5. US Consolidated Screening List (~10 MB, git-ignored)
python -m clearance.screening.csl

# 6. Check everything works
pytest                          # 79 passed
```

### `.env` settings

| Variable | Default | Purpose |
|---|---|---|
| `CLEARANCE_LLM` | `ollama` | `ollama` for the local model, or `claude` for the Anthropic API |
| `OLLAMA_MODEL` | `qwen3:8b` | Any Ollama model that supports structured output |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server address |
| `CRUSTDATA_API_KEY` | (empty) | Live Crustdata calls. Empty means fixtures only |
| `ANTHROPIC_API_KEY` | (empty) | Needed only with `CLEARANCE_LLM=claude` |
| `CLEARANCE_DB` | `clearance.db` | SQLite file for orders, evidence and API caches |
| `CLEARANCE_MAILBOX` | `mailbox` | Folder for the simulated inbox and outbox |
| `CLEARANCE_WEBHOOK_URL` | (empty) | Public URL (e.g. ngrok) for Crustdata watcher callbacks |

---

## Getting started: the two-window demo

Open two terminals and run both apps. They share the `mailbox/` folders:

```bash
streamlit run app.py                              # window 1: Clearance  -> http://localhost:8501
streamlit run buyer_app.py --server.port 8502     # window 2: buyer mail -> http://localhost:8502
```

**Window 1, Clearance**, is the service, laid out in three panes:

| Pane | What it shows |
|---|---|
| 📨 **Inbox** | Every order as a card with its status, and the full email conversation for the selected order |
| 🔍 **Processing** | Everything Clearance checked: pipeline steps, the extracted order, parts and licence, restricted-list screening, the Crustdata capability check (company data, employee background, peer percentiles, triggered rules), the end-use statement, and every piece of evidence |
| ✍️ **Action** | The recommendation with its cited explanation, **Sign**, **Override** (reason required), the audit file, and the queues *Ready to sign / Exceptions / Waiting on buyer* |

**Auto-process inbox** is on by default, so the service picks up new mail by itself. You can pause it from the sidebar.

**Window 2, Buyer mail**, is a simple mail client:
1. Pick who you are writing as (**Write as**), edit the subject and message, and click **Send ➤**.
2. Within a few seconds Clearance processes the email. When it needs something (missing details, an end-use statement, a follow-up), its email arrives in this window's **Inbox**.
3. Click **↩️ Reply**. The reply keeps the `[CLR-…]` tag and `In-Reply-To`, so Clearance links it to the original order automatically. Pick a **Quick answer** or type your own.

### Demo script

| Write as | Expected |
|---|---|
| **Astra Microwave (REAL)** | Live Crustdata lookup by the sender's domain (`astramwp.com`): clear on the screening list, *Consistent* against real Indian defence peers → **Release**. Sign it in the Action pane |
| **Data Patterns (REAL)**, export to Germany | **Licence required**, with the documents to collect listed |
| **Synthetic shell Traders** | Capability mismatch → end-use request in the buyer inbox. Reply "civilian use only" → one targeted follow-up arrives. Reply vaguely again → **Hold** in Exceptions |
| **Synthetic nodata Enterprises** | No company data → **Hold**, with an end-use statement requested. The officer decides |
| **Listed Electronic Tradng** | Close spelling of a listed entity → **Hold**, with both names side by side in Processing |

**Using real companies:** send from the company's real domain (for example `procurement@<company>.com`). Clearance identifies the buyer by the sender's corporate domain; free-mail addresses are ignored, and a website written in the email takes precedence. The first live check of a new company costs about **70 Crustdata credits** (company record, 25 employees, about 20 peers), and repeats come from the cache. Check your key and balance with `python -m clearance.crustdata_client`.

> **Ethics rule:** use real companies only as *legitimate* buyers. Never present a real company that isn't on a restricted list as suspicious. The suspicious and listed-entity scenarios use synthetic companies.

No UI at all? `python -m clearance.worker` processes the mailbox headlessly and prints each decision.

### Other entry points

```bash
python -m clearance.capability.coverage            # Crustdata coverage go/no-go for the demo companies
python -m clearance.capability.coverage acme.com   # ... or any domain (live key needed for real companies)
python eval/score.py                               # LLM extraction accuracy on eval/replies.jsonl
uvicorn clearance.watch.webhook:app --port 8000    # Crustdata watcher webhook (expose with ngrok)
python scripts/make_demo_crustdata.py              # regenerate the synthetic demo company fixtures
```

### Switch the LLM

```bash
CLEARANCE_LLM=claude ANTHROPIC_API_KEY=sk-... streamlit run app.py   # Claude API (claude-opus-5-5)
OLLAMA_MODEL=qwen3:14b streamlit run app.py                         # a bigger local model
```

Every LLM response is cached in SQLite, so a repeated request is instant and costs nothing.

---

## Project layout

```
clearance/
  models.py, evidence.py, store.py, config.py   shared contracts, evidence ledger, SQLite, every tunable
  crustdata_client.py                           cached, throttled Crustdata client (+ demo fixtures)
  catalog/      part classification + SCOMET/EAR licence rules     (data/catalog.csv, licence_rules.csv)
  screening/    US CSL download + fuzzy matching                   (data/csl.csv, csl_demo.csv)
  capability/   employee background check, buyer type, peers, risk scoring
  watch/        customer monitoring + FastAPI webhook
  llm/          local Ollama adapter, optional Claude client, prompts, evidence-ID validator
  mail/         folder mailbox, order parsing, reply matching
  enduse/       end-use request, follow-up, extraction, consistency check
  decision/     12-row rules table, cited explanation, HTML audit
  pipeline.py   the order state machine (the only orchestrator)
app.py          Clearance officer workspace (3 panes)
buyer_app.py    simulated buyer mail client (the other demo window)
data/           catalog, licence rules, demo list, synthetic Crustdata fixtures
eval/           hand-written end-use replies + scorer
tests/          pytest suite (offline: no network, fake LLM, fixtures)
```

---

## Working on the code

| | Person A | Person B |
|---|---|---|
| Brief | [`AGENTS_DATA.md`](AGENTS_DATA.md) | [`AGENTS_PRODUCT.md`](AGENTS_PRODUCT.md) |
| Branch | `dev2` | `dev` |
| Owns | Crustdata, catalog, screening, capability, watcher | LLM, mail, end-use, decision, pipeline, UI |

- **Read first:** [`WORKFLOW.md`](WORKFLOW.md) for structure and checkpoints, then your own brief from its "★ Your job" section. §1–§15 are identical in both briefs, so change them in both files in the same commit.
- **`main` must always pass its tests.** After each finished feature:
  1. run `git merge origin/main` on your branch;
  2. run `pytest` and make sure it's green;
  3. open a PR into `main`;
  4. tell your teammate, who then pulls `main`.
- **Shared files need both people's agreement.** That covers `models.py`, `evidence.py`, `store.py`, `config.py`, `pyproject.toml`, `tests/fixtures/` and `tests/conftest.py`. Commit any change to them on its own.
- **Never commit** `.env`, `clearance.db`, `data/csl.csv`, or `.eml` files in the mailbox.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `pytest` crashes importing `launch` or `yaml` | A system install (e.g. ROS) is injecting plugins. Run `env -u PYTHONPATH pytest` |
| Every order ends in **HOLD (R10)** | The LLM isn't reachable. Check `ollama serve` / `curl localhost:11434/api/version`, and that the model is pulled |
| Screening finds nothing real | Run `python -m clearance.screening.csl` to download the list (tests use a small sample) |
| A company shows "no data" | Without `CRUSTDATA_API_KEY`, only the synthetic demo companies in `data/demo_crustdata/` are known |

---

*Prototype for a hackathon. Not legal advice. In any real deployment, a qualified person reviews and signs every decision and licence application. All demo companies and the demo listed entities are synthetic.*
