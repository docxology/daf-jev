"""Read-only consumer of the daf-stack roster contract (no I/O beyond reads).

daf-stack owns the stack manifest and exposes it to sibling repositories as
plain JSON through ``daf-stack-doctor roster``:

``{"daf_root": <absolute path>, "repos": [{name, path, branch, require_board,
require_sidecar, gate_cmd, required_files, board_path}, ...]}``

This module parses that document strictly and audits one member (``daf-jev``
by default) against its declared ``required_files``. It reads filesystem
entries only: it never runs the declared gate, git, the Sidecar CLI, or any
other subprocess, and it never writes. Unknown extra fields are ignored so a
newer daf-stack release stays readable, but every documented field must be
present with its documented type; a malformed roster fails closed.

The CLI (``daf-jev stack-member``) routes through here, so the audit payload
is defined exactly once:

``{"format": "dafjev.stack-member/1", "repo", "root", "declared_path",
"branch", "require_board", "require_sidecar", "gate_cmd", "board_path",
"root_exists", "missing", "ok"}`` where ``ok`` is True only when the root
exists and every declared required file is present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from daf_jev._json import strict_json_loads

__all__ = [
    "DEFAULT_MEMBER",
    "MemberAudit",
    "RosterRepo",
    "StackRoster",
    "UnknownMemberError",
    "audit_member",
    "load_roster",
    "parse_roster",
]

#: The member this package audits unless another name is requested.
DEFAULT_MEMBER = "daf-jev"

FORMAT = "dafjev.stack-member/1"


class UnknownMemberError(LookupError):
    """The roster lists no repository with the requested name."""


def _field(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ValueError(f"{context}: missing required field {key!r}")
    return mapping[key]


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _optional_string(value: Any, context: str) -> str | None:
    if value is None:
        return None
    return _string(value, context)


def _absolute(value: Any, context: str) -> str:
    text = _string(value, context)
    if not os.path.isabs(text):
        raise ValueError(f"{context} must be an absolute path")
    return text


def _flag(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _required_files(value: Any, context: str) -> tuple[str, ...]:
    # An empty list is legitimate: daf-stack declares required_files as
    # optional extras, so a member with nothing extra still emits [].
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{context} must be a list of relative paths")
    files: list[str] = []
    for index, item in enumerate(value):
        text = _string(item, f"{context}[{index}]")
        pure = PurePosixPath(text)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(
                f"{context}[{index}] must be a relative path inside the repo"
            )
        files.append(text)
    return tuple(files)


@dataclass(frozen=True)
class RosterRepo:
    """One repository entry exactly as daf-stack declared it."""

    name: str
    path: str
    branch: str | None
    require_board: bool
    require_sidecar: bool
    gate_cmd: str | None
    required_files: tuple[str, ...]
    board_path: str | None


@dataclass(frozen=True)
class StackRoster:
    """A parsed roster document (daf-stack's repository registry)."""

    daf_root: str
    repos: tuple[RosterRepo, ...]

    def member(self, name: str = DEFAULT_MEMBER) -> RosterRepo:
        """Return the named entry; raise :class:`UnknownMemberError`."""
        for repo in self.repos:
            if repo.name == name:
                return repo
        known = ", ".join(repo.name for repo in self.repos)
        raise UnknownMemberError(f"roster lists no repo {name!r} (known: {known})")


@dataclass(frozen=True)
class MemberAudit:
    """Read-only membership result for one roster entry."""

    repo: RosterRepo
    root: str
    root_exists: bool
    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.root_exists and not self.missing

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe payload in the documented ``dafjev.stack-member/1`` shape."""
        return {
            "format": FORMAT,
            "repo": self.repo.name,
            "root": self.root,
            "declared_path": self.repo.path,
            "branch": self.repo.branch,
            "require_board": self.repo.require_board,
            "require_sidecar": self.repo.require_sidecar,
            "gate_cmd": self.repo.gate_cmd,
            "board_path": self.repo.board_path,
            "root_exists": self.root_exists,
            "missing": list(self.missing),
            "ok": self.ok,
        }


def parse_roster(value: Any) -> StackRoster:
    """Strictly parse a decoded roster document.

    Duplicate JSON keys are rejected earlier by :func:`load_roster`;
    callers decoding the document themselves must use
    :func:`daf_jev._json.strict_json_loads` to keep that guarantee.
    """
    if not isinstance(value, dict):
        raise ValueError("roster must be a JSON object")
    daf_root = _absolute(_field(value, "daf_root", "roster"), "roster.daf_root")
    raw_repos = _field(value, "repos", "roster")
    if not isinstance(raw_repos, (list, tuple)) or not raw_repos:
        raise ValueError("roster.repos must be a non-empty list")
    repos: list[RosterRepo] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_repos):
        context = f"roster.repos[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{context} must be a JSON object")
        name = _string(_field(entry, "name", context), f"{context}.name")
        if name in seen:
            raise ValueError(f"{context}.name {name!r} is listed twice")
        seen.add(name)
        repo = RosterRepo(
            name=name,
            path=_absolute(_field(entry, "path", context), f"{context}.path"),
            branch=_optional_string(
                _field(entry, "branch", context), f"{context}.branch"
            ),
            require_board=_flag(
                _field(entry, "require_board", context), f"{context}.require_board"
            ),
            require_sidecar=_flag(
                _field(entry, "require_sidecar", context),
                f"{context}.require_sidecar",
            ),
            gate_cmd=_optional_string(
                _field(entry, "gate_cmd", context), f"{context}.gate_cmd"
            ),
            required_files=_required_files(
                _field(entry, "required_files", context), f"{context}.required_files"
            ),
            board_path=(
                None
                if (board_path := _field(entry, "board_path", context)) is None
                else _absolute(board_path, f"{context}.board_path")
            ),
        )
        repos.append(repo)
    return StackRoster(daf_root=daf_root, repos=tuple(repos))


def load_roster(path: str | Path) -> StackRoster:
    """Read and strictly parse a roster JSON document from ``path``."""
    roster_path = Path(path)
    try:
        raw = roster_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read roster {roster_path}: {exc}") from exc
    try:
        decoded = strict_json_loads(raw)
    except ValueError as exc:
        raise ValueError(f"invalid roster JSON in {roster_path}: {exc}") from exc
    return parse_roster(decoded)


def audit_member(
    roster: StackRoster,
    name: str = DEFAULT_MEMBER,
    *,
    root: str | Path | None = None,
) -> MemberAudit:
    """Check one member's declared required files under its root.

    ``root`` overrides the roster's declared path (for a copy, install or
    checkout moved since the roster was produced); an explicit root that is
    not a directory raises ``ValueError``. A missing declared root is an
    audit failure, not an error, so the payload keeps every finding.
    """
    repo = roster.member(name)
    if root is None:
        target = Path(repo.path)
    else:
        target = Path(root).absolute()
        if not target.is_dir():
            raise ValueError(f"root {target} must be an existing directory")
    exists = target.is_dir()
    missing = tuple(
        rel for rel in repo.required_files if not (target / rel).exists()
    )
    return MemberAudit(
        repo=repo, root=str(target), root_exists=exists, missing=missing
    )
