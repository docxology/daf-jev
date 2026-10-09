"""Perplexity contract preparation: synthetic accounting and keyless loopback only."""

import asyncio
import copy
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from pathlib import Path

import pytest

from daf_jev import choice, noul, score
from daf_jev._yaml import strict_yaml_loads
from daf_jev.benchmark_allocation import AllocationLedger
from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_runner import (
    _liability,
    _native_billing_contract,
    _NativeContractObserver,
    execute_run,
    plan_run,
)
from daf_jev.benchmark_store import BudgetStopped, RunStore, SpendLedger
from daf_jev.decision_backends import (
    AsyncHTTPDecisionBackend,
    BackendCapabilities,
    BackendHTTPError,
    CallReceipt,
    DecisionRequest,
    HTTPDecisionBackend,
    content_hash,
    utc_now,
)

MODEL = "perplexity/pplx-decider-v1.1-27b"
CONTRACT = "openrouter-perplexity-pplx-decider-v1.1-27b-input262143/1"
ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
ROOT = Path(__file__).resolve().parents[2]


def _profile():
    return {"id": "pplx-native", "hosted": True, "kind": "http", "mode": "systemone",
        "model": MODEL, "endpoint": ENDPOINT, "context_length": 262144,
        "api_key_env": "DAFJEV_NATIVE_ADMISSION_FIXTURE_KEY",
        "capabilities": {"max_options": 255, "max_questions": 128, "max_score_levels": 10,
                         "probability_rounding_digits": None},
        "pricing": {"native_billing_contract": CONTRACT, "snapshot_at": "2026-10-09",
            "source": f"https://openrouter.ai/api/v1/models/{MODEL}/endpoints",
            "rates": {"prompt": "0.00000002", "completion": "0", "discount": "0"}},
        "options": {"provider": {"only": ["perplexity"], "allow_fallbacks": False,
            "require_parameters": True, "max_price": {"prompt": .02, "completion": 0,
                                                       "request": 0, "image": 0}}}}


