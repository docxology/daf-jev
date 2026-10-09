"""Actual ordered HTTP bodies, matched-control integrity and frozen timing IDs."""

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, replace

import httpx
import pytest

from daf_jev import choice, noul
from daf_jev.benchmark_datasets import (
    make_synthetic_dataset,
    prepared_dataset_from_dict,
    save_dataset,
)
from daf_jev.benchmark_models import RuleDecisionBackend
from daf_jev.benchmark_runner import execute_run, plan_run
from daf_jev.benchmark_sampling import timing_sample_pack
from daf_jev.decision_backends import (
    AsyncHTTPDecisionBackend,
    BackendCapabilities,
    DecisionPrediction,
    DecisionRequest,
    HTTPDecisionBackend,
    PriorBackend,
    content_hash,
)


def _rehash(payload):
    """Explicit fixture transformation updates both declared dataset digests."""
    payload["manifest"]["metadata"]["examples_sha256"] = content_hash(
        payload["examples"]
    )
    payload["manifest"]["metadata"]["order_sensitive_examples_sha256"] = hashlib.sha256(
        json.dumps(
            payload["examples"],
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def test_new_v3_order_digest_and_legacy_v1_v2_load_compatibility():
    data = make_synthetic_dataset("categorical", n=8).to_dict()
    original = data["manifest"]["metadata"]["examples_sha256"]
    q = data["examples"][0]["questions"]["decision"]
    q["criteria"] = dict(reversed(list(q["criteria"].items())))
    assert (
        content_hash(data["examples"]) == original
    )  # canonical digest alone loses order
    with pytest.raises(ValueError, match="ordered examples checksum"):
        prepared_dataset_from_dict(data)
    for version in (1, 2):
        legacy = json.loads(json.dumps(data))
        legacy["manifest"]["metadata"]["generator_version"] = version
        legacy["manifest"]["metadata"].pop("order_sensitive_examples_sha256")
        loaded = prepared_dataset_from_dict(legacy)
        assert list(loaded.examples[0].questions["decision"].criteria) == list(
            q["criteria"]
        )


@pytest.mark.parametrize("kind,count", [("categorical", 3), ("bayes", 2)])
def test_matched_controls_complete_identical_group_split_semantics_and_order(
    kind, count
):
    data = make_synthetic_dataset(kind, n=9, seed=8, matched_option_permutations=True)
    assert len(data.examples) == 9 * count
    loaded = prepared_dataset_from_dict(data.to_dict())
    for offset in range(0, len(data.examples), count):
        group = loaded.examples[offset : offset + count]
        assert len({e.group_id for e in group}) == len({e.split for e in group}) == 1
        assert len({e.state for e in group}) == 1
        assert len({e.metadata["semantic_fixture_sha256"] for e in group}) == 1
        assert {e.metadata["permutation_index"] for e in group} == set(range(count))
        assert all(
            e.metadata["control_role"] == "quality_control"
            and e.metadata["timing_eligible"] is False
            for e in group
        )
        assert (
            len({e.metadata["order_sensitive_question_sha256"] for e in group}) == count
        )
        assert all(e.targets == group[0].targets for e in group)
        with pytest.raises(TypeError):
            group[0].questions["decision"].criteria["changed"] = None


@pytest.mark.parametrize(
    "mutation",
    [
        "order",
        "missing",
        "index",
        "state",
        "truth",
        "role",
        "split",
        "semantic_hash",
        "question_hash",
        "cyclic",
        "whole_group_split",
    ],
)
def test_matched_loader_rejects_stale_or_incomplete_controls_even_with_updated_array_hashes(
    mutation,
):
    p = make_synthetic_dataset(
        "categorical", n=5, matched_option_permutations=True
    ).to_dict()
    e = p["examples"][1]
    if mutation == "order":
        e["questions"]["decision"]["criteria"] = dict(
            reversed(list(e["questions"]["decision"]["criteria"].items()))
        )
    elif mutation == "missing":
        p["examples"].pop(1)
    elif mutation == "index":
        e["metadata"]["permutation_index"] = 0
    elif mutation == "state":
        e["state"] += " changed"
    elif mutation == "truth":
        e["targets"]["decision"] = "technical"
    elif mutation == "role":
        e["metadata"]["timing_eligible"] = True
    elif mutation == "split":
        e["split"] = "test"
    elif mutation == "semantic_hash":
        e["metadata"]["semantic_fixture_sha256"] = "0" * 64
    elif mutation == "question_hash":
        e["metadata"]["order_sensitive_question_sha256"] = "0" * 64
    elif mutation == "whole_group_split":
        for member in p["examples"][:3]:
            member["split"] = "train"
    else:
        q = e["questions"]["decision"]
        q["criteria"] = dict(reversed(list(q["criteria"].items())))
        e["metadata"]["option_order"] = list(q["criteria"])
        e["metadata"]["order_sensitive_question_sha256"] = hashlib.sha256(
            json.dumps(q, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    _rehash(p)
    with pytest.raises(ValueError):
        prepared_dataset_from_dict(p)


@pytest.mark.parametrize("kind", ["binary", "ordinal"])
def test_noul_and_score_do_not_claim_choice_permutations(kind):
    data = make_synthetic_dataset(kind, n=8)
    assert "option_rotation" not in {e.metadata["variant"] for e in data.examples}
    with pytest.raises(ValueError, match="categorical or bayes"):
        make_synthetic_dataset(kind, matched_option_permutations=True)


def test_cohort_selector_is_exact100_balanced_target_free_unique_groups():
    cohorts = [
        make_synthetic_dataset(kind, n=600, seed=5).examples
        for kind in ("binary", "categorical", "ordinal")
    ]
    matched = make_synthetic_dataset(
        "categorical", n=50, matched_option_permutations=True
    )
    first = timing_sample_pack([*cohorts, matched.examples], seed=9, samples=100)
    assert first["selected_examples"] == first["selected_base_groups"] == 100
    assert first["excluded_quality_control_examples"] == 30
    assert {r["dataset"] for r in first["examples"]} == {0, 1, 2}
    counts = [sum(r["dataset"] == i for r in first["examples"]) for i in range(3)]
    assert max(counts) - min(counts) <= 1
    altered = [
        tuple(replace(e, targets={key: "changed" for key in e.targets}) for e in es)
        for es in cohorts
    ]
    assert (
        timing_sample_pack([*altered, matched.examples], seed=9, samples=100) == first
    )
    assert (
        timing_sample_pack([*cohorts, matched.examples], seed=10, samples=100)["sha256"]
        != first["sha256"]
    )
    with pytest.raises(ValueError, match="exact cohort timing"):
        timing_sample_pack([matched.examples], seed=9, samples=100)
    legacy = timing_sample_pack(cohorts, seed=9, samples=100, scope="per_dataset")
    assert legacy["selected_examples"] == 300
    with pytest.raises(ValueError, match="timing_sampling_scope"):
        timing_sample_pack(cohorts, seed=9, samples=100, scope="silent")


def _plan_config(tmp_path, *, profiles=None, scope=None, samples=100):
    save_dataset(
        make_synthetic_dataset("categorical", n=500, seed=14),
        tmp_path / "ordinary.json",
    )
    save_dataset(
        make_synthetic_dataset(
            "categorical", n=10, seed=4, matched_option_permutations=True
        ),
        tmp_path / "matched.json",
    )
    config = {
        "format": "dafjev.benchmark-run/1",
        "sampling": "all",
        "seed": 14,
        "budget_usd": "0",
        "capability_probes": False,
        "timing_samples": samples,
        "timing_repetitions": 5,
        "datasets": [{"path": "ordinary.json"}, {"path": "matched.json"}],
        "backends": profiles
        or [{"id": "one", "kind": "uniform"}, {"id": "two", "kind": "uniform"}],
    }
    if scope is not None:
        config["timing_sampling_scope"] = scope
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


def test_plan_frozen_pack_shared100_per_profile_five_rounds_and_quality_controls(
    tmp_path,
):
    path = _plan_config(tmp_path)
    store = plan_run(path, tmp_path / "runs")
    pack = store.manifest["protocol"]["timing_sample_pack"]
    assert (
        pack["timing_sampling_scope"] == "cohort" and pack["selected_examples"] == 100
    )
    for backend in ("one", "two"):
        for repeat in range(1, 6):
            ids = {
                (c["dataset"], c["example_id"])
                for c in store.manifest["cells"]
                if c["backend"] == backend and c["repeat"] == repeat
            }
            assert ids == {(r["dataset"], r["example_id"]) for r in pack["examples"]}
        assert not any(
            c["phase"] == "warm_repeat" and c["dataset"] == 1
            for c in store.manifest["cells"]
        )
    assert any(
        c["phase"] == "quality" and c["dataset"] == 1 for c in store.manifest["cells"]
    )
    config = json.loads(path.read_text())
    config["timing_sample_pack"] = json.loads(json.dumps(dict(pack)))
    path.write_text(json.dumps(config))
    same = plan_run(path, tmp_path / "runs")
    assert same.manifest["protocol"]["timing_sample_pack"] == pack
    config["timing_sample_pack"]["examples"][0]["example_id"] = "tampered"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="frozen timing_sample_pack"):
        plan_run(path, tmp_path / "runs")


def test_unsupported_profile_retains_all100_and500_planned_warm_denominators(tmp_path):
    profile = {"id": "wrong-task", "kind": "uniform", "datasets": ["wine"]}
    store = plan_run(_plan_config(tmp_path, profiles=[profile]), tmp_path / "runs")
    report = execute_run(store.directory)
    assert report["denominators"] == {"unsupported": len(store.manifest["cells"])}
    assert sum(c["phase"] == "warm_repeat" for c in store.manifest["cells"]) == 500
    assert report["timing_sampling_scope"] == "cohort"
    assert report["timing_sample_pack"]["selected_examples"] == 100


@pytest.mark.parametrize("mode", ["chat", "letter", "systemone"])
def test_actual_http_preserves_requested_option_order_and_letter_meanings(stub, mode):
    bodies = []
    values = []
    for keys in [("b", "a"), ("a", "b")]:
        questions = (
            {"second": choice("Choisir café.", dict.fromkeys(keys))}
            if mode == "letter"
            else {
                "second": choice("Choisir café.", dict.fromkeys(keys)),
                "first": noul("真?"),
            }
        )
        if mode == "systemone":
            response = {
                "model": "fixture",
                "answers": {
                    "second": {
                        "type": "choice",
                        "choice": keys[0],
                        "probabilities": dict(zip(keys, [0.6, 0.4], strict=True)),
                        "confidence": 0.6,
                    },
                    "first": {"type": "noul", "noul": 0.7},
                },
                "usage": {},
            }
        else:
            response = {
                "choices": [
                    {
                        "message": {
                            "content": "A"
                            if mode == "letter"
                            else json.dumps(
                                {
                                    "answers": {
                                        "second": {"value": keys[0]},
                                        "first": {"value": 0.7},
                                    }
                                }
                            )
                        }
                    }
                ]
            }
        stub.enqueue(body=response)
        backend = HTTPDecisionBackend(
            endpoint=stub.base_url
            + "/v1/"
            + ("systemone" if mode == "systemone" else "chat/completions"),
            model="fixture",
            mode=mode,
        )
        try:
            result = backend.predict(
                DecisionRequest(
                    {"東京": "café", "later": {"β": 1, "a": 2}}, questions, timeout=2
                )
            )
        finally:
            backend.close()
        values.append(result.predictions["second"].value)
        bodies.append(stub.hits[-1]["json"])
        if mode == "systemone":
            assert list(bodies[-1]["questions"]) == ["second", "first"]
            assert list(bodies[-1]["questions"]["second"]["criteria"]) == list(keys)
        else:
            prompt = json.loads(bodies[-1]["messages"][1]["content"])
            if mode == "letter":
                assert prompt["options"]["A"]["key"] == keys[0]
            else:
                assert list(prompt["questions"]) == ["second", "first"]
                assert list(prompt["questions"]["second"]["criteria"]) == list(keys)
                schema = bodies[-1]["response_format"]["json_schema"]["schema"]
                assert schema["properties"]["answers"]["properties"]["second"][
                    "properties"
                ]["value"]["enum"] == list(keys)
            assert list(prompt["state"]) == ["東京", "later"]
    assert values == ["b", "a"]
    assert (
        hashlib.sha256(stub.hits[0]["body"].encode()).digest()
        != hashlib.sha256(stub.hits[1]["body"].encode()).digest()
    )
    if mode == "systemone":
        assert content_hash(bodies[0]) == content_hash(
            bodies[1]
        )  # identity canonicalizes mappings
    else:
        assert content_hash(bodies[0]) != content_hash(
            bodies[1]
        )  # ordered content is a string
    assert content_hash({"criteria": {"b": None, "a": None}}) == content_hash(
        {"criteria": {"a": None, "b": None}}
    )


def test_custom_response_schema_stays_fixed_while_model_visible_prompt_rotates(stub):
    schema = {"type": "json_object"}
    for keys in [("b", "a"), ("a", "b")]:
        stub.enqueue(
            body={
                "choices": [{"message": {"content": '{"answers":{"q":{"value":"a"}}}'}}]
            }
        )
        backend = HTTPDecisionBackend(
            endpoint=stub.base_url + "/v1/chat/completions",
            model="fixture",
            mode="chat",
            options={"response_format": schema},
        )
        try:
            backend.predict(
                DecisionRequest(
                    "state", {"q": choice("Choose.", dict.fromkeys(keys))}, timeout=2
                )
            )
        finally:
            backend.close()
        body = stub.hits[-1]["json"]
        assert body["response_format"] == schema
        assert list(
            json.loads(body["messages"][1]["content"])["questions"]["q"]["criteria"]
        ) == list(keys)


class _Observer:
    def __init__(self):
        self.receipts = []

    def before(self, *args):
        return "fixture-attempt"

    def after(self, receipt):
        self.receipts.append(receipt)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "raw",
    [
        '{"usage":{"cost":100,"cost":0}}',
        '{"model":"bad","model":"good"}',
        '{"answers":{"q":{},"q":{}}}',
        '{"answers":{"q":{"probabilities":{"a":0,"a":1}}}}',
        '{"usage":{"cost":NaN}}',
        pytest.param(
            '{"nested":' * 2000 + '{"duplicate":0,"duplicate":1}' + "}" * 2000,
            id="deep-ambiguous-object",
        ),
    ],
)
def test_real_http_ambiguous_outer_json_is_rejected_and_receipt_preserved(
    stub, asynchronous, raw
):
    stub.enqueue(text=raw, content_type="application/json")
    log = _Observer()
    question = {"q": choice("Choose.", {"a": None, "b": None})}
    if asynchronous:

        async def run():
            backend = AsyncHTTPDecisionBackend(
                endpoint=stub.base_url + "/v1/systemone", model="fixture", observer=log
            )
            try:
                with pytest.raises(ValueError):
                    await backend.predict(
                        DecisionRequest("public", question, timeout=2)
                    )
            finally:
                await backend.close()

        asyncio.run(run())
    else:
        backend = HTTPDecisionBackend(
            endpoint=stub.base_url + "/v1/systemone", model="fixture", observer=log
        )
        try:
            with pytest.raises(ValueError):
                backend.predict(DecisionRequest("public", question, timeout=2))
        finally:
            backend.close()
    assert len(stub.hits) == len(log.receipts) == 1
    assert log.receipts[0].error == "invalid_json"


def test_hosted_ambiguous_outer_billing_unknown_but_inner_answer_failure_paid():
    backend = HTTPDecisionBackend(
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        model="fixture",
        mode="chat",
        hosted=True,
        api_key="public-unit-fixture",
    )
    request = DecisionRequest(
        "public", {"q": choice("Choose.", {"a": None, "b": None})}
    )
    body = backend._body(request)
    try:
        ambiguous = httpx.Response(502, content=b'{"usage":{"cost":100,"cost":0}}')
        receipt = backend._receipt(
            "fixture", body, time.perf_counter(), ambiguous, "BackendHTTPError"
        )
        assert (
            receipt.error == "invalid_json"
            and receipt.cost_status == "unknown"
            and receipt.cost_usd is None
        )
        paid = httpx.Response(
            200,
            json={
                "usage": {"cost": "0.00125"},
                "choices": [
                    {
                        "message": {
                            "content": '{"answers":{"q":{"value":"a","value":"b"}}}'
                        }
                    }
                ],
            },
        )
        receipt = backend._receipt("paid", body, time.perf_counter(), paid)
        with pytest.raises(ValueError):
            backend._decode(paid, request, receipt)
        assert receipt.cost_status == "reported" and receipt.cost_usd == "0.00125"
        deep_invalid = (
            '{"nested":' * 2000 + '{"duplicate":0,"duplicate":1}' + "}" * 2000
        )
        outer = httpx.Response(200, content=deep_invalid.encode())
        unknown = backend._receipt("deep-outer", body, time.perf_counter(), outer)
        assert (
            unknown.error == "invalid_json"
            and unknown.cost_status == "unknown"
            and unknown.cost_usd is None
        )
        inner = httpx.Response(
            200,
            json={
                "usage": {"cost": "0.00125"},
                "choices": [{"message": {"content": deep_invalid}}],
            },
        )
        paid_inner = backend._receipt("deep-inner", body, time.perf_counter(), inner)
        with pytest.raises(ValueError):
            backend._decode(inner, request, paid_inner)
        assert paid_inner.cost_status == "reported" and paid_inner.cost_usd == "0.00125"
    finally:
        backend.close()


def test_appended_semantics_positional_api_baselines_and_real_native_unknown(stub):
    prediction = DecisionPrediction(
        "choice", "a", {"a": 1}, 1.0, "source", "confidence", 4
    )
    assert (
        prediction.probability_semantics is None
        and asdict(prediction)["probability_rounding_digits"] == 4
    )
    question = {"q": choice("Choose.", {"a": None, "b": None})}
    assert (
        PriorBackend()
        .predict(DecisionRequest("x", question))
        .predictions["q"]
        .probability_semantics
        == "uniform_reference_distribution"
    )
    assert (
        PriorBackend({"q": {"a": 0.7, "b": 0.3}})
        .predict(DecisionRequest("x", question))
        .predictions["q"]
        .probability_semantics
        == "training_label_frequency"
    )
    bayes = make_synthetic_dataset("bayes", n=1).examples[0]
    assert (
        RuleDecisionBackend("bayes")
        .predict(DecisionRequest(bayes.state, bayes.questions))
        .predictions["decision"]
        .probability_semantics
        == "analytical_conditional_probability"
    )
    for meaning in (None, "normalized_label_compatibility_distribution"):
        stub.enqueue(
            body={
                "model": "fixture",
                "usage": {},
                "answers": {
                    "q": {
                        "type": "choice",
                        "choice": "a",
                        "confidence": 0.7,
                        "probabilities": {"a": 0.7, "b": 0.3},
                    }
                },
            }
        )
        backend = HTTPDecisionBackend(
            endpoint=stub.base_url + "/v1/systemone",
            model="fixture",
            capabilities=BackendCapabilities(probability_semantics=meaning),
        )
        try:
            result = backend.predict(DecisionRequest("x", question, timeout=2))
        finally:
            backend.close()
        assert result.predictions["q"].probability_semantics == meaning


@pytest.mark.parametrize("bad", [True, {}, "", "  ", 3])
def test_probability_semantics_rejects_invalid_values_before_prediction(bad):
    with pytest.raises(ValueError, match="probability_semantics"):
        BackendCapabilities(probability_semantics=bad)
    with pytest.raises(ValueError, match="probability_semantics"):
        DecisionPrediction("choice", "a", probability_semantics=bad)


def test_pilot_matched_sampling_preserves_complete_groups():
    from daf_jev.benchmark_datasets import pilot_samples

    full = make_synthetic_dataset("categorical", n=35, matched_option_permutations=True)
    selected = pilot_samples(full, per_class=1, seed=18)
    loaded = prepared_dataset_from_dict(selected.to_dict())
    assert len(loaded.examples) < len(full.examples)
    for group_id in {e.group_id for e in loaded.examples}:
        members = [e for e in loaded.examples if e.group_id == group_id]
        assert len(members) == 3
        assert {e.metadata["permutation_index"] for e in members} == {0, 1, 2}
    assert (
        selected.manifest.metadata["pilot"]["sampling_unit"]
        == "complete matched base-fixture group"
    )


def test_probability_meaning_serialization_journal_report_and_replay(tmp_path):
    from daf_jev.benchmark_policies import replay_policy

    path = tmp_path / "data.json"
    save_dataset(make_synthetic_dataset("categorical", n=6), path)
    config = {
        "format": "dafjev.benchmark-run/1",
        "sampling": "all",
        "timing_samples": 1,
        "timing_repetitions": 1,
        "capability_probes": False,
        "datasets": [{"path": path.name}],
        "backends": [{"id": "uniform", "kind": "uniform"}],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    store = plan_run(config_path, tmp_path / "runs")
    report = execute_run(store.directory)
    meanings = {
        prediction["probability_semantics"]
        for event in store.events()
        if event.get("event") == "cell_finished"
        for prediction in event["predictions"].values()
    }
    assert meanings == {"uniform_reference_distribution"}
    rows = report["cohorts"][0]["rows"]
    assert all(
        row["probability_semantics"] == "uniform_reference_distribution" for row in rows
    )
    assert report["cohorts"][0]["metrics"]["probability_meaning_summary"] == {
        "declared": ["uniform_reference_distribution"],
        "unknown_distributions": 0,
    }
    weak = {**rows[0], "backend_id": "weak", "confidence": 0.1}
    strong = {
        **weak,
        "backend_id": "strong",
        "confidence": 0.9,
        "probability_source": "classifier",
        "probability_semantics": "estimated_class_probability",
    }
    replayed = replay_policy(
        [weak], policy="cascade", threshold=0.8, strong_rows=[strong]
    )[0]
    assert replayed["probability_semantics"] == "estimated_class_probability"
    assert (
        replayed["weak_backend_id"] == "weak"
        and replayed["strong_backend_id"] == "strong"
    )


def test_legacy_manifest_missing_timing_scope_reports_per_dataset_without_replanning(
    tmp_path,
):
    from daf_jev.benchmark_runner import report_run
    from daf_jev.benchmark_store import RunStore
    from daf_jev.decision_backends import canonical_json

    source = tmp_path / "data.json"
    save_dataset(make_synthetic_dataset("categorical", n=6), source)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "format": "dafjev.benchmark-run/1",
                "sampling": "all",
                "timing_samples": 1,
                "timing_repetitions": 1,
                "capability_probes": False,
                "datasets": [{"path": source.name}],
                "backends": [{"id": "u", "kind": "uniform"}],
            }
        )
    )
    planned = plan_run(config, tmp_path / "new")
    manifest = json.loads(canonical_json(planned.manifest))
    manifest["protocol"].pop("timing_sampling_scope")
    manifest["protocol"].pop("timing_sample_pack")
    legacy = RunStore.create(tmp_path / "legacy", manifest)
    (legacy.directory / "inputs").mkdir()
    for dataset in legacy.manifest["datasets"]:
        (legacy.directory / dataset["file"]).write_bytes(
            (planned.directory / dataset["file"]).read_bytes()
        )
    before = {
        name: (legacy.directory / name).read_bytes()
        for name in ("manifest.json", "events.jsonl", "head.json")
    }
    report = report_run(legacy)
    assert (
        report["timing_sampling_scope"] == "per_dataset"
        and report["timing_sample_pack"] is None
    )
    assert report["planned_cells"] == len(manifest["cells"])
    assert report["denominators"] == {"unattempted": len(manifest["cells"])}
    assert before == {name: (legacy.directory / name).read_bytes() for name in before}


def test_exact100_plan_holds_before_artifact_creation_if_pool_insufficient(tmp_path):
    source = tmp_path / "data.json"
    save_dataset(make_synthetic_dataset("binary", n=120), source)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "format": "dafjev.benchmark-run/1",
                "sampling": "all",
                "datasets": [{"path": source.name}],
                "backends": [{"id": "u", "kind": "uniform"}],
            }
        )
    )
    output = tmp_path / "runs"
    with pytest.raises(ValueError, match=r"requires 100.*available 24"):
        plan_run(config, output)
    assert not output.exists()
