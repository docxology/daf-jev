"""Unit tests for daf_jev.bayesnet_posteriors: posterior sidecar ingest,
GraphSpec cross-checks, and calibration pairing.

Every probability number asserted here is hand-computed in comments (Brier
scores over the state union, row-sum deviations, ECE bucket math against
daf_jev.calibration bucket edges). No mocks, no patching of daf_jev
internals: fixture documents are written to tmp_path and fed through the
real ``load_posteriors`` loader. Case numbering in the docstrings follows
the wave-2 ticket inventory (cases 1-41).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from daf_jev.bayesnet_posteriors import (
    FORMAT_MARGINALS,
    FORMAT_POSTERIORS,
    CalibrationPairing,
    PosteriorsSidecar,
    load_posteriors,
    pair_for_calibration,
    row_sum_deviations,
)
from daf_jev.calibration import (
    brier_score,
    expected_calibration_error,
    reliability_table,
)
from daf_jev.cli import main

GRAPH_SPEC_FORMAT = "dafjev.bayesnet/1"


# -------------------------------------------------------------- fixtures ----
def _write_json(tmp_path: Path, name: str, document: dict) -> Path:
    """Serialize a document to tmp_path, preserving insertion order."""
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _valid_a_document() -> dict:
    """A valid variant-A sidecar: non-alphabetical outer order, nested state
    order kept, and one-hot evidence rows at both boundaries.

    The exact one-hot row {t: 1.0, f: 0.0} and the boundary row
    {t: 0.999999, f: 0.000001} both pass: the observed state needs
    p >= 1.0 - ONE_HOT_TOLERANCE (bayesnet_posteriors.py:64, :291) and any
    other state must carry p <= ONE_HOT_TOLERANCE (:299) — 0.000001 equals
    the tolerance, hence is not rejected.
    """
    return {
        "format": FORMAT_POSTERIORS,
        "evidence": {"umbrella": "t", "sprinkler": "t"},
        "posteriors": {
            "zeta": {"no": 0.5, "yes": 0.25, "maybe": 0.25},
            "umbrella": {"t": 1.0, "f": 0.0},
            "sprinkler": {"t": 0.999999, "f": 0.000001},
            # Drift row: sum deviates 9.000000000813912e-07 from 1.0, inside
            # the flat A budget ROW_SUM_TOLERANCE = 1e-6 (:62, :249-253) —
            # the CLI/MCP summaries pin this as their max deviation.
            "gauge": {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.2500009},
        },
    }


def _valid_b_document(source_model: str | None) -> dict:
    """A valid variant-B marginals sidecar with the given source_model."""
    return {
        "format": FORMAT_MARGINALS,
        "marginals": {"m1": {"a": 0.25, "b": 0.75}},
        "source_model": source_model,
    }


def _graphspec_document() -> dict:
    """A valid dafjev.bayesnet/1 spec defining every fixture variable.

    ``description`` is extra spec detail the cross-check must ignore.
    """
    return {
        "format": GRAPH_SPEC_FORMAT,
        "variables": [
            {
                "key": "zeta",
                "description": "outcome of the toss",
                "states": ["no", "yes", "maybe"],
            },
            {"key": "umbrella", "description": "umbrella up", "states": ["t", "f"]},
            {"key": "sprinkler", "description": "sprinkler on", "states": ["t", "f"]},
            {"key": "gauge", "description": "drift gauge", "states": ["a", "b", "c", "d"]},
        ],
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


# -------------------------------------------------- variant A: loader (1-12) -
def test_a_valid_round_trip_and_order(tmp_path: Path) -> None:
    """Case 1: valid A round-trips fields, isinstance types, and insertion
    order of both outer variables and nested states."""
    path = _write_json(tmp_path, "a.json", _valid_a_document())
    sidecar = load_posteriors(path)
    assert isinstance(sidecar, PosteriorsSidecar)
    assert sidecar.format == FORMAT_POSTERIORS
    assert isinstance(sidecar.posteriors, dict)
    assert isinstance(sidecar.evidence, dict)
    assert list(sidecar.posteriors) == ["zeta", "umbrella", "sprinkler", "gauge"]
    assert list(sidecar.posteriors["zeta"]) == ["no", "yes", "maybe"]
    assert sidecar.posteriors == {
        "zeta": {"no": 0.5, "yes": 0.25, "maybe": 0.25},
        "umbrella": {"t": 1.0, "f": 0.0},
        "sprinkler": {"t": 0.999999, "f": 0.000001},
        "gauge": {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.2500009},
    }
    assert sidecar.evidence == {"umbrella": "t", "sprinkler": "t"}
    assert sidecar.source_model is None


def test_a_accepts_integer_probabilities_as_floats(tmp_path: Path) -> None:
    """Added: int probabilities are JSON numbers and convert to float."""
    doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {"v": "t"},
        "posteriors": {"v": {"t": 1, "f": 0}},
    }
    sidecar = load_posteriors(_write_json(tmp_path, "ints.json", doc))
    assert sidecar.posteriors == {"v": {"t": 1.0, "f": 0.0}}


def test_a_rejects_unknown_format_string(tmp_path: Path) -> None:
    """Case 2: an unsupported format string is named in the error."""
    doc = _valid_a_document()
    doc["format"] = "dafjev.bayesnet-posteriors/2"
    with pytest.raises(
        ValueError, match=r"unsupported format 'dafjev\.bayesnet-posteriors/2'"
    ):
        load_posteriors(_write_json(tmp_path, "fmt.json", doc))


def test_a_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    """Case 3: an A-only document carrying 'marginals' names the key."""
    doc = _valid_a_document()
    doc["marginals"] = {"x": {"s": 1.0}}
    with pytest.raises(ValueError, match="unexpected top-level key") as excinfo:
        load_posteriors(_write_json(tmp_path, "unknown.json", doc))
    assert "['marginals']" in str(excinfo.value)


def test_a_rejects_missing_required_key(tmp_path: Path) -> None:
    """Case 4: A without 'evidence' names the missing key."""
    doc = _valid_a_document()
    del doc["evidence"]
    with pytest.raises(ValueError, match="missing top-level key") as excinfo:
        load_posteriors(_write_json(tmp_path, "missing.json", doc))
    assert "'evidence'" in str(excinfo.value)


def test_a_rejects_non_string_evidence_value(tmp_path: Path) -> None:
    """Case 5: a non-str evidence value names the variable."""
    doc = _valid_a_document()
    doc["evidence"]["umbrella"] = 3
    with pytest.raises(ValueError, match="evidence value for variable 'umbrella'"):
        load_posteriors(_write_json(tmp_path, "bad_ev.json", doc))


def test_a_row_sum_drift_both_sides(tmp_path: Path) -> None:
    """Case 6: drift 9e-7 passes the flat A budget 1e-6 (:62); 1.5e-6
    breach names the variable."""
    ok_row = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.2500009}
    sidecar = load_posteriors(
        _write_json(
            tmp_path, "ok_drift.json",
            {"format": FORMAT_POSTERIORS, "evidence": {}, "posteriors": {"V": ok_row}},
        )
    )
    assert row_sum_deviations(sidecar) == {"V": 9.000000000813912e-07}

    bad_row = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.2500015}
    with pytest.raises(ValueError, match=r"row for variable 'V' sums to 1\.0000015"):
        load_posteriors(
            _write_json(
                tmp_path, "bad_drift.json",
                {"format": FORMAT_POSTERIORS, "evidence": {}, "posteriors": {"V": bad_row}},
            )
        )


def _evidence_doc(row: dict) -> dict:
    """An A document whose single variable 'v' carries the given row."""
    return {
        "format": FORMAT_POSTERIORS,
        "evidence": {"v": "t"},
        "posteriors": {"v": row},
    }


def test_a_one_hot_violations(tmp_path: Path) -> None:
    """Case 7: all four one-hot rejection modes plus the passing boundary."""
    # observed state carries only 0.98: below 1.0 - ONE_HOT_TOLERANCE (:291)
    with pytest.raises(ValueError, match="evidence one-hot violated for variable 'v'"):
        load_posteriors(
            _write_json(tmp_path, "oh98.json", _evidence_doc({"t": 0.98, "f": 0.02}))
        )
    # observed state absent from the row: defaults to 0.0 (:290)
    with pytest.raises(ValueError, match=r"observed state 't' carries 0\.0"):
        load_posteriors(_write_json(tmp_path, "ohmiss.json", _evidence_doc({"f": 1.0})))
    # evidence variable has no posteriors row at all (:283-289)
    doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {"ghost": "x"},
        "posteriors": {"v": {"t": 1.0, "f": 0.0}},
    }
    with pytest.raises(ValueError, match="evidence variable 'ghost' has no posteriors row"):
        load_posteriors(_write_json(tmp_path, "ohnovar.json", doc))
    # another state carries 1.5e-06 > tolerance 1e-06 (:299)
    with pytest.raises(ValueError, match=r"state 'f' carries 1\.5e-06 > tolerance"):
        load_posteriors(
            _write_json(
                tmp_path, "ohother.json",
                _evidence_doc({"t": 0.999999, "f": 0.0000015}),
            )
        )
    # boundary p_e = 0.999999 passes (== 1.0 - ONE_HOT_TOLERANCE)
    sidecar = load_posteriors(
        _write_json(tmp_path, "ohbnd.json", _evidence_doc({"t": 0.999999, "f": 0.000001}))
    )
    assert sidecar.evidence == {"v": "t"}


def test_a_rejects_non_finite_probability(tmp_path: Path) -> None:
    """Case 8: NaN/Infinity via json.dumps are non-finite; the error names
    var and state (:236-241)."""
    path = _write_json(tmp_path, "nan.json", _evidence_doc({"t": float("nan"), "f": 0.0}))
    with pytest.raises(ValueError, match="state 't' must be finite, got nan"):
        load_posteriors(path)
    path = _write_json(tmp_path, "inf.json", _evidence_doc({"t": float("inf"), "f": 0.0}))
    with pytest.raises(ValueError, match="state 't' must be finite, got inf"):
        load_posteriors(path)


def test_a_rejects_negative_probability(tmp_path: Path) -> None:
    """Case 9: negative probabilities are rejected, naming var and state."""
    with pytest.raises(ValueError, match=r"state 't' must be >= 0, got -0\.1"):
        load_posteriors(
            _write_json(tmp_path, "neg.json", _evidence_doc({"t": -0.1, "f": 1.1}))
        )


def test_a_rejects_bool_probabilities(tmp_path: Path) -> None:
    """Case 10: bool is an int subclass — the strict contract rejects it."""
    for state, value in (("t", True), ("t", False)):
        doc = _evidence_doc({state: value, "f": 0.0})
        with pytest.raises(ValueError, match="must be an int or float, got bool"):
            load_posteriors(_write_json(tmp_path, f"bool_{value}.json", doc))


def test_a_rejects_string_probabilities(tmp_path: Path) -> None:
    """Case 11: no str() coercion for numeric strings."""
    doc = _evidence_doc({"t": "0.5", "f": 0.5})
    with pytest.raises(ValueError, match="must be an int or float, got str"):
        load_posteriors(_write_json(tmp_path, "str.json", doc))


def test_a_rejects_non_object_row(tmp_path: Path) -> None:
    """Case 12: a row that is not a JSON object names the variable."""
    doc = _valid_a_document()
    doc["posteriors"]["W"] = ["t", "f"]
    with pytest.raises(ValueError, match="row for variable 'W' must be a JSON object"):
        load_posteriors(_write_json(tmp_path, "rowlist.json", doc))


# ------------------------------------------- added: strict top-level gates ---
def test_sidecar_rejects_invalid_json(tmp_path: Path) -> None:
    """Added (branch :159-162): malformed JSON text is a ValueError."""
    path = tmp_path / "broken.json"
    path.write_text('{"format": ', encoding="utf-8")
    with pytest.raises(ValueError, match="is not valid JSON"):
        load_posteriors(path)


def test_sidecar_rejects_non_object_top_level(tmp_path: Path) -> None:
    """Added (branch :163-167): a top-level JSON array fails."""
    path = tmp_path / "array.json"
    path.write_text(json.dumps(["format"]), encoding="utf-8")
    with pytest.raises(ValueError, match="top level must be a JSON object, got list"):
        load_posteriors(path)


def test_sidecar_rejects_missing_format_key(tmp_path: Path) -> None:
    """Added (branch :168-171): no 'format' key at all."""
    path = _write_json(tmp_path, "nofmt.json", {"posteriors": {}})
    with pytest.raises(ValueError, match="missing the required 'format' key"):
        load_posteriors(path)


def test_sidecar_rejects_non_string_format(tmp_path: Path) -> None:
    """Added (branch :173-177): 'format' must be a string."""
    doc = _valid_a_document()
    doc["format"] = 42
    with pytest.raises(ValueError, match="'format' must be a string, got int"):
        load_posteriors(_write_json(tmp_path, "fmtint.json", doc))


def test_sidecar_rejects_non_mapping_rows_and_evidence(tmp_path: Path) -> None:
    """Added (branches :206-211, :268-273): rows/evidence must be objects."""
    doc = _valid_a_document()
    doc["posteriors"] = []
    with pytest.raises(ValueError, match="'posteriors' must be a JSON object"):
        load_posteriors(_write_json(tmp_path, "rows.json", doc))
    doc = _valid_a_document()
    doc["evidence"] = ["umbrella"]
    with pytest.raises(ValueError, match="'evidence' must be a JSON object"):
        load_posteriors(_write_json(tmp_path, "evlist.json", doc))


def test_sidecar_overflow_probability_is_rejected(tmp_path: Path) -> None:
    """Added (branch :230-235): an int beyond float range hits the
    OverflowError seam."""
    doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {},
        "posteriors": {"v": {"t": 10**400, "f": -1.0}},
    }
    with pytest.raises(ValueError, match="state 't' is out of float range"):
        load_posteriors(_write_json(tmp_path, "huge.json", doc))


# ---------------------------------------------------- variant B: loader (13) -
def test_b_valid_round_trip_source_model_str_and_null(tmp_path: Path) -> None:
    """Case 13: B loads with .posteriors == marginals rows, .evidence None,
    source_model 'm' and null both accepted."""
    for name, source_model in (("str", "m"), ("null", None)):
        path = _write_json(tmp_path, f"b_{name}.json", _valid_b_document(source_model))
        sidecar = load_posteriors(path)
        assert isinstance(sidecar, PosteriorsSidecar)
        assert sidecar.format == FORMAT_MARGINALS
        assert sidecar.posteriors == {"m1": {"a": 0.25, "b": 0.75}}
        assert sidecar.evidence is None
        assert sidecar.source_model == source_model


def test_b_rejects_non_string_source_model(tmp_path: Path) -> None:
    """Added (branch :307-312): 'source_model' must be a string or null."""
    doc = _valid_b_document(None)
    doc["source_model"] = 42
    with pytest.raises(
        ValueError, match="'source_model' must be a string or null, got int"
    ):
        load_posteriors(_write_json(tmp_path, "srcint.json", doc))


# ------------------------------------------------- variant B: budget (14) ----
def test_b_row_sum_budget_is_length_widened(tmp_path: Path) -> None:
    """Case 14: B budget = ROW_SUM_TOLERANCE + n * ROUNDED_STATE_BUDGET
    (:62-63, :249-253): drift 2.5e-6 on an n=4 row (budget 3e-06) passes;
    3.5e-6 exceeds it and the error names the var and the budget."""
    ok_doc = {
        "format": FORMAT_MARGINALS,
        "marginals": {"m4": {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.2500025}},
        "source_model": None,
    }
    sidecar = load_posteriors(_write_json(tmp_path, "b25.json", ok_doc))
    assert row_sum_deviations(sidecar) == {"m4": 2.4999999999053557e-06}

    bad_doc = dict(
        ok_doc, marginals={"m4": {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.2500035}}
    )
    with pytest.raises(ValueError, match="row-sum budget 3e-06") as excinfo:
        load_posteriors(_write_json(tmp_path, "b35.json", bad_doc))
    assert "'m4'" in str(excinfo.value)


def test_b_budget_asymmetry_against_a_at_receipt_drift(tmp_path: Path) -> None:
    """Case 14 (receipt pin): the wave-1 drift row {0.2 x4, 0.200001} sums
    to nextafter(double(1.000001), 2.0), i.e. deviates exactly
    1.000000000139778e-06 — rejected under A's flat 1e-06 budget but
    accepted under B's widened budget (n=5 -> 3.5e-06)."""
    row = {"a": 0.2, "b": 0.2, "c": 0.2, "d": 0.2, "e": 0.200001}
    with pytest.raises(ValueError, match="row-sum budget 1e-06"):
        load_posteriors(
            _write_json(
                tmp_path, "asym_a.json",
                {
                    "format": FORMAT_POSTERIORS,
                    "evidence": {},
                    "posteriors": {"P": dict(row)},
                },
            )
        )
    sidecar = load_posteriors(
        _write_json(
            tmp_path, "asym_b.json",
            {
                "format": FORMAT_MARGINALS,
                "marginals": {"P": dict(row)},
                "source_model": None,
            },
        )
    )
    assert row_sum_deviations(sidecar) == {"P": 1.000000000139778e-06}