def _plan(tmp_path, profile=None, *, budget="0"):
    save_dataset(make_synthetic_dataset("categorical", seed=13, n=6), tmp_path / "dataset.json")
    allocation = AllocationLedger.create(tmp_path / "fixture-allocation",
                                         allocation_id="public-unit-fixture", limit="25")
    config = {"format": "dafjev.benchmark-run/1", "seed": 13, "budget_usd": budget,
              "shared_allocation": allocation.identity(), "sampling": "all",
              "timing_samples": 1, "timing_repetitions": 1, "capability_probes": False,
              "timeout_s": 2, "datasets": [{"path": "dataset.json"}],
              "backends": [profile or _profile()]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return plan_run(path, tmp_path / "runs")


def _receipt(observer, *, tokens=100, cost=".000002", resolved=MODEL, provider="Perplexity", status=200):
    attempt = observer.before("owned-receipt-hash", MODEL, ENDPOINT)
    return CallReceipt(attempt, utc_now(), ENDPOINT, MODEL, resolved, provider,
        "owned-response", "owned-receipt-hash", .1, status, tokens, 50, cost, "reported")


def test_perplexity_manifest_owns_total_input_bound_independent_of_context(tmp_path):
    profile = _profile()
    profile["context_length"] = 999999999
    profile["artifact"] = {"aggregate_input_tokens": 999999999}
    before = copy.deepcopy(profile)
    with localcontext() as ambient:
        ambient.prec, ambient.rounding, ambient.Emax = 2, ROUND_DOWN, 0
        ambient.traps[Inexact] = True
        store = _plan(tmp_path, profile)
        frozen = store.manifest["backends"][0]
        assert Decimal(frozen["liability_usd"]) == Decimal(".00524286")
        assert ambient.prec == 2 and ambient.traps[Inexact]
    assert profile == before
    contract = frozen["native_billing_contract"]
    assert contract["id"] == CONTRACT and contract["max_input_tokens"] == 262143
    assert contract["input_scope"] == "state, images and all questions"
    assert contract["input_price_usd_per_token"] == "0.00000002"
    assert contract["max_score_levels"] == 10 and contract["max_choice_options"] == 255
    assert tuple(contract["resolved_models"]) == (MODEL, "pplx-decider-v1.1-27b",
                                                 "perplexity/pplx-decider-v1.1-27b-20261006")
    assert contract["resolution_evidence"]["catalog"]["sha256"] == "594c20ac042cd08ee79e6f5fed8a8dd87a50f47a510903115c77cc3097f959be"
    assert contract["provider_tag"] == "perplexity"
    assert frozen["capabilities"]["probability_rounding_digits"] is None
    assert frozen["admission_reason"] is None and store.events() == []


@pytest.mark.parametrize("path,value", [
    (("pricing", "native_billing_contract"), None),
    (("pricing", "native_billing_contract"), CONTRACT + "-caller"),
    (("pricing", "native_billing_contract"), "openrouter-typesafe-jev-1.13-input32000/1"),
    (("model",), "perplexity/pplx-decider"),
    (("model",), "pplx-decider-v1.1-27b"),
    (("model",), "perplexity/pplx-decider-v1.1-27b-20261006"),
    (("model",), "perplexity/pplx-decider-v1-27b"),
    (("endpoint",), "https://openrouter.ai/api/v1/systemone"),
    (("endpoint",), "https://api.perplexity.ai/v1/decisions"),
    (("mode",), "chat"), (("hosted",), False), (("kind",), "cascade"),
    (("pricing", "source"), "caller proof"), (("pricing", "snapshot_at"), ""),
    (("options", "provider", "only"), ["perplexity", "other"]),
    (("options", "provider", "only"), ["typesafe"]),
    (("options", "provider", "allow_fallbacks"), True),
    (("options", "provider", "require_parameters"), False),
    (("options", "provider", "max_price", "prompt"), .019),
    (("options", "provider", "max_price", "prompt"), .021),
    (("options", "provider", "max_price", "completion"), .01),
    (("options", "provider", "max_price", "request"), .01),
    (("options", "provider", "max_price", "image"), .01),
    (("pricing", "rates", "prompt"), "0.000000021"),
    (("pricing", "rates", "completion"), "0.000000001"),
    (("pricing", "rates", "input_cache_read"), "0.00000001"),
    (("pricing", "rates", "input_cache_write"), "0.00000003"),
    (("pricing", "rates", "discount"), "1"),
    (("pricing", "rates", "unknown_surcharge"), "0"),
    (("capabilities", "max_options"), 256),
    (("capabilities", "max_questions"), 129),
    (("capabilities", "max_score_levels"), 11),
    (("capabilities", "max_score_levels"), 10.0),
    (("capabilities", "max_score_levels"), True),
    (("capabilities", "probability_rounding_digits"), 2),
    (("options", "temperature"), 0), (("options", "max_tokens"), 1),
    (("options", "plugins"), []), (("options", "provider", "sort"), "price"),
], ids=[f"contract-defect-{i:02}" for i in range(39)])
def test_perplexity_contract_refuses_unsupported_identity_route_price_or_caps(path, value):
    profile = _profile()
    item = profile
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = value
    before = copy.deepcopy(profile)
    assert _native_billing_contract(profile) is None
    if profile["hosted"]:
        assert _liability(profile) is None
    assert profile == before


@pytest.mark.parametrize("location,key", [
    ("pricing", "native_billing_contract"), ("pricing", "rates"),
    ("rates", "prompt"), ("rates", "completion"), ("options", "provider"),
    ("provider", "max_price"), ("ceilings", "request"),
    ("caps", "max_score_levels"), ("caps", "probability_rounding_digits"),
], ids=[f"missing-field-{i:02}" for i in range(9)])
def test_missing_perplexity_contract_fields_do_not_get_invented(location, key):
    profile = _profile()
    objects = {"pricing": profile["pricing"], "rates": profile["pricing"]["rates"],
        "options": profile["options"], "provider": profile["options"]["provider"],
        "ceilings": profile["options"]["provider"]["max_price"], "caps": profile["capabilities"]}
    objects[location].pop(key)
    assert _native_billing_contract(profile) is None and _liability(profile) is None


@pytest.mark.parametrize("defect", ["missing", "expanded", "changed_price", "changed_ids", "selector", "resolution_proof"],
                         ids=["missing", "expanded", "price", "identities", "selector", "resolution-proof"])
def test_perplexity_frozen_contract_drift_refuses_without_transport(tmp_path, monkeypatch, defect):
    planned = _plan(tmp_path)
    manifest = json.loads(json.dumps(planned.manifest))
    profile = manifest["backends"][0]
    if defect == "missing":
        profile.pop("native_billing_contract")
    elif defect == "expanded":
        profile["native_billing_contract"]["max_input_tokens"] = 262144
    elif defect == "changed_price":
        profile["native_billing_contract"]["input_price_usd_per_token"] = "0.00000003"
    elif defect == "changed_ids":
        profile["native_billing_contract"]["resolved_models"].append("perplexity/alias")
    elif defect == "resolution_proof":
        profile["native_billing_contract"]["resolution_evidence"]["catalog"]["sha256"] = "0" * 64
    else:
        profile["pricing"].pop("native_billing_contract")
    store = RunStore.create(tmp_path / "mutated-fixture", manifest)
    (store.directory / "inputs").mkdir()
    shutil.copyfile(planned.directory / "inputs/dataset-0.json", store.directory / "inputs/dataset-0.json")
    original = (store.directory / "manifest.json").read_bytes()
    monkeypatch.setenv("DAFJEV_NATIVE_ADMISSION_FIXTURE_KEY", "public-unit-placeholder")
    result = execute_run(store.directory)
    assert result["denominators"] == {"unattempted": 4}
    assert {cell["reason"] for cell in result["cells"]} == {"frozen_native_billing_contract_mismatch"}
    assert not any(e["event"] == "attempt_started" for e in store.events())
    assert (store.directory / "manifest.json").read_bytes() == original


@pytest.mark.parametrize("changes,dimension", [
    ({"tokens": 262143, "cost": ".00524286"}, None),
    ({"tokens": 262144, "cost": ".000002"}, "input_tokens"),
    ({"cost": ".000002000000000001"}, "reported_cost"),
    ({"tokens": 0, "cost": ".00000001"}, "reported_cost"),
    ({"tokens": None}, "missing_billed_input_usage"),
    ({"resolved": "perplexity/pplx-decider-v1-27b"}, "resolved_identity"),
    ({"resolved": "perplexity/pplx-decider-v1.1-27b-20261006"}, None),
    ({"resolved": "perplexity/pplx-decider-v1.1-27b-20261007"}, "resolved_identity"),
    ({"resolved": "perplexity/pplx-decider-v1.1-27b-20261006:free"}, "resolved_identity"),
    ({"resolved": None}, "resolved_identity"),
    ({"provider": "other"}, "resolved_identity"),
    ({"provider": None}, "resolved_identity"),
    ({"resolved": "pplx-decider-v1.1-27b", "provider": "perplexity"}, None),
    ({"cost": "0"}, None),
    ({"status": 503, "resolved": None, "provider": None, "cost": "0"}, None),
], ids=[f"receipt-case-{i:02}" for i in range(15)])
def test_perplexity_receipt_first_stop_and_shared_reconciliation(tmp_path, changes, dimension):
    store = _plan(tmp_path, budget="25")
    allocation = AllocationLedger(tmp_path / "fixture-allocation")
    contract = _native_billing_contract(_profile())
    with allocation.execution(store):
        ledger = SpendLedger(store, limit="25", allocation=allocation)
        observer = _NativeContractObserver(ledger.observer(cell_id=store.manifest["cells"][0]["id"],
            hosted=True, liability_usd=".00524286"), ledger, contract)
        receipt = _receipt(observer, **changes)
        with localcontext() as ambient:
            ambient.prec = 2
            ambient.traps[Inexact] = True
            if dimension:
                with pytest.raises(BudgetStopped, match="contract breached"):
                    observer.after(receipt)
                with pytest.raises(BudgetStopped):
                    observer.before("owned-next-hash", MODEL, ENDPOINT)
            else:
                observer.after(receipt)
        rows = store.events()
        assert [e["receipt"] for e in rows if e["event"] == "attempt_finished"] == [receipt.to_dict()]
        rejected = [e for e in rows if e["event"] == "accounting_rejected"]
        assert [e["breach_dimension"] for e in rejected] == ([dimension] if dimension else [])
        snapshot = ledger.snapshot()
        assert Decimal(snapshot["reported_cost_usd"]) == Decimal(receipt.cost_usd)
        assert snapshot["unresolved_attempts"] == [] and Decimal(snapshot["reserved_usd"]) == 0
        assert snapshot["admission_stopped"] is bool(dimension)
    snapshot = AllocationLedger(tmp_path / "fixture-allocation", read_only=True).snapshot()
    assert snapshot["admission_stopped"] is bool(dimension)
    assert ("native_input_contract_breach" in snapshot["stop_reasons"]) is bool(dimension)


@pytest.mark.parametrize("value", [True, False, 0, 1, -1, 10.0, "10"],
                         ids=["true", "false", "zero", "one", "negative", "float", "string"])
def test_score_capability_requires_protocol_compatible_integer(value):
    with pytest.raises(ValueError, match="max_score_levels"):
        BackendCapabilities(max_score_levels=value)


def _answer(question):
    wire = question.to_wire()
    if wire["type"] == "noul":
        return {"type": "noul", "noul": .5}
    criteria = wire["criteria"]
    labels = list(criteria) if wire["type"] == "choice" else [str(i) for i in range(len(criteria))]
    result = {"type": wire["type"], "probabilities": {key: float(i == 0) for i, key in enumerate(labels)},
              "confidence": .5}
    if wire["type"] == "choice":
        result["choice"] = labels[0]
    else:
        result.update({"score": 0, "legend": dict(zip(labels, criteria, strict=True))})
    return result


@pytest.mark.parametrize("kind,size", [("choice", 77), ("choice", 151), ("choice", 255),
                                      ("score", 5), ("score", 10), ("questions", 128)],
                         ids=["banking77", "clinc151", "choice255", "wine5", "score10", "questions128"])
def test_keyless_native_wire_preserves_complete_vocabularies_and_limits(tmp_path, stub, kind, size):
    caps = BackendCapabilities(**_profile()["capabilities"])
    questions = ({"decision": choice("Choose.", {f"option-{i:03}": None for i in range(size)})}
                 if kind == "choice" else {"decision": score("Level?", [f"level-{i}" for i in range(size)])}
                 if kind == "score" else {f"question-{i}": noul("Condition?") for i in range(size)})
    stub.enqueue(body={"model": MODEL, "provider": "Perplexity",
        "answers": {key: _answer(q) for key, q in questions.items()},
        "usage": {"input_tokens": 262143, "output_tokens": 50}})
    store = RunStore.create(tmp_path / "loopback", {"fixture": "keyless native limits"})
    ledger = SpendLedger(store)
    observer = _NativeContractObserver(ledger.observer(cell_id="loopback", hosted=False, liability_usd="0"),
                                       ledger, _native_billing_contract(_profile()))
    with closing(HTTPDecisionBackend(endpoint=stub.base_url + "/api/alpha/decisions", model=MODEL,
            capabilities=caps, options=_profile()["options"], observer=observer)) as backend:
        result = backend.predict(DecisionRequest("owned fixture input", questions))
    assert len(stub.hits) == 1 and "authorization" not in stub.hits[0]["headers"]
    assert stub.hits[0]["json"]["questions"] == {key: q.to_wire() for key, q in questions.items()}
    assert stub.hits[0]["json"]["provider"] == _profile()["options"]["provider"]
    assert set(result.predictions) == set(questions)
    assert all(p.probability_semantics is None for p in result.predictions.values())
    assert len(result.receipts) == 1 and result.receipts[0].input_tokens == 262143
    assert result.receipts[0].request_hash == content_hash(stub.hits[0]["json"])
    assert ledger.snapshot()["admission_stopped"] is False


@pytest.mark.parametrize("kind,size,error", [("choice", 256, "option count"),
    ("score", 11, "score level count"), ("questions", 129, "question count")],
    ids=["choice256", "score11", "questions129"])
def test_native_over_limit_requests_refuse_before_transport_and_reservation(tmp_path, stub, kind, size, error):
    questions = ({"decision": choice("Choose.", {f"option-{i}": None for i in range(size)})}
                 if kind == "choice" else {"decision": score("Level?", [f"level-{i}" for i in range(size)])}
                 if kind == "score" else {f"question-{i}": noul("Condition?") for i in range(size)})
    store = RunStore.create(tmp_path / "loopback", {"fixture": "over-limit request"})
    ledger = SpendLedger(store)
    with closing(HTTPDecisionBackend(endpoint=stub.base_url + "/decisions", model=MODEL,
            capabilities=BackendCapabilities(**_profile()["capabilities"]),
            observer=ledger.observer(cell_id="loopback", hosted=False, liability_usd="0"))) as backend, pytest.raises(ValueError, match=error):
        backend.predict(DecisionRequest("owned fixture input", questions))
    assert stub.hits == [] and store.events() == []


def test_default_score_capability_remains_unbounded_for_other_profiles(stub):
    question = score("Level?", [f"level-{i}" for i in range(11)])
    stub.enqueue(body={"model": "fixture", "answers": {"decision": _answer(question)},
                       "usage": {"input_tokens": 1, "output_tokens": 0}})
    with closing(HTTPDecisionBackend(endpoint=stub.base_url + "/decisions", model="fixture")) as backend:
        result = backend.predict(DecisionRequest("fixture input", {"decision": question}))
    assert result.predictions["decision"].value == 0 and BackendCapabilities().max_score_levels is None


def test_perplexity_strict_mass_failure_retains_paid_transport_shape(tmp_path, stub):
    question = choice("Choose.", {"yes": None, "no": None})
    answer = {"type": "choice", "choice": "yes", "probabilities": {"yes": .5, "no": .49}, "confidence": .5}
    stub.enqueue(body={"model": MODEL, "provider": "Perplexity", "answers": {"decision": answer},
                       "usage": {"input_tokens": 100, "output_tokens": 0}})
    store = RunStore.create(tmp_path / "mass", {"fixture": "strict consumer probability protocol"})
    ledger = SpendLedger(store)
    with closing(HTTPDecisionBackend(endpoint=stub.base_url + "/decisions", model=MODEL,
            capabilities=BackendCapabilities(**_profile()["capabilities"]),
            observer=ledger.observer(cell_id="mass", hosted=False, liability_usd="0"))) as backend, pytest.raises(ValueError, match="sum"):
        backend.predict(DecisionRequest("owned fixture input", {"decision": question}))
    finished = [e["receipt"] for e in store.events() if e["event"] == "attempt_finished"]
    assert len(finished) == len(stub.hits) == 1 and finished[0]["error"] == "ValueError"


def test_two_explicit_transport_attempts_have_separate_admissions(tmp_path, stub):
    question = choice("Choose.", {"yes": None, "no": None})
    stub.enqueue(503, body={"model": MODEL, "provider": "Perplexity", "usage": {"input_tokens": 1}})
    stub.enqueue(body={"model": MODEL, "provider": "Perplexity", "answers": {"decision": _answer(question)},
                       "usage": {"input_tokens": 2, "output_tokens": 0}})
    store = RunStore.create(tmp_path / "retry", {"fixture": "explicit keyless retry accounting"})
    ledger = SpendLedger(store)
    observer = _NativeContractObserver(ledger.observer(cell_id="retry", hosted=False, liability_usd="0"),
                                       ledger, _native_billing_contract(_profile()))
    with closing(HTTPDecisionBackend(endpoint=stub.base_url + "/decisions", model=MODEL,
            capabilities=BackendCapabilities(**_profile()["capabilities"]), observer=observer)) as backend:
        request = DecisionRequest("owned fixture input", {"decision": question})
        with pytest.raises(BackendHTTPError):
            backend.predict(request)
        assert len(stub.hits) == 1  # adapter never retries invisibly
        assert backend.predict(request).predictions["decision"].value == "yes"
    receipts = [e["receipt"] for e in store.events() if e["event"] == "attempt_finished"]
    assert len(stub.hits) == len(receipts) == 2 and receipts[0]["attempt_id"] != receipts[1]["attempt_id"]
    assert [e["status_code"] for e in receipts] == [503, 200]
    assert len([e for e in store.events() if e["event"] == "attempt_started"]) == 2


def test_perplexity_cost_stop_excludes_racing_admission(tmp_path):
    store = RunStore.create(tmp_path / "race", {"fixture": "Perplexity cost-stop race"})
    ledger = SpendLedger(store)
    delegate = ledger.observer(cell_id="race", hosted=True, liability_usd=".00524286")
    entered, release, racing = threading.Event(), threading.Event(), threading.Event()

    class PausedFinalizer:
        def before(self, *args):
            return delegate.before(*args)

        def after(self, receipt):
            entered.set()
            assert release.wait(2)
            delegate.after(receipt)

    observer = _NativeContractObserver(PausedFinalizer(), ledger, _native_billing_contract(_profile()))
    receipt = _receipt(observer, cost=".000003")

    def race():
        racing.set()
        with pytest.raises(BudgetStopped):
            observer.before("owned-second-hash", MODEL, ENDPOINT)

    with ThreadPoolExecutor(max_workers=2) as pool:
        finish = pool.submit(observer.after, receipt)
        assert entered.wait(2)
        next_admission = pool.submit(race)
        assert racing.wait(2)
        try:
            with pytest.raises(TimeoutError):
                next_admission.result(timeout=.05)
        finally:
            release.set()
        with pytest.raises(BudgetStopped, match="contract breached"):
            finish.result(timeout=2)
        next_admission.result(timeout=2)
    assert [e["receipt"] for e in store.events() if e["event"] == "attempt_finished"] == [receipt.to_dict()]
    assert len([e for e in store.events() if e["event"] == "attempt_started"]) == 1


def test_cancelled_native_http_preserves_receipt_and_async_lifecycle(tmp_path, stub):
    store = RunStore.create(tmp_path / "cancel", {"fixture": "Perplexity cancellation"})
    ledger = SpendLedger(store)
    observer = _NativeContractObserver(ledger.observer(cell_id="cancel", hosted=False, liability_usd="0"),
                                       ledger, _native_billing_contract(_profile()))
    stub.enqueue(body={}, delay=.3)

    async def call():
        backend = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/decisions", model=MODEL,
                                           capabilities=BackendCapabilities(**_profile()["capabilities"]))
        task = asyncio.create_task(backend.predict(DecisionRequest("owned fixture input",
            {"decision": noul("Condition?")}, observer=observer)))
        try:
            for _ in range(100):
                if stub.hits:
                    break
                await asyncio.sleep(.005)
            assert len(stub.hits) == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await backend.close()

    asyncio.run(call())
    receipts = [e["receipt"] for e in store.events() if e["event"] == "attempt_finished"]
    assert len(receipts) == 1 and receipts[0]["error"] == "CancelledError"
    assert "authorization" not in stub.hits[0]["headers"]
    assert ledger.snapshot()["unresolved_attempts"] == []


