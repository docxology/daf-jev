"""Native billing uncertainty refuses transport without rewriting saved plans."""

import json
import shutil
from contextlib import closing
from decimal import Decimal

import pytest

from daf_jev import choice
from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_runner import _liability, execute_run, plan_run
from daf_jev.benchmark_store import BudgetStopped, RunStore, SpendLedger
from daf_jev.decision_backends import DecisionRequest, HTTPDecisionBackend


def _profile(*, nominal="0.000001", ceiling=None, explicit_mode=True):
    profile = {"id": "native", "kind": "http", "hosted": True,
        "endpoint": "https://openrouter.ai/api/alpha/decisions", "model": "fixture",
        "api_key_env": "DAFJEV_NATIVE_ADMISSION_FIXTURE_KEY", "context_length": 1000,
        "pricing": {"source": "public fixture tariff", "snapshot_at": "2026-10-08T00:00:00Z",
                    "rates": {"prompt": nominal, "completion": "0"}}}
    if explicit_mode:
        profile["mode"] = "systemone"
    if ceiling is not None:
        profile["options"] = {"provider": {"max_price": {"prompt": ceiling, "completion": 0}}}
    return profile


def _plan(tmp_path, profile):
    dataset = tmp_path / "dataset.json"
    save_dataset(make_synthetic_dataset("categorical", seed=13, n=6), dataset)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"format": "dafjev.benchmark-run/1", "seed": 13,
        "budget_usd": "0", "sampling": "all", "timing_samples": 1, "timing_repetitions": 1,
        "capability_probes": False, "timeout_s": 2, "datasets": [{"path": dataset.name}],
        "backends": [profile]}))
    return plan_run(path, tmp_path / "runs")


@pytest.mark.parametrize("explicit_mode", [True, False])
@pytest.mark.parametrize("nominal,ceiling", [("0.000001", None), ("0", 2)])
def test_paid_native_catalog_or_positive_sent_ceiling_refuses_before_http(
        tmp_path, stub, monkeypatch, explicit_mode, nominal, ceiling):
    monkeypatch.setenv("DAFJEV_NATIVE_ADMISSION_FIXTURE_KEY", "public-fixture-placeholder")
    store = _plan(tmp_path, _profile(nominal=nominal, ceiling=ceiling, explicit_mode=explicit_mode))
    frozen = store.manifest["backends"][0]
    assert frozen["liability_usd"] is None
    assert frozen["admission_reason"] == "native_aggregate_billing_unverified"
    original = (store.directory / "manifest.json").read_bytes()

    # Exercise the real HTTP adapter against an owned keyless loopback server.
    # Hosted USD admission is a separate observer contract; no production
    # credential or hosted-origin policy is weakened to create this fixture.
    ledger = SpendLedger(store, limit="25")
    working = json.loads(json.dumps(frozen))
    observer = ledger.observer(cell_id=store.manifest["cells"][0]["id"], hosted=True,
                               liability_usd=_liability(working))
    with closing(HTTPDecisionBackend(endpoint=stub.base_url + "/decisions", model="fixture",
            observer=observer)) as backend, pytest.raises(BudgetStopped, match="unbounded liability"):
        backend.predict(DecisionRequest("owned input", {"decision": choice("Choose.", {"yes": None, "no": None})}))
    assert stub.hits == []
    assert ledger.snapshot()["reserved_usd"] == ledger.snapshot()["reported_cost_usd"] == "0"

    # The full executor and resume retain every denominator and a precise
    # refusal. A zero budget is an additional guard against unintended remote
    # transport if this policy ever regresses; no hosted request is authorized.
    for _ in range(2):
        report = execute_run(store.directory)
        assert report["denominators"] == {"unattempted": len(store.manifest["cells"])}
        assert all(row["reason"] == "native_aggregate_billing_unverified" for row in report["cells"])
        assert report["accounting"]["reported_cost_usd"] == report["accounting"]["reserved_usd"] == "0"
    assert not any(event["event"] in ("attempt_started", "backend_ready") for event in store.events())
    assert (store.directory / "manifest.json").read_bytes() == original


@pytest.mark.parametrize("nominal,ceiling", [("0.000001", None), ("0", 2)])
def test_old_saved_positive_native_liability_cannot_bypass_current_policy(tmp_path, monkeypatch, nominal, ceiling):
    monkeypatch.setenv("DAFJEV_NATIVE_ADMISSION_FIXTURE_KEY", "public-fixture-placeholder")
    planned = _plan(tmp_path, _profile(nominal=nominal, ceiling=ceiling))
    legacy = json.loads(json.dumps(planned.manifest))
    profile = legacy["backends"][0]
    profile["liability_usd"] = "0.002"  # former one-context reservation
    profile.pop("admission_reason")
    # An unverified caller declaration must never become a numeric bypass.
    profile["aggregate_billing_guarantee"] = {"max_tokens": 1, "source": "caller assertion"}
    store = RunStore.create(tmp_path / "legacy-runs", legacy)
    (store.directory / "inputs").mkdir()
    shutil.copyfile(planned.directory / "inputs/dataset-0.json", store.directory / "inputs/dataset-0.json")
    original = (store.directory / "manifest.json").read_bytes()
    for _ in range(2):
        report = execute_run(store.directory)
        assert report["denominators"] == {"unattempted": len(store.manifest["cells"])}
        assert all(row["reason"] == "native_aggregate_billing_unverified" for row in report["cells"])
        assert report["accounting"]["reserved_usd"] == report["accounting"]["reported_cost_usd"] == "0"
    refusals = [event for event in store.events() if event["event"] == "hosted_admission_unavailable"]
    assert refusals and all(event["reason"] == "native_aggregate_billing_unverified" for event in refusals)
    assert not any(event["event"] in ("attempt_started", "backend_ready") for event in store.events())
    assert (store.directory / "manifest.json").read_bytes() == original
    assert store.manifest["backends"][0]["liability_usd"] == "0.002"


