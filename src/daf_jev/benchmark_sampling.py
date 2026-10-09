"""Frozen, backend-independent timing IDs; no labels, fitting or network I/O."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from daf_jev.benchmark_datasets import BenchmarkExample
from daf_jev.decision_backends import content_hash


def timing_sample_pack(cohorts: Sequence[Sequence[BenchmarkExample]], *, seed: int,
                       samples: int, scope: str = "cohort") -> dict[str, Any]:
    """Select exactly N ordinary physical examples globally, or capped per dataset.

    Global selection takes one deterministic representative per input group,
    balanced by dataset and native task types. Matched permutation groups are
    explicitly declared quality controls and never enter the timing treatment.
    An insufficient exact cohort fails before planning any execution artifacts.
    """
    if scope not in {"cohort", "per_dataset"}:
        raise ValueError("timing_sampling_scope must be cohort or per_dataset")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("timing_samples must be a positive integer")
    rows: list[dict[str, Any]] = []
    excluded = 0
    for index, examples in enumerate(cohorts):
        for example in examples:
            if example.split != "test":
                continue
            if example.metadata.get("timing_eligible") is False:
                excluded += 1
                continue
            rows.append({"dataset": index, "example_id": example.id, "group_id": example.group_id,
                         "task_types": sorted({q.to_wire()["type"] for q in example.questions.values()})})
    if scope == "per_dataset":
        selected = [row for index in range(len(cohorts)) for row in sorted(
            (r for r in rows if r["dataset"] == index),
            key=lambda r: content_hash([seed, r["example_id"]]))[:samples]]
        unit = "physical_examples; legacy per-dataset capped selection"
    else:
        groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[(row["dataset"], row["group_id"])].append(row)
        buckets: dict[tuple[int, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
        for identity, members in groups.items():
            if len({tuple(r["task_types"]) for r in members}) != 1:
                raise ValueError("timing input group crosses task types")
            chosen = min(members, key=lambda r: content_hash([seed, "timing_representative", *identity, r["example_id"]]))
            buckets[(chosen["dataset"], tuple(chosen["task_types"]))].append(chosen)
        if len(groups) < samples:
            raise ValueError(f"exact cohort timing requires {samples} ordinary input groups; available {len(groups)}; matched quality controls are excluded")
        for key, bucket in buckets.items():
            bucket.sort(key=lambda r: content_hash([seed, "timing_group", *key, r["group_id"], r["example_id"]]))
        counts: dict[tuple[int, tuple[str, ...]], int] = defaultdict(int)
        selected = []
        while len(selected) < samples:
            key = min((k for k, bucket in buckets.items() if bucket),
                      key=lambda k: (counts[k], content_hash([seed, "timing_stratum", *k])))
            selected.append(buckets[key].pop(0))
            counts[key] += 1
        unit = "physical_example; one deterministic representative per dataset/input group"
    pack = {"format": "dafjev.benchmark-timing-sample/1", "timing_sampling_scope": scope,
            "seed": seed, "requested_examples": samples, "selected_examples": len(selected),
            "selected_base_groups": len({(r["dataset"], r["group_id"]) for r in selected}),
            "sampling_unit": unit, "selection_labels_used": False,
            "selection_method": "deterministic_dataset_task_balanced_round_robin" if scope == "cohort" else "legacy_per_dataset_hash_rank",
            "excluded_quality_control_examples": excluded, "examples": selected}
    return {**pack, "sha256": content_hash(pack)}
