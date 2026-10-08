"""Frozen pass selection and actual loopback request phase barriers."""

import json
from collections import Counter
from itertools import pairwise

import pytest

from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_graphical import reference_graph
from daf_jev.benchmark_runner import execute_run, plan_run, report_run


def _config(tmp_path, endpoint, *, selection=None, probes=True):
    save_dataset(make_synthetic_dataset("categorical", seed=13, n=10), tmp_path / "dataset.json")
    value = {"format": "dafjev.benchmark-run/1", "seed": 13, "budget_usd": "0",
             "sampling": "all", "timing_samples": 2, "timing_repetitions": 5,
             "capability_probes": probes, "timeout_s": 2,
             "datasets": [{"path": "dataset.json"}],
             "backends": [{"id": "local", "kind": "http", "model": "fixture", "endpoint": endpoint}]}
    if selection is not None:
        value["execution_selection"] = selection
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    return path


def _native():
    return {"model": "fixture", "usage": {}, "answers": {
        "decision": {"type": "choice", "choice": "billing", "confidence": .6,
                     "probabilities": {"billing": .6, "account": .2, "technical": .2}}}}


def _phase(cell):
    return ({"capability_probe": 0, "quality": 1, "warm_repeat": 2, "graphical": 3}[cell["phase"]],
            cell["repeat"] if cell["phase"] == "warm_repeat" else 0)


def test_default_all_actual_requests_await_primary_and_each_of_five_rounds(tmp_path, stub):
    store = plan_run(_config(tmp_path, stub.base_url + "/v1/systemone"), tmp_path / "runs")
    cells = {cell["id"]: cell for cell in store.manifest["cells"]}
    assert store.manifest["protocol"]["execution_selection"] == {"phase": "all"}
    for _ in cells:
        stub.enqueue(body=_native())

    report = execute_run(store.directory)
    events = store.events()
    starts = [event for event in events if event.get("event") == "attempt_started"]
    finished = {event["cell_id"]: index for index, event in enumerate(events) if event.get("event") == "cell_finished"}
    positions = {event["attempt_id"]: index for index, event in enumerate(events) if event.get("event") == "attempt_started"}
    phases = [_phase(cells[event["cell_id"]]) for event in starts]
    assert phases == sorted(phases)
    assert len(stub.hits) == len(starts) == len(cells)
    assert set(key for key, _ in phases) == {0, 1, 2}
    assert {repeat for key, repeat in phases if key == 2} == {1, 2, 3, 4, 5}
    for before, after in pairwise(starts):
        if _phase(cells[before["cell_id"]]) != _phase(cells[after["cell_id"]]):
            assert finished[before["cell_id"]] < positions[after["attempt_id"]]
    quality_ids = {cell["example_id"] for cell in cells.values() if cell["phase"] == "quality"}
    warm = [cell for cell in cells.values() if cell["phase"] == "warm_repeat"]
    assert all(cell["example_id"] in quality_ids for cell in warm)
    assert len({frozenset(cell["example_id"] for cell in warm if cell["repeat"] == repeat)
                for repeat in range(1, 6)}) == 1
    assert report["denominators"] == {"completed": len(cells)}


def test_known_primary_failure_remains_denominator_and_does_not_cancel_warm_rounds(tmp_path, stub):
    store = plan_run(_config(tmp_path, stub.base_url + "/v1/systemone", probes=False), tmp_path / "runs")
    timed = next(cell["example_id"] for cell in store.manifest["cells"] if cell["phase"] == "warm_repeat")
    failed = next(cell for cell in store.manifest["cells"] if cell["phase"] == "quality" and cell["example_id"] == timed)
    for cell in store.manifest["cells"]:
        if cell["id"] == failed["id"]:
            stub.enqueue(422, body={"usage": {}, "error": "known failure fixture"})
        else:
            stub.enqueue(body=_native())

    report = execute_run(store.directory)
    assert report["denominators"] == {"failed": 1, "completed": len(store.manifest["cells"]) - 1}
    assert all(cell["status"] == "completed" for cell in report["cells"] if cell["phase"] == "warm_repeat")
    assert len(stub.hits) == len(store.manifest["cells"])


def test_graphical_actual_requests_begin_only_after_last_warm_terminal(tmp_path, stub):
    path = _config(tmp_path, stub.base_url + "/v1/systemone")
    value = json.loads(path.read_text())
    value["graphical_experiments"] = True
    path.write_text(json.dumps(value))
    store = plan_run(path, tmp_path / "runs")
    for cell in store.manifest["cells"]:
        if cell["phase"] != "graphical":
            stub.enqueue(body=_native())
    graph = reference_graph()
    answers = {}
    for key, cpt in graph.cpts.items():
        parents = graph.parents_of(key)
        for assignment, row in cpt.table:
            suffix = "|".join(f"{parent}={state}" for parent, state in zip(parents, assignment, strict=True))
            probabilities = dict(zip(graph.variable(key).states, row, strict=True))
            answers[f"cpt::{key}|{suffix}"] = {"type": "choice", "choice": max(probabilities, key=probabilities.__getitem__),
                                               "probabilities": probabilities, "confidence": .8}
    stub.enqueue(body={"model": "fixture", "usage": {}, "answers": answers})
    stub.enqueue(422, body={"usage": {}, "error": "known structure failure fixture"})

    report = execute_run(store.directory)
    events = store.events()
    cell_map = {cell["id"]: cell for cell in store.manifest["cells"]}
    warm_finish = [index for index, event in enumerate(events) if event.get("event") == "cell_finished"
                   and cell_map[event["cell_id"]]["phase"] == "warm_repeat"]
    graphical_start = [index for index, event in enumerate(events) if event.get("event") == "attempt_started"
                       and cell_map[event["cell_id"]]["phase"] == "graphical"]
    assert len(graphical_start) == 2 and max(warm_finish) < min(graphical_start)
    assert len(stub.hits) == len(store.manifest["cells"]) + 1
    graphical = next(cell for cell in report["cells"] if cell["phase"] == "graphical")
    assert graphical["status"] == "failed"
    assert report["graphical_experiments"][0]["record"]["phase"] == "propose_structure"


