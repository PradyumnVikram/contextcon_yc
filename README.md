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
pytest                          # 72 passed
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

## Getting started

### Run the officer app

```bash
streamlit run app.py
```

Then try the main demo flow:

1. **Inbox:** open *Compose test email*, pick the preset **"Radar firm order (clean)"**, and click **Drop into inbox**.
2. Click **📥 Process inbox** in the sidebar. The local LLM parses the email, and the order moves through classification, screening and the capability check.
3. **Ready to sign:** enter your name in the sidebar (*Officer name*) and click **✍️ Sign RELEASE**.
4. **Customers:** the buyer now appears as a watched customer. Click **Simulate Crustdata event** to re-tier it.

Other presets to try:

| Preset | What should happen |
|---|---|
| Shell trader order | **AWAITING_END_USE**. An end-use request is sent (see *Inbox → Sent by Clearance*). Reply with the same `[CLR-…]` subject and a vague answer: you get one follow-up, then **HOLD** |
| Unknown company (no data) | **HOLD**: no company data, so an end-use statement is requested and never auto-released |
| Close spelling of a listed name | **HOLD**, with both records side by side under *Order detail → Screening* |
| Order with missing destination | Clearance emails the buyer for the missing field. Reply, and the order continues |

*Order detail* shows the state timeline, every evidence item, the rule trace, the capability features with peer percentiles, the audit file download, and override with a required note.

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
app.py          Streamlit officer UI
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
