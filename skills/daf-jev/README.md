# daf-jev skill

Agent-facing skill for the daf-jev Python toolkit. The skill itself is
[`SKILL.md`](SKILL.md) (YAML frontmatter + Markdown body); installing skill
directories into an agent is covered one level up in
[`../README.md`](../README.md).

## What this skill covers

- When to reach for daf-jev, install, and the Python API surface
  (builders, clients, evaluation, compose, ledger, resilience, decider,
  calibration, graphical models).
- CLI, provider registry (six providers, stable keys), MCP server.
- Jev to RxInfer.jl pipeline quick reference (elicit → GraphSpec → GNN
  bridge → Julia marginals → posteriors fed back), with artifact links.

## Install the package (context for the skill)

```bash
uv sync --extra dev            # tests + tooling
uv sync --extra figures        # PNG plotters (graphical_viz, figures)
uv sync --extra mcp            # only for `daf-jev serve` (MCP server)
export JEV_API_KEY=...         # or any provider's key; .env also loaded
```

Every `examples/` script and `scripts/bayes_experiment.py` prints
`SKIP: JEV_API_KEY not set` and exits 0 without a key.

## Pointers

- Human overview: [`../../README.md`](../../README.md) (graphical models:
  [`#graphical-models`](../../README.md#graphical-models))
- Agent contract + cross-repo pipeline story: [`../../AGENTS.md`](../../AGENTS.md)
- Architecture contract: [`../../docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
- Live experiment receipts:
  [`../../output/experiments/asia/receipts.json`](../../output/experiments/asia/receipts.json)
- Cross-repo bridge: GNN
  [PR #165](https://github.com/ActiveInferenceInstitute/Generalized_Notation_Notation/pull/165)
  (branch `feat/rxinfer-bridge`, `examples/rxinfer/`)