def test_unknown_hosted_billing_stays_reserved_even_for_valid_perplexity_identity(tmp_path):
    store = RunStore.create(tmp_path / "unknown", {"fixture": "unknown Perplexity billing"})
    ledger = SpendLedger(store)
    observer = _NativeContractObserver(ledger.observer(cell_id="unknown", hosted=True, liability_usd=".00524286"),
                                       ledger, _native_billing_contract(_profile()))
    receipt = replace(_receipt(observer), cost_usd=None, cost_status="unknown")
    observer.after(receipt)
    assert ledger.snapshot()["unresolved_attempts"] == [receipt.attempt_id]
    assert Decimal(ledger.snapshot()["reserved_usd"]) == Decimal(".00524286")
    with pytest.raises(BudgetStopped):
        observer.before("owned-next-hash", MODEL, ENDPOINT)


@pytest.mark.parametrize("name,count", [("native-perplexity-pilot.yaml", 3), ("native-perplexity-full.yaml", 12)],
                         ids=["pilot", "full"])
def test_prepared_recipe_binds_exact_perplexity_contract_without_acceptance_claims(name, count):
    recipe = strict_yaml_loads((ROOT / "benchmarks/configs" / name).read_bytes())
    assert len(recipe["datasets"]) == count and len(recipe["backends"]) == 1
    profile = recipe["backends"][0]
    assert Decimal(_liability(profile)) == Decimal(".00524286")
    assert _native_billing_contract(profile)["max_input_tokens"] == 262143
    assert recipe["budget_usd"] == "25" and recipe["timing_repetitions"] == 5
    assert recipe["timing_sampling_scope"] == "cohort"
    assert profile["capabilities"]["evidence"] == "primary_documentation_unverified_execution"