# ------------------------------------------------------- B/A dispatch (15-16) -
def test_dispatch_rejects_sibling_only_fields(tmp_path: Path) -> None:
    """Case 15: B files may not carry 'evidence'; A files may not carry
    'source_model' — each error names the unexpected key (:191-197)."""
    b_doc = _valid_b_document("m")
    b_doc["evidence"] = {"m1": "a"}
    with pytest.raises(ValueError, match="unexpected top-level key") as excinfo:
        load_posteriors(_write_json(tmp_path, "b_ev.json", b_doc))
    assert "['evidence']" in str(excinfo.value)

    a_doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {},
        "posteriors": {},
        "source_model": "m",
    }
    with pytest.raises(ValueError, match="unexpected top-level key") as excinfo:
        load_posteriors(_write_json(tmp_path, "a_src.json", a_doc))
    assert "['source_model']" in str(excinfo.value)


def test_b_rejects_missing_source_model_key(tmp_path: Path) -> None:
    """Case 16: B without 'source_model' names the missing key (:198-203)."""
    doc = {"format": FORMAT_MARGINALS, "marginals": {"m1": {"a": 0.25, "b": 0.75}}}
    with pytest.raises(ValueError, match="missing top-level key") as excinfo:
        load_posteriors(_write_json(tmp_path, "nosrc.json", doc))
    assert "'source_model'" in str(excinfo.value)


