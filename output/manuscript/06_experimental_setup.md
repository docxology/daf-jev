# Experimental Setup: Live-API Benchmark Protocol, Environment, and Data Provenance {#sec:experimental_setup}

This section records the environment, configuration, and measurement protocol behind the results in [@sec:results], so that the runs can be reproduced bit-for-bit in intent.

## Software environment

All measurements were taken with daf-jev version 0.6.0, running under 3.14.4 on the platform reported as `macOS-26.6.2-arm64-arm-64bit-Mach-O`. The package targets Python 3.10 or newer and depends, at runtime, only on `httpx` for transport and `pyyaml` for configuration parsing; the benchmark scripts additionally use the standard library. The development toolchain is `uv`-managed, and the unit test suite is executed with `pytest` under a coverage gate.

The model-level claims in [@sec:jev_model] are grounded in a local, hash-manifested snapshot of the TypeSafe documentation (snapshot b79c9cd6008489f1, 108 pages) rather than the live website, so the primary-source basis of this manuscript is itself versioned and verifiable.

## Benchmark configuration

All benchmarks execute against the real jev-latest model with a live API key resolved through the package's credential precedence chain (injected mapping, then process environment, then the project `.env` file). Without a key, the scripts print a skip notice and exit successfully — they are benchmarks, not tests, and never run inside the test suite.

- **Batching benchmark** (`benchmarks/bench_batching.py`) — for each configured batch width (5, 10, 20 questions, as recorded under `experiment.batching_n_values` in `manuscript/config.yaml`), it compares one batched call against the same number of sequential single-question calls over a fixed state paragraph and a mixed noul/choice/score question set, repeating each strategy for the configured number of runs (default recorded under `experiment.batching_runs`) and recording wall time and token totals to `output/benchmarks/batching_<date>.json`.
- **Decision-pattern benchmark** (`benchmarks/bench_patterns.py`) — runs the composite-score and intent-routing pipelines 6 times each (default recorded under `experiment.patterns_runs`), reporting mean, median, and tail wall times plus token totals to `output/benchmarks/patterns_<date>.json`. An asynchronous mode executes the same runs concurrently through `AsyncJevClient` and compares against the sequential wall time.
- **Calibration benchmark** (`benchmarks/bench_calibration.py`) — runs 6 short states 5 times each (defaults recorded under `experiment.calibration_states` and `experiment.calibration_repeats`) against the jev-latest model, scores choice answers under the self-consistency proxy (agreement with the modal choice across repeats) and noul answers by mean pairwise stability, and writes the expected calibration error, Brier score, per-bucket reliability data, and the mean pairwise noul gap to `output/benchmarks/calibration_<date>.json`, together with a `notes` field stating the proxy semantics.

The batching and decision-pattern scripts take `--runs` and `--model` (`bench_patterns.py` additionally accepts `--async` for the asynchronous mode described above); the calibration script takes `--states`, `--repeats`, and `--model`, with no run-repetition argument. The defaults are recorded as data under the `experiment:` block of `manuscript/config.yaml`, which is the same file the manuscript-variable generator reads — configuration, prose, and figures cannot disagree about the protocol.

## Measurement protocol

Percentiles follow the benchmark helper shared by all three scripts: the reported tail statistic is the value at the ceiling-rank position of the ordered sample, computed over the recorded runs rather than a sliding window. Wall time covers the full pipeline — transport, retries (none should occur in a healthy run), parsing, and composition logic — so the numbers in [@tbl:latency] are conservative upper bounds on what an integrating application would add to its request path. Token totals are read from the response usage records, not estimated.

This manuscript was generated at 2026-09-24T16:38:44Z; the rendered values in [@sec:results] correspond to the benchmark JSONs current at that timestamp, and the figure generators resolve "latest" the same way (latest by filename date) so that re-rendering after a new benchmark run updates prose, tables, and figures together.
