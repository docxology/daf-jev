#!/usr/bin/env python3
"""Freeze an offline hosted obligation projection; never send an API request.

Inputs are exact-bound public catalog metadata, a prepared dataset fragment and
the previously selected hosted summary. The output contains hashes, IDs, counts
and routing settings, never states, targets, credentials or absolute paths.
This projection is intentionally not an executable RunStore or a new budget.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from daf_jev._json import strict_json_loads  # noqa: E402
from daf_jev.benchmark_datasets import prepared_dataset_from_dict  # noqa: E402
from daf_jev.benchmark_runner import (  # noqa: E402
    _catalog_profiles,
    _liability,
    _liability_reason,
)
from daf_jev.benchmark_sampling import timing_sample_pack  # noqa: E402
from daf_jev.benchmark_store import currency_context, usd  # noqa: E402
from daf_jev.decision_backends import canonical_json, content_hash  # noqa: E402

ALLOCATION = "first-authorized-hosted-usd25"


def read_bound(path: Path, expected: str | None = None) -> tuple[bytes, str]:
    path = path.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink input is unsupported")
    before = path.stat()
    if not path.is_file():
        raise ValueError("input must be a regular file")
    raw = path.read_bytes()
    after = path.stat()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("input symlink lineage changed while consumed")
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise ValueError("input changed while consumed")
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError("input SHA-256 mismatch")
    return raw, digest


def checked_output_path(path: Path) -> Path:
    """Reject an existing or symlinked destination before creating artifacts."""
    path = path.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink output lineage is unsupported")
    if path.exists():
        raise FileExistsError("output directory already exists")
    return path


def source() -> dict[str, Any]:
    files = {str(p.relative_to(ROOT)): read_bound(p)[1]
             for p in sorted((ROOT / "src" / "daf_jev").glob("*.py"))}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          check=True, capture_output=True, text=True).stdout.strip()
    changed = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--",
                              "src/daf_jev", "scripts/prepare_hosted_expansion.py"], cwd=ROOT,
                             check=True, capture_output=True, text=True).stdout.splitlines()
    return {"git_head": head, "sdk_files": files,
            "sdk_file_map_sha256": content_hash(files),
            "generator_sha256": read_bound(Path(__file__))[1],
            "committed_source": not changed,
            "source_worktree_changes": changed}


def safe_identity(value: Any, *, name: str) -> str:
    """Keep arbitrary input strings out of public identity fields."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/+-]{1,160}", value):
        raise ValueError(f"{name} must be a bounded portable identity")
    return value


def ids_digest(ids: list[str]) -> str:
    """SHA-256 of the canonical JSON array of sorted cell IDs, without copies."""
    digest = hashlib.sha256(b"[")
    for index, identity in enumerate(sorted(ids)):
        if index:
            digest.update(b",")
        digest.update(json.dumps(identity).encode())
    digest.update(b"]")
    return digest.hexdigest()


def supports(example: Any, caps: dict[str, Any]) -> bool:
    for question in example.questions.values():
        wire = question.to_wire()
        if wire["type"] not in caps["primitives"]:
            return False
        if caps.get("max_options") and len(wire.get("criteria", {})) > caps["max_options"]:
            return False
    return True