# ------------------------------------------------ GraphSpec cross-check (17+) -
def test_graphspec_valid_spec_passes_and_description_ignored(tmp_path: Path) -> None:
    """Case 17: a valid spec passes; 'description' is present and ignored."""
    sidecar_path = _write_json(tmp_path, "a.json", _valid_a_document())
    spec_path = _write_json(tmp_path, "spec.json", _graphspec_document())
    sidecar = load_posteriors(sidecar_path, graphspec=spec_path)
    assert isinstance(sidecar, PosteriorsSidecar)
    assert list(sidecar.posteriors) == ["zeta", "umbrella", "sprinkler", "gauge"]


def _spec_with(**overrides: object) -> dict:
    """The valid spec with top-level keys overridden for failure cases."""
    doc = _graphspec_document()
    doc.update(overrides)
    return doc


def test_graphspec_rejects_wrong_format(tmp_path: Path) -> None:
    """Case 18: a spec with the wrong format names the spec path."""
    sidecar_path = _write_json(tmp_path, "a.json", _valid_a_document())
    spec_path = _write_json(tmp_path, "spec.json", _spec_with(format="nope/9"))
    with pytest.raises(ValueError, match=r"graphspec .*spec\.json.* format must be"):
        load_posteriors(sidecar_path, graphspec=spec_path)


