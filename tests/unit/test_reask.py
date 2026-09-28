"""Unit tests for daf_jev.reask: max-entropy re-ask policy over
posteriors sidecars (M1 part b).

Every entropy value asserted here is hand-computed in comments (log2
bits). No mocks, no patching of daf_jev internals: fixture documents are
written to tmp_path and fed through the real ``load_posteriors`` loader
(and through the real CLI main / MCP tool coroutines for the seams).
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import math
from pathlib import Path

import pytest

from daf_jev.bayesnet_posteriors import (
    FORMAT_MARGINALS,
    FORMAT_POSTERIORS,
    load_posteriors,
)
from daf_jev.cli import main
from daf_jev.reask import ReAskPlan, entropy_bits, next_question, reask_plan


# -------------------------------------------------------------- fixtures ----
def _write_json(tmp_path: Path, name: str, document: dict) -> Path:
    """Serialize a document to tmp_path, preserving insertion order."""
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _variant_a() -> dict:
    """A valid variant-A sidecar with distinct entropy levels and ties.

    Hand-computed entropies (bits):
    - ``uniform4`` {a,b,c,d: 0.25} -> exactly log2(4) = 2.0
    - ``skew`` {t: 0.75, f: 0.25} -> 0.75*log2(4/3) + 0.25*log2(4)
                                   = 0.8112781244591328
    - ``tie1`` {x: 0.5, y: 0.5} -> exactly 1.0
    - ``tie2`` {m: 0.5, n: 0.5} -> exactly 1.0 (ties tie1, later insertion)
    - ``hot`` {t: 1.0, f: 0.0} -> 0.0 (one-hot; also the evidence row:
      observed state ``t`` carries p = 1.0 >= 1 - ONE_HOT_TOLERANCE)
    """
    return {
        "format": FORMAT_POSTERIORS,
        "evidence": {"hot": "t"},
        "posteriors": {
            "skew": {"t": 0.75, "f": 0.25},
            "uniform4": {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25},
            "tie2": {"m": 0.5, "n": 0.5},
            "hot": {"t": 1.0, "f": 0.0},
            "tie1": {"x": 0.5, "y": 0.5},
        },
    }


def _variant_b() -> dict:
    return {
        "format": FORMAT_MARGINALS,
        "marginals": {"m1": {"a": 0.25, "b": 0.75}},
        "source_model": "bridge-1",
    }


def run_cli(argv: list[str]) -> int:
    """main() returns an exit code; argparse usage errors raise SystemExit(2).

    Copied verbatim from tests/unit/test_cli.py:15-23 (in-file helper per
    the lane contract, not imported).
    """
    try:
        code = main(argv)
    except SystemExit as exc:
        code = exc.code
    return 0 if code is None else int(code)


# ------------------------------------------------------------ entropy_bits --
def test_entropy_uniform_row_is_log2_n() -> None:
    """A uniform k-state row carries exactly log2(k) bits."""
    assert entropy_bits({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}) == pytest.approx(math.log2(4))
    assert entropy_bits({"a": 0.5, "b": 0.5}) == pytest.approx(1.0)


def test_entropy_one_hot_row_is_zero() -> None:
    assert entropy_bits({"t": 1.0, "f": 0.0}) == 0.0


def test_entropy_skew_hand_computed() -> None:
    """0.75/0.25 -> 0.75*log2(4/3) + 0.25*2 bits."""
    expected = 0.75 * math.log2(4 / 3) + 0.25 * 2.0
    assert entropy_bits({"t": 0.75, "f": 0.25}) == pytest.approx(expected)


def test_entropy_empty_row_is_zero() -> None:
    assert entropy_bits({}) == 0.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_entropy_rejects_non_finite(bad: float) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        entropy_bits({"t": 0.5, "f": bad})


def test_entropy_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        entropy_bits({"t": 1.25, "f": -0.25})


def test_entropy_rejects_drift_with_deviation_in_message() -> None:
    """A row drifting beyond ROW_SUM_TOLERANCE raises with the deviation
    named — never renormalized."""
    with pytest.raises(ValueError) as excinfo:
        entropy_bits({"t": 0.5, "f": 0.5 + 1e-3})
    message = str(excinfo.value)
    assert "1.001" in message and "0.0009999999999998899" in message
    # Just inside the flat budget passes (the loader's boundary row).
    assert entropy_bits({"t": 0.999999, "f": 0.000001}) == pytest.approx(
        0.999999 * math.log2(1 / 0.999999) + 0.000001 * math.log2(1 / 0.000001)
    )


# ---------------------------------------------------- variant-B rejection ---
def test_next_question_rejects_variant_b_with_both_formats(tmp_path: Path) -> None:
    """The fail-closed contract: gnn.marginals/1 has no evidence to
    replay; the message names both format strings."""
    sidecar = load_posteriors(_write_json(tmp_path, "b.json", _variant_b()))
    with pytest.raises(ValueError) as excinfo:
        next_question(sidecar)
    message = str(excinfo.value)
    assert "dafjev.bayesnet-posteriors/1" in message
    assert "gnn.marginals/1" in message


# --------------------------------------------------------- next_question ----
def test_next_question_picks_max_entropy(tmp_path: Path) -> None:
    sidecar = load_posteriors(_write_json(tmp_path, "a.json", _variant_a()))
    assert next_question(sidecar) == "uniform4"  # 2.0 bits beats 1.0/0.81/0.0


def test_next_question_tie_broken_by_insertion_order(tmp_path: Path) -> None:
    """tie2 (row 3) and tie1 (row 5) both carry exactly 1.0 bits; the
    earlier-inserted tie2 wins."""
    sidecar = load_posteriors(_write_json(tmp_path, "a.json", _variant_a()))
    plan = reask_plan(sidecar, asked={"uniform4", "skew", "hot"})
    assert plan.next_question == "tie2"
    assert plan.entropy == pytest.approx(1.0)


def test_next_question_skips_asked_and_unknown_names(tmp_path: Path) -> None:
    """Unknown asked names are inert; every candidate asked -> None."""
    sidecar = load_posteriors(_write_json(tmp_path, "a.json", _variant_a()))
    assert next_question(sidecar, asked=["not_a_variable"]) == "uniform4"
    everything = set(sidecar.posteriors)
    assert next_question(sidecar, asked=everything) is None


def test_next_question_empty_sidecar_is_none(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path,
        "empty.json",
        {"format": FORMAT_POSTERIORS, "evidence": {}, "posteriors": {}},
    )
    assert next_question(load_posteriors(path)) is None


# ------------------------------------------------------------- reask_plan ---
def test_plan_orders_descending_with_insertion_ties(tmp_path: Path) -> None:
    sidecar = load_posteriors(_write_json(tmp_path, "a.json", _variant_a()))
    plan = reask_plan(sidecar)
    assert [var for var, _ in plan.queue] == [
        "uniform4", "tie2", "tie1", "skew", "hot",
    ]
    assert [tuple(entry) for entry in plan.queue] == [
        ("uniform4", 2.0),
        ("tie2", 1.0),
        ("tie1", 1.0),
        ("skew", 0.8112781244591328),
        ("hot", 0.0),
    ]
    assert plan.queue[0][1] == pytest.approx(2.0)
    assert plan.queue[1][1] == pytest.approx(1.0)
    assert plan.queue[3][1] == pytest.approx(0.8112781244591328)
    assert plan.next_question == "uniform4"
    assert plan.entropy == pytest.approx(2.0)


def test_plan_evidence_passthrough_verbatim(tmp_path: Path) -> None:
    """The sidecar's evidence mapping rides the plan untouched."""
    sidecar = load_posteriors(_write_json(tmp_path, "a.json", _variant_a()))
    plan = reask_plan(sidecar)
    assert plan.evidence == {"hot": "t"}
    assert plan.evidence is sidecar.evidence  # verbatim, not rebuilt


