"""Unit tests for daf_jev.stack_roster: strict parsing and read-only audit.

The roster fixture mirrors the contract daf-stack emits from
``daf-stack-doctor roster``; the audit tests use real temporary
directories, never mocks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from daf_jev.cli import main
from daf_jev.stack_roster import (
    DEFAULT_MEMBER,
    RosterRepo,
    StackRoster,
    UnknownMemberError,
    audit_member,
    load_roster,
    parse_roster,
)


def run_cli(argv: list[str]) -> int:
    """main() returns an exit code; argparse usage errors raise SystemExit(2)."""
    try:
        code = main(argv)
    except SystemExit as exc:
        code = exc.code
    return 0 if code is None else int(code)


# --------------------------------------------------------------- fixtures ----


def entry(**overrides: Any) -> dict[str, Any]:
    """One roster entry in daf-stack's documented shape."""
    base: dict[str, Any] = {
        "name": DEFAULT_MEMBER,
        "path": "/roster/daf-jev",
        "branch": "main",
        "require_board": True,
        "require_sidecar": False,
        "gate_cmd": "bash scripts/gate.sh",
        "required_files": ["AGENTS.md", "tasks.yaml"],
        "board_path": "/roster/daf-jev/tasks.yaml",
    }
    base.update(overrides)
    return base


def roster(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"daf_root": "/roster", "repos": list(entries) or [entry()]}


def write_roster(tmp_path: Path, payload: Any) -> Path:
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def make_checkout(root: Path, files: tuple[str, ...] = ("AGENTS.md", "tasks.yaml")) -> Path:
    for rel in files:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------- parsing ----


def test_parse_roster_exposes_the_declared_contract() -> None:
    parsed = parse_roster(roster())

    assert parsed.daf_root == "/roster"
    assert parsed.repos == (
        RosterRepo(
            name="daf-jev",
            path="/roster/daf-jev",
            branch="main",
            require_board=True,
            require_sidecar=False,
            gate_cmd="bash scripts/gate.sh",
            required_files=("AGENTS.md", "tasks.yaml"),
            board_path="/roster/daf-jev/tasks.yaml",
        ),
    )


def test_parse_roster_allows_optional_fields_and_empty_required_files() -> None:
    parsed = parse_roster(
        roster(
            entry(
                branch=None,
                gate_cmd=None,
                board_path=None,
                require_board=False,
                required_files=[],
            )
        )
    )
    repo = parsed.member()

    assert repo.branch is None
    assert repo.gate_cmd is None
    assert repo.board_path is None
    assert repo.required_files == ()


def test_parse_roster_accepts_tuples_from_programmatic_callers() -> None:
    parsed = parse_roster({"daf_root": "/roster", "repos": (entry(required_files=("a",)),)})

    assert parsed.repos[0].required_files == ("a",)


def test_load_roster_reads_a_document(tmp_path: Path) -> None:
    path = write_roster(tmp_path, roster())

    assert load_roster(path).member().name == DEFAULT_MEMBER


def test_load_roster_rejects_duplicate_object_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"daf_root": "/roster", "daf_root": "/other", "repos": []}')

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_roster(path)


def test_load_roster_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid roster JSON"):
        load_roster(path)