def test_graphspec_rejects_bad_variables_shapes(tmp_path: Path) -> None:
    """Case 19: non-list 'variables' and non-dict/key-less/state-less
    elements each name the spec path and the offender (:333-360)."""
    sidecar_path = _write_json(tmp_path, "a.json", _valid_a_document())

    spec_path = _write_json(tmp_path, "notlist.json", _spec_with(variables={"zeta": []}))
    with pytest.raises(ValueError, match=r"'variables' must be a list, got dict"):
        load_posteriors(sidecar_path, graphspec=spec_path)

    spec_path = _write_json(tmp_path, "elem.json", _spec_with(variables=[3]))
    with pytest.raises(
        ValueError,
        match=r"variables\[0\] must be a JSON object carrying 'key' and 'states'",
    ):
        load_posteriors(sidecar_path, graphspec=spec_path)

    spec_path = _write_json(
        tmp_path, "nokey.json", _spec_with(variables=[{"states": ["no"]}])
    )
    with pytest.raises(
        ValueError, match=r"variables\[0\] must carry a string 'key', got None"
    ):
        load_posteriors(sidecar_path, graphspec=spec_path)

    spec_path = _write_json(
        tmp_path, "nostates.json", _spec_with(variables=[{"key": "zeta"}])
    )
    with pytest.raises(
        ValueError, match=r"variables\['zeta'\] must carry a 'states' list"
    ):
        load_posteriors(sidecar_path, graphspec=spec_path)


def test_graphspec_rejects_unknown_evidence_variable(tmp_path: Path) -> None:
    """Case 20: an evidence variable absent from the spec names the var."""
    sidecar_path = _write_json(tmp_path, "a.json", _valid_a_document())
    spec = _graphspec_document()
    spec["variables"] = spec["variables"][:1]  # keep zeta only
    spec_path = _write_json(tmp_path, "partial.json", spec)
    with pytest.raises(
        ValueError, match="evidence variable 'umbrella' is not defined in graphspec"
    ):
        load_posteriors(sidecar_path, graphspec=spec_path)


def test_graphspec_rejects_unknown_evidence_state(tmp_path: Path) -> None:
    """Added (branch :370-375): an observed state outside the spec's
    states list names var and state."""
    sidecar_path = _write_json(tmp_path, "a.json", _valid_a_document())
    spec = _graphspec_document()
    spec["variables"][1]["states"] = ["no", "yes"]  # drop 't' from umbrella's OWN spec states — the evidence loop (bayesnet_posteriors.py:362-375) runs before the posterior walk
    spec_path = _write_json(tmp_path, "states.json", spec)
    with pytest.raises(
        ValueError,
        match="evidence state 't' of variable 'umbrella' is not among graphspec states",
    ):
        load_posteriors(sidecar_path, graphspec=spec_path)


