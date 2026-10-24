# Agent Skills index

Skills use the Agent Skills directory convention: each skill lives under `.agents/skills/<name>/SKILL.md`, starts with YAML frontmatter, has a focused description, and may carry on-demand references/scripts. Keep skills atomic and below 500 lines.

- `research-orchestration` — task selection, gate sequencing, checkpointing, handoffs.
- `historical-universe` — historical point-in-time market-cap ranks, expanding cohorts, resume cursors.
- `funding-accounting` — funding settlement timing, long/short cash-flow signs, price/basis PnL, fees and slippage.
- `red-team-audit` — leakage, missingness, costs, multiple testing, reproducibility, independent review.

Always-on invariants live in `AGENTS.md`; the full experiment lives in `docs/research_protocol.md`; the durable next task lives in `HANDOFF.md`.