def test_load_roster_rejects_unreadable_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot read roster"):
        load_roster(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "roster must be a JSON object"),
        ({"repos": [entry()]}, "missing required field 'daf_root'"),
        ({"daf_root": "relative", "repos": [entry()]}, "roster.daf_root must be an absolute path"),
        ({"daf_root": "/roster", "repos": []}, "roster.repos must be a non-empty list"),
        ({"daf_root": "/roster", "repos": "daf-jev"}, "roster.repos must be a non-empty list"),
        ({"daf_root": "/roster", "repos": ["daf-jev"]}, "roster.repos[0] must be a JSON object"),
        ({"daf_root": "/roster", "repos": [{"path": "/x"}]}, "missing required field 'name'"),
        (roster(entry(name="")), "roster.repos[0].name must be a non-empty string"),
        (roster(entry(), entry()), "is listed twice"),
        (roster({"name": "x"}), "missing required field 'path'"),
        (roster(entry(path="relative")), "roster.repos[0].path must be an absolute path"),
        (roster(entry(branch="")), "roster.repos[0].branch must be a non-empty string"),
        (roster(entry(require_board=1)), "roster.repos[0].require_board must be a boolean"),
        (roster(entry(require_sidecar="false")), "roster.repos[0].require_sidecar must be a boolean"),
        (roster(entry(gate_cmd="")), "roster.repos[0].gate_cmd must be a non-empty string"),
        (roster(entry(required_files="AGENTS.md")), "roster.repos[0].required_files must be a list"),
        (roster(entry(required_files=["/etc/passwd"])), "must be a relative path inside the repo"),
        (roster(entry(required_files=["../outside"])), "must be a relative path inside the repo"),
        (roster(entry(required_files=[1])), "roster.repos[0].required_files[0] must be a non-empty string"),
        (roster(entry(board_path="tasks.yaml")), "roster.repos[0].board_path must be an absolute path"),
    ],
)
def test_parse_roster_rejects_malformed_documents(payload: Any, message: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_roster(payload)

    assert message in str(excinfo.value)


# ----------------------------------------------------------------- lookup ----


def test_member_selects_by_name() -> None:
    parsed = parse_roster(roster(entry(), entry(name="daf-operator", path="/roster/daf-operator")))

    assert parsed.member("daf-operator").path == "/roster/daf-operator"


def test_member_reports_unknown_names_with_the_known_set() -> None:
    parsed = parse_roster(roster())

    with pytest.raises(UnknownMemberError) as excinfo:
        parsed.member("daf-missing")

    assert "daf-missing" in str(excinfo.value)
    assert "daf-jev" in str(excinfo.value)


# ------------------------------------------------------------------ audit ----


def test_audit_reports_a_conforming_member(tmp_path: Path) -> None:
    checkout = make_checkout(tmp_path / "checkout")
    parsed = parse_roster(roster(entry(path=str(checkout))))

    audit = audit_member(parsed)

    assert audit.ok is True
    assert audit.root_exists is True
    assert audit.missing == ()
    payload = audit.to_dict()
    assert payload["format"] == "dafjev.stack-member/1"
    assert payload["repo"] == DEFAULT_MEMBER
    assert payload["root"] == str(checkout)
    assert payload["declared_path"] == str(checkout)
    assert payload["branch"] == "main"
    assert payload["require_board"] is True
    assert payload["require_sidecar"] is False
    assert payload["gate_cmd"] == "bash scripts/gate.sh"
    assert payload["board_path"] == "/roster/daf-jev/tasks.yaml"
    assert payload["missing"] == []
    assert payload["ok"] is True
    assert json.loads(json.dumps(payload)) == payload


def test_audit_lists_missing_declared_files(tmp_path: Path) -> None:
    checkout = make_checkout(tmp_path / "checkout", files=("AGENTS.md",))
    parsed = parse_roster(roster(entry(path=str(checkout))))

    audit = audit_member(parsed)

    assert audit.ok is False
    assert audit.root_exists is True
    assert audit.missing == ("tasks.yaml",)


def test_audit_treats_a_missing_root_as_a_failure(tmp_path: Path) -> None:
    parsed = parse_roster(roster(entry(path=str(tmp_path / "absent"))))

    audit = audit_member(parsed)

    assert audit.ok is False
    assert audit.root_exists is False
    assert audit.missing == ("AGENTS.md", "tasks.yaml")


def test_audit_root_override_uses_the_given_checkout(tmp_path: Path) -> None:
    checkout = make_checkout(tmp_path / "moved")
    parsed = parse_roster(roster(entry(path=str(tmp_path / "stale"))))

    audit = audit_member(parsed, root=checkout)

    assert audit.ok is True
    assert audit.root == str(checkout)
    assert audit.repo.path == str(tmp_path / "stale")


def test_audit_root_override_must_be_a_directory(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")
    parsed = parse_roster(roster())

    with pytest.raises(ValueError, match="must be an existing directory"):
        audit_member(parsed, root=target)


def test_audit_of_an_empty_required_file_list_checks_the_root_only(
    tmp_path: Path,
) -> None:
    checkout = make_checkout(tmp_path / "checkout", files=("AGENTS.md",))
    parsed = parse_roster(roster(entry(path=str(checkout), required_files=[])))

    assert audit_member(parsed).ok is True

    parsed = parse_roster(
        roster(entry(path=str(tmp_path / "absent"), required_files=[]))
    )
    assert audit_member(parsed).ok is False


# -------------------------------------------------------------------- CLI ----


def test_cli_reports_a_conforming_member(tmp_path: Path, capsys) -> None:
    checkout = make_checkout(tmp_path / "checkout")
    path = write_roster(tmp_path, roster(entry(path=str(checkout))))

    assert run_cli(["stack-member", str(path), "--pretty"]) == 0

    stdout = json.loads(capsys.readouterr().out)
    assert stdout["format"] == "dafjev.stack-member/1"
    assert stdout["ok"] is True
    assert stdout["missing"] == []


def test_cli_exits_one_for_missing_files(tmp_path: Path, capsys) -> None:
    checkout = make_checkout(tmp_path / "checkout", files=("AGENTS.md",))
    path = write_roster(tmp_path, roster(entry(path=str(checkout))))

    assert run_cli(["stack-member", str(path)]) == 1

    stdout = json.loads(capsys.readouterr().out)
    assert stdout["ok"] is False
    assert stdout["missing"] == ["tasks.yaml"]


def test_cli_honours_repo_and_root_overrides(tmp_path: Path, capsys) -> None:
    checkout = make_checkout(tmp_path / "checkout")
    other = entry(name="daf-operator", path=str(tmp_path / "stale"))
    path = write_roster(tmp_path, roster(entry(path=str(tmp_path / "stale")), other))

    assert run_cli(["stack-member", str(path), "--repo", "daf-operator", "--root", str(checkout)]) == 0

    stdout = json.loads(capsys.readouterr().out)
    assert stdout["repo"] == "daf-operator"
    assert stdout["root"] == str(checkout)


def test_cli_unknown_repo_is_a_usage_error(tmp_path: Path, capsys) -> None:
    path = write_roster(tmp_path, roster())

    assert run_cli(["stack-member", str(path), "--repo", "daf-missing"]) == 2

    stderr = json.loads(capsys.readouterr().err)
    assert stderr["error"] == "UsageError"


def test_cli_malformed_roster_exits_one(tmp_path: Path, capsys) -> None:
    path = write_roster(tmp_path, {"daf_root": "/roster", "repos": []})

    assert run_cli(["stack-member", str(path)]) == 1

    stderr = json.loads(capsys.readouterr().err)
    assert stderr["error"] == "ValueError"
    assert "roster.repos" in stderr["message"]


def test_cli_missing_roster_file_exits_one(tmp_path: Path, capsys) -> None:
    assert run_cli(["stack-member", str(tmp_path / "absent.json")]) == 1

    stderr = json.loads(capsys.readouterr().err)
    assert stderr["error"] == "ValueError"


def test_cli_requires_the_roster_argument(capsys) -> None:
    assert run_cli(["stack-member"]) == 2
    assert capsys.readouterr().err


# ------------------------------------------------- real external membership ----


def test_checkout_satisfies_the_stack_declared_required_files() -> None:
    """This checkout's own files meet the membership daf-stack declares.

    The entry mirrors daf-stack's built-in manifest for daf-jev (name,
    required_files and gate); losing one of those files would silently break
    the external membership, so this test binds it locally.
    """
    checkout = Path(__file__).resolve().parents[2]
    declared = entry(
        path=str(checkout),
        require_board=True,
        gate_cmd="bash scripts/gate.sh",
        required_files=[
            "AGENTS.md",
            "README.md",
            "pyproject.toml",
            "uv.lock",
            "scripts/gate.sh",
            "tasks.yaml",
        ],
        board_path=str(checkout / "tasks.yaml"),
    )
    parsed = parse_roster(roster(declared))

    audit = audit_member(parsed)

    assert isinstance(parsed, StackRoster)
    assert audit.ok is True
    assert audit.missing == ()