def test_graphspec_rejects_unknown_posterior_variable_and_state(tmp_path: Path) -> None:
    """Case 21 (branches :376-389): a posterior variable and a posterior
    state absent from the spec each name the offender.

    The evidence cross-check loop (:362-375) runs before the posterior
    walk (:376-389), so these evidence-free sidecars are required to
    reach the posterior direction at all."""
    spec = _graphspec_document()
    spec["variables"] = spec["variables"][:1]  # only zeta
    spec_path = _write_json(tmp_path, "novar.json", spec)
    ghost_doc = {"format": FORMAT_POSTERIORS, "evidence": {},
                 "posteriors": {"ghost": {"a": 1.0}}}
    with pytest.raises(
        ValueError, match="posterior variable 'ghost' is not defined in graphspec"
    ):
        load_posteriors(_write_json(tmp_path, "ghost.json", ghost_doc),
                        graphspec=spec_path)

    spec = _graphspec_document()
    spec["variables"][0]["states"] = ["no", "yes"]  # drop "maybe"
    spec_path = _write_json(tmp_path, "nostate.json", spec)
    zeta_doc = {"format": FORMAT_POSTERIORS, "evidence": {},
                "posteriors": {"zeta": {"no": 0.5, "yes": 0.25, "maybe": 0.25}}}
    with pytest.raises(
        ValueError,
        match="posterior state 'maybe' of variable 'zeta' is not among graphspec states",
    ):
        load_posteriors(_write_json(tmp_path, "zeta.json", zeta_doc),
                        graphspec=spec_path)


def test_missing_files_propagate_filenotfound(tmp_path: Path) -> None:
    """Case 22: a missing sidecar AND a missing graphspec both propagate
    FileNotFoundError (only JSONDecodeError is translated)."""
    sidecar_path = _write_json(tmp_path, "a.json", _valid_a_document())
    spec_path = _write_json(tmp_path, "spec.json", _graphspec_document())
    with pytest.raises(FileNotFoundError):
        load_posteriors(tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        load_posteriors(
            tmp_path / "missing.json", graphspec=tmp_path / "also_missing.json"
        )
    with pytest.raises(FileNotFoundError):
        load_posteriors(sidecar_path, graphspec=tmp_path / "no_spec.json")
    with pytest.raises(FileNotFoundError):
        load_posteriors(tmp_path / "missing.json", graphspec=spec_path)


def test_graphspec_variant_b_skip_and_malformed_spec_payloads(tmp_path: Path) -> None:
    """Branch closers: variant B carries no evidence, so the evidence
    cross-check loop (bayesnet_posteriors.py:362-375) is skipped and the
    posterior walk (:376-389) still runs; malformed spec payloads name the
    spec path (:319 invalid JSON, :323 non-object top level)."""
    sidecar_path = _write_json(
        tmp_path, "b.json",
        {
            "format": FORMAT_MARGINALS,
            "marginals": {"zeta": {"no": 0.5, "yes": 0.25, "maybe": 0.25}},
            "source_model": None,
        },
    )
    spec_path = _write_json(tmp_path, "spec.json", _graphspec_document())
    sidecar = load_posteriors(sidecar_path, graphspec=spec_path)
    assert sidecar.evidence is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(
        ValueError, match=r"graphspec .*broken\.json is not valid JSON"
    ):
        load_posteriors(sidecar_path, graphspec=broken)

    listed = tmp_path / "list.json"
    listed.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(
        ValueError, match=r"graphspec .*list\.json.* top level must be"
    ):
        load_posteriors(sidecar_path, graphspec=listed)


# --------------------------------------------------- row_sum_deviations (23) -
def test_row_sum_deviations_hand_computed(tmp_path: Path) -> None:
    """Case 23: per-variable |sum(row) - 1| (:101-103, :399-404) in
    insertion order; empty posteriors give {}.

    Hand-computed: sum(0.25, 0.25, 0.25, 0.2500009) = 1.0000009 ->
    deviation 9.000000000813912e-07; sum(0.5, 0.5) = 1.0 -> 0.0."""
    doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {},
        "posteriors": {
            "W": {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.2500009},
            "V": {"x": 0.5, "y": 0.5},
        },
    }
    sidecar = load_posteriors(_write_json(tmp_path, "devs.json", doc))
    deviations = row_sum_deviations(sidecar)
    assert list(deviations) == ["W", "V"]
    assert deviations == {"W": 9.000000000813912e-07, "V": 0.0}

    empty = load_posteriors(
        _write_json(
            tmp_path, "empty.json",
            {"format": FORMAT_POSTERIORS, "evidence": {}, "posteriors": {}},
        )
    )
    assert row_sum_deviations(empty) == {}


# ------------------------------------------------ pair_for_calibration (24+) -
def _pairing_sidecar(tmp_path: Path) -> PosteriorsSidecar:
    """Reference rows: R {A: 0.7, B: 0.3}; T {X: 0.5, Y: 0.5} (tie)."""
    doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {},
        "posteriors": {
            "R": {"A": 0.7, "B": 0.3},
            "T": {"X": 0.5, "Y": 0.5},
        },
    }
    return load_posteriors(_write_json(tmp_path, "pairing.json", doc))


