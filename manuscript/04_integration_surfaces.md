# Integration Surfaces: CLI, MCP Server, Agent Skill, and Worked Examples {#sec:integration_surfaces}

The Python API is the primary door into {{PACKAGE_NAME}}, but not the only one. Four additional surfaces sit on top of the same layering described in [@sec:methodology] — transport, client, primitives, composition — and add accessibility rather than logic: the command-line interface, an MCP server, an agent skill, and a set of runnable examples. These interfaces delegate policy and validation to the package modules; the benchmark orchestration surface additionally manages explicit planning, execution and reporting lifecycles. A behaviour fixed in the composition layer therefore reaches every consumer at once: the CLI and the MCP server call the same client and compose functions the Python API calls, the skill documents those entry points, and the examples exercise them.

## Command-line interface

The `daf-jev` console script (`src/daf_jev/cli.py`) exposes commands that cover the package's main paths without writing Python:

- **`daf-jev ask`** — one call, one state: the state arrives as inline text or JSON (`--state`) or from a file (`--state-file`), and one or more `--question ID=SPEC` flags build the question set from a compact grammar (`noul:<instructions>`, `choice:<instructions>:k1=desc,k2=...`, `score:<instructions>:l1,l2,...`). The answer is emitted as JSON (compact by default, `--pretty` for readability).
- **`daf-jev evaluate`** — the batch `Evaluator` of [@sec:methodology] as a command: a fixed question set runs concurrently over many states, and the evaluation records — answers, per-state failures, and measured latency — are emitted as JSON.
- **`daf-jev models`** — lists the available model surface, with `--pick latest|first|last` selecting a single identifier for scripting.
- **`daf-jev docs-verify`** — re-hashes the bundled documentation snapshot against its manifest and exits non-zero on drift; this is the command-line face of Design ruling 4 ([@sec:reproducibility]).
- **`daf-jev serve`** — launches the MCP server described next, over the stdio transport.
- **`daf-jev providers`** — lists the stable registry without network access.
- **`daf-jev posteriors-load` / `posteriors-reask`** — validate retained sidecars and construct a max-entropy plan without a model call.
- **`daf-jev benchmark`** — prepares/fetches datasets, explicitly snapshots a public catalog, freezes a plan, executes/resumes and reports exact retained observations; its orchestration is documented in `docs/decision_benchmarking.md`.

The CLI is a thin adapter in the same sense as the composition layer is pure: it parses arguments, delegates to the client or the composition helpers, and serializes the result. It owns no retry policy, no parsing of answers, and no thresholds.

## MCP server

`src/daf_jev/mcp_server.py` exposes the same core to any MCP-capable agent host. Launched with `daf-jev serve` over the stdio transport, it advertises nine tools that mirror the package one-to-one:

- `jev_ask` — drives the client's single-call path: named questions (`noul` / `choice` / `score`, given in the same compact grammar the CLI accepts or as native `{type, instructions, criteria}` dicts) asked about one state;
- `jev_evaluate` — drives the batch path, running a fixed question set over many states concurrently;
- `jev_models` — reports (and optionally picks from) the available model surface;
- `jev_composite_score`, `jev_confidence_gate`, and `jev_tiered_gate` — expose the composition patterns of [@sec:methodology]; these combine answers locally with no API call at all;
- `jev_docs_verify` — re-runs the documentation drift check of Design ruling 4;
- `jev_posteriors_load` and `jev_reask_plan` — validate sidecars and compute an evidence-bearing posterior plan, with no API call.

A `jev://docs/snapshot` resource serves a summary of the bundled documentation snapshot itself, so an agent can inspect what the model-level claims rest on without leaving its host. The server is a thin adapter — it owns no retry policy, no parsing, and no thresholds; every call delegates to `JevClient`, `AsyncJevClient`, or the pure composition functions.

Registering the server with an MCP client is a one-block stdio configuration; with the package installed (or, equivalently, `command: "uv"` with `args: ["run", "daf-jev", "serve"]` inside the repository):

```json
{
  "mcpServers": {
    "daf-jev": {
      "command": "daf-jev",
      "args": ["serve"]
    }
  }
}
```

The MCP extra (`pip install "daf-jev[mcp]"` or `uv sync --extra mcp`) is the only optional dependency this surface adds; the core package does not depend on it.

## Agent skill

`skills/daf-jev/SKILL.md` is a skill manifest for coding agents: it states when to reach for the package, and how — the builders and their constraints, the client surface, the evaluation harness, the composition patterns, the CLI subcommands, and the MCP tools — so an agent can use the package correctly without reading its source. The skill carries no logic of its own; it is documentation positioned where agents look for it, and it points at the same entry points the CLI and MCP server expose.

## Worked examples

Thirteen self-contained scripts under `examples/` walk the typical integration path from a first call to a batch evaluation, doubling as executable documentation of the composition layer:

- **`quickstart.py`** — the shortest path to a typed answer: build a question set, make one call, read the typed answers;
- **`triage_router.py`** — confidence-gated routing end to end: a `choice` call dispatched by `route()` with a fallback for low-confidence answers;
- **`composite_scoring.py`** — a `score` call turned into a comparable scalar by `composite_score()` and verdict-banded by `confidence_gate()`;
- **`evaluate_corpus.py`** — the batch `Evaluator` over many states, with per-state failure capture and summary aggregates;
- **`decider_loop.py`** — the decision-point loop end to end: observe → compose → ask → gate → fail-open, with typed hooks, a deterministic lexicon as the floor action, a `Budget` bound, and JSON decision receipts;
- **`gated_fallback.py`** — a deterministic keyword heuristic answering first, with the model called only when the heuristic is not confident enough, `confidence_gate(below="escalate")` as the final escalation lane, and a `UsageLedger` accounting every model call the fallback makes.

The remaining walkthroughs cover provider dispatch, Asia elicitation/inference, resilience, in-loop async evaluation, calibration, retry policies and posterior re-asking. Model-backed scripts use the real endpoint when a key is present and skip without a key; `providers_example.py` always uses an injected transport. These walkthroughs demonstrate APIs rather than a labeled benchmark corpus.

## Benchmark orchestration and offline reports

The benchmark CLI exposes dataset preparation and views, explicit catalog snapshots, immutable planning, execution/resume and offline reporting. Planning performs no inference. Catalog retrieval is a separate public metadata operation. Execution requires the selected backend's actual capability, financial and resource admission; a saved plan does not grant those conditions. Reports retain dataset IDs and exact prepared-input hashes, planned cell and decision counts, probability-meaning availability and attempt outcomes.

This surface connects reusable adapters to experiments without placing policy inside a provider client. CPU comparators fit only the declared training view, gates select on validation, and the evaluator scores retained test targets. Markdown, JSON and PDF summaries can be regenerated from selected records without making a new model request. The example scripts demonstrate APIs; the experiment manifests and their retained receipts establish which benchmark operations actually ran.
