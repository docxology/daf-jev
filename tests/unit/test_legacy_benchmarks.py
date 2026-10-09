"""Real local HTTP reproductions of legacy benchmark protocol defects."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from benchmarks import bench_batching, bench_calibration, bench_patterns
from benchmarks._util import percentile, write_result
from daf_jev import JevClient
from daf_jev._retry import RetryPolicy


def test_calibration_selected_state_count_matches_actual_calls(stub):
    for _ in range(2):
        stub.enqueue(body={"model": "fixture", "answers": {
            "sentiment": {"type": "choice", "choice": "praise", "probabilities": {
                "praise": .8, "urgent_issue": .1, "minor_issue": .1}, "confidence": .8}},
            "usage": {"input_tokens": 1, "output_tokens": 1}})
        stub.enqueue(body={"model": "fixture", "answers": {"resolved": {"type": "noul", "noul": .5}},
                                  "usage": {"input_tokens": 1, "output_tokens": 1}})
    with JevClient(api_key="local-fixture", base_url=stub.base_url, model="fixture",
                   retry=RetryPolicy(max_attempts=1), timeout=2) as client:
        answers, nouls, errors = bench_calibration.collect_answers(
            client, 2, states=bench_calibration.STATES[:1])
    assert len(answers) == len(nouls) == 1 and errors == 0
    assert len(stub.hits) == 4
    assert all(hit["json"]["state"] == bench_calibration.STATES[0] for hit in stub.hits)


@pytest.mark.parametrize("main,args", [
    (bench_batching.main, ["--runs", "0"]), (bench_patterns.main, ["--runs", "-1"]),
    (bench_calibration.main, ["--repeats", "0"]), (bench_calibration.main, ["--states", "0"]),
])
def test_invalid_counts_reject_before_credentials_or_network(main, args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_same_day_concurrent_receipts_never_overwrite_and_json_is_strict(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda i: write_result("batching", {"trial": i}, out_dir=tmp_path), range(16)))
    assert len(set(paths)) == 16
    assert {json.loads(p.read_text())["trial"] for p in paths} == set(range(16))
    assert all(json.loads(p.read_text())["percentile_method"] == "nearest_rank" for p in paths)
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        write_result("batching", {"metric": float("nan")}, out_dir=tmp_path)
    assert set(tmp_path.iterdir()) == before
    with pytest.raises(ValueError):
        write_result("../escaped", {}, out_dir=tmp_path)
    assert percentile([1., 2.], 95) == 2
