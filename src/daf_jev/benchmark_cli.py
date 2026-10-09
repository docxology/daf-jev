"""Thin, explicit-network argparse surface for benchmark workflows."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from daf_jev.decision_backends import canonical_json


def register_benchmark_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="benchmark_command", required=True)
    dataset = sub.add_parser("dataset", help="prepare independent labeled datasets")
    ds = dataset.add_subparsers(dest="dataset_command", required=True)
    synthetic = ds.add_parser("synthetic", help="generate seeded labeled tasks offline")
    synthetic.add_argument("--kind", choices=("binary", "categorical", "ordinal", "bayes"), default="categorical")
    synthetic.add_argument("--samples", type=int, default=120,
                           help="base fixture count; matched controls expand by option count")
    synthetic.add_argument("--matched-option-permutations", action="store_true",
                           help="categorical/Bayes only: identical-fixture cyclic Choice-order controls")
    synthetic.add_argument("--seed", type=int, default=20261007)
    synthetic.add_argument("--output", required=True, type=Path)
    synthetic.add_argument("--packed", action="store_true", help="share ordered question definitions in prepared format two")
    fetch = ds.add_parser("fetch", help="explicitly download pinned public dataset bytes")
    fetch.add_argument("--kind", required=True, choices=("banking77", "clinc150", "wine"))
    fetch.add_argument("--out-dir", required=True, type=Path)
    prepare = ds.add_parser("prepare", help="adapt already downloaded source files offline")
    prepare.add_argument("--kind", required=True, choices=("banking77", "clinc150", "wine"))
    prepare.add_argument("--source", required=True, type=Path)
    prepare.add_argument("--seed", type=int, default=20261007)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--packed", action="store_true", help="share ordered question definitions in prepared format two")
    folds = ds.add_parser("folds", help="export retained original split and grouped-fold identities offline")
    folds.add_argument("--source", required=True, type=Path, help="complete freshly prepared real dataset")
    folds.add_argument("--output", required=True, type=Path)
    view = ds.add_parser("view", help="prepare a separate selection, evaluation or final-training cohort")
    view.add_argument("--source", required=True, type=Path, help="complete freshly prepared real dataset")
    view.add_argument("--view", choices=("evaluation", "selection", "final_train"), default="evaluation")
    view.add_argument("--validation-fold", type=int)
    view.add_argument("--test-fold", type=int, default=0)
    view.add_argument("--cohort", choices=("canonical", "leakage_clean"), default="canonical")
    view.add_argument("--output", required=True, type=Path)
    view.add_argument("--packed", action="store_true", help="share ordered question definitions in prepared format two")
    catalog = sub.add_parser("catalog", help="explicit public GET of OpenRouter decision catalog")
    catalog.add_argument("--output", required=True, type=Path)
    catalog.add_argument("--profiles-output", type=Path)
    allocation = sub.add_parser("allocation", help="explicit shared USD allocation administration; no inference")
    accounting = allocation.add_subparsers(dest="allocation_command", required=True)
    initialize = accounting.add_parser("init", help="create one allocation exclusively; never implicit")
    initialize.add_argument("directory", type=Path)
    initialize.add_argument("--allocation-id", required=True)
    initialize.add_argument("--limit-usd", default="25")
    initialize.add_argument("--required-import", type=Path, action="append", default=[],
                            help="exact legacy binding JSON; must be imported before execution")
    inspect = accounting.add_parser("inspect", help="read existing allocation without mutation")
    inspect.add_argument("directory", type=Path)
    legacy = accounting.add_parser("import-legacy", help="append verified old-run accounting explicitly")
    legacy.add_argument("directory", type=Path)
    legacy.add_argument("--binding", required=True, type=Path)
    target = accounting.add_parser("reconciliation-target", help="read exact imported UNKNOWN attempt identity; no proof or writes")
    target.add_argument("directory", type=Path)
    target.add_argument("--legacy-manifest-hash", required=True)
    target.add_argument("--attempt-id", required=True)
    for name in ("preview-reconciliation", "reconcile"):
        recovery = accounting.add_parser(name, help="validate exact provider evidence offline" if name.startswith("preview") else "explicit append-only externally reviewed legacy charge")
        recovery.add_argument("directory", type=Path)
        recovery.add_argument("--evidence", required=True, type=Path)
        recovery.add_argument("--evidence-sha256", required=True)
        recovery.add_argument("--review", required=True, type=Path)
        recovery.add_argument("--review-sha256", required=True)
    plan = sub.add_parser("plan", help="freeze experiment inputs without inference")
    plan.add_argument("--config", required=True, type=Path)
    plan.add_argument("--out-dir", required=True, type=Path)
    for command in ("run", "resume"):
        action = sub.add_parser(command, help="execute only unattempted frozen cells")
        action.add_argument("directory", type=Path)
        action.add_argument("--output", type=Path)
        action.add_argument("--through-phase", choices=("capability_probe", "quality", "warm_repeat", "graphical"),
                            help="stop after this phase; later frozen cells remain unattempted in the same run")
    report = sub.add_parser("report", help="recompute exact selected evidence offline")
    report.add_argument("directory", type=Path)
    report.add_argument("--output", type=Path)
    report.add_argument("--markdown", type=Path)
    report.add_argument("--pdf", type=Path)
    report.add_argument("--gates-output", type=Path)
    parser.set_defaults(func=main)


def main(args: argparse.Namespace) -> int:
    from daf_jev.benchmark_datasets import (
        dataset_fold_pack,
        dataset_view,
        fetch_dataset,
        load_dataset,
        load_prepared_dataset,
        make_synthetic_dataset,
        save_dataset,
    )
    from daf_jev.benchmark_runner import (
        _input_bytes,
        catalog_profiles,
        execute_run,
        plan_run,
        report_run,
        save_report,
        snapshot_catalog,
    )
    result: dict[str, Any]
    command = args.benchmark_command
    if command == "dataset":
        if args.dataset_command == "fetch":
            fetched = fetch_dataset(args.kind, args.out_dir)
            result = {"source_directory": str(fetched.parent)}
        elif args.dataset_command == "folds":
            pack = dataset_fold_pack(load_prepared_dataset(args.source))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(canonical_json(pack) + "\n")
            result = {"fold_pack": str(args.output), "sha256": pack["sha256"], "rows": len(pack["assignments"])}
        else:
            if args.dataset_command == "synthetic":
                prepared = make_synthetic_dataset(args.kind, seed=args.seed, n=args.samples,
                    matched_option_permutations=args.matched_option_permutations)
            elif args.dataset_command == "view":
                prepared = dataset_view(load_prepared_dataset(args.source), view=args.view,
                    validation_fold=args.validation_fold, test_fold=args.test_fold, cohort=args.cohort)
            else:
                prepared = load_dataset(args.source, kind=args.kind, seed=args.seed)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            save_dataset(prepared, args.output, packed=args.packed)
            result = {"dataset": str(args.output), "prepared_format": "dafjev.benchmark-dataset/2" if args.packed else "dafjev.benchmark-dataset/1",
                      "manifest": prepared.manifest.to_dict()}
    elif command == "catalog":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        catalog = snapshot_catalog(args.output)
        if args.profiles_output:
            with args.profiles_output.open("x") as handle:
                handle.write(canonical_json(catalog_profiles(args.output)) + "\n")
        result = {"catalog": str(args.output), "models": len(catalog["payload"]["data"]), "evidence": "discovery_only"}
    elif command == "allocation":
        from daf_jev._json import strict_json_loads
        from daf_jev.benchmark_allocation import AllocationLedger, LegacyRunBinding

        def binding(path: Path) -> LegacyRunBinding:
            return LegacyRunBinding.from_dict(strict_json_loads(_input_bytes(path)))

        if args.allocation_command == "init":
            required = tuple(binding(path) for path in args.required_import)
            ledger = AllocationLedger.create(args.directory, allocation_id=args.allocation_id,
                                             limit=args.limit_usd, required_imports=required)
        else:
            ledger = AllocationLedger(args.directory, read_only=args.allocation_command in {"inspect", "reconciliation-target", "preview-reconciliation"})
            if args.allocation_command == "import-legacy":
                ledger.import_run(binding(args.binding))
            elif args.allocation_command == "reconciliation-target":
                result = ledger.reconciliation_target(args.legacy_manifest_hash, args.attempt_id)
                print(canonical_json(result))
                return 0
            elif args.allocation_command in {"preview-reconciliation", "reconcile"}:
                operation = ledger.preview_reconciliation if args.allocation_command == "preview-reconciliation" else ledger.reconcile
                result = operation(evidence=args.evidence, evidence_sha256=args.evidence_sha256,
                                   review=args.review, review_sha256=args.review_sha256)
                print(canonical_json(result))
                return 0
        result = {"binding": ledger.identity(), "accounting": ledger.snapshot(),
                  "operation": args.allocation_command, "evidence": "accounting_only; no inference"}
    elif command == "plan":
        store = plan_run(args.config, args.out_dir)
        result = {"directory": str(store.directory), "manifest_hash": store.manifest_hash,
                  "planned_cells": len(store.manifest["cells"]), "budget_usd": store.manifest["budget_usd"],
                  "shared_allocation": store.manifest.get("shared_allocation")}
    else:
        result = (execute_run(args.directory, through_phase=args.through_phase)
                  if command in ("run", "resume") else report_run(args.directory))
        if command == "report":
            from daf_jev.benchmark_publication import write_publication
            for output in (args.markdown, args.pdf):
                if output:
                    write_publication(result, output)
            if args.gates_output:
                with args.gates_output.open("x") as handle:
                    handle.write(canonical_json(result["gate_evidence"]) + "\n")
        if args.output:
            save_report(result, args.output)
            result = {"report": str(args.output), "status": result["status"],
                      "denominators": result["denominators"], "accounting": result["accounting"]}
    print(canonical_json(result))
    return 1 if result.get("status") == "partial" and command in ("run", "resume") else 0