def test_joint_native_recipe_preserves_each_profile_and_same_full_input_protocol():
    folder = ROOT / "benchmarks/configs"
    joint = strict_yaml_loads((folder / "native-comparison-full.yaml").read_bytes())
    ppl = strict_yaml_loads((folder / "native-perplexity-full.yaml").read_bytes())
    jev = strict_yaml_loads((folder / "native-jev-pilot.yaml").read_bytes())
    assert joint["datasets"] == ppl["datasets"] and len(joint["datasets"]) == 12
    assert joint["backends"] == [jev["backends"][0], ppl["backends"][0]]
    assert len({backend["id"] for backend in joint["backends"]}) == 2
    assert joint["budget_usd"] == "25" and "shared_allocation" not in joint
    assert joint["sampling"] == "all" and joint["seed"] == 20261007
    assert joint["hosted_concurrency"] == 4 and joint["timeout_s"] == 60
    assert joint["timing_samples"] == 100 and joint["timing_repetitions"] == 5
    assert joint["timing_sampling_scope"] == "cohort" and joint["graphical_experiments"] is True
    assert [Decimal(_liability(copy.deepcopy(profile))) for profile in joint["backends"]] == [
        Decimal(".001344"), Decimal(".00524286")]
    assert all(p["mode"] == "systemone" and p["endpoint"] == ENDPOINT for p in joint["backends"])