def test_unresolved_primary_refuses_its_five_warm_calls_with_retained_denominators(tmp_path, stub):
    store = plan_run(_config(tmp_path, stub.base_url + "/v1/systemone", probes=False), tmp_path / "runs")
    timed = next(cell["example_id"] for cell in store.manifest["cells"] if cell["phase"] == "warm_repeat")
    primary = next(cell for cell in store.manifest["cells"] if cell["phase"] == "quality" and cell["example_id"] == timed)
    store.append({"event": "cell_started", "cell_id": primary["id"]})
    for _ in store.manifest["cells"]:
        stub.enqueue(body=_native())

    report = execute_run(store.directory)
    blocked = [cell for cell in report["cells"] if cell["example_id"] == timed and cell["phase"] == "warm_repeat"]
    assert len(blocked) == 5
    assert all(cell["status"] == "unattempted" and cell["reason"] == "primary_quality_unresolved" for cell in blocked)
    assert len(stub.hits) == len(store.manifest["cells"]) - 6
    blocked_ids = {cell["id"] for cell in blocked}
    assert not any(event.get("event") == "attempt_started" and event["cell_id"] in blocked_ids for event in store.events())
    assert report["denominators"]["unresolved"] == 1


def test_unsupported_primary_is_propagated_without_transport_attempts(tmp_path, stub):
    path = _config(tmp_path, stub.base_url + "/v1/systemone", probes=False)
    value = json.loads(path.read_text())
    value["backends"][0]["capabilities"] = {"max_options": 2}
    path.write_text(json.dumps(value))
    store = plan_run(path, tmp_path / "runs")

    report = execute_run(store.directory)
    assert report["denominators"] == {"unsupported": len(store.manifest["cells"])}
    assert all(cell["reason"] == "primary_quality_unsupported" for cell in report["cells"] if cell["phase"] == "warm_repeat")
    assert stub.hits == []


@pytest.mark.parametrize("phase,repeat", [("quality", None), ("warm_repeat", 3), ("graphical", None)])
def test_selected_pass_preserves_logical_ids_samples_probes_and_its_denominators(tmp_path, stub, phase, repeat):
    path = _config(tmp_path, stub.base_url + "/v1/systemone")
    value = json.loads(path.read_text())
    value["graphical_experiments"] = True
    path.write_text(json.dumps(value))
    full = plan_run(path, tmp_path / "runs")
    selection = {"phase": phase, "study_id": "shared-study", "pass_id": "explicit-pass"}
    if repeat is not None:
        selection["repeat"] = repeat
        selection["prior_quality"] = {"manifest_hash": "0" * 64, "binding_scope": "coordinator verifies artifacts before launch"}
    value["execution_selection"] = selection
    path.write_text(json.dumps(value))
    selected = plan_run(path, tmp_path / "runs")

    expected = [cell for cell in full.manifest["cells"] if cell["phase"] == "capability_probe"
                or (cell["phase"] == phase and (repeat is None or cell["repeat"] == repeat))]
    assert selected.manifest["cells"] == tuple(expected)
    assert selected.manifest["protocol"]["execution_selection"] == selection
    assert report_run(selected.directory)["denominators"] == {"unattempted": len(expected)}
    assert selected.manifest["datasets"] == full.manifest["datasets"]
    assert selected.manifest["backends"] == full.manifest["backends"]


def test_warm_pass_is_frozen_when_input_config_changes_after_planning(tmp_path, stub):
    path = _config(tmp_path, stub.base_url + "/v1/systemone", selection={"phase": "warm_repeat", "repeat": 2})
    store = plan_run(path, tmp_path / "runs")
    value = json.loads(path.read_text())
    value["execution_selection"] = {"phase": "quality"}
    path.write_text(json.dumps(value))
    for _ in store.manifest["cells"]:
        stub.enqueue(body=_native())

    report = execute_run(store.directory)
    assert report["denominators"] == {"completed": len(store.manifest["cells"])}
    assert Counter(cell["phase"] for cell in report["cells"]) == {"capability_probe": 1, "warm_repeat": 2}
    assert all(cell["repeat"] == 2 for cell in report["cells"] if cell["phase"] == "warm_repeat")
    assert report["repeatability"] == []
    assert "cross-pass" in report["repeatability_scope"]
    assert len(stub.hits) == 3


@pytest.mark.parametrize("selection", [
    "warm_repeat", {"phase": "unknown"}, {"phase": "all", "repeat": 1},
    {"phase": "warm_repeat"}, {"phase": "warm_repeat", "repeat": True},
    {"phase": "warm_repeat", "repeat": 0}, {"phase": "warm_repeat", "repeat": 6},
    {"phase": "quality", "study_id": ""}, {"phase": "quality", "pass_id": 3},
    {"phase": "warm_repeat", "repeat": 2, "prior_quality": "permission"},
    {"phase": "all", "runtime_phase": "quality"}, {"phase": "graphical"},
])
def test_invalid_or_empty_frozen_selector_is_rejected_before_run_creation(tmp_path, stub, selection):
    with pytest.raises(ValueError, match="execution_selection"):
        plan_run(_config(tmp_path, stub.base_url + "/v1/systemone", selection=selection), tmp_path / "runs")
    assert stub.hits == []
    assert not (tmp_path / "runs").exists()