def test_free_native_zero_tariffs_and_caps_need_no_unknown_token_bound(tmp_path, stub):
    profile = _profile(nominal="0", ceiling=0)
    profile.pop("context_length")
    store = _plan(tmp_path, profile)
    frozen = store.manifest["backends"][0]
    assert frozen["liability_usd"] == "0" and frozen["admission_reason"] is None
    assert frozen["options"]["provider"] == {"allow_fallbacks": False, "require_parameters": True,
        "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0}}
    stub.enqueue(body={"model": "fixture", "answers": {"decision": {"type": "choice", "choice": "yes",
        "probabilities": {"yes": .75, "no": .25}, "confidence": .75}}, "usage": {}})
    ledger = SpendLedger(store, limit="0")
    with closing(HTTPDecisionBackend(endpoint=stub.base_url + "/decisions", model="fixture",
            options=frozen["options"], observer=ledger.observer(cell_id="local-free-transport",
                hosted=False, liability_usd="0"))) as backend:
        result = backend.predict(DecisionRequest("owned input", {"decision": choice("Choose.", {"yes": None, "no": None})}))
    assert result.predictions["decision"].value == "yes" and len(stub.hits) == 1
    assert "authorization" not in stub.hits[0]["headers"]
    assert stub.hits[0]["json"]["provider"] == frozen["options"]["provider"]
    assert ledger.snapshot()["reserved_usd"] == ledger.snapshot()["reported_cost_usd"] == "0"


def test_chat_context_and_output_price_cap_formula_is_preserved(tmp_path):
    profile = _profile(nominal="0.000001")
    profile.update({"mode": "chat", "endpoint": "https://openrouter.ai/api/v1/chat/completions",
                    "options": {"max_tokens": 20}})
    profile["pricing"]["rates"]["completion"] = "0.000002"
    store = _plan(tmp_path, profile)
    assert Decimal(store.manifest["backends"][0]["liability_usd"]) == Decimal("0.00104")
    assert store.manifest["backends"][0]["admission_reason"] is None


def test_native_charged_output_still_requires_documented_bound(tmp_path):
    profile = _profile(nominal="0")
    profile["pricing"]["rates"]["completion"] = "0.000002"
    store = _plan(tmp_path, profile)
    assert store.manifest["backends"][0]["liability_usd"] is None
    assert store.manifest["backends"][0]["admission_reason"] == "native_output_billing_unbounded"


def test_legacy_cascade_known_paid_native_dependency_refuses_before_weak_http(tmp_path, stub, monkeypatch):
    from daf_jev.benchmark_policies import GateCalibration
    from daf_jev.benchmark_runner import _gate_identity
    from daf_jev.decision_backends import content_hash

    monkeypatch.setenv("DAFJEV_NATIVE_ADMISSION_FIXTURE_KEY", "public-fixture-placeholder")
    planned = _plan(tmp_path, _profile())
    manifest = json.loads(json.dumps(planned.manifest))
    manifest["backends"][0]["liability_usd"] = "0.001"
    manifest["backends"][0].pop("admission_reason")
    manifest["backends"].append({"id": "weak", "kind": "http", "model": "fixture",
                                  "endpoint": stub.base_url + "/weak"})
    calibration = GateCalibration("insufficient_evidence", None, .05, None, 0, 0, 0)
    manifest["backends"].append({"id": "cascade", "kind": "cascade", "hosted": True,
        "weak": "weak", "strong": "native", "gate_evidence": {
            "format": "dafjev.policy-gates/1", "source_manifest_hash": planned.manifest_hash,
            "gates": [{"backend": "weak", "dataset_sha256": manifest["datasets"][0]["manifest"]["sha256"],
                "validation_identity": _gate_identity(manifest, "weak", 0), "calibration": calibration.to_dict()}]}})
    manifest["cells"] = [{**cell, "backend": "cascade", "id": content_hash([
        cell["dataset"], cell["example_id"], "cascade", cell["repeat"]])} for cell in manifest["cells"]]
    store = RunStore.create(tmp_path / "legacy-cascade-runs", manifest)
    (store.directory / "inputs").mkdir()
    shutil.copyfile(planned.directory / "inputs/dataset-0.json", store.directory / "inputs/dataset-0.json")
    original = (store.directory / "manifest.json").read_bytes()
    for _ in range(2):
        report = execute_run(store.directory)
        assert report["denominators"] == {"unattempted": len(store.manifest["cells"])}
        assert all(row["reason"] == "native_aggregate_billing_unverified" for row in report["cells"])
        assert report["accounting"]["reserved_usd"] == report["accounting"]["reported_cost_usd"] == "0"
    assert stub.hits == []
    assert not any(event["event"] in ("attempt_started", "backend_ready") for event in store.events())
    assert (store.directory / "manifest.json").read_bytes() == original