def test_pair_str_form_hand_computed(tmp_path: Path) -> None:
    """Case 24: str assignment vs row {A: 0.7, B: 0.3}.

    Brier over the state union: chosen B -> (1.0-0.3)^2 + (0.0-0.7)^2
    = 0.49 + 0.49 = 0.98, pair (0.3, False); chosen A -> (1.0-0.7)^2 +
    (0.0-0.3)^2 = 0.09 + 0.09 = 0.18, pair (0.7, True) — the row's modal
    state is A (:106-116, :519-520)."""
    sidecar = _pairing_sidecar(tmp_path)
    b = pair_for_calibration(sidecar, {"R": "B"})
    assert b.brier_scores["R"] == pytest.approx(0.98)
    assert b.pairs == ((0.3, False),)
    a = pair_for_calibration(sidecar, {"R": "A"})
    assert a.brier_scores["R"] == pytest.approx(0.18)
    assert a.pairs == ((0.7, True),)


def test_pair_dict_form_hand_computed(tmp_path: Path) -> None:
    """Case 25: dict assignment {A: 0.6, B: 0.4} -> Brier (0.6-0.7)^2 +
    (0.4-0.3)^2 = 0.01 + 0.01 = 0.02, pair (0.7, True); the tie fixture
    {X: 0.5, Y: 0.5} reduces to its argmax, which breaks to the first
    maximum in insertion order on both sides."""
    sidecar = _pairing_sidecar(tmp_path)
    b = pair_for_calibration(sidecar, {"R": {"A": 0.6, "B": 0.4}})
    assert b.brier_scores["R"] == pytest.approx(0.02)
    assert b.pairs == ((0.7, True),)
    tie = pair_for_calibration(sidecar, {"T": {"X": 0.5, "Y": 0.5}})
    assert tie.brier_scores["T"] == pytest.approx(0.0)
    assert tie.pairs == ((0.5, True),)  # chosen X: row tie -> first max


def test_pair_partial_pairing_order(tmp_path: Path) -> None:
    """Case 26: unassigned sidecar vars are skipped; the result order
    equals assignment insertion order (P3 then P1).

    Hand-computed: P3 chosen s2 -> (1.0-0.5)^2 + (0.0-0.5)^2 = 0.5, pair
    (0.5, False) (the row tie breaks to modal s1); P1 chosen a ->
    (1.0-0.9)^2 + (0.0-0.1)^2 = 0.01 + 0.01 = 0.02, pair (0.9, True)."""
    doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {},
        "posteriors": {
            "P1": {"a": 0.9, "b": 0.1},
            "P2": {"t": 1.0, "f": 0.0},
            "P3": {"s1": 0.5, "s2": 0.5},
        },
    }
    sidecar = load_posteriors(_write_json(tmp_path, "partial.json", doc))
    pairing = pair_for_calibration(sidecar, {"P3": "s2", "P1": "a"})
    assert list(pairing.brier_scores) == ["P3", "P1"]
    assert pairing.brier_scores == {"P3": 0.5, "P1": pytest.approx(0.02)}
    assert pairing.pairs == ((0.5, False), (0.9, True))


def test_pair_rejects_unknown_assignment_variable(tmp_path: Path) -> None:
    """Case 27: an assignment variable absent from the sidecar names it."""
    sidecar = _pairing_sidecar(tmp_path)
    with pytest.raises(ValueError, match="assignment variable 'nope' is not present"):
        pair_for_calibration(sidecar, {"nope": "A"})


def test_pair_state_vocabulary_is_the_row(tmp_path: Path) -> None:
    """Case 28: a str chosen state and a dict state outside the row both
    fail; the row defines the vocabulary (:463-469, :496-502)."""
    sidecar = _pairing_sidecar(tmp_path)
    with pytest.raises(
        ValueError, match="assignment state 'C' of variable 'R' is not among"
    ):
        pair_for_calibration(sidecar, {"R": "C"})
    with pytest.raises(ValueError, match="the row defines the vocabulary") as excinfo:
        pair_for_calibration(sidecar, {"R": {"A": 0.5, "Z": 0.5}})
    assert "'Z'" in str(excinfo.value)


def test_pair_dict_form_rejects_invalid_probabilities(tmp_path: Path) -> None:
    """Case 29: dict assignments reject negative/non-finite/bool/string
    probabilities and row-sum breaches, naming var and state (:472-508)."""
    sidecar = _pairing_sidecar(tmp_path)
    bads = [
        ({"A": -0.1, "B": 1.1}, "must be >= 0, got -0.1"),
        ({"A": float("nan"), "B": 1.0}, "must be finite, got nan"),
        ({"A": True, "B": 0.0}, "must be an int or float, got bool"),
        ({"A": "0.5", "B": 0.5}, "must be an int or float, got str"),
        ({"A": 0.7, "B": 0.4}, "sums to 1.1, deviating more than 1e-06"),
    ]
    for assignment, match in bads:
        with pytest.raises(ValueError, match=match):
            pair_for_calibration(sidecar, {"R": assignment})


def test_pair_rejects_non_str_non_mapping_assignment(tmp_path: Path) -> None:
    """Case 30: an assignment that is neither str nor mapping names the
    variable and the value's type (:447-451)."""
    sidecar = _pairing_sidecar(tmp_path)
    with pytest.raises(ValueError, match="must be a state name") as excinfo:
        pair_for_calibration(sidecar, {"R": 3})  # type: ignore[arg-type]
    assert "got int" in str(excinfo.value)
    assert "'R'" in str(excinfo.value)


def test_pair_accepts_integer_distribution(tmp_path: Path) -> None:
    """Added: integer assignment probabilities are valid numbers.

    {A: 1, B: 0} vs row {A: 0.7, B: 0.3} -> Brier (1.0-0.7)^2 +
    (0.0-0.3)^2 = 0.18, chosen A, pair (0.7, True)."""
    sidecar = _pairing_sidecar(tmp_path)
    pairing = pair_for_calibration(sidecar, {"R": {"A": 1, "B": 0}})
    assert pairing.brier_scores["R"] == pytest.approx(0.18)
    assert pairing.pairs == ((0.7, True),)