def test_plan_empty_sidecar_shape(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path,
        "empty.json",
        {"format": FORMAT_POSTERIORS, "evidence": {}, "posteriors": {}},
    )
    plan = reask_plan(load_posteriors(path))
    assert plan.next_question is None
    assert plan.entropy is None
    assert plan.queue == ()
    assert plan.evidence == {}


def test_plan_is_frozen_dataclass_json_safe(tmp_path: Path) -> None:
    """ReAskPlan is frozen and its asdict survives a JSON round-trip
    (mcp_server's JSON-safety convention)."""
    sidecar = load_posteriors(_write_json(tmp_path, "a.json", _variant_a()))
    plan = reask_plan(sidecar)
    assert isinstance(plan, ReAskPlan)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.next_question = "x"  # type: ignore[misc]
    payload = dataclasses.asdict(plan)
    payload["queue"] = [list(entry) for entry in payload["queue"]]
    round_trip = json.loads(json.dumps(payload))
    assert round_trip["next_question"] == "uniform4"
    assert round_trip["evidence"] == {"hot": "t"}
    assert round_trip["entropy"] == pytest.approx(2.0)


# ------------------------------------------------------------- CLI seam -----
def test_cli_reask_ok_path(tmp_path: Path, capsys) -> None:
    """Valid sidecar -> exit 0, JSON plan {next_question, entropy, queue,
    evidence} on stdout."""
    path = _write_json(tmp_path, "a.json", _variant_a())
    assert run_cli(["posteriors-reask", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next_question"] == "uniform4"
    assert payload["entropy"] == pytest.approx(2.0)
    assert [entry[0] for entry in payload["queue"]] == [
        "uniform4", "tie2", "tie1", "skew", "hot",
    ]
    assert payload["evidence"] == {"hot": "t"}


def test_cli_reask_asked_flag_excludes_variables(tmp_path: Path, capsys) -> None:
    """--asked VAR (repeatable) removes variables from the queue."""
    path = _write_json(tmp_path, "a.json", _variant_a())
    assert run_cli(["posteriors-reask", str(path), "--asked", "uniform4", "--asked", "skew"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next_question"] == "tie2"
    assert [entry[0] for entry in payload["queue"]] == ["tie2", "tie1", "hot"]


def test_cli_reask_variant_b_exits_one(tmp_path: Path, capsys) -> None:
    """A variant-B document exits 1 with {error, message} on stderr; the
    message names both formats; stdout stays empty."""
    path = _write_json(tmp_path, "b.json", _variant_b())
    assert run_cli(["posteriors-reask", str(path)]) == 1
    out = capsys.readouterr()
    assert out.out == ""
    payload = json.loads(out.err)
    assert payload["error"] == "ValueError"
    assert "dafjev.bayesnet-posteriors/1" in payload["message"]
    assert "gnn.marginals/1" in payload["message"]


def test_cli_reask_usage_errors_exit_two(tmp_path: Path, capsys) -> None:
    path = _write_json(tmp_path, "a.json", _variant_a())
    assert run_cli(["posteriors-reask"]) == 2
    assert "usage:" in capsys.readouterr().err
    assert run_cli(["posteriors-reask", str(path), "--bogus"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_cli_reask_graphspec_passthrough(tmp_path: Path, capsys) -> None:
    """--graphspec rides through to the loader (validation parity with
    posteriors-load): a defining spec exits 0; a spec missing a posterior
    variable exits 1 naming the variable."""
    sidecar_path = _write_json(tmp_path, "a.json", _variant_a())
    spec_path = _write_json(
        tmp_path,
        "spec.json",
        {
            "format": "dafjev.bayesnet/1",
            "variables": [
                {"key": "skew", "states": ["t", "f"]},
                {"key": "uniform4", "states": ["a", "b", "c", "d"]},
                {"key": "tie2", "states": ["m", "n"]},
                {"key": "hot", "states": ["t", "f"]},
                {"key": "tie1", "states": ["x", "y"]},
            ],
        },
    )
    assert run_cli(["posteriors-reask", str(sidecar_path), "--graphspec", str(spec_path)]) == 0
    assert json.loads(capsys.readouterr().out)["next_question"] == "uniform4"

    partial_spec_path = _write_json(
        tmp_path,
        "partial.json",
        {"format": "dafjev.bayesnet/1", "variables": [{"key": "skew", "states": ["t", "f"]}]},
    )
    assert run_cli(["posteriors-reask", str(sidecar_path), "--graphspec", str(partial_spec_path)]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "ValueError"
    assert "evidence variable 'hot' is not defined in graphspec" in payload["message"]


# -------------------------------------------------------------- MCP seam ----
def _mcp_server_module():
    """The MCP server module, only when mcp is installed (test_bayesnet_
    posteriors.py:923-927 guard style, mirrored in-file)."""
    pytest.importorskip("mcp")
    return pytest.importorskip("daf_jev.mcp_server")


def _run(coro):
    return asyncio.run(coro)


async def _tool_names(server) -> set[str]:
    """Enumerate FastMCP tool names, tolerating SDK introspection drift.

    Copied verbatim from tests/unit/test_mcp_server.py:133-144."""
    for attr in ("list_tools", "_list_tools"):
        fn = getattr(server, attr, None)
        if callable(fn):
            result = fn()
            if inspect.isawaitable(result):
                result = await result
            return {tool.name for tool in result}
    manager = getattr(server, "_tool_manager", None)
    if manager is not None and hasattr(manager, "list_tools"):
        return {tool.name for tool in manager.list_tools()}
    pytest.skip("no FastMCP tool introspection API available")


def test_mcp_reask_plan_ok_dict(tmp_path: Path) -> None:
    ms = _mcp_server_module()
    path = _write_json(tmp_path, "a.json", _variant_a())
    result = _run(ms.jev_reask_plan(str(path)))
    assert result["next_question"] == "uniform4"
    assert result["entropy"] == pytest.approx(2.0)
    assert [entry[0] for entry in result["queue"]] == [
        "uniform4", "tie2", "tie1", "skew", "hot",
    ]
    assert result["evidence"] == {"hot": "t"}
    assert "ok" not in result  # the plan shape, not a summary envelope


def test_mcp_reask_plan_asked_list(tmp_path: Path) -> None:
    ms = _mcp_server_module()
    path = _write_json(tmp_path, "a.json", _variant_a())
    result = _run(ms.jev_reask_plan(str(path), asked=["uniform4", "tie2"]))
    assert result["next_question"] == "tie1"


def test_mcp_reask_plan_variant_b_is_error_dict(tmp_path: Path) -> None:
    ms = _mcp_server_module()
    path = _write_json(tmp_path, "b.json", _variant_b())
    result = _run(ms.jev_reask_plan(str(path)))
    assert result == {
        "error": "ValueError",
        "message": result["message"],
        "ok": False,
    }
    assert "dafjev.bayesnet-posteriors/1" in result["message"]
    assert "gnn.marginals/1" in result["message"]


def test_mcp_reask_plan_graphspec_passthrough(tmp_path: Path) -> None:
    ms = _mcp_server_module()
    sidecar_path = _write_json(tmp_path, "a.json", _variant_a())
    spec_path = _write_json(
        tmp_path,
        "spec.json",
        {
            "format": "dafjev.bayesnet/1",
            "variables": [{"key": var, "states": list(states)} for var, states in [
                ("skew", ["t", "f"]),
                ("uniform4", ["a", "b", "c", "d"]),
                ("tie2", ["m", "n"]),
                ("hot", ["t", "f"]),
                ("tie1", ["x", "y"]),
            ]],
        },
    )
    ok = _run(ms.jev_reask_plan(str(sidecar_path), graphspec_path=str(spec_path)))
    assert ok["next_question"] == "uniform4"


def test_mcp_reask_plan_registration() -> None:
    """jev_reask_plan is among build_server's tool names."""
    ms = _mcp_server_module()
    server = ms.build_server()
    tools = _run(_tool_names(server))
    assert "jev_reask_plan" in tools


def test_mcp_reask_plan_json_safe(tmp_path: Path) -> None:
    """The tool payload survives json.dumps -> json.loads unchanged."""
    ms = _mcp_server_module()
    path = _write_json(tmp_path, "a.json", _variant_a())
    result = _run(ms.jev_reask_plan(str(path)))
    assert json.loads(json.dumps(result)) == result
