"""Unit tests for daf_jev.cli: docs-verify, spec parsing, ask/models over the stub."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from daf_jev.cli import main, parse_question_spec


def run_cli(argv: list[str]) -> int:
    """main() returns an exit code; argparse usage errors raise SystemExit(2)."""
    try:
        code = main(argv)
    except SystemExit as exc:
        code = exc.code
    return 0 if code is None else int(code)


# ------------------------------------------------- docs-verify fixtures ------


def build_docs_fixture(root: Path) -> Path:
    """Create a small docs/reference tree plus a matching MANIFEST.json."""
    pages = {
        "introduction.md": "# Introduction\n\nhello\n",
        "concepts/system-one.md": "# System One\n\nbody text\n",
    }
    entries: dict[str, Any] = {}
    for rel, text in pages.items():
        page = root / rel
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        entries[rel] = {
            "title": rel,
            "url": f"https://docs.typesafe.ai/{rel}",
            "sha256": digest,
            "bytes": len(text.encode("utf-8")),
        }
    concatenated = "".join(entries[rel]["sha256"] for rel in entries)
    manifest = {
        "source": "test fixture",
        "base_url": "https://docs.typesafe.ai",
        "index_url": "https://docs.typesafe.ai/llms.txt",
        "scraped_at_utc": "2026-09-16T00:00:00Z",
        "index_sha256": "0" * 64,
        "page_count": len(entries),
        "pages": entries,
        "snapshot_id": hashlib.sha256(concatenated.encode("utf-8")).hexdigest()[:16],
    }
    manifest_path = root / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


# ------------------------------------------------------------- docs-verify ---


def test_docs_verify_match_exits_zero(tmp_path: Path, capsys) -> None:
    manifest = build_docs_fixture(tmp_path)
    assert run_cli(["docs-verify", "--manifest", str(manifest)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)


def test_docs_verify_tampered_file_exits_one(tmp_path: Path) -> None:
    manifest = build_docs_fixture(tmp_path)
    page = tmp_path / "introduction.md"
    page.write_text(page.read_text() + "tampered\n", encoding="utf-8")
    assert run_cli(["docs-verify", "--manifest", str(manifest)]) == 1


def test_docs_verify_missing_file_exits_one(tmp_path: Path) -> None:
    manifest = build_docs_fixture(tmp_path)
    (tmp_path / "concepts" / "system-one.md").unlink()
    assert run_cli(["docs-verify", "--manifest", str(manifest)]) == 1


def test_docs_verify_default_manifest_matches_real_snapshot(capsys) -> None:
    # The shipped manifest matches docs/reference on disk; no network involved.
    assert run_cli(["docs-verify"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)


# ----------------------------------------------------------- ask/spec parsing


def test_cli_ask_with_all_three_spec_forms(stub, monkeypatch, capsys) -> None:
    stub.enqueue(
        body={
            "model": "jev-latest",
            "usage": {"input_tokens": 5, "output_tokens": 6},
            "answers": {
                "billing": {"type": "noul", "noul": 0.5},
                "tone": {
                    "type": "choice",
                    "choice": "calm",
                    "probabilities": {"calm": 1.0},
                    "confidence": 0.9,
                },
                "severity": {
                    "type": "score",
                    "score": 1.0,
                    "legend": {"0": "low", "1": "high"},
                    "probabilities": {"0": 0.5, "1": 0.5},
                    "confidence": 0.9,
                },
            },
        },
        headers={"x-typesafe-request-id": "req-cli"},
    )
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    code = run_cli(
        [
            "ask",
            "--state",
            "hello world",
            "--question",
            "billing=noul:Is this about billing?",
            "--question",
            "tone=choice:What tone?:calm=,angry=hostile",
            "--question",
            "severity=score:Rate it:low,high,critical",
            "--base-url",
            stub.base_url,
            "--json",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    # All output is JSON to stdout; answers must be present.
    assert "billing" in json.dumps(out)

    hit = stub.hits[-1]
    assert hit["method"] == "POST"
    assert hit["json"]["state"] == "hello world"
    questions = hit["json"]["questions"]
    assert questions["billing"] == {
        "type": "noul",
        "instructions": "Is this about billing?",
    }
    assert questions["tone"] == {
        "type": "choice",
        "instructions": "What tone?",
        "criteria": {"calm": None, "angry": "hostile"},  # empty description -> None
    }
    assert questions["severity"] == {
        "type": "score",
        "instructions": "Rate it",
        "criteria": ["low", "high", "critical"],
    }


def test_cli_ask_runtime_error_exits_one(stub, monkeypatch) -> None:
    stub.enqueue(status=401, body={"error": {"message": "bad key"}})
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    assert (
        run_cli(
            [
                "ask",
                "--state",
                "hello",
                "--question",
                "q=noul:Is it fine?",
                "--base-url",
                stub.base_url,
            ]
        )
        == 1
    )


def test_cli_models_via_stub(stub, monkeypatch, capsys) -> None:
    stub.enqueue(
        body={
            "models": [
                {"name": "jev-latest", "description": "current", "release_date": "2026-01-01"}
            ]
        }
    )
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    assert run_cli(["models", "--base-url", stub.base_url]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "jev-latest" in json.dumps(out)


# -------------------------------------------------------------- bad usage ----


def test_cli_unknown_command_exits_two() -> None:
    assert run_cli(["definitely-not-a-command"]) == 2


def test_cli_missing_required_option_exits_two() -> None:
    assert run_cli(["ask"]) == 2


# ------------------------------------------------------- spec parsing edges ---


def test_parse_question_spec_rejects_malformed_specs() -> None:
    bad_specs = [
        "",  # no type
        "nocolon",  # no separator
        "noul:",  # noul without instructions
        "choice:Pick one",  # choice without criteria segment
        "choice::a=b",  # choice without instructions
        "choice:Pick one:,a=b",  # empty option key
        "score:Rate one:only",  # score needs >= 2 levels
        "score:Rate one:a,,b",  # empty level
        "bogus:Anything:x",  # unknown question type
    ]
    for spec in bad_specs:
        with pytest.raises(ValueError):
            parse_question_spec(spec)


def test_parse_question_spec_escapes_commas_backslashes_and_colons() -> None:
    comma = parse_question_spec("choice:Pick one:a=x\\,y,b=z")
    assert comma.criteria == {"a": "x,y", "b": "z"}

    backslash = parse_question_spec("choice:Pick one:a=x\\\\,b=y")
    assert backslash.criteria == {"a": "x\\", "b": "y"}

    colon = parse_question_spec("choice:What: tone?:calm,angry")
    assert colon.instructions == "What: tone?"
    assert colon.criteria == {"calm": None, "angry": None}

    # Escaped commas split criteria, not instructions: instructions are verbatim.
    score = parse_question_spec("score:Rate it:low\\,high,mid")
    assert score.instructions == "Rate it"
    assert score.criteria == ["low,high", "mid"]


# ------------------------------------------------------------- ask failures ---


def test_cli_ask_malformed_question_entry_exits_one_with_error_json(
    stub, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    code = run_cli(
        ["ask", "--state", "x", "--question", "not-a-spec", "--base-url", stub.base_url]
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "ValueError"
    assert stub.hits == []


def test_cli_models_connection_error_exits_one_with_error_json(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    code = run_cli(["models", "--base-url", "http://127.0.0.1:1"])
    assert code == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "APIConnectionError"


# ------------------------------------------------------------ docs-verify -----


def test_cli_docs_verify_missing_manifest_exits_one_with_error_json(
    tmp_path, capsys
) -> None:
    code = run_cli(["docs-verify", "--manifest", str(tmp_path / "absent.json")])
    assert code == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "FileNotFoundError"


def test_cli_docs_verify_url_rel_mismatch_is_drift(tmp_path, capsys) -> None:
    manifest = build_docs_fixture(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    rel = next(iter(data["pages"]))
    data["pages"][rel]["url"] = "https://docs.typesafe.ai/elsewhere.md"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    assert run_cli(["docs-verify", "--manifest", str(manifest)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["missing"] == []
    assert len(out["drifted"]) == 1 and out["drifted"][0].startswith(rel)
    assert out["ok"] is False


def test_cli_docs_verify_pretty_output(tmp_path, capsys) -> None:
    manifest = build_docs_fixture(tmp_path)
    assert run_cli(["docs-verify", "--manifest", str(manifest), "--pretty"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)  # still valid JSON
    assert "\n" in out.strip()  # printed across multiple lines


# -------------------------------------------------------------- evaluate ------


def _evaluate_body() -> dict:
    return {
        "model": "jev-latest",
        "usage": {"input_tokens": 10, "output_tokens": 4},
        "answers": {
            "billing": {"type": "noul", "noul": 0.7},
            "tone": {
                "type": "choice",
                "choice": "calm",
                "probabilities": {"calm": 1.0, "angry": 0.0},
                "confidence": 0.8,
            },
            "severity": {
                "type": "score",
                "score": 0.5,
                "legend": {"0": "low", "1": "high"},
                "probabilities": {"0": 0.5, "1": 0.5},
                "confidence": 0.9,
            },
        },
    }


def _write_spec_questions_file(tmp_path: Path) -> Path:
    path = tmp_path / "questions-spec.yaml"
    path.write_text(
        'billing: "noul:Is this about billing?"\n'
        'tone: "choice:What tone?:calm=,angry=hostile"\n'
        'severity: "score:Rate severity:low,high"\n',
        encoding="utf-8",
    )
    return path


def _write_native_questions_file(tmp_path: Path) -> Path:
    path = tmp_path / "questions-native.yaml"
    path.write_text(
        "billing:\n"
        "  type: noul\n"
        "  instructions: Is this about billing?\n"
        "tone:\n"
        "  type: choice\n"
        "  instructions: What tone?\n"
        "  criteria:\n"
        "    calm: null\n"
        "    angry: hostile\n"
        "severity:\n"
        "  type: score\n"
        "  instructions: Rate severity\n"
        "  criteria: [low, high]\n",
        encoding="utf-8",
    )
    return path


def test_cli_evaluate_spec_string_questions_over_stub(
    stub, monkeypatch, capsys, tmp_path
) -> None:
    questions_file = _write_spec_questions_file(tmp_path)
    states_file = tmp_path / "states.txt"
    states_file.write_text("alpha\n\nbeta\ngamma\n", encoding="utf-8")  # blank skipped
    for _ in range(3):
        stub.enqueue(body=_evaluate_body())
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    code = run_cli(
        [
            "evaluate",
            "--questions-file",
            str(questions_file),
            "--states-file",
            str(states_file),
            "--concurrency",
            "1",
            "--base-url",
            stub.base_url,
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_states"] == 3
    assert out["n_errors"] == 0
    assert out["total_input_tokens"] == 30
    assert out["total_output_tokens"] == 12
    assert out["questions"]["billing"]["kind"] == "noul"
    assert out["questions"]["billing"]["mean"] == pytest.approx(0.7)
    assert "records" not in out  # summary only unless --include-records
    # spec-string questions wire exactly like the ask command's --question specs
    questions = stub.hits[0]["json"]["questions"]
    assert questions["billing"] == {"type": "noul", "instructions": "Is this about billing?"}
    assert questions["tone"] == {
        "type": "choice",
        "instructions": "What tone?",
        "criteria": {"calm": None, "angry": "hostile"},
    }
    assert questions["severity"] == {
        "type": "score",
        "instructions": "Rate severity",
        "criteria": ["low", "high"],
    }


def test_cli_evaluate_native_yaml_questions_over_stub(
    stub, monkeypatch, capsys, tmp_path
) -> None:
    questions_file = _write_native_questions_file(tmp_path)
    states_file = tmp_path / "states.txt"
    states_file.write_text("alpha\nbeta\n", encoding="utf-8")
    for _ in range(2):
        stub.enqueue(body=_evaluate_body())
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    code = run_cli(
        [
            "evaluate",
            "--questions-file",
            str(questions_file),
            "--states-file",
            str(states_file),
            "--model",
            "jev-latest",
            "--base-url",
            stub.base_url,
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_states"] == 2
    assert out["n_errors"] == 0
    questions = stub.hits[0]["json"]["questions"]
    assert questions["billing"] == {"type": "noul", "instructions": "Is this about billing?"}
    assert questions["tone"]["criteria"] == {"calm": None, "angry": "hostile"}
    assert questions["severity"]["criteria"] == ["low", "high"]


def test_cli_evaluate_json_states_file(stub, monkeypatch, capsys, tmp_path) -> None:
    questions_file = _write_spec_questions_file(tmp_path)
    states_file = tmp_path / "states.json"
    states_file.write_text('["s1", "s2"]', encoding="utf-8")
    for _ in range(2):
        stub.enqueue(body=_evaluate_body())
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    code = run_cli(
        [
            "evaluate",
            "--questions-file",
            str(questions_file),
            "--states-file",
            str(states_file),
            "--include-records",
            "--base-url",
            stub.base_url,
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_states"] == 2
    records = out["records"]
    assert len(records) == 2
    assert records[0]["state"] == "s1"
    assert records[1]["state"] == "s2"
    assert records[0]["state_id"] == "state_0000"
    assert records[0]["error"] is None
    assert records[0]["response"]["model"] == "jev-latest"


def test_cli_evaluate_records_one_error_among_successes(
    stub, monkeypatch, capsys, tmp_path
) -> None:
    questions_file = _write_spec_questions_file(tmp_path)
    states_file = tmp_path / "states.txt"
    states_file.write_text("good\nbad\ngood2\n", encoding="utf-8")
    stub.enqueue(body=_evaluate_body())
    stub.enqueue(status=401, body={"error": {"message": "bad key"}})
    stub.enqueue(body=_evaluate_body())
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    code = run_cli(
        [
            "evaluate",
            "--questions-file",
            str(questions_file),
            "--states-file",
            str(states_file),
            "--base-url",
            stub.base_url,
        ]
    )
    assert code == 0  # a per-state error does not fail the batch
    out = json.loads(capsys.readouterr().out)
    assert out["n_states"] == 3
    assert out["n_errors"] == 1
    # aggregates exclude the errored state
    assert out["questions"]["billing"]["mean"] == pytest.approx(0.7)
    assert out["total_input_tokens"] == 20


def test_cli_evaluate_empty_states_exits_two(
    stub, monkeypatch, capsys, tmp_path
) -> None:
    questions_file = _write_spec_questions_file(tmp_path)
    states_file = tmp_path / "states.txt"
    states_file.write_text("\n   \n\n", encoding="utf-8")  # blank lines only
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    code = run_cli(
        [
            "evaluate",
            "--questions-file",
            str(questions_file),
            "--states-file",
            str(states_file),
            "--base-url",
            stub.base_url,
        ]
    )
    assert code == 2
    assert stub.hits == []  # usage error: no request reaches the API


# ------------------------------------------------- models --pick / --contains -


def _models_body() -> dict:
    return {
        "models": [
            {"name": "jev-latest", "description": "flagship", "release_date": "2026-01-01"},
            {"name": "jev-mini", "description": "small", "release_date": "2026-06-01"},
            {"name": "jev-classic", "description": "old", "release_date": "2025-06-01"},
            {"name": "jev-legacy", "description": "retired", "release_date": None},
        ]
    }


def test_cli_models_pick_latest(stub, monkeypatch, capsys) -> None:
    stub.enqueue(body=_models_body())
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    assert run_cli(["models", "--base-url", stub.base_url, "--pick", "latest"]) == 0
    out = json.loads(capsys.readouterr().out)
    # Output shape (bare card vs wrapped) is an implementation detail; the
    # pick semantics are what matters: exactly the newest card is reported.
    assert "jev-mini" in json.dumps(out)
    assert "jev-latest" not in json.dumps(out)


def test_cli_models_pick_first_and_last(stub, monkeypatch, capsys) -> None:
    stub.enqueue(body=_models_body())
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    assert run_cli(["models", "--base-url", stub.base_url, "--pick", "first"]) == 0
    assert "jev-latest" in json.dumps(capsys.readouterr().out)
    stub.enqueue(body=_models_body())
    assert run_cli(["models", "--base-url", stub.base_url, "--pick", "last"]) == 0
    assert "jev-legacy" in json.dumps(capsys.readouterr().out)


def test_cli_models_contains_and_pick(stub, monkeypatch, capsys) -> None:
    stub.enqueue(body=_models_body())
    monkeypatch.setenv("JEV_API_KEY", "cli-key")
    # case-insensitive substring filter applied before the pick
    assert (
        run_cli(
            ["models", "--base-url", stub.base_url, "--contains", "CLASSIC", "--pick", "latest"]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert "jev-classic" in json.dumps(out)
    assert "jev-mini" not in json.dumps(out)
    stub.enqueue(body=_models_body())
    assert (
        run_cli(["models", "--base-url", stub.base_url, "--contains", "mini"])
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert "jev-mini" in json.dumps(out)
    assert "jev-classic" not in json.dumps(out)
