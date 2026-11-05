# contextcon_yc: Clearance

An autonomous export-compliance agent for Indian electronics exporters, built for ContextCon (Crustdata), theme "Services, Replaced". An order email comes in, and Clearance classifies the parts, screens every party against the US Consolidated Screening List, and checks whether the buyer can actually use what it's buying, using Crustdata evidence. It then recommends RELEASE / LICENCE_REQUIRED / HOLD / BLOCK and cites the evidence behind it. A compliance officer signs every release and block.

## Who does what
| | Person A | Person B |
|---|---|---|
| Brief | `AGENTS_DATA.md` | `AGENTS_PRODUCT.md` |
| Branch | `dev2` | `dev` |
| Job | Data and risk signals: Crustdata, catalog and licence, CSL screening, capability engine, watcher | Agent and product: local LLM (Ollama), mail, end-use loop, decisions and audit, pipeline, UI |
| Tasks | S1–S5, A1–A12, I1–I3 | S1–S5, B1–B9, I1–I3 |

Open your own brief and start at the "★ Your job" section.

## Agent briefs
- [`AGENTS_DATA.md`](AGENTS_DATA.md): Person A, data and risk signals (Crustdata, catalog, screening, capability, watcher).
- [`AGENTS_PRODUCT.md`](AGENTS_PRODUCT.md): Person B, agent, LLM and product (local LLM, mail, end-use loop, decision, pipeline, UI).

§1–§15 are shared and identical in both files. Change them in both files in the same commit.

## Branching
See `WORKFLOW.md` §6. `main` is the always-green integration branch with the shared foundation. Person A works on `dev2`, Person B on `dev`. After each finished, tested feature: merge `origin/main` into your branch, run `pytest`, merge into `main`, and the other person pulls `main`.

Start with [`WORKFLOW.md`](WORKFLOW.md) for structure, flow, setup and checkpoints.