def test_pair_rejects_empty_sidecar_row() -> None:
    """Added (branch :458-462): an empty row cannot be paired against.

    Unreachable through load_posteriors (an empty row deviates 1.0 from
    1.0, far beyond every row-sum budget), so the frozen dataclass is
    constructed directly — no patching involved."""
    sidecar = PosteriorsSidecar(
        format=FORMAT_POSTERIORS, posteriors={"E": {}}, evidence=None, source_model=None
    )
    with pytest.raises(ValueError, match="row for variable 'E' is empty; cannot pair"):
        pair_for_calibration(sidecar, {"E": "t"})


# ------------------------------------------------ calibration consumption (31) -
def test_pairs_feed_calibration_statistics(tmp_path: Path) -> None:
    """Case 31: pairs from pair_for_calibration feed the daf_jev.calibration
    statistics end-to-end.

    Bucket edges (calibration.py:24-34): index i covers [i/10, (i+1)/10),
    the final bucket closed at 1.0 — bucket_index(0.3) = 3 so the pair
    (0.3, False) lands in bucket [0.3, 0.4); bucket_index(0.7) = 7 so
    (0.7, True) lands in bucket [0.7, 0.8).

    Hand-computed: reliability row n=1 mean_confidence=0.3 accuracy=0.0
    and n=1 mean_confidence=0.7 accuracy=1.0;
    ECE = (1/2)|0.0-0.3| + (1/2)|1.0-0.7| = 0.15 + 0.15 = 0.3;
    brier_score = ((0.3-0)^2 + (0.7-1)^2)/2 = (0.09 + 0.09)/2 = 0.09."""
    doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {},
        "posteriors": {
            "R1": {"A": 0.7, "B": 0.3},
            "R2": {"A": 0.7, "B": 0.3},
        },
    }
    sidecar = load_posteriors(_write_json(tmp_path, "cal.json", doc))
    pairing = pair_for_calibration(sidecar, {"R1": "B", "R2": "A"})
    assert pairing.pairs == ((0.3, False), (0.7, True))
    assert brier_score(pairing.pairs) == pytest.approx(0.09)
    table = reliability_table(pairing.pairs)
    assert table == [
        {
            "bucket_lo": 0.3,
            "bucket_hi": 0.4,
            "n": 1,
            "mean_confidence": pytest.approx(0.3),
            "accuracy": pytest.approx(0.0),
        },
        {
            "bucket_lo": 0.7,
            "bucket_hi": 0.8,
            "n": 1,
            "mean_confidence": pytest.approx(0.7),
            "accuracy": pytest.approx(1.0),
        },
    ]
    assert expected_calibration_error(pairing.pairs) == pytest.approx(0.3)


