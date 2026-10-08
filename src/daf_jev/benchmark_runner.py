"""Explicit experiment planning, bounded execution, resume, and offline reports."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import math
import os
import platform
import random
import stat
import subprocess
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from daf_jev._json import strict_json_loads
from daf_jev._yaml import strict_yaml_loads
from daf_jev.benchmark_datasets import pilot_samples, prepared_dataset_from_dict
from daf_jev.benchmark_graphical import (
    GraphicalExperimentError,
    reference_graph,
    run_graphical_experiment,
)
from daf_jev.benchmark_metrics import audit_dataset, repeatability, score_predictions
from daf_jev.benchmark_models import (
    RuleDecisionBackend,
    SklearnDecisionBackend,
    fit_prior,
)
from daf_jev.benchmark_policies import calibrate_gate, replay_policy
from daf_jev.benchmark_resources import ResourceSampler, hardware_identity
from daf_jev.benchmark_sampling import timing_sample_pack
from daf_jev.benchmark_store import (
    BudgetStopped,
    RunStore,
    SpendLedger,
    currency_context,
    sync_directory,
    usd,
    usd_total,
)
from daf_jev.benchmark_workflows import CascadeDecisionBackend, gate_from_dict
from daf_jev.decision_backends import (
    AsyncHTTPDecisionBackend,
    BackendCapabilities,
    BackendHTTPError,
    DecisionRequest,
    DecisionResult,
    PriorBackend,
    ThreadedAsyncBackend,
    canonical_json,
    content_hash,
    utc_now,
    validate_endpoint,
)

FORMAT = "dafjev.benchmark-run/1"
ROOT = Path(__file__).resolve().parents[2]
EXECUTION_PHASES = ("capability_probe", "quality", "warm_repeat", "graphical")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input_bytes(path: Path) -> bytes:
    """Consume one regular file once, checking identity throughout the read."""
    path = path.absolute()
    lineage = [path, *path.parents]
    if any(item.is_symlink() for item in lineage):
        raise ValueError("benchmark inputs must not traverse symlinks")
    ancestors = [(parent, parent.stat().st_dev, parent.stat().st_ino) for parent in path.parents]
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("benchmark input must be a regular file")
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            data = handle.read()
        after = os.fstat(descriptor)
        current = path.stat()
        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (identity(before) != identity(after) or identity(current) != identity(after)
                or any(item.is_symlink() for item in lineage)
                or any((parent.stat().st_dev, parent.stat().st_ino) != (dev, ino) for parent, dev, ino in ancestors)):
            raise ValueError("benchmark input changed during consumption")
        return data
    finally:
        os.close(descriptor)


def snapshot_catalog(path: Path) -> dict[str, Any]:
    """Explicit public GET only. This establishes discovery, never inference."""
    url = "https://openrouter.ai/api/v1/models?output_modalities=decisions"
    with urlopen(url, timeout=30) as response:
        payload = strict_json_loads(response.read())
    if not isinstance(payload.get("data"), list):
        raise ValueError("invalid model catalog")
    result = {"format": "dafjev.model-catalog/1", "source": url, "fetched_at": utc_now(), "payload": payload}
    with path.open("x") as handle:
        handle.write(canonical_json(result) + "\n")
    return result


def source_identity() -> dict[str, Any]:
    files = {str(p.relative_to(ROOT)): _file_hash(p) for p in sorted((ROOT / "src" / "daf_jev").glob("*.py"))}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    packages: dict[str, str | None] = {}
    for name in ("httpx", "PyYAML", "scikit-learn", "numpy", "psutil"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"git_head": head, "files": files, "python": platform.python_version(),
            "platform": platform.system(), "architecture": platform.machine(), "hardware": hardware_identity(),
            "dependencies": packages}


def _reporter_source(package_root: Path) -> dict[str, Any]:
    """Bind the complete SDK Python inventory, consuming verified regular files.

    This identifies the reducer source separately from a run's frozen inference
    source. It contains no timestamp or hardware observations.
    """
    files = {"src/daf_jev/" + path.name: hashlib.sha256(_input_bytes(path)).hexdigest()
             for path in sorted(package_root.glob("*.py"))}
    if not files:
        raise ValueError("reporter source inventory must be nonempty")
    return {"format": "dafjev.benchmark-reporter-source/1", "files": files,
            "scope": "complete SDK Python source inventory for this offline reduction"}


def _check_reporter_source(expected: dict[str, Any], package_root: Path) -> None:
    if _reporter_source(package_root) != expected:
        raise ValueError("reporter source changed during reduction")


def _reporter_environment() -> dict[str, Any]:
    """Static reducer runtime metadata, distinct from inference environment."""
    packages: dict[str, str | None] = {}
    for name in ("httpx", "PyYAML", "scikit-learn", "numpy", "psutil"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": platform.python_version(), "dependencies": packages}


def _positive(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _execution_selection(config: dict[str, Any], repetitions: int) -> dict[str, Any]:
    """Freeze a pass selector; study bindings are evidence metadata, not authority.

    A split warm pass is coordinated externally: the caller must verify the
    retained primary manifest, journal/head, report, stable model/input/source
    identities and cumulative profile time before launching its fresh process.
    This selector never opens or grants approval from another run's artifacts.
    """
    value = config.get("execution_selection", {"phase": "all"})
    if not isinstance(value, dict) or set(value) - {"phase", "repeat", "study_id", "pass_id", "prior_quality"}:
        raise ValueError("execution_selection must be a frozen pass mapping")
    selection = dict(value)
    phase = selection.setdefault("phase", "all")
    if phase not in ("all", "quality", "warm_repeat", "graphical"):
        raise ValueError("execution_selection.phase must be all, quality, warm_repeat or graphical")
    if phase == "warm_repeat":
        repeat = _positive(selection.get("repeat"), "execution_selection.repeat")
        if repeat > repetitions:
            raise ValueError("execution_selection.repeat exceeds timing_repetitions")
    elif "repeat" in selection:
        raise ValueError("execution_selection.repeat applies only to warm_repeat")
    for key in ("study_id", "pass_id"):
        if key in selection and (not isinstance(selection[key], str) or not selection[key].strip()):
            raise ValueError(f"execution_selection.{key} must be a nonempty string")
    if "prior_quality" in selection and not isinstance(selection["prior_quality"], dict):
        raise ValueError("execution_selection.prior_quality must be retained evidence metadata")
    return selection


def _phase_key(cell: dict[str, Any]) -> tuple[int, int]:
    """Await each phase before admitting the following phase/round."""
    phase = cell["phase"]
    return (EXECUTION_PHASES.index(phase),
            cell["repeat"] if phase == "warm_repeat" else 0)


def _phase_boundary(through_phase: str | None) -> int:
    if through_phase is None:
        return len(EXECUTION_PHASES) - 1
    if not isinstance(through_phase, str) or through_phase not in EXECUTION_PHASES:
        raise ValueError("through_phase must be capability_probe, quality, warm_repeat or graphical")
    return EXECUTION_PHASES.index(through_phase)


def _liability(profile: dict[str, Any]) -> str | None:
    with localcontext(currency_context()):
        return _priced_liability(profile)


def _priced_liability(profile: dict[str, Any]) -> str | None:
    if not profile.get("hosted"):
        return "0"
    pricing = profile.get("pricing")
    if not isinstance(pricing, dict) or not pricing.get("source") or not pricing.get("snapshot_at"):
        return None
    # Non-token surcharges are ineligible unless an explicit upper bound exists.
    rates = pricing.get("rates", {})
    if any(usd(rates[key]) != 0 for key in set(rates) - {"prompt", "completion", "input_cache_read", "input_cache_write"}):
        return None
    if "prompt" not in rates or "completion" not in rates:
        return None
    nominal_input = max(usd(rates.get(k, "0")) for k in ("prompt", "input_cache_read", "input_cache_write"))
    nominal_output = usd(rates["completion"])
    options = profile.setdefault("options", {})
    provider = options.setdefault("provider", {})
    if not isinstance(provider, dict):
        return None
    ceilings = provider.setdefault("max_price", {"prompt": float(nominal_input * 1_000_000),
        "completion": float(nominal_output * 1_000_000), "request": 0, "image": 0})
    if not isinstance(ceilings, dict) or "prompt" not in ceilings or "completion" not in ceilings:
        return None
    ceilings.setdefault("request", 0)
    ceilings.setdefault("image", 0)
    if usd(ceilings.get("request", "0")) or usd(ceilings.get("image", "0")):
        return None
    provider.update({"allow_fallbacks": False, "require_parameters": True})
    # Bind liability to the actual sent price ceilings (USD per million tokens),
    # not catalog minimum prices. Cache premiums need a pinned billing contract.
    if any(usd(rates.get(key, "0")) > usd(rates["prompt"])
           for key in ("input_cache_read", "input_cache_write")):
        return None
    input_rate = usd(ceilings["prompt"]) / Decimal(1_000_000)
    output_rate = usd(ceilings["completion"]) / Decimal(1_000_000)
    if input_rate < nominal_input:
        return None  # ceiling insufficient for the frozen declared cache rates
    if profile.get("mode", "systemone") == "systemone":
        # A model context window is not an established bound on aggregate native
        # billing across state, questions and options. No such frozen contract
        # is currently supported; caller-declared numeric bounds cannot enable it.
        if input_rate or output_rate:
            return None
        return "0"  # every admitted tariff and surcharge ceiling is zero
    context = profile.get("context_length")
    if isinstance(context, bool) or not isinstance(context, int) or context < 1:
        return None
    # Chat input is bounded by its advertised context; completion by max_tokens.
    output_limit = profile.get("options", {}).get("max_tokens", 512)
    if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit < 1:
        return None
    return str(Decimal(context) * input_rate + Decimal(output_limit) * output_rate)


def _liability_reason(profile: dict[str, Any]) -> str:
    """Explain unavailable admission without treating catalog context as proof."""
    if profile.get("kind", "http") == "http" and profile.get("mode", "systemone") == "systemone":
        pricing = profile.get("pricing", {})
        rates = pricing.get("rates", {}) if isinstance(pricing, dict) else {}
        options = profile.get("options", {})
        provider = options.get("provider", {}) if isinstance(options, dict) else {}
        ceilings = provider.get("max_price", {}) if isinstance(provider, dict) else {}
        ceilings = ceilings if isinstance(ceilings, dict) else {}
        if any(usd(value) for value in [rates.get(key, "0") for key in
                ("prompt", "input_cache_read", "input_cache_write")] + [ceilings.get("prompt", "0")]):
            return "native_aggregate_billing_unverified"
        if usd(rates.get("completion", "0")) or usd(ceilings.get("completion", "0")):
            return "native_output_billing_unbounded"
    return "unbounded_or_unverified_pricing"


def _allocated_billing(total: str, question_ids: list[str]) -> dict[str, str]:
    """Conserve request billing in exact 1E-18 USD units.

    Questions follow their retained dataset order. Each receives the floor of
    the equal unit share; the first remainder questions receive one extra unit.
    These are declared allocations, while the original receipt/ledger remains
    the billing evidence for the request as a whole.
    """
    if not question_ids:
        raise ValueError("request billing requires at least one target")
    with localcontext(currency_context()):
        quantum = Decimal("1E-18")
        units = int(usd_total(total) / quantum)
        base, remainder = divmod(units, len(question_ids))
        return {key: str(Decimal(base + (index < remainder)) * quantum)
                for index, key in enumerate(question_ids)}


def _gate_identity(manifest: dict[str, Any], backend: str, index: int) -> str:
    profile = next(p for p in manifest["backends"] if p["id"] == backend)
    return content_hash({"dataset_id": manifest["datasets"][index].get("id"),
        "prepared_dataset_sha256": manifest["datasets"][index]["sha256"],
        "weak_profile": profile, "training_seed": manifest["seed"],
        "source_files": manifest["source"]["files"]})


def plan_run(config_path: Path, output_root: Path) -> RunStore:
    """Freeze configuration, dataset bytes, cohort and software without inference."""
    config_bytes = _input_bytes(config_path)
    config = strict_yaml_loads(config_bytes)
    if not isinstance(config, dict) or config.get("format") != FORMAT:
        raise ValueError(f"configuration must declare {FORMAT}")
    seed = config.get("seed", 20261007)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    limit = usd(config.get("budget_usd", "25"))
    if limit > 25:
        raise ValueError("this pilot's authorized maximum is USD 25")
    profiles = config.get("backends", [])
    catalog_path = config.get("backends_from_catalog")
    catalog_bytes = None
    if catalog_path:
        catalog_bytes = _input_bytes(config_path.parent / catalog_path)
        profiles = list(profiles) + _catalog_profiles(strict_json_loads(catalog_bytes))
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("explicit backend cohort is required")
    names = []
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("id"), str):
            raise ValueError("backend profile requires an id")
        names.append(profile["id"])
        allowed_datasets = profile.get("datasets")
        if allowed_datasets is not None and (not isinstance(allowed_datasets, list)
                or any(not isinstance(name, str) or not name for name in allowed_datasets)):
            raise ValueError("backend datasets allowlist must be a list of dataset names")
        if any(k in profile for k in ("api_key", "authorization", "headers")):
            raise ValueError("manifest must contain credential environment names, never values")
        if profile.get("kind", "http") == "http":
            validate_endpoint(profile["endpoint"], hosted=bool(profile.get("hosted")))
            profile.setdefault("capabilities", {})["authentication"] = "bearer" if profile.get("hosted") else "none"
        if profile.get("kind") == "cascade":
            evidence_bytes = _input_bytes(config_path.parent / profile["gate_file"])
            evidence = strict_json_loads(evidence_bytes)
            if evidence.get("format") != "dafjev.policy-gates/1" or not evidence.get("source_manifest_hash"):
                raise ValueError("cascade requires frozen validation gate evidence")
            profile["gate_evidence"] = evidence
            profile["gate_sha256"] = hashlib.sha256(evidence_bytes).hexdigest()
            profile["hosted"] = True
        profile["liability_usd"] = _liability(profile)
        if profile.get("hosted"):
            profile["admission_reason"] = _liability_reason(profile) if profile["liability_usd"] is None else None
    lookup = {p["id"]: p for p in profiles}
    for profile in profiles:
        if profile.get("kind") == "cascade":
            weak, strong = lookup.get(profile.get("weak")), lookup.get(profile.get("strong"))
            if not weak or not strong or weak.get("hosted") or not strong.get("hosted") or strong.get("kind", "http") != "http":
                raise ValueError("executed cascade requires declared local weak and hosted HTTP strong profiles")
    if len({p.get("weak") for p in profiles if p.get("kind") == "cascade"}) > 1:
        raise ValueError("executed cascades require one resident local weak profile per run")
    if len(set(names)) != len(names):
        raise ValueError("duplicate backend IDs")
    repetitions = _positive(config.get("timing_repetitions", 5), "timing_repetitions")
    selection = _execution_selection(config, repetitions)
    sampling = config.get("sampling", "pilot")
    if sampling not in ("pilot", "all"):
        raise ValueError("sampling must be pilot or all")
    timing_samples = _positive(config.get("timing_samples", 100), "timing_samples")
    concurrency = _positive(config.get("hosted_concurrency", 4), "hosted_concurrency")
    capability_probes = config.get("capability_probes", True)
    if not isinstance(capability_probes, bool):
        raise ValueError("capability_probes must be a boolean")
    timeout = float(config.get("timeout_s", 60))
    profile_limit = float(config.get("local_time_limit_s", 7200))
    if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(profile_limit) or profile_limit <= 0:
        raise ValueError("timeouts must be finite and positive")
    datasets: list[dict[str, Any]] = []
    inputs = []
    cells = []
    selected_cohorts = []
    dataset_ids: set[str] = set()
    for index, item in enumerate(config.get("datasets", [])):
        source = config_path.parent / item["path"]
        raw = _input_bytes(source)
        dataset = prepared_dataset_from_dict(strict_json_loads(raw))
        selected = list(dataset.examples) if sampling == "all" else list(pilot_samples(dataset, seed=seed).examples)
        selected = [e for e in selected if e.split in ("validation", "test")]
        if not selected:
            raise ValueError("dataset has no validation/test evaluation samples")
        identifier = item.get("id", dataset.manifest.name)
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("dataset id must be a nonempty string")
        if identifier in dataset_ids:
            raise ValueError("duplicate dataset IDs; same-family datasets require explicit distinct ids")
        dataset_ids.add(identifier)
        datasets.append({"id": identifier, "file": f"inputs/dataset-{index}.json",
                         "sha256": hashlib.sha256(raw).hexdigest(), "manifest": dataset.manifest.to_dict()})
        inputs.append(raw)
        selected_cohorts.append(selected)
    timing_scope = config.get("timing_sampling_scope", "cohort")
    if timing_scope not in ("cohort", "per_dataset"):
        raise ValueError("timing_sampling_scope must be cohort or per_dataset")
    timing_enabled = selection["phase"] in ("all", "warm_repeat") or config.get("timing_sample_pack") is not None
    if timing_enabled:
        pack = timing_sample_pack(selected_cohorts, seed=seed, samples=timing_samples, scope=timing_scope)
    else:
        # A validation-only quality view has no test timing treatment. Preserve
        # an explicit empty binding rather than requiring held-out examples or
        # silently accepting a capped legacy timing cohort. Coordinated quality
        # passes can still bind the full shared pack explicitly above.
        empty_pack = {"format": "dafjev.benchmark-timing-sample/1", "timing_sampling_scope": timing_scope,
            "seed": seed, "requested_examples": 0, "selected_examples": 0,
            "selected_base_groups": 0, "sampling_unit": "none", "selection_labels_used": False,
            "selection_method": "disabled_for_quality_or_graphical_only",
            "excluded_quality_control_examples": 0, "examples": []}
        pack = {**empty_pack, "sha256": content_hash(empty_pack)}
    if config.get("timing_sample_pack") is not None and config["timing_sample_pack"] != pack:
        raise ValueError("frozen timing_sample_pack differs from deterministic selected input IDs")
    for index, selected in enumerate(selected_cohorts):
        probe_ids = {}
        if capability_probes:
            validation = sorted((e for e in selected if e.split == "validation"), key=lambda e: e.id)
            if not validation:
                raise ValueError("capability probes require a selected validation example")
            probe = validation[0]
            for profile in profiles:
                identity = [index, probe.id, profile["id"], "capability_probe"]
                probe_ids[profile["id"]] = content_hash(identity)
                cells.append({"id": content_hash(identity), "dataset": index, "example_id": probe.id,
                              "backend": profile["id"], "repeat": 0, "phase": "capability_probe"})
        timing_ids = {row["example_id"] for row in pack["examples"] if row["dataset"] == index}
        for example in selected:
            for profile in profiles:
                for repeat in range(1 + (repetitions if example.id in timing_ids else 0)):
                    if selection["phase"] != "all" and not (
                            (selection["phase"] == "quality" and repeat == 0)
                            or (selection["phase"] == "warm_repeat" and repeat == selection["repeat"])):
                        continue
                    identity = [index, example.id, profile["id"], repeat]
                    cells.append({"id": content_hash(identity), "dataset": index, "example_id": example.id,
                                  "backend": profile["id"], "repeat": repeat, "phase": "quality" if repeat == 0 else "warm_repeat",
                                  **({"capability_probe_id": probe_ids[profile["id"]]} if capability_probes else {})})
    if not datasets:
        raise ValueError("explicit prepared datasets are required")
    graphical = config.get("graphical_experiments", False)
    if graphical:
        selected_profiles = names if graphical is True else graphical
        if not isinstance(selected_profiles, list) or set(selected_profiles) - set(names):
            raise ValueError("graphical_experiments must name declared profiles")
        if selection["phase"] in ("all", "graphical"):
            first = prepared_dataset_from_dict(strict_json_loads(inputs[0])).examples[0]
            for name in selected_profiles:
                cells.append({"id": content_hash(["graphical", name, seed]), "dataset": 0,
                    "example_id": first.id, "backend": name, "repeat": 0, "phase": "graphical"})
    if not any(cell["phase"] != "capability_probe" for cell in cells):
        raise ValueError("execution_selection contains no evaluation cells")
    cells.sort(key=lambda cell: (_phase_key(cell), content_hash([seed, "execution_order", cell["id"]])))
    manifest = {"format": FORMAT, "created_at": utc_now(), "seed": seed, "budget_usd": str(limit),
        "source": source_identity(), "catalog": ({"sha256": hashlib.sha256(catalog_bytes).hexdigest(), "file": "inputs/catalog.json"} if catalog_bytes is not None else None), "datasets": datasets, "backends": profiles, "cells": cells,
        "protocol": {"timeout_s": timeout, "local_time_limit_s": profile_limit,
            "hosted_concurrency": concurrency, "local_concurrency": 1, "max_attempts": 2,
            "timing_samples": timing_samples, "timing_enabled": timing_enabled,
            "sampling": sampling, "timing_sampling_scope": timing_scope,
            "timing_sample_pack": pack, "timing_repetitions": repetitions, "percentile": "nearest_rank",
            "execution_selection": selection,
            "phase_order": "capability_probe, quality, warm_repeat by ascending repeat, graphical; local per-profile and hosted awaited barriers",
            "split_warm_prerequisite": "external coordinator verifies prior quality custody, stable model/input/source/sample identity and cumulative profile time; prior_quality metadata grants no permission",
            "bootstrap_samples": 2000, "test_labels_used_for_selection": False,
            "capability_probes": capability_probes,
            "capability_probe_scope": "one selected validation fixture; does not prove maximum boundary support",
            "graphical": {"enabled": bool(graphical), "reference_graph": reference_graph().to_json(),
                "cpt_chunk_size": 32, "exact_limit": 8, "edge_penalty": 1.0,
                "max_reveals": 3, "observation_costs": {"cloudy": 1.0, "rain": 1.0, "wet": 1.0},
                "model_reask": True}},
        "config_sha256": hashlib.sha256(config_bytes).hexdigest()}
    store = RunStore.create(output_root, manifest)
    (store.directory / "inputs").mkdir()
    if catalog_bytes is not None:
        with (store.directory / "inputs" / "catalog.json").open("xb") as handle:
            handle.write(catalog_bytes)
    for item, raw in zip(datasets, inputs, strict=True):
        with (store.directory / item["file"]).open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    sync_directory(store.directory / "inputs")
    sync_directory(store.directory)
    return store


def _datasets(store: RunStore) -> list[Any]:
    result = []
    inputs = store.directory / "inputs"
    catalog = store.manifest.get("catalog")
    if catalog:
        path = store.directory / catalog["file"]
        if path.parent != inputs:
            raise ValueError("catalog path escapes run inputs")
        if hashlib.sha256(_input_bytes(path)).hexdigest() != catalog["sha256"]:
            raise ValueError("catalog bytes changed")
    for item in store.manifest["datasets"]:
        path = store.directory / item["file"]
        if path.parent != inputs:
            raise ValueError("dataset path escapes run inputs")
        raw = _input_bytes(path)
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("dataset bytes changed")
        result.append(prepared_dataset_from_dict(strict_json_loads(raw)))
    return result


def _key(profile: dict[str, Any]) -> str | None:
    if not profile.get("hosted"):
        if profile.get("api_key_env"):
            raise ValueError("local benchmark servers must be keyless; provider credentials stay hosted")
        return None
    name = profile.get("api_key_env", "OPENROUTER_API_KEY" if profile.get("hosted") else "")
    if not isinstance(name, str):
        raise ValueError("api_key_env must be an environment-variable name")
    # Deliberately no implicit .env or cross-provider credential fallback.
    return os.environ.get(name) if name else None


def _budget_stop_outcome(store: RunStore, cell_id: str, error: BudgetStopped) -> tuple[str, str]:
    """Refused admission cannot erase an earlier admitted request's intent.

    An admission intent does not prove that transport reached the provider, but
    it prevents classifying the cell as demonstrably unattempted. Receipt and
    charge reconciliation remain unchanged; a cell start alone is not admission.
    """
    if any(event.get("event") == "attempt_started" and event.get("cell_id") == cell_id
           for event in store.events()):
        return "failed", "BudgetStopped"
    return "unattempted", str(error)


async def _execute(store: RunStore, *, through_phase: str | None = None) -> dict[str, Any]:
    boundary = _phase_boundary(through_phase)
    if store.manifest.get("format") != FORMAT:
        raise ValueError("unknown benchmark manifest")
    if source_identity() != store.manifest["source"]:
        raise ValueError("source bytes changed; plan a new run")
    datasets = _datasets(store)
    examples = [{e.id: e for e in dataset.examples} for dataset in datasets]
    ledger = SpendLedger(store, limit=store.manifest["budget_usd"])
    events = store.events()
    outcomes = {r["cell_id"]: r for r in events if r.get("event") == "cell_finished"}
    completed = {r["cell_id"] for r in events if r.get("event") == "cell_finished" and r.get("status") != "unattempted"}
    started = {r["cell_id"] for r in events if r.get("event") == "attempt_started" or (r.get("event") == "cell_started" and r["cell_id"] not in {e["cell_id"] for e in events if e.get("event") == "cell_finished"})}
    unknown = started - completed
    profiles = {p["id"]: p for p in store.manifest["backends"]}
    execution_liabilities = {name: profile.get("liability_usd") for name, profile in profiles.items()}
    admission_unavailable = {}
    for name, profile in profiles.items():
        if profile.get("hosted") and profile.get("kind", "http") == "http":
            # Preserve immutable old manifests. The pricing helper fills route
            # defaults, so evaluate an independent plain JSON working copy.
            current = strict_json_loads(canonical_json(profile))
            recomputed = _liability(current)
            if recomputed is None:
                execution_liabilities[name] = None
                admission_unavailable[name] = _liability_reason(current)
            elif canonical_json(current.get("options")) != canonical_json(profile.get("options")):
                # Defaults added only to a working copy do not constrain the
                # actual request sent with the immutable profile's settings.
                execution_liabilities[name] = None
                admission_unavailable[name] = "frozen_execution_settings_unbounded"
            elif profile.get("liability_usd") != recomputed:
                execution_liabilities[name] = None
                admission_unavailable[name] = "frozen_liability_mismatch"
    protocol = store.manifest["protocol"]
    backends: dict[tuple[str, int], Any] = {}
    failures: dict[tuple[str, int], str] = {}
    starts: dict[str, float] = {}
    consumed: dict[str, float] = defaultdict(float)
    finished_profiles = {event.get("profile_execution_id") for event in events
                         if event.get("event") == "resources_observed"}
    unknown_profile_wall = {event["backend"] for event in events
                           if event.get("event") == "local_profile_started"
                           and event["profile_execution_id"] not in finished_profiles}
    for event in events:
        if event.get("event") == "resources_observed":
            wall = event["resources"]["wall_s"]
            if isinstance(wall, bool) or not isinstance(wall, (int, float)) or not math.isfinite(wall) or wall < 0:
                raise ValueError("invalid retained profile wall time")
            consumed[event["backend"]] += wall
    windows: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    cascade_diagnostics: dict[str, str | None] = {}

    @asynccontextmanager
    async def local_window(profile_id: str, scope: str) -> AsyncIterator[str | None]:
        sampler, monitor, diagnostic = None, None, None
        try:
            sampler = ResourceSampler(profiles[profile_id].get("artifact", {}).get("process"))
            monitor = asyncio.create_task(sampler.monitor())
        except Exception as exc:
            diagnostic = type(exc).__name__
        began = time.perf_counter()
        starts[profile_id] = began - consumed[profile_id]
        execution_id = uuid.uuid4().hex
        store.append({"event": "local_profile_started", "backend": profile_id,
                      "profile_execution_id": execution_id, "consumed_wall_s": consumed[profile_id]})
        try:
            yield diagnostic
        finally:
            resource: dict[str, Any]
            try:
                resource = sampler.finish() if sampler is not None else {"wall_s": time.perf_counter() - began,
                    "observed_peak_rss_bytes": None, "unavailable_reason": diagnostic}
            except Exception as exc:
                resource = {"wall_s": time.perf_counter() - began, "observed_peak_rss_bytes": None,
                            "unavailable_reason": type(exc).__name__}
            if monitor is not None:
                try:
                    await monitor
                except Exception as exc:
                    resource["unavailable_reason"] = type(exc).__name__
            resource["execution_scope"] = scope
            store.append({"event": "resources_observed", "backend": profile_id,
                          "profile_execution_id": execution_id, "resources": resource})
            # Later cascades in this invocation must carry direct-local time,
            # just as a fresh executor carries prior journal windows.
            consumed[profile_id] += resource["wall_s"]

    def finish(event: dict[str, Any]) -> None:
        store.append(event)
        outcomes[event["cell_id"]] = event
        if event["status"] != "unattempted":
            completed.add(event["cell_id"])

    async def make_backend(profile: dict[str, Any], dataset_index: int) -> Any:
        key = (profile["id"], dataset_index)
        if key in backends:
            return backends[key]
        if key in failures:
            raise ValueError(failures[key])
        start = time.perf_counter()
        try:
            backend: Any
            kind = profile.get("kind", "http")
            if kind == "prior":
                backend = ThreadedAsyncBackend(fit_prior(datasets[dataset_index]))
            elif kind == "uniform":
                backend = ThreadedAsyncBackend(PriorBackend())
            elif kind == "rule":
                manifest = datasets[dataset_index].manifest
                if manifest.metadata.get("generator") not in {"dafjev.synthetic/1", "dafjev.synthetic/3", "dafjev.synthetic-matched-options/3"} or not manifest.name.startswith("synthetic-"):
                    raise ValueError("rule backend is restricted to declared synthetic datasets")
                backend = ThreadedAsyncBackend(RuleDecisionBackend(manifest.name.removeprefix("synthetic-").removesuffix("-matched-options-v3")))
            elif kind in ("sklearn_text", "sklearn_structured"):
                backend = ThreadedAsyncBackend(SklearnDecisionBackend(datasets[dataset_index], structured=kind == "sklearn_structured", seed=store.manifest["seed"]))
            elif kind == "http":
                backend = AsyncHTTPDecisionBackend(endpoint=profile["endpoint"], model=profile["model"],
                    api_key=_key(profile), hosted=bool(profile.get("hosted")), mode=profile.get("mode", "systemone"),
                    options=profile.get("options"), capabilities=BackendCapabilities(**profile.get("capabilities", {})))
            else:
                raise ValueError("unsupported backend kind")
            backends[key] = backend
            store.append({"event": "backend_ready", "backend": profile["id"], "dataset": dataset_index,
                "setup_elapsed_s": time.perf_counter() - start, "profile": profile.get("artifact", {}),
                "training": getattr(getattr(backend, "backend", backend), "training", None)})
            return backend
        except (ValueError, ImportError) as exc:
            failures[key] = str(exc)
            raise

    async def cell(cell: dict[str, Any]) -> None:
        identity = cell["id"]
        if identity in completed or identity in unknown:
            return
        profile = profiles[cell["backend"]]
        local_id = profile["weak"] if profile.get("kind") == "cascade" else (
            None if profile.get("hosted") else profile["id"])
        dataset_index = cell["dataset"]
        example = examples[dataset_index][cell["example_id"]]
        if profile.get("datasets") is not None and datasets[dataset_index].manifest.name not in profile["datasets"]:
            finish({"event": "cell_finished", "cell_id": identity, "status": "unsupported",
                    "reason": "dataset_outside_backend_allowlist"})
            return
        dependency = profile.get("strong") if profile.get("kind") == "cascade" else profile["id"]
        if (profile["id"] in admission_unavailable
                or admission_unavailable.get(dependency) in {"native_aggregate_billing_unverified",
                    "frozen_execution_settings_unbounded", "frozen_liability_mismatch"}):
            finish({"event": "cell_finished", "cell_id": identity, "status": "unattempted",
                    "reason": admission_unavailable[dependency], "admission_backend": dependency})
            return
        if local_id in unknown_profile_wall:
            finish({"event": "cell_finished", "cell_id": identity, "status": "unattempted",
                    "reason": "local_execution_time_unknown"})
            return
        if (local_id is not None and cascade_diagnostics.get(local_id)
                and profiles[local_id].get("artifact", {}).get("process")):
            return  # an explicitly bound serving process was not verified
        if local_id is not None and time.perf_counter() - starts[local_id] >= protocol["local_time_limit_s"]:
            finish({"event": "cell_finished", "cell_id": identity, "status": "unattempted",
                    "reason": "local_execution_deadline"})
            return
        probe_id = cell.get("capability_probe_id")
        if probe_id is not None:
            probe_status = outcomes.get(probe_id, {}).get("status")
            if probe_status in ("failed", "unsupported"):
                finish({"event": "cell_finished", "cell_id": identity, "status": "unsupported",
                        "reason": "capability_probe_" + probe_status, "capability_probe_id": probe_id})
                return
            if probe_status != "completed":
                return  # missing credentials/budget or unresolved probe remains unattempted
        if cell["phase"] == "warm_repeat" and protocol.get("execution_selection", {}).get("phase", "all") == "all":
            primary_id = content_hash([dataset_index, example.id, profile["id"], 0])
            primary_status = outcomes.get(primary_id, {}).get("status")
            if primary_status == "unsupported":
                finish({"event": "cell_finished", "cell_id": identity, "status": "unsupported",
                        "reason": "primary_quality_unsupported", "primary_cell_id": primary_id})
                return
            if primary_status not in ("completed", "failed"):
                finish({"event": "cell_finished", "cell_id": identity, "status": "unattempted",
                        "reason": "primary_quality_unresolved" if primary_id in unknown else "primary_quality_unattempted",
                        "primary_cell_id": primary_id})
                return
        try:
            if profile.get("kind") == "cascade":
                weak_profile, strong_profile = profiles[profile["weak"]], profiles[profile["strong"]]
                binding = _gate_identity(store.manifest, profile["weak"], dataset_index)
                gates = [g for g in profile["gate_evidence"]["gates"] if g["backend"] == profile["weak"]
                         and g["dataset_sha256"] == datasets[dataset_index].manifest.sha256
                         and g.get("validation_identity") == binding]
                if len(gates) != 1:
                    raise ValueError("missing unique validation gate for this dataset")
                weak, strong = await make_backend(weak_profile, dataset_index), await make_backend(strong_profile, dataset_index)
                def child_observer(child: str) -> Any:
                    arm = weak_profile if child == "weak" else strong_profile
                    return ledger.observer(cell_id=identity, hosted=bool(arm.get("hosted")), liability_usd=execution_liabilities[arm["id"]])
                backend = CascadeDecisionBackend(weak, strong, gate=gate_from_dict(gates[0]["calibration"]), observers=child_observer)
            else:
                backend = await make_backend(profile, dataset_index)
        except ValueError as exc:
            if profile.get("kind") in ("sklearn_text", "sklearn_structured", "prior", "rule"):
                finish({"event": "cell_finished", "cell_id": identity, "status": "unsupported",
                        "reason": "unsupported_backend_input:" + type(exc).__name__})
            return
        except ImportError:
            return  # demonstrably unattempted, resumable after external setup
        def remaining() -> float | None:
            return (protocol["local_time_limit_s"] - (time.perf_counter() - starts[local_id])
                    if local_id is not None else None)
        left = remaining()
        if left is not None and left <= 0:
            finish({"event": "cell_finished", "cell_id": identity, "status": "unattempted",
                    "reason": "local_execution_deadline"})
            return
        observer = ledger.observer(cell_id=identity, hosted=bool(profile.get("hosted")), liability_usd=execution_liabilities[profile["id"]])
        request = DecisionRequest(example.state, example.questions, timeout=protocol["timeout_s"], observer=observer)
        if cell["phase"] == "graphical" and backend.capabilities.probability_source is None:
            finish({"event": "cell_finished", "cell_id": identity, "status": "unsupported", "reason": "graphical_requires_genuine_beliefs"})
            return
        if cell["phase"] == "graphical" and "choice" not in backend.capabilities.primitives:
            finish({"event": "cell_finished", "cell_id": identity, "status": "unsupported", "reason": "graphical_requires_choice_primitive"})
            return
        if isinstance(backend, AsyncHTTPDecisionBackend) and cell["phase"] != "graphical":
            try:
                backend._body(request)  # capability validation before durable attempt intent
            except ValueError as exc:
                finish({"event": "cell_finished", "cell_id": identity, "status": "unsupported", "reason": str(exc)})
                return
        store.append({"event": "cell_started", "cell_id": identity})
        began = time.perf_counter()
        status, error, result = "failed", None, None
        async def predict() -> DecisionResult:
            if cell["phase"] == "graphical":
                settings = protocol["graphical"]
                record = await run_graphical_experiment(backend, seed=store.manifest["seed"],
                    max_reveals=settings["max_reveals"], observation_costs=settings["observation_costs"],
                    model_reask=settings["model_reask"], observer=observer, timeout=protocol["timeout_s"])
                return DecisionResult({}, workflow=record)
            return await backend.predict(request)
        try:
            for attempt in range(protocol["max_attempts"]):
                try:
                    left = remaining()
                    if left is not None and left <= 0:
                        status, error = (("failed", "TimeoutError") if attempt else
                                         ("unattempted", "local_execution_deadline"))
                        break
                    if left is not None:
                        result = await asyncio.wait_for(predict(), timeout=left)
                    else:
                        result = await predict()
                    status = "completed"
                    break
                except BackendHTTPError as exc:
                    error = type(exc).__name__ + ":" + str(exc.status_code)
                    if exc.status_code not in (429, 529, 502, 503, 504) or attempt + 1 == protocol["max_attempts"]:
                        break
                    delay = .1 * (2 ** attempt)
                    left = remaining()
                    await asyncio.sleep(min(delay, max(0, left)) if left is not None else delay)
            error = None if result is not None else error
        except asyncio.TimeoutError as exc:
            error = "TimeoutError"
            partial = getattr(exc.__cause__, "dafjev_workflow", None)
            if partial is not None:
                result = DecisionResult({}, workflow=partial)
        except GraphicalExperimentError as exc:
            error = type(exc).__name__
            result = DecisionResult({}, workflow=exc.record)
        except BudgetStopped as exc:
            partial = getattr(exc, "dafjev_workflow", None)
            if partial is None:
                status, error = _budget_stop_outcome(store, identity, exc)
            else:
                status, error = "failed", "BudgetStopped"
                result = DecisionResult({}, workflow=partial)
        except asyncio.CancelledError as exc:
            store.append({"event": "cell_cancelled", "cell_id": identity,
                          "workflow": getattr(exc, "dafjev_workflow", None)})
            raise
        except Exception as exc:
            error = type(exc).__name__  # raw exceptions may contain private inputs/URLs
        elapsed = time.perf_counter() - began
        predictions = {k: asdict(v) for k,v in result.predictions.items()} if result else {}
        evidence = None
        if cell["phase"] == "capability_probe":
            wires = {key: question.to_wire() for key, question in example.questions.items()}
            evidence = {"scope": "selected_validation_fixture", "maximum_boundaries_verified": False,
                        "question_count": len(wires), "primitives": sorted({wire["type"] for wire in wires.values()}),
                        "options_per_question": {key: len(wire["criteria"]) for key, wire in wires.items() if "criteria" in wire},
                        "state_sha256": content_hash(example.state), "empirical_success": status == "completed"}
        elif status in ("completed", "failed"):
            key = (cell["backend"], dataset_index, example.split, cell["phase"])
            window = windows.setdefault(key, {"start": began, "finish": began, "cell_ids": []})
            window["finish"] = time.perf_counter()
            window["cell_ids"].append(identity)
        finish({"event": "cell_finished", "cell_id": identity, "status": status,
            "error": error, "elapsed_s": elapsed, "predictions": predictions,
            "workflow": result.workflow if result else None, "capability_evidence": evidence})

    pending = [c for c in store.manifest["cells"] if c["id"] not in completed and c["id"] not in unknown
               and _phase_key(c)[0] <= boundary]
    for name, reason in admission_unavailable.items():
        store.append({"event": "hosted_admission_unavailable", "backend": name, "reason": reason,
                      "scope": "current execution policy; frozen manifest retained unchanged"})
    store.append({"event": "execution_started", "unresolved_cells": sorted(unknown),
                  "through_phase": through_phase})
    try:
        # Separate resident local profiles; hosted arms interleave with bounded workers.
        local_ids = sorted({c["backend"] for c in pending if not profiles[c["backend"]].get("hosted")})
        random.Random(store.manifest["seed"]).shuffle(local_ids)
        for profile_id in local_ids:
            if profile_id in unknown_profile_wall:
                for item in pending:
                    if item["backend"] == profile_id:
                        finish({"event": "cell_finished", "cell_id": item["id"], "status": "unattempted",
                                "reason": "local_execution_time_unknown"})
                continue
            try:
                async with local_window(profile_id, "direct local profile execution") as diagnostic:
                    ordered = sorted((item for item in pending if item["backend"] == profile_id),
                                     key=_phase_key)
                    for item in ordered:
                        if diagnostic and profiles[profile_id].get("artifact", {}).get("process"):
                            continue  # an explicitly bound serving PID must be verified
                        await cell(item)
            finally:
                for key, backend in list(backends.items()):
                    if key[0] == profile_id:
                        await backend.close()
                        del backends[key]
        async def hosted_batch(items: list[dict[str, Any]]) -> None:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            for item in items:
                queue.put_nowait(item)
            async def worker() -> None:
                while not queue.empty():
                    item = queue.get_nowait()
                    try:
                        await cell(item)
                    finally:
                        queue.task_done()
            count = 1 if any(p.get("kind") == "cascade" for p in profiles.values()) else protocol["hosted_concurrency"]
            await asyncio.gather(*(worker() for _ in range(count)))
        hosted = [item for item in pending if profiles[item["backend"]].get("hosted")]
        async with AsyncExitStack() as stack:
            weak_ids = sorted({profiles[item["backend"]]["weak"] for item in hosted
                               if profiles[item["backend"]].get("kind") == "cascade"})
            for weak_id in weak_ids:
                if weak_id not in unknown_profile_wall:
                    cascade_diagnostics[weak_id] = await stack.enter_async_context(local_window(
                        weak_id, "cascade weak residence; conservatively includes hosted interleaving"))
            for hosted_phase in sorted({_phase_key(item) for item in hosted}):
                await hosted_batch([item for item in hosted if _phase_key(item) == hosted_phase])
    finally:
        for backend in backends.values():
            await backend.close()
        store.append({"event": "execution_finished", "accounting": ledger.snapshot(), "unavailable_backends": [
            {"backend": k[0], "dataset": k[1], "reason": v} for k,v in failures.items()]})
        for (backend_id, dataset_index, split, phase), window in windows.items():
            store.append({"event": "cohort_observed", "backend": backend_id, "dataset": dataset_index,
                          "split": split, "phase": phase, "wall_s": window["finish"] - window["start"],
                          "cell_ids": window["cell_ids"], "timing_scope": "observed execution window including interleaving"})
    _datasets(store)  # independently rehash over the complete consumption interval
    if source_identity() != store.manifest["source"]:
        raise ValueError("source mutated during execution")
    return report_run(store)


def execute_run(directory: Path, *, through_phase: str | None = None) -> dict[str, Any]:
    """Resume the same manifest and ledger, optionally stopping after a phase.

    Later cells retain their planned identities and remain unattempted. A later
    invocation can continue them; completed or unresolved work is never replayed.
    """
    _phase_boundary(through_phase)  # reject invalid boundaries before opening the run
    store = RunStore(directory)
    with store.lease():
        return asyncio.run(_execute(store, through_phase=through_phase))


def report_run(store_or_path: RunStore | Path) -> dict[str, Any]:
    """Offline reduction bound to frozen inference and current reducer source.

    Reporter source is checked before and after reduction; it does not change
    the source identity of any retained inference attempt. No model/network calls.
    """
    package_root = Path(__file__).absolute().parent
    reporter_source = _reporter_source(package_root)
    reporter_environment = _reporter_environment()
    store = store_or_path if isinstance(store_or_path, RunStore) else RunStore(store_or_path, read_only=True)
    datasets = _datasets(store)
    example_maps = [{e.id: e for e in d.examples} for d in datasets]

    def dataset_identity(index: int) -> dict[str, Any]:
        frozen = store.manifest["datasets"][index]
        return {"dataset": datasets[index].manifest.name, "dataset_id": frozen.get("id", datasets[index].manifest.name),
                "dataset_index": index, "prepared_dataset_sha256": frozen["sha256"]}

    def reduce_rows(rows: list[dict[str, Any]], planned: list[dict[str, Any]], index: int,
                    wall_s: float | None = None) -> dict[str, Any]:
        dataset = datasets[index]
        metrics = score_predictions(rows, labels=dataset.manifest.labels, label_kind=dataset.manifest.label_kind,
            bootstrap_samples=store.manifest["protocol"]["bootstrap_samples"], seed=store.manifest["seed"],
            wall_s=wall_s, planned_rows=planned)
        planned_cells = {row["cell_id"]: row["status"] for row in planned}
        return {**metrics, "planned_decisions": len(planned), "planned_cells": len(planned_cells),
            "planned_status_counts": dict(Counter(row["status"] for row in planned)),
            "planned_cell_status_counts": dict(Counter(planned_cells.values())),
            "planned_coverage": metrics["n_success"] / len(planned) if planned else None,
            "coverage_scope": "coverage uses attempted outcomes; planned_coverage uses all frozen decisions"}

    events = store.events()
    outcomes = {e["cell_id"]: e for e in events if e.get("event") == "cell_finished"}
    attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("event") == "attempt_finished":
            attempts[event["cell_id"]].append(event["receipt"])
    started = {e["cell_id"] for e in events if e.get("event") in ("cell_started", "attempt_started")}
    statuses: Counter[str] = Counter()
    groups: dict[tuple[str, int, str, str], list[dict[str, Any]]] = defaultdict(list)
    repeated_rows: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    cells = []
    profiles = {p["id"]: p for p in store.manifest["backends"]}
    probes = []
    unavailable = {(item["backend"], item["dataset"]) for event in events if event.get("event") == "execution_finished"
                   for item in event.get("unavailable_backends", [])}
    executions = [event for event in events if event.get("event") == "execution_started"]
    through_phase = executions[-1].get("through_phase") if executions else None
    boundary = _phase_boundary(through_phase)
    for cell in store.manifest["cells"]:
        outcome = outcomes.get(cell["id"], {})
        status = outcome.get("status", "unresolved" if cell["id"] in started else "unattempted")
        statuses[status] += 1
        reason = outcome.get("reason", outcome.get("error"))
        if status == "unattempted" and reason is None and _phase_key(cell)[0] > boundary:
            reason = "execution_phase_boundary"
        if status == "unattempted" and reason is None and cell.get("capability_probe_id"):
            probe_id = cell["capability_probe_id"]
            probe_status = outcomes.get(probe_id, {}).get("status", "unresolved" if probe_id in started else "unattempted")
            if probe_status != "completed":
                reason = "capability_probe_" + probe_status
        if status == "unattempted" and reason is None and (cell["backend"], cell["dataset"]) in unavailable:
            reason = "backend_unavailable"
        cells.append({**cell, "status": status, "reason": reason})
        if cell["phase"] == "capability_probe":
            probes.append({"backend": cell["backend"], **dataset_identity(cell["dataset"]),
                           "cell_id": cell["id"], "example_id": cell["example_id"], "status": status, "reason": reason,
                           "evidence": outcome.get("capability_evidence"), "attempts": len(attempts[cell["id"]])})
            continue
        if cell["phase"] in ("quality", "warm_repeat"):
            example = example_maps[cell["dataset"]][cell["example_id"]]
            groups[(cell["backend"], cell["dataset"], example.split, cell["phase"])]
            for qid, target in example.to_dict()["targets"].items():
                prediction = outcome.get("predictions", {}).get(qid, {})
                repeated_rows[(cell["backend"], cell["dataset"])].append({
                    "cell_id": cell["id"], "example_id": example.id, "question_id": qid, "phase": cell["phase"], "repeat": cell["repeat"],
                    "split": example.split, "target": target,
                    "leakage_filtered": example.metadata.get("duplicate_sensitivity_cohort", True),
                    "status": status, "error": outcome.get("error"), "prediction": prediction.get("value"),
                    "probabilities": prediction.get("probabilities"), "probability_source": prediction.get("probability_source"),
                    "probability_semantics": prediction.get("probability_semantics"),
                    "probability_rounding_digits": prediction.get("probability_rounding_digits")})
        if status not in ("completed", "failed") or cell["phase"] == "graphical":
            continue
        example = example_maps[cell["dataset"]][cell["example_id"]]
        receipts = attempts[cell["id"]]
        hosted_receipts = [r for r in receipts if r["cost_status"] != "local"]
        with localcontext(currency_context()):
            cost = None if any(r["cost_status"] != "reported" for r in hosted_receipts) else str(sum((usd(r["cost_usd"]) for r in hosted_receipts), Decimal(0)))
        allocated = _allocated_billing(cost, list(example.targets)) if cost is not None else {}
        for qid, target in example.to_dict()["targets"].items():
            prediction = outcome.get("predictions", {}).get(qid, {})
            groups[(cell["backend"], cell["dataset"], example.split, cell["phase"])].append({
                "backend_id": cell["backend"], "cell_id": cell["id"], "billing_group_id": cell["id"],
                "leakage_filtered": example.metadata.get("duplicate_sensitivity_cohort", True),
                "example_id": example.id, "group_id": example.group_id, "question_id": qid, "split": example.split,
                "target": target, "prediction": prediction.get("value"), "probabilities": prediction.get("probabilities"),
                "confidence": prediction.get("confidence"), "probability_source": prediction.get("probability_source"),
                    "probability_semantics": prediction.get("probability_semantics"),
                "confidence_semantics": prediction.get("confidence_semantics"),
                "probability_rounding_digits": prediction.get("probability_rounding_digits"),
                "latency_s": outcome.get("elapsed_s"), "error": outcome.get("error"), "cost_usd": allocated.get(qid),
                "cost_scope": "allocated request billing; local compute expense is separate",
                "cost_allocation": "floor equal share in 1E-18 USD units; first remainder targets receive one extra unit; retained dataset target order",
            })
    cohorts = []
    for (backend, dataset_index, split, phase), rows in groups.items():
        dataset = datasets[dataset_index]
        observations = [e for e in events if e.get("event") == "cohort_observed" and
                        (e["backend"], e["dataset"], e["split"], e["phase"]) == (backend, dataset_index, split, phase)]
        observed_cells = {cell_id for event in observations for cell_id in event["cell_ids"]}
        wall_s = sum(event["wall_s"] for event in observations) if observations and observed_cells == {row["cell_id"] for row in rows} else None
        planned_rows = [row for row in repeated_rows[(backend, dataset_index)] if row["phase"] == phase and row["split"] == split]
        cohorts.append({"backend": backend, **dataset_identity(dataset_index), "split": split, "phase": phase,
            "metrics": reduce_rows(rows, planned_rows, dataset_index, wall_s),
            "throughput_scope": "observed execution windows including interleaving" if wall_s is not None else "unavailable",
            "rows": rows})
    for cohort in list(cohorts):
        filtered = [row for row in cohort["rows"] if row["leakage_filtered"]]
        index = cohort["dataset_index"]
        planned = [row for row in repeated_rows[(cohort["backend"], index)]
                   if row["phase"] == cohort["phase"] and row["split"] == cohort["split"]]
        planned_rows = [row for row in planned if row["leakage_filtered"]]
        if len(planned_rows) != len(planned):
            cohorts.append({**cohort, "phase": cohort["phase"] + "_leakage_filtered", "rows": filtered,
                "throughput_scope": "unavailable; post-hoc cohort filtering",
                "metrics": reduce_rows(filtered, planned_rows, index)})
    policies = []
    gates = []
    quality = {(c["backend"], c["dataset_index"], c["split"]): c for c in cohorts if c["phase"] == "quality"}
    for (backend, dataset_index, split), cohort in quality.items():
        if split != "test":
            continue
        validation = quality.get((backend, dataset_index, "validation"))
        if (validation is None or datasets[dataset_index].manifest.label_kind == "soft"
                or any(isinstance(row["target"], dict) for row in repeated_rows[(backend, dataset_index)]
                       if row["phase"] == "quality" and row["split"] == "validation")):
            continue
        gate = calibrate_gate(validation["rows"])
        dataset = datasets[dataset_index]
        gates.append({"backend": backend, **dataset_identity(dataset_index), "dataset_sha256": dataset.manifest.sha256,
            "validation_identity": _gate_identity(store.manifest, backend, dataset_index), "calibration": gate.to_dict()})
        for policy, strong_id, strong_rows in [("gate", None, None), *[("cascade", other, candidate["rows"]) for (other, index, other_split), candidate in quality.items() if index == dataset_index and other_split == "test" and not profiles[backend].get("hosted") and profiles[other].get("hosted")]]:
            rows = replay_policy(cohort["rows"], policy=policy, gate=gate, strong_rows=strong_rows)
            for row in rows:
                row["latency_s"] = None  # replay does not establish end-to-end or model-switch timing
            policies.append({"policy": policy, "weak": backend, "strong": strong_id, **dataset_identity(dataset_index),
                "evidence": "offline_replay", "replay_input_scope": "attempted outcomes only; frozen planned denominators retained",
                "gate": gate.to_dict(), "metrics": reduce_rows(rows, [row for row in repeated_rows[(backend, dataset_index)]
                    if row["phase"] == "quality" and row["split"] == "test"], dataset_index)})
    ledger = SpendLedger(store, limit=store.manifest["budget_usd"])
    cell_statuses = {cell["id"]: cell["status"] for cell in cells}
    inference_source = store.manifest.get("source")
    inference_files = inference_source.get("files") if isinstance(inference_source, dict) else None
    report = {"format": "dafjev.benchmark-report/1", "manifest_hash": store.manifest_hash,
        "journal_hash": events[-1]["hash"] if events else store.manifest_hash,
        "inference_source": inference_source,
        "inference_source_hash": content_hash(inference_files) if isinstance(inference_files, dict) and inference_files else None,
        "reporter_source": reporter_source, "reporter_source_hash": content_hash(reporter_source["files"]),
        "reporter_environment": reporter_environment,
        "source_hash_scheme": "SHA-256 of canonical JSON mapping SDK source paths to their SHA-256 hashes",
        "status": "complete" if not any(statuses[k] for k in ("failed", "unattempted", "unresolved")) else "partial",
        "denominators": dict(statuses), "planned_cells": len(cells), "cells": cells,
        "accounting": ledger.snapshot(), "cohorts": cohorts, "policies": policies,
        "execution_selection": store.manifest["protocol"].get("execution_selection", {"phase": "all"}),
        "execution_phase_boundary": through_phase,
        "timing_sampling_scope": store.manifest["protocol"].get("timing_sampling_scope", "per_dataset"),
        "timing_sample_pack": store.manifest["protocol"].get("timing_sample_pack"),
        "repeatability_scope": ("cross-pass reduction requires retained primary and warm observations"
            if store.manifest["protocol"].get("execution_selection", {}).get("phase") == "warm_repeat"
            else "this manifest's planned primary and warm observations"),
        "repeatability": [] if store.manifest["protocol"].get("execution_selection", {}).get("phase") == "warm_repeat" else [{"backend": backend, **dataset_identity(index),
            **repeatability(rows, labels=datasets[index].manifest.labels, label_kind=datasets[index].manifest.label_kind)}
            for (backend, index), rows in repeated_rows.items()],
        "dataset_audits": [{**audit_dataset(dataset, selected_example_ids=sorted({cell["example_id"] for cell in store.manifest["cells"]
            if cell["dataset"] == index and cell["phase"] in ("quality", "warm_repeat")})), **dataset_identity(index)}
            for index, dataset in enumerate(datasets)],
        "graphical_experiments": [{"cell_id": cell["id"], "backend": cell["backend"],
            "status": cell_statuses[cell["id"]], "record": outcomes.get(cell["id"], {}).get("workflow")}
            for cell in store.manifest["cells"] if cell["phase"] == "graphical"], "capability_probes": probes,
        "resources": [{"backend": e["backend"], **e["resources"]} for e in events if e.get("event") == "resources_observed"],
        "gate_evidence": {"format": "dafjev.policy-gates/1", "source_manifest_hash": store.manifest_hash, "gates": gates},
        "limits": ["Local monetary expense is unknown without supplied rates.",
                   "Synchronous baseline fitting is not preemptible by the asynchronous prediction deadline.",
                   "Replay is distinct from executed end-to-end latency.",
                   "Catalog metadata does not prove inference capability."]}
    _check_reporter_source(reporter_source, package_root)
    if _reporter_environment() != reporter_environment:
        raise ValueError("reporter environment changed during reduction")
    return report


def save_report(report: dict[str, Any], path: Path) -> None:
    with path.open("x") as handle:
        handle.write(canonical_json(report) + "\n")


def catalog_profiles(path: Path) -> list[dict[str, Any]]:
    """Discover candidate profiles. Capabilities stay unverified until probing."""
    return _catalog_profiles(strict_json_loads(_input_bytes(path)))


def _catalog_profiles(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    models = catalog["payload"]["data"]
    by_id = {model["id"]: model for model in models}

    def alias_slug(model: dict[str, Any]) -> str | None:
        alias = model.get("alias_target")
        value = alias.get("slug") if isinstance(alias, dict) else alias
        return value if isinstance(value, str) else None

    def executable_metadata(model: dict[str, Any]) -> dict[str, Any]:
        architecture = model.get("architecture", {})
        return {**{key: model.get(key) for key in ("pricing", "context_length", "top_provider",
            "per_request_limits", "supported_parameters", "default_parameters")},
            "input_modalities": architecture.get("input_modalities"),
            "output_modalities": architecture.get("output_modalities")}

    def complete_contract(model: dict[str, Any]) -> bool:
        pricing, context, architecture = (model.get(key) for key in ("pricing", "context_length", "architecture"))
        if (not isinstance(pricing, dict) or not {"prompt", "completion"} <= set(pricing)
                or isinstance(context, bool) or not isinstance(context, int) or context < 1
                or not isinstance(architecture, dict)):
            return False
        for field in ("input_modalities", "output_modalities"):
            values = architecture.get(field)
            if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
                return False
        try:
            for rate in pricing.values():
                usd(rate)
        except ValueError:
            return False
        return True

    for model in models:
        target = by_id.get(alias_slug(model))
        if (target is not None and target is not model and not target.get("alias_target")
                and complete_contract(model) and complete_contract(target)
                and executable_metadata(model) == executable_metadata(target)):
            continue
        key = model["id"]
        dispatch_id = target["id"] if target is not None else key
        # Tev is served by a chat contract despite its decision modality.
        mode = "letter" if dispatch_id.startswith("togethercomputer/tev1") else "systemone"
        primitives = ["noul"] if dispatch_id.startswith("respan/") else (["choice"] if mode == "letter" else ["noul", "choice", "score"])
        result.append({"id": key, "kind": "http", "model": key, "hosted": True, "mode": mode,
            "endpoint": "https://openrouter.ai/api/v1/chat/completions" if mode == "letter" else "https://openrouter.ai/api/alpha/decisions",
            "api_key_env": "OPENROUTER_API_KEY", "context_length": model.get("context_length"),
            "artifact": {"canonical_slug": model.get("canonical_slug"), "declared_alias_target": alias_slug(model),
                "license": "consult_model_card", "model_training_overlap": "unknown"},
            "capabilities": {"primitives": primitives, "max_options": 24 if mode == "letter" else None,
                "probability_source": None if mode == "letter" else "native", "evidence": "catalog_only"},
            "pricing": {"source": catalog["source"], "snapshot_at": catalog["fetched_at"], "rates": model.get("pricing", {})},
            "options": {"provider": {"allow_fallbacks": False}} if mode == "systemone" else {"max_tokens": 8}})
    return result
