# contextcon_yc: Clearance

An autonomous export-compliance agent for Indian electronics exporters, built for ContextCon (Crustdata), theme "Services, Replaced". An order email comes in, and Clearance classifies the parts, screens every party against the US Consolidated Screening List, and checks whether the buyer can actually use what it's buying, using Crustdata evidence. It then recommends RELEASE / LICENCE_REQUIRED / HOLD / BLOCK and cites the evidence behind it. A compliance officer signs every release and block.

## Agent briefs
- [`AGENTS_DATA.md`](AGENTS_DATA.md): Person A, data and risk signals (Crustdata, catalog, screening, capability, watcher).
- [`AGENTS_PRODUCT.md`](AGENTS_PRODUCT.md): Person B, agent, LLM and product (Claude, mail, end-use loop, decision, pipeline, UI).

§1–§15 are shared and identical in both files. Change them in both files in the same commit.

## Branching
- `main`: stable. Only receives `dev` by pull request when a feature is complete.
- `dev`: integration branch. Shared tasks (S1–S5) are done here together.
- `data`: Person A's branch. `product`: Person B's branch. After each finished task with tests passing, rebase on `dev` and merge into `dev`.
- Changes to the shared contracts (`clearance/models.py`, `store.py` schema, `config.py` keys) go to `dev` first, in their own commit, and both branches pull straight away.