# ------------------------------------------------------------- CLI (32-36) ---
def test_cli_ok_path_prints_six_field_summary(tmp_path: Path, capsys) -> None:
    """Case 32: a valid sidecar exits 0 and prints exactly the six pinned
    fields to stdout.

    Hand-computed: zeta and umbrella rows sum to exactly 1.0 (dev 0.0);
    the 0.25 x3 + 0.2500009 row deviates 9.000000000813912e-07 -> min 0.0,
    max 9.000000000813912e-07; evidence_count 2, variable_count 4."""
    path = _write_json(tmp_path, "a.json", _valid_a_document())
    assert run_cli(["posteriors-load", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "ok",
        "format",
        "evidence_count",
        "variable_count",
        "min_row_sum_deviation",
        "max_row_sum_deviation",
    }
    assert payload["ok"] is True
    assert payload["format"] == FORMAT_POSTERIORS
    assert payload["evidence_count"] == 2
    assert payload["variable_count"] == 4
    assert payload["min_row_sum_deviation"] == 0.0
    assert payload["max_row_sum_deviation"] == pytest.approx(9.000000000813912e-07)


def test_cli_validation_error_exits_one(tmp_path: Path, capsys) -> None:
    """Case 33: a validation error emits {error, message} JSON on stderr
    and exits 1 (house _cmd_docs_verify convention); stdout stays empty."""
    doc = _valid_a_document()
    doc["format"] = "dafjev.bayesnet-posteriors/2"
    path = _write_json(tmp_path, "bad.json", doc)

    assert run_cli(["posteriors-load", str(path)]) == 1
    out = capsys.readouterr()
    assert out.out == ""
    payload = json.loads(out.err)
    assert set(payload) == {"error", "message"}
    assert payload["error"] == "ValueError"
    assert "unsupported format 'dafjev.bayesnet-posteriors/2'" in payload["message"]


def test_cli_usage_errors_exit_two(tmp_path: Path, capsys) -> None:
    """Case 34: argparse usage errors are NOT intercepted into JSON —
    SystemExit(2) with usage text on stderr, per the run_cli helper."""
    path = _write_json(tmp_path, "a.json", _valid_a_document())
    assert run_cli(["posteriors-load"]) == 2
    missing_file_err = capsys.readouterr().err
    assert "usage:" in missing_file_err
    assert run_cli(["posteriors-load", str(path), "--bogus"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_cli_graphspec_passthrough(tmp_path: Path, capsys) -> None:
    """Case 35: --graphspec passes through to the loader — a defining spec
    exits 0; a spec missing a posterior variable exits 1 naming the var."""
    sidecar_path = _write_json(tmp_path, "a.json", _valid_a_document())
    spec_path = _write_json(tmp_path, "spec.json", _graphspec_document())
    assert run_cli(["posteriors-load", str(sidecar_path), "--graphspec", str(spec_path)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    # Spec missing 'umbrella': the evidence loop is skipped (no evidence) so
    # the posterior walk is what fails, naming the unregistered variable.
    spec = _graphspec_document()
    spec["variables"] = spec["variables"][:1]  # only zeta defined
    failing_spec_path = _write_json(tmp_path, "partial.json", spec)

    doc = {
        "format": FORMAT_POSTERIORS,
        "evidence": {},
        "posteriors": {"umbrella": {"t": 1.0, "f": 0.0}},
    }
    failing_sidecar_path = _write_json(tmp_path, "unregistered.json", doc)
    assert run_cli(["posteriors-load", str(failing_sidecar_path),
                    "--graphspec", str(failing_spec_path)]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "ValueError"
    assert "posterior variable 'umbrella' is not defined in graphspec" in payload["message"]


def test_cli_empty_posteriors_zero_summary(tmp_path: Path, capsys) -> None:
    """Case 36: empty posteriors and evidence -> min/max 0.0, counts 0."""
    path = _write_json(
        tmp_path, "empty.json",
        {"format": FORMAT_POSTERIORS, "evidence": {}, "posteriors": {}},
    )
    assert run_cli(["posteriors-load", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["evidence_count"] == 0
    assert payload["variable_count"] == 0
    assert payload["min_row_sum_deviation"] == 0.0
    assert payload["max_row_sum_deviation"] == 0.0


# ------------------------------------------------------------------ MCP (37+) -
def _mcp_server_module():
    """The MCP server module, only when mcp is installed (test_mcp_server.py
    :22-25 guard style, mirrored in-file so loader tests never skip)."""
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


def test_mcp_ok_dict(tmp_path: Path) -> None:
    """Case 37: the ok path returns the six-field summary via a direct
    coroutine call (values as in the CLI ok case)."""
    ms = _mcp_server_module()
    path = _write_json(tmp_path, "a.json", _valid_a_document())
    result = _run(ms.jev_posteriors_load(str(path)))
    assert set(result) == {
        "ok",
        "format",
        "evidence_count",
        "variable_count",
        "min_row_sum_deviation",
        "max_row_sum_deviation",
    }
    assert result["ok"] is True
    assert result["format"] == FORMAT_POSTERIORS
    assert result["evidence_count"] == 2
    assert result["variable_count"] == 4
    assert result["min_row_sum_deviation"] == 0.0
    assert result["max_row_sum_deviation"] == pytest.approx(9.000000000813912e-07)


def test_mcp_invalid_document_is_error_dict(tmp_path: Path) -> None:
    """Case 38: a ValueError becomes {error, message, ok: False} (only
    ValueError is caught; jev_docs_verify :373-374 style)."""
    ms = _mcp_server_module()
    doc = _valid_a_document()
    doc["format"] = "dafjev.bayesnet-posteriors/2"
    path = _write_json(tmp_path, "bad.json", doc)
    result = _run(ms.jev_posteriors_load(str(path)))
    assert set(result) == {"error", "message", "ok"}
    assert result["ok"] is False
    assert result["error"] == "ValueError"
    assert "unsupported format 'dafjev.bayesnet-posteriors/2'" in result["message"]


def test_mcp_graphspec_path_passthrough(tmp_path: Path) -> None:
    """Case 39: graphspec_path passes through — ok on a defining spec and
    an error dict naming the offender on a cross-check failure."""
    ms = _mcp_server_module()
    sidecar_path = _write_json(tmp_path, "a.json", _valid_a_document())
    spec_path = _write_json(tmp_path, "spec.json", _graphspec_document())
    result = _run(
        ms.jev_posteriors_load(str(sidecar_path), graphspec_path=str(spec_path))
    )
    assert result["ok"] is True

    spec = _graphspec_document()
    spec["variables"] = spec["variables"][:1]  # only zeta
    failing_spec_path = _write_json(tmp_path, "partial.json", spec)
    evidence_free = {"format": FORMAT_POSTERIORS, "evidence": {},
                     "posteriors": {"umbrella": {"t": 0.6, "f": 0.4}}}
    result = _run(
        ms.jev_posteriors_load(
            str(_write_json(tmp_path, "umbrella.json", evidence_free)),
            graphspec_path=str(failing_spec_path),
        )
    )
    assert result["ok"] is False
    assert "posterior variable 'umbrella'" in result["message"]


def test_mcp_missing_file_propagates_filenotfound(tmp_path: Path) -> None:
    """Added: FileNotFoundError is not caught by the tool — it raises
    (mirrors jev_docs_verify)."""
    ms = _mcp_server_module()
    with pytest.raises(FileNotFoundError):
        _run(ms.jev_posteriors_load(str(tmp_path / "missing.json")))


def test_mcp_registration_includes_jev_posteriors_load() -> None:
    """Case 40: jev_posteriors_load is among build_server's tool names."""
    ms = _mcp_server_module()
    server = ms.build_server()
    tools = _run(_tool_names(server))
    assert "jev_posteriors_load" in tools


# ------------------------------------------------------------- re-exports (41) -
def test_public_reexports_are_the_module_objects() -> None:
    """Case 41: the four public names re-exported from daf_jev are the
    bayesnet_posteriors objects themselves (__init__.py:28-33)."""
    import daf_jev

    assert daf_jev.load_posteriors is load_posteriors
    assert daf_jev.PosteriorsSidecar is PosteriorsSidecar
    assert daf_jev.pair_for_calibration is pair_for_calibration
    assert daf_jev.CalibrationPairing is CalibrationPairing