def build(catalog: dict[str, Any], endpoints: dict[str, Any], fragment: dict[str, Any],
          prior: dict[str, Any], *, fragment_parent: Path) -> dict[str, Any]:
    """Produce an exact fixed obligation; admission metadata grants no authority."""
    if (catalog.get("format") != "dafjev.model-catalog/1"
            or catalog.get("source") != "https://openrouter.ai/api/v1/models?output_modalities=decisions"):
        raise ValueError("a frozen official decisions catalog is required")
    models = catalog["payload"]["data"]
    model_ids = [safe_identity(model["id"], name="catalog model ID") for model in models]
    if not model_ids or len(set(model_ids)) != len(model_ids):
        raise ValueError("catalog model IDs must be nonempty and distinct")
    account_input = prior["hosted_pilot"]["accounting"]
    account = {key: account_input[key] for key in ("limit_usd", "admission_stopped",
               "reported_cost_usd", "reserved_usd", "unresolved_attempts")}
    if (prior["hosted_pilot"]["allocation_id"] != ALLOCATION
            or account["limit_usd"] != "25"
            or account["admission_stopped"] is not True
            or not account["unresolved_attempts"]):
        raise ValueError("the original stopped USD 25 allocation must be retained")
    usd(account["reported_cost_usd"])
    usd(account["reserved_usd"])
    unresolved = account["unresolved_attempts"]
    if (not isinstance(unresolved, list) or len(set(unresolved)) != len(unresolved)
            or any(not isinstance(identity, str) or not identity for identity in unresolved)):
        raise ValueError("unresolved attempt identities must be distinct nonempty strings")
    for identity in unresolved:
        safe_identity(identity, name="unresolved attempt")
    attempts = prior["hosted_pilot"]["actual_transport_attempts"]
    if type(attempts) is not int or attempts < len(unresolved):
        raise ValueError("prior transport attempts must cover every unresolved identity")
    for field in ("manifest_hash", "journal_hash"):
        if not isinstance(prior["hosted_pilot"][field], str) or not re.fullmatch(r"[0-9a-f]{64}", prior["hosted_pilot"][field]):
            raise ValueError("prior manifest/journal identity must be SHA-256")
    if (fragment.get("format") != "dafjev.private-local-study-fragment/2"
            or fragment.get("sampling") != "all" or type(fragment.get("timing_samples")) is not int
            or fragment["timing_samples"] != 100 or type(fragment.get("timing_repetitions")) is not int
            or fragment["timing_repetitions"] != 5
            or fragment.get("timing_sampling_scope") != "cohort"):
        raise ValueError("full expansion requires all quality and global 100 x 5 timing")
    seed = fragment["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    receipt_ref = fragment["selection_receipt"]
    receipt_raw, receipt_sha = read_bound(fragment_parent / receipt_ref["path"], receipt_ref["sha256"])
    receipt = strict_json_loads(receipt_raw)
    input_refs = {item["id"]: item for item in receipt["inputs"]}
    if len(input_refs) != len(receipt["inputs"]):
        raise ValueError("preparation receipt contains duplicate input IDs")
    declarations = fragment["expected_quality_counts"]
    if len(declarations) != len(fragment["datasets"]):
        raise ValueError("quality count declarations must cover every ordered dataset")
    cohorts, dataset_rows, seen = [], [], set()
    for index, item in enumerate(fragment["datasets"]):
        identifier = safe_identity(item["id"], name="dataset ID")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("dataset IDs must be distinct nonempty strings")
        seen.add(identifier)
        role = item["role"]
        if role not in {"ordinary", "quality_control"}:
            raise ValueError("dataset role must be ordinary or quality_control")
        if Path(item["path"]).absolute() != Path(input_refs[identifier]["path"]).absolute():
            raise ValueError("dataset path differs from preparation receipt")
        raw, sha = read_bound(fragment_parent / item["path"], input_refs[identifier]["sha256"])
        dataset = prepared_dataset_from_dict(strict_json_loads(raw))
        selected = [e for e in dataset.examples if e.split in {"validation", "test"}]
        is_control = dataset.manifest.metadata.get("control_role") == "quality_control"
        if (role == "quality_control") != is_control:
            raise ValueError("declared dataset role differs from prepared control metadata")
        if is_control and any(e.metadata.get("timing_eligible") is not False for e in selected):
            raise ValueError("quality control rows must be excluded from timing")
        validation = sorted((e for e in selected if e.split == "validation"), key=lambda e: e.id)
        if not validation:
            raise ValueError("each dataset needs a validation capability fixture")
        cohorts.append(selected)
        splits = Counter(e.split for e in selected)
        observed = {"id": identifier, "quality_control_examples": len(selected) if is_control else 0,
                    "quality_decisions": sum(len(e.questions) for e in selected),
                    "quality_examples": len(selected), "test_examples": splits["test"],
                    "validation_examples": splits["validation"]}
        declared = declarations[index]
        if (any(type(declared.get(key)) is not int for key in observed if key != "id")
                or declared != observed):
            raise ValueError("declared ordered quality counts differ from actual inputs")
        dataset_rows.append({"index": index, "id": identifier, "role": role,
            "portable_input_file": f"inputs/dataset-{index}.json", "input_sha256": sha,
            "input_bytes": len(raw), "dataset_manifest_sha256": dataset.manifest.sha256,
            "validation_examples": splits["validation"], "test_examples": splits["test"],
            "validation_groups": len({e.group_id for e in validation}),
            "test_groups": len({e.group_id for e in selected if e.split == "test"}),
            "probe_example_id": validation[0].id,
            "validation_example_ids_sha256": content_hash(sorted(e.id for e in validation)),
            "test_example_ids_sha256": content_hash(sorted(e.id for e in selected if e.split == "test"))})
    pack = timing_sample_pack(cohorts, seed=seed, samples=100, scope="cohort")
    if pack != fragment["timing_sample_pack"]:
        raise ValueError("frozen shared timing IDs differ from the prepared inputs")
    profiles = _catalog_profiles(catalog)
    if endpoints["data"].get("id") != "qwen/qwen3.5-9b":
        raise ValueError("Qwen endpoint metadata identifies a different model")
    endpoint = next((e for e in endpoints["data"]["endpoints"] if e["tag"] == "darkbloom/fp4"), None)
    if endpoint is None or not {"max_tokens", "response_format", "structured_outputs"} <= set(endpoint["supported_parameters"]):
        raise ValueError("the pinned Qwen endpoint contract is unavailable")
    profiles.append({"id": "qwen3.5-9b-chat", "kind": "http", "hosted": True, "mode": "chat",
        "model": "qwen/qwen3.5-9b", "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "api_key_env": "OPENROUTER_API_KEY", "context_length": endpoint["context_length"],
        "capabilities": {"primitives": ["noul", "choice", "score"], "probability_source": None,
                         "probability_semantics": None, "evidence": "catalog_only"},
        "pricing": {"source": "https://openrouter.ai/api/v1/models/qwen/qwen3.5-9b/endpoints",
                    "snapshot_at": catalog["fetched_at"], "rates": endpoint["pricing"]},
        "options": {"max_tokens": 512, "temperature": 0,
                    "provider": {"only": ["darkbloom/fp4"], "allow_fallbacks": False}}})
    if len({p["id"] for p in profiles}) != len(profiles):
        raise ValueError("profile identities collide")
    timing = {(row["dataset"], row["example_id"]) for row in pack["examples"]}
    arms: list[dict[str, Any]] = []
    for profile in profiles:
        safe_identity(profile["id"], name="profile ID")
        safe_identity(profile["model"], name="model ID")
        quote = _liability(profile)
        profile["capabilities"]["probability_semantics"] = None
        profile["capabilities"]["authentication"] = "bearer"
        phase_ids: dict[str, list[str]] = {p: [] for p in ("quality", "warm_repeat", "capability_probe", "graphical")}
        compatible: Counter[str] = Counter()
        caps = profile["capabilities"]
        for index, cohort in enumerate(cohorts):
            probe_id = dataset_rows[index]["probe_example_id"]
            probe = next(e for e in cohort if e.id == probe_id)
            phase_ids["capability_probe"].append(content_hash([index, probe_id, profile["id"], "capability_probe"]))
            compatible["capability_probe"] += supports(probe, caps)
            for example in cohort:
                phase_ids["quality"].append(content_hash([index, example.id, profile["id"], 0]))
                compatible["quality"] += supports(example, caps)
                if (index, example.id) in timing:
                    for repeat in range(1, 6):
                        phase_ids["warm_repeat"].append(content_hash([index, example.id, profile["id"], repeat]))
                        compatible["warm_repeat"] += supports(example, caps)
        phase_ids["graphical"].append(content_hash(["graphical", profile["id"], seed]))
        compatible["graphical"] = int(caps.get("probability_source") is not None and "choice" in caps["primitives"])
        counts = {key: len(value) for key, value in phase_ids.items()}
        with localcontext(currency_context()):
            priced_calls = sum(compatible[p] for p in ("quality", "warm_repeat", "capability_probe"))
            one = str(Decimal(quote) * priced_calls) if quote is not None else None
            two = str(Decimal(quote) * priced_calls * 2) if quote is not None else None
        arms.append({"profile": profile, "planned_phase_counts": counts,
            "planned_cells": sum(counts.values()), "static_compatible_phase_counts": dict(compatible),
            "cell_ids_sha256_by_phase": {key: ids_digest(value) for key, value in phase_ids.items()},
            "liability_usd_per_attempt": quote,
            "admission_reason": _liability_reason(profile) if quote is None else None,
            "compatible_non_graph_one_attempt_ceiling_usd": one,
            "compatible_non_graph_two_attempt_ceiling_usd": two})
    totals: Counter[str] = Counter()
    for arm in arms:
        totals.update(arm["planned_phase_counts"])
    return {"format": "dafjev.hosted-expansion-obligation/1", "status": "BLOCKED_UNKNOWN_BILLING",
        "execution_authority": False,
        "selection_receipt": {"portable_input_file": "inputs/selection-receipt.json",
                              "sha256": receipt_sha, "bytes": len(receipt_raw)},
        "allocation": {"id": ALLOCATION, "limit_usd": "25", "new_funding": False,
            "prior_accounting": account, "prior_transport_attempts": prior["hosted_pilot"]["actual_transport_attempts"],
            "prior_manifest_hash": prior["hosted_pilot"]["manifest_hash"],
            "prior_journal_hash": prior["hosted_pilot"]["journal_hash"],
            "new_transport_attempts": 0, "reconciliation_status": "not_performed"},
        "protocol": {"seed": seed, "sampling": "all", "hosted_concurrency": 4, "max_attempts": 2,
            "timeout_s": 60, "timing_samples": 100, "timing_repetitions": 5,
            "timing_sampling_scope": "cohort", "bootstrap_samples": 2000,
            "validation_policy_selection": "pending; validation-only; no test-driven selection",
            "validation_gate_rule": {"method": "grouped_wilson_upper", "confidence_level": .95,
                "max_risk": .05, "candidate_thresholds": "observed valid validation confidence values",
                "scope": "descriptive same-validation threshold admission, not a distribution-free guarantee"},
            "test_exposure": "official tests already observed in retained earlier studies",
            "capability_scope": "one selected validation fixture per dataset, not maximum boundary proof",
            "phase_order": "capability_probe, quality, warm_repeat ascending repeat, graphical",
            "cell_identity": "content_hash([dataset_index, example_id, backend_id, repeat]); probe repeat=capability_probe; graphical=[graphical,backend_id,seed]",
            "graphical_scope": "one surrogate-factor workflow per arm; calibrated/posterior meaning not established"},
        "datasets": dataset_rows, "timing_sample_pack": pack, "arms": arms,
        "planned_phase_counts": dict(totals), "planned_cells": sum(totals.values()),
        "new_observed_outcomes": {"completed": 0, "failed": 0, "unsupported": 0,
                                  "unresolved": 0, "unattempted": sum(totals.values())},
        "limitations": ["Compact obligation projection; not an executable RunStore or funding approval.",
            "A new RunStore's empty ledger cannot establish that the original allocation is clear.",
            "Reopening requires exact billing or independently defensible old-attempt liability-bound evidence within the same USD 25 total.",
            "Per-attempt reservations use actual sent tariff ceilings; full ceilings are not spend forecasts.",
            "Static compatibility is not empirical endpoint, input-consumption or probability-meaning evidence.",
            "Free model account quotas and provider availability are unverified."]}


def render_matrix(plan: dict[str, Any], directory: Path) -> dict[str, str]:
    """Render static admission categories; no model outcomes enter the figure."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    columns = ["Binary", "Choice ≤24", "BANK77", "CLINC151", "Score", "Graph", "Tariff bound"]
    categories = {"unverified": 0, "adapter_unsupported": 1, "unbounded": 2,
                  "bounded": 3, "zero_tariff": 4}
    colours = ["#d9e3f0", "#ededed", "#edb8ac", "#c7b8e5", "#c2dfc7"]
    rows = []
    for arm in plan["arms"]:
        caps = arm["profile"]["capabilities"]
        cells = []
        for kind, options in (("noul", 2), ("choice", 3), ("choice", 77), ("choice", 151), ("score", 5)):
            allowed = (kind in caps["primitives"] and
                       (not caps.get("max_options") or options <= caps["max_options"]))
            cells.append("unverified" if allowed else "adapter_unsupported")
        cells.append("unverified" if caps.get("probability_source") is not None
                     and "choice" in caps["primitives"] else "adapter_unsupported")
        quote = arm["liability_usd_per_attempt"]
        cells.append("unbounded" if quote is None else "zero_tariff" if Decimal(quote) == 0 else "bounded")
        rows.append({"profile": arm["profile"]["id"], "cells": cells})
    data = {"format": "dafjev.hosted-admission-matrix/1", "plan_sha256": content_hash(plan),
            "columns": columns, "rows": rows, "categories": categories,
            "scope": "Static adapter restrictions and tariff bounds only; every arm remains blocked by prior UNKNOWN billing; no inference measurements."}
    data_raw = (canonical_json(data) + "\n").encode()
    (directory / "admission-matrix.json").open("xb").write(data_raw)
    epoch = datetime(2026, 10, 8, tzinfo=timezone.utc)
    style = {"font.family": "DejaVu Sans", "font.size": 8, "svg.fonttype": "path",
             "svg.hashsalt": content_hash(data), "pdf.fonttype": 42, "axes.grid": False,
             "figure.facecolor": "white", "savefig.facecolor": "white"}
    # rc_context does not restore backend changes, so leave that process setting
    # untouched while replacing every rendering parameter with a fixed default.
    defaults = {key: value for key, value in plt.rcParamsDefault.items() if key != "backend"}
    defaults.update(style)
    with plt.rc_context(defaults):
        fig, ax = plt.subplots(figsize=(12, max(6.2, 0.28 * len(rows) + 2)))
        ax.imshow([[categories[c] for c in row["cells"]] for row in rows],
                  cmap=ListedColormap(colours), vmin=-0.5, vmax=4.5, aspect="auto", origin="upper")
        ax.set_xticks(range(len(columns)), columns)
        ax.set_yticks(range(len(rows)), [row["profile"] for row in rows])
        ax.tick_params(length=0)
        abbreviations = {"unverified": "Unverified", "adapter_unsupported": "Adapter limit",
                         "unbounded": "Unbounded", "bounded": "Bounded", "zero_tariff": "Zero tariff"}
        for index, row in enumerate(rows):
            for column, cell in enumerate(row["cells"]):
                ax.text(column, index, abbreviations[cell], ha="center", va="center", fontsize=7)
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.subplots_adjust(left=0.32, right=0.985, top=0.85, bottom=0.24)
        fig.text(0.02, 0.965, "Hosted expansion admission matrix", fontsize=16, weight="bold")
        fig.text(0.02, 0.925, "Plan only · all new admission BLOCKED · original USD 25 allocation has one UNKNOWN charge", fontsize=10)
        fig.text(0.02, 0.155, "Unverified: catalog/interface candidate, no successful hosted capability evidence. Adapter limit: declared client restriction.", fontsize=8)
        fig.text(0.02, 0.12, "Bounded/zero tariff: conditional per-attempt quote, not actual billing or permission. Unbounded: native aggregate billing not established.", fontsize=8)
        fig.text(0.02, 0.085, "BANK/CLINC retain all 77/151 options. Graph cells concern surrogate-factor workflows; calibrated/posterior meaning is unknown.", fontsize=8)
        fig.text(0.02, 0.05, "Exact catalog, profiles, cohort and cell-denominator bindings are in plan.json. No quality, latency, calibration or spend result is plotted.", fontsize=8)
        try:
            for extension in ("svg", "pdf", "png"):
                target = directory / ("admission-matrix." + extension)
                if target.exists():
                    raise FileExistsError("figure output already exists")
                metadata = ({"Date": epoch.isoformat()} if extension == "svg" else
                            {"CreationDate": epoch, "ModDate": epoch} if extension == "pdf" else {})
                fig.savefig(target, dpi=180, metadata=metadata)
        finally:
            plt.close(fig)
    return {p.name: read_bound(p)[1] for p in sorted(directory.glob("admission-matrix.*"))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("catalog", "endpoints", "fragment", "prior-summary"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--figures", action="store_true", help="render the static admission matrix; requires figures extra")
    args = parser.parse_args()
    output = checked_output_path(args.out_dir)
    before = source()
    values, bindings = {}, {}
    for name in ("catalog", "endpoints", "fragment", "prior_summary"):
        raw, sha = read_bound(getattr(args, name), getattr(args, name + "_sha256"))
        values[name] = strict_json_loads(raw)
        bindings[name] = {"sha256": sha, "bytes": len(raw)}
    result = build(values["catalog"], values["endpoints"], values["fragment"],
                   values["prior_summary"], fragment_parent=args.fragment.absolute().parent)
    after = source()
    if after != before:
        raise ValueError("source changed during projection; retain inputs and retry only after a new freeze")
    result["source"] = before
    result["input_bindings"] = bindings
    checked_output_path(output).mkdir(parents=True, exist_ok=False)
    payload = (canonical_json(result) + "\n").encode()
    with (output / "plan.json").open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if args.figures:
        render_matrix(result, output)
        if source() != before:
            raise ValueError("source changed during static rendering; outputs are not accepted")
    output_hashes = {p.name: read_bound(p)[1] for p in sorted(output.iterdir()) if p.is_file()}
    with (output / "generation.json").open("xb") as handle:
        handle.write((canonical_json({"format": "dafjev.hosted-expansion-generation/1",
            "source": before, "inputs": bindings, "outputs": output_hashes,
            "inference_attempts": 0, "credentials_read": False, "new_funding": False,
            "scope": "offline non-executable obligations and static figure only"}) + "\n").encode())
    print(json.dumps({"planned_cells": result["planned_cells"], "status": result["status"],
                      "plan_sha256": hashlib.sha256(payload).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"ERROR: {type(exc).__name__}; no inference performed", file=sys.stderr)
        raise SystemExit(1) from None
