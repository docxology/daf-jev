"""Offline independent-target dataset and split-custody scenarios."""

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from daf_jev.benchmark_datasets import (
    BenchmarkDataset,
    BenchmarkExample,
    DatasetManifest,
    dataset_fold_pack,
    dataset_view,
    fetch_dataset,
    load_dataset,
    load_prepared_dataset,
    make_synthetic_dataset,
    pilot_samples,
    prepared_dataset_from_dict,
    save_dataset,
)
from daf_jev.primitives import choice, noul, score


@pytest.mark.parametrize("kind", ["binary", "categorical", "ordinal", "bayes"])
def test_synthetic_repeatability_and_independent_truth(kind):
    dataset = make_synthetic_dataset(kind, seed=19, n=35)
    assert dataset.to_dict() == make_synthetic_dataset(kind, seed=19, n=35).to_dict()
    assert dataset.to_dict() != make_synthetic_dataset(kind, seed=20, n=35).to_dict()
    assert {e.split for e in dataset.examples} == {"train", "validation", "test"}
    assert dataset.manifest.metadata["target_semantics"] in {"exact rule", "analytical posterior"}
    if kind == "bayes":
        for e in dataset.examples:
            state = json.loads(e.state)
            prior = state["prior_true"]
            lt = state["p_observation_true_given_true"]
            lf = state["p_observation_true_given_false"]
            if not state["observation"]:
                lt, lf = 1 - lt, 1 - lf
            assert e.targets["decision"]["true"] == pytest.approx(prior * lt / (prior * lt + (1 - prior) * lf))
    with pytest.raises(TypeError):
        dataset.manifest.metadata["seed"] = 0
    with pytest.raises(TypeError):
        dataset.examples[0].targets["decision"] = "fabricated"


def test_prepared_roundtrip_and_tamper_detection(tmp_path):
    original = make_synthetic_dataset("ordinal", seed=4, n=13)
    path = save_dataset(original, tmp_path / "dataset.json")
    assert load_prepared_dataset(path).to_dict() == original.to_dict()
    assert prepared_dataset_from_dict(json.loads(path.read_bytes())).to_dict() == original.to_dict()
    with pytest.raises(FileExistsError):
        save_dataset(original, path)
    payload = json.loads(path.read_text())
    payload["examples"][0]["targets"]["decision"] = 27
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="checksum"):
        load_prepared_dataset(path)
    with pytest.raises(ValueError, match="object"):
        prepared_dataset_from_dict([])


@pytest.mark.parametrize("kind", ["binary", "categorical", "ordinal", "bayes"])
def test_examples_digest_matches_prior_whole_array_canonical_bytes(kind):
    dataset = make_synthetic_dataset(kind, seed=20261007, n=33)
    # This is the pre-existing public canonical-array contract, independently
    # encoded as a whole in a small fixture. Streaming must retain exact bytes.
    payload = dataset.to_dict()
    payload["examples"][0]["metadata"]["unicode_note"] = "naïve café — 東京"
    reference = json.dumps(payload["examples"], sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    payload["manifest"]["metadata"]["examples_sha256"] = hashlib.sha256(reference).hexdigest()
    payload["manifest"]["metadata"]["order_sensitive_examples_sha256"] = hashlib.sha256(json.dumps(payload["examples"], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    loaded = prepared_dataset_from_dict(payload)
    assert loaded.manifest.metadata["examples_sha256"] == hashlib.sha256(reference).hexdigest()
    assert loaded.to_dict() == payload
    original_reference = json.dumps(dataset.to_dict()["examples"], sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert dataset.manifest.metadata["examples_sha256"] == hashlib.sha256(original_reference).hexdigest()


def test_prepared_question_sharing_preserves_order_request_bytes_and_mutation_guards():
    original = make_synthetic_dataset("categorical", seed=21, n=3)
    payload = original.to_dict()
    definition = {"type": "choice", "instructions": "Choose among café, account and technical.",
                  "criteria": {"billing": "café", "account": "account", "technical": "technical"}}
    rotated = {**definition, "criteria": {"technical": "technical", "billing": "café", "account": "account"}}
    payload["examples"][0]["questions"] = {"decision": definition}
    payload["examples"][1]["questions"] = {"decision": json.loads(json.dumps(definition))}
    payload["examples"][2]["questions"] = {"decision": rotated}
    payload["manifest"]["metadata"]["examples_sha256"] = hashlib.sha256(json.dumps(
        payload["examples"], sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    payload["manifest"]["metadata"]["order_sensitive_examples_sha256"] = hashlib.sha256(json.dumps(payload["examples"], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    loaded = prepared_dataset_from_dict(payload)
    first, repeated, other_order = [e.questions["decision"] for e in loaded.examples]
    assert first is repeated
    assert first is not other_order
    assert list(first.criteria) == ["billing", "account", "technical"]
    assert list(other_order.criteria) == ["technical", "billing", "account"]
    for example, raw in zip(loaded.examples, payload["examples"], strict=True):
        assert json.dumps(example.questions["decision"].to_wire(), ensure_ascii=False) == json.dumps(
            raw["questions"]["decision"], ensure_ascii=False)
    with pytest.raises(TypeError):
        first.criteria["billing"] = "changed"
    definition["criteria"]["billing"] = "input mutated after validation"
    assert first.criteria["billing"] == repeated.criteria["billing"] == "café"
    wire = first.to_wire()
    wire["criteria"]["billing"] = "output mutated"
    assert repeated.criteria["billing"] == "café"
    # A malformed row still validates independently rather than borrowing an
    # earlier valid question (tuple/list JSON equivalence must not bypass it).
    malformed = original.to_dict()
    malformed["examples"][1]["questions"]["decision"] = {"type": "score", "instructions": "levels", "criteria": ("low", "high")}
    with pytest.raises(ValueError, match="must be a list"):
        prepared_dataset_from_dict(malformed)


@pytest.mark.parametrize("question", [choice("route", {"left": "l", "right": "r"}),
    score("rate", ["low", "high"]), noul("approve", true_desc="yes", false_desc="no")])
def test_direct_example_copies_and_freezes_question_criteria(question):
    before = question.to_wire()
    example = BenchmarkExample("one", "one", "test", "state", {"decision": question}, {"decision": 0})
    retained = example.questions["decision"]
    assert retained.to_wire() == before
    if isinstance(question.criteria, dict):
        key = next(iter(question.criteria))
        question.criteria[key] = "original mutated"
        with pytest.raises(TypeError):
            retained.criteria[key] = "retained mutated"
    else:
        question.criteria[0] = "original mutated"
        with pytest.raises(TypeError):
            retained.criteria[0] = "retained mutated"
    assert retained.to_wire() == before


def _bank_fixture(root: Path):
    root.mkdir()
    (root / "categories.json").write_text(json.dumps(["card_arrival", "cash_withdrawal"]))
    for split in ("train", "test"):
        with (root / f"{split}.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["text", "category"])
            for label in ("card_arrival", "cash_withdrawal"):
                for i in range(15):
                    writer.writerow([f"{split} {label} request {i}", label])
            writer.writerow([" Duplicate Shared Text ", "card_arrival"])
            if split == "test":
                writer.writerow(["duplicate shared text", "card_arrival"])


def test_banking_group_split_preserves_official_test_duplicates(tmp_path):
    pytest.importorskip("sklearn")
    root = tmp_path / "bank"
    _bank_fixture(root)
    dataset = load_dataset(root, kind="banking77", seed=11)
    assert dataset.manifest.metadata["official_bytes_verified"] is False
    assert dataset.manifest.metadata["cross_split_duplicates_excluded"] == 0
    assert dataset.manifest.metadata["source_counts"] == {"train.csv": 31, "test.csv": 32}
    assert dataset.manifest.metadata["canonical_retained_rows"] == len(dataset.examples) == 63
    test = [e for e in dataset.examples if e.split == "test"]
    assert len(test) == 32
    duplicate = [e for e in test if e.metadata["duplicate_group"]]
    assert len(duplicate) == 2
    assert not any(e.metadata["duplicate_sensitivity_cohort"] for e in duplicate)
    groups = {}
    for e in dataset.examples:
        groups.setdefault(e.group_id, set()).add(e.split)
    assert sum(len(splits) > 1 for splits in groups.values()) == 1
    assert dataset.manifest.metadata["cross_split_duplicate_groups"] == 1
    assert dataset.to_dict() == load_dataset(root, kind="banking77", seed=11).to_dict()
    pilot = pilot_samples(dataset, per_class=5, seed=3)
    assert pilot.manifest.labels == dataset.manifest.labels
    assert max(pilot.manifest.metadata["split_counts"].values()) <= 10


def test_banking_all_rotations_and_final_training_preserve_original_wire_and_test(tmp_path):
    pytest.importorskip("sklearn")
    root = tmp_path / "bank"
    _bank_fixture(root)
    original = load_dataset(root, kind="banking77", seed=11)
    pack = dataset_fold_pack(original)
    assert pack == dataset_fold_pack(load_prepared_dataset(save_dataset(original, tmp_path / "full.json")))
    assert pack["seed"] == 11 and pack["algorithm_version"] == 1
    assert set(row["fold_index"] for row in pack["assignments"] if row["official_split"] == "train") == set(range(5))
    held = original.to_dict()
    source = {example.id: example for example in original.examples}
    validations = []
    for fold in range(5):
        selected = dataset_view(original, view="selection", validation_fold=fold)
        assert not any(example.split == "test" for example in selected.examples)
        assert len(selected.examples) == 31
        assert selected.manifest.metadata["view_projection"]["omitted_test_rows"] == 32
        validations.extend(example.id for example in selected.examples if example.split == "validation")
        evaluated = dataset_view(original, validation_fold=fold)
        assert {example.id for example in evaluated.examples if example.split == "test"} == {key for key, example in source.items() if example.metadata["official_split"] == "test"}
        for example in selected.examples:
            assert example.state == source[example.id].state
            assert example.targets == source[example.id].targets
            assert example.questions["decision"] is source[example.id].questions["decision"]
            assert list(example.questions["decision"].criteria) == list(source[example.id].questions["decision"].criteria)
    assert len(validations) == len(set(validations)) == 31
    assert set(validations) == {example.id for example in original.examples if example.metadata["official_split"] == "train"}
    final = dataset_view(original, view="final_train")
    assert len([example for example in final.examples if example.split == "train"]) == 31
    assert len([example for example in final.examples if example.split == "test"]) == 32
    assert not any(example.split == "validation" for example in final.examples)
    assert final.manifest.metadata["policy_validation_available"] is False
    assert original.to_dict() == held
    with pytest.raises(ValueError, match="complete original"):
        dataset_fold_pack(selected)
    with pytest.raises(ValueError, match="complete original"):
        dataset_view(selected)


def test_separately_prepared_leakage_clean_training_removes_overlapping_groups(tmp_path):
    pytest.importorskip("sklearn")
    root = tmp_path / "bank"
    _bank_fixture(root)
    original = load_dataset(root, kind="banking77", seed=11)
    canonical = dataset_view(original, view="final_train")
    clean = dataset_view(original, view="final_train", cohort="leakage_clean")
    assert len(canonical.examples) == 63 and len(clean.examples) == 60
    assert clean.manifest.metadata["view_projection"]["excluded_rows"] == 3
    assert canonical.manifest.sha256 != clean.manifest.sha256
    assert len([example for example in clean.examples if example.split == "train"]) == 30
    assert len([example for example in clean.examples if example.split == "test"]) == 30
    assert not ({example.group_id for example in clean.examples if example.split == "train"} &
                {example.group_id for example in clean.examples if example.split == "test"})
    assert clean.manifest.labels == canonical.manifest.labels
    assert load_prepared_dataset(save_dataset(clean, tmp_path / "clean.json")).to_dict() == clean.to_dict()


def test_clinc_selection_and_final_train_do_not_reuse_merged_validation_for_policy(tmp_path):
    payload = {"train": [["shared", "account"], ["ordinary train", "account"]],
        "val": [["shared", "account"], ["ordinary validation", "account"]],
        "test": [["shared", "account"], ["test independent", "account"]],
        "oos_train": [["unsupported train", "oos"]], "oos_val": [["unsupported validation", "oos"]],
        "oos_test": [["unsupported test", "oos"]]}
    path = tmp_path / "data_full.json"
    path.write_text(json.dumps(payload))
    original = load_dataset(path, kind="clinc150")
    selection = dataset_view(original, view="selection")
    assert len(selection.examples) == 6 and all(example.split != "test" for example in selection.examples)
    final = dataset_view(original, view="final_train")
    assert final.manifest.metadata["split_counts"] == {"train": 6, "test": 3}
    assert final.manifest.metadata["policy_validation_available"] is False
    clean = dataset_view(original, view="final_train", cohort="leakage_clean")
    assert clean.manifest.metadata["split_counts"] == {"train": 4, "test": 2}
    assert {example.targets["decision"] for example in clean.examples} == {"account", "oos"}
    # Once test is omitted, the repeated training/validation input still cannot
    # cross a leakage-clean selection boundary.
    clean_selection = dataset_view(original, view="selection", cohort="leakage_clean")
    assert len(clean_selection.examples) == 4
    with pytest.raises(ValueError, match="published validation"):
        dataset_view(original, validation_fold=1)


def test_fold_metadata_missing_or_ambiguous_refuses_rotation(tmp_path):
    pytest.importorskip("sklearn")
    root = tmp_path / "bank"
    _bank_fixture(root)
    original = load_dataset(root, kind="banking77", seed=11)
    metadata = original.manifest.to_dict()["metadata"]
    metadata.pop("fold_algorithm_version")
    legacy = BenchmarkDataset(replace(original.manifest, metadata=metadata), original.examples)
    with pytest.raises(ValueError, match="re-prepare"):
        dataset_view(legacy)
    first = next(example for example in original.examples if example.metadata["official_split"] == "train")
    bad = replace(first, metadata={**first.metadata, "fold_index": True})
    damaged = BenchmarkDataset(original.manifest, tuple(bad if example.id == first.id else example for example in original.examples))
    with pytest.raises(ValueError, match="integer"):
        dataset_fold_pack(damaged)
    for kwargs, message in [({"view": "unknown"}, "view must"), ({"cohort": "deduplicate"}, "cohort must"),
                            ({"validation_fold": True}, "integer"), ({"test_fold": 1}, "official intent")]:
        with pytest.raises(ValueError, match=message):
            dataset_view(original, **kwargs)
    with pytest.raises(ValueError, match="only"):
        dataset_fold_pack(make_synthetic_dataset(n=3))


def test_fold_inventory_rejects_crossfold_groups_and_malformed_source_metadata(tmp_path):
    pytest.importorskip("sklearn")
    root = tmp_path / "bank"
    _bank_fixture(root)
    original = load_dataset(root, kind="banking77", seed=11)
    for update, message in [({"source_counts": {"train.csv": True}}, "integer source counts"),
                            ({"source_counts": {"train.csv": 1}}, "complete original"),
                            ({"split_seed": True}, "integer seed"),
                            ({"fold_algorithm": {}}, "explicit algorithm"),
                            ({"fold_algorithm_version": True}, "re-prepare")]:
        bad = BenchmarkDataset(replace(original.manifest, metadata={**original.manifest.metadata, **update}), original.examples)
        with pytest.raises(ValueError, match=message):
            dataset_fold_pack(bad)
    first = next(example for example in original.examples if example.metadata["official_split"] == "train")
    clone = replace(first, id="cloned-original-training-row", metadata={**first.metadata, "fold_index": (first.metadata["fold_index"] + 1) % 5})
    extra = BenchmarkDataset(replace(original.manifest, metadata={**original.manifest.metadata,
        "source_counts": {"train.csv": 32, "test.csv": 32}}), (*original.examples, clone))
    with pytest.raises(ValueError, match="crosses folds"):
        dataset_fold_pack(extra)
    for update, message in [({"official_split": {}}, "official split"), ({"official_split": "test", "fold_index": 0}, "must not have")]:
        changed = replace(first, metadata={**first.metadata, **update})
        damaged = BenchmarkDataset(original.manifest, tuple(changed if example.id == first.id else example for example in original.examples))
        with pytest.raises(ValueError, match=message):
            dataset_fold_pack(damaged)


@pytest.mark.parametrize("kind", ["binary", "categorical", "ordinal", "bayes"])
def test_streamed_prepared_output_is_byte_identical_to_full_json_encoding(tmp_path, kind):
    dataset = make_synthetic_dataset(kind, seed=17, n=8)
    reference = (json.dumps(dataset.to_dict(), indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    assert save_dataset(dataset, tmp_path / "streamed.json").read_bytes() == reference


@pytest.mark.parametrize("kind", ["binary", "categorical", "ordinal", "bayes"])
def test_packed_expansion_preserves_each_native_body_and_independent_target(tmp_path, stub, kind):
    from daf_jev.decision_backends import DecisionRequest, HTTPDecisionBackend
    original = make_synthetic_dataset(kind, seed=17, n=8)
    inline = save_dataset(original, tmp_path / "inline.json")
    packed = save_dataset(original, tmp_path / "packed.json", packed=True)
    payload = json.loads(packed.read_bytes())
    assert payload["format"] == "dafjev.benchmark-dataset/2"
    assert all("questions" not in row for row in payload["examples"])
    expanded = load_prepared_dataset(packed)
    assert expanded.to_dict() == original.to_dict() == load_prepared_dataset(inline).to_dict()
    assert len(payload["question_sets"]) <= 3
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/native", model="keyless-fixture")
    try:
        for first, second in zip(original.examples, expanded.examples, strict=True):
            assert first.targets == second.targets and first.group_id == second.group_id and first.split == second.split
            wire = first.questions["decision"].to_wire()
            answer = {"type": wire["type"],
                ("choice" if wire["type"] == "choice" else "score" if wire["type"] == "score" else "noul"):
                next(iter(wire["criteria"])) if wire["type"] == "choice" else .5}
            if wire["type"] != "noul":
                options = list(wire["criteria"]) if wire["type"] == "choice" else [str(i) for i in range(len(wire["criteria"]))]
                answer.update(probabilities={key: float(index == 0) for index, key in enumerate(options)}, confidence=1.)
            if wire["type"] == "score":
                answer["legend"] = {str(i): value for i, value in enumerate(wire["criteria"])}
            for example in (first, second):
                stub.enqueue(body={"model": "keyless-fixture", "answers": {"decision": answer}, "usage": {}})
                backend.predict(DecisionRequest(example.state, example.questions))
            assert stub.hits[-2]["body"] == stub.hits[-1]["body"]
    finally:
        backend.close()


def test_packed_preserves_unicode_object_state_and_question_and_option_order(tmp_path):
    questions = {"日本": choice("café?", {"z": "末", "a": "先"}),
                 "λ": choice("再び?", {"a": "先", "z": "末"})}
    examples = (BenchmarkExample("first", "one", "test", {"z": ["東京", 2], "a": "café"}, questions,
                                 {"日本": "z", "λ": "a"}),
                BenchmarkExample("second", "two", "validation", "λ", dict(reversed(list(questions.items()))),
                                 {"λ": "a", "日本": "z"}))
    dataset = BenchmarkDataset(DatasetManifest("fixture", "1", "owned fixture", "MIT", "a" * 64,
                                              "categorical", ("z", "a")), examples)
    path = save_dataset(dataset, tmp_path / "packed.json", packed=True)
    payload = json.loads(path.read_bytes())
    assert len(payload["question_sets"]) == 2
    loaded = load_prepared_dataset(path)
    assert loaded.to_dict() == dataset.to_dict()
    assert list(loaded.examples[0].questions) == ["日本", "λ"]
    assert list(loaded.examples[1].questions) == ["λ", "日本"]
    assert list(loaded.examples[0].questions["日本"].criteria) == ["z", "a"]
    assert list(loaded.examples[0].state) == ["z", "a"]
    with pytest.raises(TypeError):
        loaded.examples[0].questions["日本"].criteria["z"] = "mutated"
    # Format two also protects order for real/programmatic inputs without a
    # synthetic-v3 manifest. A canonical sorted hash alone cannot do this.
    payload["question_sets"][0]["日本"]["criteria"] = {"a": "先", "z": "末"}
    with pytest.raises(ValueError, match="ordered examples checksum"):
        prepared_dataset_from_dict(payload)


@pytest.mark.parametrize("reference", [True, False, -1, 999, 0.0, "0", None, {}, []])
def test_packed_malformed_question_reference_refuses_without_fallback(tmp_path, reference):
    path = save_dataset(make_synthetic_dataset(n=3), tmp_path / "packed.json", packed=True)
    payload = json.loads(path.read_bytes())
    payload["examples"][0]["questions_ref"] = reference
    with pytest.raises(ValueError, match="questions_ref"):
        prepared_dataset_from_dict(payload)


def test_packed_all_definitions_validate_and_mixed_or_stale_orders_fail(tmp_path):
    original = make_synthetic_dataset("categorical", n=12)
    path = save_dataset(original, tmp_path / "packed.json", packed=True)
    payload = json.loads(path.read_bytes())
    mixed = json.loads(path.read_bytes())
    mixed["examples"][0]["questions"] = original.examples[0].to_dict()["questions"]
    with pytest.raises(ValueError, match="must not mix"):
        prepared_dataset_from_dict(mixed)
    payload["question_sets"].append({"unused": {"type": "choice", "instructions": True, "criteria": {"a": "a"}}})
    with pytest.raises(ValueError, match="instructions"):
        prepared_dataset_from_dict(payload)
    reordered = json.loads(path.read_bytes())
    first = reordered["question_sets"][0]["decision"]
    first["criteria"] = dict(reversed(list(first["criteria"].items())))
    with pytest.raises(ValueError, match="ordered examples checksum"):
        prepared_dataset_from_dict(reordered)
    inline = original.to_dict()
    inline["examples"][0]["questions_ref"] = 0
    with pytest.raises(ValueError, match="inline format"):
        prepared_dataset_from_dict(inline)
    inline["question_sets"] = []
    with pytest.raises(ValueError, match="inline format"):
        prepared_dataset_from_dict(inline)
    for update, message in [({"question_sets": {}}, "must be a list"),
                            ({"question_sets": [{}]}, "nonempty"),
                            ({"examples": {}}, "examples must"),
                            ({"examples": [None]}, "example must"),
                            ({"format": {}}, "expected")]:
        malformed = {**json.loads(path.read_bytes()), **update}
        with pytest.raises(ValueError, match=message):
            prepared_dataset_from_dict(malformed)
    for field in ("expanded_examples_sha256", "order_sensitive_examples_sha256"):
        missing = json.loads(path.read_bytes())
        missing.pop(field)
        with pytest.raises(ValueError, match="checksum"):
            prepared_dataset_from_dict(missing)
    with pytest.raises(ValueError, match="packed must"):
        save_dataset(original, tmp_path / "not-created.json", packed="yes")
    assert not (tmp_path / "not-created.json").exists()


def test_packed_real_fold_views_and_cli_keep_original_rows(tmp_path, capsys):
    pytest.importorskip("sklearn")
    from daf_jev.cli import main
    root = tmp_path / "bank"
    _bank_fixture(root)
    source = tmp_path / "source.json"
    assert main(["benchmark", "dataset", "prepare", "--kind", "banking77", "--source", str(root), "--packed", "--output", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["prepared_format"] == "dafjev.benchmark-dataset/2"
    original = load_prepared_dataset(source)
    target = tmp_path / "final.json"
    assert main(["benchmark", "dataset", "view", "--source", str(source), "--view", "final_train", "--packed", "--output", str(target)]) == 0
    capsys.readouterr()
    final = load_prepared_dataset(target)
    assert len(final.examples) == len(original.examples)
    assert {example.id for example in final.examples if example.split == "test"} == {example.id for example in original.examples if example.split == "test"}
    assert final.manifest.metadata["policy_validation_available"] is False
    assert dataset_fold_pack(original)["source_examples_sha256"] == original.manifest.metadata["examples_sha256"]
    with pytest.raises(ValueError, match="complete original"):
        dataset_view(final)


def test_dataset_cli_fold_inventory_and_selection_view_are_exclusive_offline(tmp_path, capsys):
    pytest.importorskip("sklearn")
    from daf_jev.cli import main
    root = tmp_path / "bank"
    _bank_fixture(root)
    prepared = tmp_path / "prepared.json"
    assert main(["benchmark", "dataset", "prepare", "--kind", "banking77", "--source", str(root), "--output", str(prepared)]) == 0
    capsys.readouterr()
    pack = tmp_path / "folds.json"
    assert main(["benchmark", "dataset", "folds", "--source", str(prepared), "--output", str(pack)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["rows"] == 63 and result["sha256"] == json.loads(pack.read_bytes())["sha256"]
    selected = tmp_path / "selected.json"
    assert main(["benchmark", "dataset", "view", "--source", str(prepared), "--view", "selection", "--validation-fold", "3", "--output", str(selected)]) == 0
    capsys.readouterr()
    assert len(load_prepared_dataset(selected).examples) == 31
    held = pack.read_bytes()
    assert main(["benchmark", "dataset", "folds", "--source", str(prepared), "--output", str(pack)]) == 1
    assert "FileExistsError" in capsys.readouterr().err
    assert pack.read_bytes() == held


def test_clinc_published_splits_and_oos(tmp_path):
    payload = {"train": [["a train utterance", "account"]],
               "val": [["a validation utterance", "account"]],
               "test": [["a test utterance", "account"], ["a test utterance", "account"]],
               "oos_train": [["train unsupported", "oos"]],
               "oos_val": [["validation unsupported", "oos"]],
               "oos_test": [["test unsupported", "oos"]]}
    path = tmp_path / "data_full.json"
    path.write_text(json.dumps(payload))
    dataset = load_dataset(path, kind="clinc150")
    assert dataset.manifest.license == "CC-BY-3.0"
    assert dataset.manifest.labels == ("account", "oos")
    assert [e.split for e in dataset.examples if e.metadata["oos"]] == ["train", "validation", "test"]
    assert sum(e.split == "test" for e in dataset.examples) == 3
    with pytest.raises(ValueError, match="checksum"):
        load_dataset(path, kind="clinc150", expected_sha256="0" * 64)
    payload.pop("oos_test")
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="six"):
        load_dataset(path, kind="clinc150")


def test_clinc_all_official_rows_preserved_with_explicit_leakage_sensitivity(tmp_path):
    payload = {"train": [["shared utterance", "account"]], "val": [],
               "test": [["shared utterance", "account"]], "oos_train": [], "oos_val": [],
               "oos_test": [["SHARED utterance", "oos"]]}
    path = tmp_path / "data_full.json"
    path.write_text(json.dumps(payload))
    dataset = load_dataset(path, kind="clinc150")
    assert len(dataset.examples) == 3
    assert [e.split for e in dataset.examples] == ["train", "test", "test"]
    assert {e.targets["decision"] for e in dataset.examples} == {"account", "oos"}
    assert dataset.manifest.metadata["conflicting_duplicate_groups"] == 1
    assert dataset.manifest.metadata["cross_split_duplicates_excluded"] == 0
    assert dataset.manifest.metadata["source_counts"] == {key: len(rows) for key, rows in payload.items()}
    assert all(not e.metadata["duplicate_sensitivity_cohort"] for e in dataset.examples)
    assert all(e.metadata["cross_split_duplicate_group"] for e in dataset.examples)
    assert all(e.metadata["conflicting_duplicate_group"] for e in dataset.examples)


def test_within_test_duplicates_are_leakage_clean_but_not_unique_input_sensitivity(tmp_path):
    payload = {"train": [], "val": [], "test": [["repeat", "account"], ["REPEAT", "account"]],
               "oos_train": [], "oos_val": [], "oos_test": []}
    path = tmp_path / "data_full.json"
    path.write_text(json.dumps(payload))
    dataset = load_dataset(path, kind="clinc150")
    assert len(dataset.examples) == 2
    assert all(e.metadata["duplicate_sensitivity_cohort"] for e in dataset.examples)
    assert all(not e.metadata["unique_input_sensitivity_cohort"] for e in dataset.examples)


def test_group_cross_split_exception_is_limited_to_declared_official_cohorts():
    synthetic = make_synthetic_dataset(n=2)
    first, second = synthetic.examples
    crossed = (first, replace(second, group_id=first.group_id))
    with pytest.raises(ValueError, match="crosses"):
        BenchmarkDataset(synthetic.manifest, crossed)
    with pytest.raises(ValueError, match="duplicate example"):
        BenchmarkDataset(synthetic.manifest, (first, first))
    manifest = replace(synthetic.manifest, name="banking77", metadata={"cohort": "official_canonical",
                       "cross_split_leakage_declared": True, "cross_split_duplicate_group_ids": []})
    with pytest.raises(ValueError, match="crosses"):
        BenchmarkDataset(manifest, crossed)
    declared = replace(manifest, metadata={**manifest.metadata, "cross_split_duplicate_group_ids": [first.group_id]})
    assert BenchmarkDataset(declared, crossed).examples == crossed


def test_wine_quality_bins_type_and_grouped_folds(tmp_path):
    pytest.importorskip("sklearn")
    columns = ["fixed acidity", "volatile acidity", "citric acid", "residual sugar", "chlorides",
               "free sulfur dioxide", "total sulfur dioxide", "density", "pH", "sulphates", "alcohol", "quality"]
    for wine_type in ("red", "white"):
        with (tmp_path / f"winequality-{wine_type}.csv").open("w", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(columns)
            for grade in (2, 4, 6, 8, 10):
                for i in range(15):
                    writer.writerow([grade + i / 100 + j / 1000 for j in range(11)] + [grade])
    dataset = load_dataset(tmp_path, kind="wine", seed=2)
    assert dataset.manifest.label_kind == "ordinal"
    assert dataset.manifest.metadata["grade_bins"] == ((0, 2), (3, 4), (5, 6), (7, 8), (9, 10))
    assert {e.split for e in dataset.examples} == {"train", "validation", "test"}
    for e in dataset.examples:
        assert e.targets["decision"] == (e.metadata["original_grade"] // 2) - 1
        assert e.metadata["wine_type"] in {"red", "white"}
        assert "quality" not in json.loads(e.state)["features"]
    pilot = pilot_samples(dataset, wine_per_type=10)
    counts = {}
    for e in pilot.examples:
        key = (e.split, e.metadata["wine_type"])
        counts[key] = counts.get(key, 0) + 1
    assert all(n <= 10 for n in counts.values())
    tests = []
    for test_fold in range(5):
        rotated = dataset_view(dataset, test_fold=test_fold, validation_fold=(test_fold + 1) % 5)
        tests.extend(example.id for example in rotated.examples if example.split == "test")
        splits = {}
        for example in rotated.examples:
            assert example.metadata["original_grade"] in (2, 4, 6, 8, 10)
            assert splits.setdefault(example.group_id, example.split) == example.split
    assert len(tests) == len(set(tests)) == len(dataset.examples)
    final = dataset_view(dataset, view="final_train", test_fold=3, validation_fold=4)
    assert not any(example.split == "validation" for example in final.examples)
    assert all((example.split == "test") == (example.metadata["fold_index"] == 3) for example in final.examples)
    with pytest.raises(ValueError, match="must differ"):
        dataset_view(dataset, test_fold=2, validation_fold=2)


def test_dataset_invalid_inputs_never_fetch(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        fetch_dataset("not-a-dataset", tmp_path)
    with pytest.raises(ValueError, match="timeout"):
        fetch_dataset("clinc150", tmp_path, timeout=float("nan"))
    with pytest.raises(ValueError):
        make_synthetic_dataset("unknown")
    with pytest.raises(ValueError):
        make_synthetic_dataset(n=0)
    with pytest.raises(ValueError):
        pilot_samples(make_synthetic_dataset(n=5), per_class=0)


@pytest.mark.parametrize("raw", [
    '{"name":"other","name":"clinc150"}',
    '{"name":"clinc150","files":{"data_full.json":{"sha256":"first","sha256":"last"}}}',
    '{"name":"clinc150","untrusted":NaN}',
    '{"name":"clinc150","untrusted":Infinity}',
])
def test_source_manifest_rejects_ambiguous_json_before_official_binding(tmp_path, raw):
    (tmp_path / "data_full.json").write_text('{"train":[],"val":[],"test":[],"oos_train":[],"oos_val":[],"oos_test":[]}')
    (tmp_path / "source_manifest.json").write_text(raw)
    held = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(ValueError, match=r"duplicate|non-finite JSON constant"):
        load_dataset(tmp_path, kind="clinc150")
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == held


@pytest.mark.parametrize("raw", [
    '{"train":[["first","account"]],"train":[["last","account"]],"val":[],"test":[],"oos_train":[],"oos_val":[],"oos_test":[]}',
    '{"train":[],"val":[],"test":[],"oos_train":[],"oos_val":[],"oos_test":[],"nested":{"label":"first","label":"last"}}',
    '{"train":[],"val":[],"test":[],"oos_train":[],"oos_val":[],"oos_test":[],"untrusted":NaN}',
    '{"train":[],"val":[],"test":[],"oos_train":[],"oos_val":[],"oos_test":[],"untrusted":-Infinity}',
])
def test_clinc_source_rejects_duplicate_split_or_nested_label_and_constants(tmp_path, raw):
    path = tmp_path / "data_full.json"
    path.write_text(raw)
    before = path.read_bytes()
    with pytest.raises(ValueError, match=r"duplicate|non-finite JSON constant"):
        load_dataset(path, kind="clinc150")
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("raw", [
    '[{"label":"card_arrival","label":"cash_withdrawal"}]',
    '[{"label":"card_arrival","la\\u0062el":"cash_withdrawal"}]',
    '["card_arrival",NaN]',
    '["card_arrival",Infinity]',
])
def test_banking_label_source_rejects_ambiguity_before_group_split(tmp_path, raw):
    (tmp_path / "categories.json").write_text(raw)
    for split in ("train", "test"):
        (tmp_path / f"{split}.csv").write_text("text,category\n")
    held = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(ValueError, match=r"duplicate|non-finite JSON constant"):
        load_dataset(tmp_path, kind="banking77")
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == held
