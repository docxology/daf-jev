"""``daf-jev`` command-line interface.

Thin argparse front end over :mod:`daf_jev.client`. Results are JSON on
stdout; errors are JSON on stderr. Exit codes: 0 ok, 1 runtime error,
2 usage error.

Usage::

    daf-jev ask (--state-file FILE | --state TEXT)
                [--question ID=SPEC ...] [--model M] [--base-url URL]
                [--json | --pretty]
    daf-jev models [--base-url URL] [--pick latest|first|last]
                [--contains STR] [--json | --pretty]
    daf-jev evaluate --questions-file PATH --states-file PATH
                [--concurrency N] [--model M] [--base-url URL]
                [--include-records] [--json | --pretty]
    daf-jev docs-verify [--manifest PATH] [--json | --pretty]

Question SPEC grammar (commas may be escaped as ``\\,``):

- ``noul:<instructions>``
- ``choice:<instructions>:opt1=desc,opt2=...`` (empty description -> None)
- ``score:<instructions>:level1,level2,...`` (>= 2 levels)
- ``evaluate --questions-file``: YAML mapping id -> SPEC string (grammar
  above) or id -> native mapping ``{type, instructions, criteria}``.
- ``evaluate --states-file``: one state per line (blank lines skipped)
  or a JSON array of strings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

from daf_jev import config

DEFAULT_MANIFEST = Path("docs/reference/MANIFEST.json")

__all__ = ["main", "parse_question_spec"]


# ---------------------------------------------------------------- questions


def _split_unescaped_commas(text: str) -> list[str]:
    """Split on commas, honoring ``\\,`` (and ``\\\\``) escapes."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in (",", "\\"):
            current.append(text[i + 1])
            i += 2
            continue
        if ch == ",":
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return parts


def parse_question_spec(spec: str) -> Any:
    """Parse a question SPEC into a ``daf_jev`` question object.

    The type is taken before the first ``:``; for ``choice``/``score`` the
    criteria segment starts after the last ``:`` so instructions may contain
    colons. Commas in options/levels are escaped as ``\\,``. Raises
    ``ValueError`` on malformed specs.
    """
    from daf_jev._types import ChoiceQuestion, NoulQuestion, ScoreQuestion

    qtype, sep, rest = spec.partition(":")
    if not sep or not qtype:
        raise ValueError(
            f"invalid question spec {spec!r}: expected 'noul:<instructions>', "
            f"'choice:<instructions>:k1=desc,k2=...' or 'score:<instructions>:l1,l2,...'"
        )

    if qtype == "noul":
        if not rest:
            raise ValueError(f"invalid noul spec {spec!r}: instructions required")
        return NoulQuestion(instructions=rest)

    instructions, sep, criteria_text = rest.rpartition(":")
    if not sep:
        raise ValueError(
            f"invalid {qtype} spec {spec!r}: expected '<instructions>:<criteria>'"
        )
    if not instructions:
        raise ValueError(f"invalid {qtype} spec {spec!r}: instructions required")

    if qtype == "choice":
        options: dict[str, Optional[str]] = {}
        for item in _split_unescaped_commas(criteria_text):
            key, eq, desc = item.partition("=")
            key = key.strip()
            if not key:
                raise ValueError(
                    f"invalid choice spec {spec!r}: empty option key in {item!r}"
                )
            options[key] = desc.strip() if desc.strip() else None
        if not options:
            raise ValueError(
                f"invalid choice spec {spec!r}: at least one option required"
            )
        return ChoiceQuestion(instructions=instructions, criteria=options)

    if qtype == "score":
        levels = [item.strip() for item in _split_unescaped_commas(criteria_text)]
        if len(levels) < 2 or any(not level for level in levels):
            raise ValueError(
                f"invalid score spec {spec!r}: at least 2 non-empty levels required"
            )
        return ScoreQuestion(instructions=instructions, criteria=levels)

    raise ValueError(
        f"invalid question spec {spec!r}: unknown type {qtype!r} "
        f"(expected noul, choice or score)"
    )


# ------------------------------------------------------------------- output


def _emit(payload: Any, pretty: bool, stream: Any = None) -> None:
    print(
        json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False),
        file=stream or sys.stdout,
    )


def _emit_error(payload: Any, pretty: bool) -> None:
    """Errors are JSON on stderr."""
    _emit(payload, pretty, stream=sys.stderr)


def _state_from_args(args: argparse.Namespace) -> Any:
    text = args.state_file.read_text(encoding="utf-8") if args.state_file else args.state
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _make_client(args: argparse.Namespace) -> Any:
    from daf_jev.client import JevClient

    return JevClient(
        base_url=args.base_url or config.resolve_base_url(),
        model=getattr(args, "model", None) or config.resolve_model(),
    )


def _usage_error(exc: Exception, pretty: bool) -> int:
    """Bad CLI input (unreadable/empty files, invalid contents): exit 2."""
    _emit_error({"error": "UsageError", "message": str(exc)}, pretty)
    return 2


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value!r} must be >= 1")
    return number


def _question_from_yaml(spec: Any, path: Path) -> Any:
    """Build a question from a SPEC string or a native YAML mapping."""
    from daf_jev._types import ChoiceQuestion, NoulQuestion, ScoreQuestion

    if isinstance(spec, str):
        return parse_question_spec(spec)
    if not isinstance(spec, dict):
        raise ValueError(
            f"questions file {path}: question must be a SPEC string or a "
            f"{{type, instructions, criteria}} mapping, got {type(spec).__name__}"
        )
    qtype = spec.get("type")
    instructions = spec.get("instructions")
    criteria = spec.get("criteria")
    if not qtype:
        raise ValueError(
            f"questions file {path}: native question mapping requires 'type'"
        )
    if instructions is None:
        raise ValueError(
            f"questions file {path}: native question mapping requires "
            f"'instructions'"
        )
    if qtype == "noul":
        if criteria is not None and not isinstance(criteria, dict):
            raise ValueError(
                f"questions file {path}: noul criteria must be a mapping "
                f"with optional 'true'/'false' keys"
            )
        return NoulQuestion(instructions=instructions, criteria=criteria)
    if qtype == "choice":
        if not isinstance(criteria, dict) or not criteria:
            raise ValueError(
                f"questions file {path}: choice criteria must be a "
                f"non-empty mapping of option -> description"
            )
        return ChoiceQuestion(
            instructions=instructions,
            criteria={str(key): value for key, value in criteria.items()},
        )
    if qtype == "score":
        if not isinstance(criteria, list) or len(criteria) < 2:
            raise ValueError(
                f"questions file {path}: score criteria must be a list of "
                f">= 2 level names"
            )
        return ScoreQuestion(
            instructions=instructions,
            criteria=[str(level) for level in criteria],
        )
    raise ValueError(
        f"questions file {path}: unknown question type {qtype!r} "
        f"(expected noul, choice or score)"
    )


def _load_questions_file(path: Path) -> dict[str, Any]:
    """Load a YAML mapping of id -> SPEC string or native question mapping."""
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ValueError(
            f"questions file {path} must be a non-empty YAML mapping of "
            f"id -> question spec"
        )
    return {
        str(qid): _question_from_yaml(spec, path) for qid, spec in data.items()
    }


def _load_states_file(path: Path) -> list[str]:
    """JSON array of strings, else one state per line (blank lines skipped)."""
    text = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, list):
        for index, item in enumerate(parsed):
            if not isinstance(item, str):
                raise ValueError(
                    f"states file {path}: JSON array must contain only "
                    f"strings; item {index} is {type(item).__name__}"
                )
        return parsed
    return [line.strip() for line in text.splitlines() if line.strip()]


 # ----------------------------------------------------------------- commands


# ----------------------------------------------------------------- commands


def _cmd_ask(args: argparse.Namespace) -> int:
    from daf_jev._errors import TypeSafeError

    questions: dict[str, Any] = {}
    for entry in args.question or []:
        qid, sep, spec = entry.partition("=")
        if not sep or not qid:
            raise ValueError(f"invalid --question {entry!r}: expected 'ID=SPEC'")
        questions[qid] = parse_question_spec(spec)

    try:
        with _make_client(args) as client:
            response = client.ask(_state_from_args(args), questions)
    except (TypeSafeError, ValueError, OSError) as exc:
        _emit_error({"error": type(exc).__name__, "message": str(exc)}, args.pretty)
        return 1

    payload: dict[str, Any] = {
        "model": response.model,
        "answers": {
            qid: {**asdict(ans), "type": ans.type}
            for qid, ans in response.answers.items()
        },
        "usage": asdict(response.usage),
    }
    if response.request_id is not None:
        payload["request_id"] = response.request_id
    _emit(payload, args.pretty)
    return 0


def _cmd_models(args: argparse.Namespace) -> int:
    from daf_jev._errors import TypeSafeError

    try:
        with _make_client(args) as client:
            cards = client.models()
    except (TypeSafeError, ValueError, OSError) as exc:
        _emit_error({"error": type(exc).__name__, "message": str(exc)}, args.pretty)
        return 1

    if getattr(args, "pick", None) is not None or getattr(args, "contains", None):
        # Lazy import: models.py is a sibling module built concurrently.
        from daf_jev.models import pick_model

        try:
            card = pick_model(
                cards, contains=args.contains, prefer=args.pick or "latest"
            )
        except ValueError as exc:
            _emit_error(
                {"error": type(exc).__name__, "message": str(exc)}, args.pretty
            )
            return 1
        _emit({"model": asdict(card)}, args.pretty)
        return 0

    _emit({"models": [asdict(card) for card in cards]}, args.pretty)
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from daf_jev._errors import TypeSafeError
    from daf_jev.evaluate import Evaluator

    try:
        questions = _load_questions_file(Path(args.questions_file))
        states = _load_states_file(Path(args.states_file))
    except (ValueError, OSError) as exc:
        return _usage_error(exc, args.pretty)
    if not states:
        return _usage_error(
            ValueError(f"states file {args.states_file} contains no states"),
            args.pretty,
        )

    try:
        with _make_client(args) as client:
            evaluator = Evaluator(
                client,
                questions,
                concurrency=args.concurrency,
                model=args.model,
            )
            records = evaluator.evaluate(states)
            payload = evaluator.summary(records)
            if args.include_records:
                payload["records"] = evaluator.to_json(records)
    except (TypeSafeError, ValueError, OSError) as exc:
        _emit_error({"error": type(exc).__name__, "message": str(exc)}, args.pretty)
        return 1

    _emit(payload, args.pretty)
    return 0


def _derive_rel(url: str) -> str:
    """Relative path (from the docs root) that a page URL maps to."""
    return urlparse(url).path.lstrip("/")


def _cmd_docs_verify(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _emit_error({"error": type(exc).__name__, "message": str(exc)}, args.pretty)
        return 1

    root = manifest_path.parent
    pages = manifest.get("pages", {})
    missing: list[str] = []
    drifted: list[str] = []
    for rel, meta in pages.items():
        expected_rel = _derive_rel(meta.get("url", ""))
        if expected_rel != rel:
            drifted.append(f"{rel} (url maps to {expected_rel!r})")
            continue
        path = root / rel
        try:
            data = path.read_bytes()
        except OSError:
            missing.append(rel)
            continue
        if (
            hashlib.sha256(data).hexdigest() != meta.get("sha256")
            or len(data) != meta.get("bytes")
        ):
            drifted.append(rel)

    summary = {
        "manifest": str(manifest_path),
        "pages": len(pages),
        "missing": sorted(missing),
        "drifted": sorted(drifted),
        "ok": not missing and not drifted,
    }
    _emit(summary, args.pretty)
    return 0 if summary["ok"] else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    from daf_jev.mcp_server import main as serve_main

    serve_main()
    return 0


# ------------------------------------------------------------------- parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daf-jev", description="TypeSafe Jev (System One) client."
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--base-url",
            default=None,
            help="API base URL (default: resolved from config, e.g. JEV_BASE_URL).",
        )
        p.add_argument("--json", action="store_true", help="compact JSON output (default)")
        p.add_argument("--pretty", action="store_true", help="pretty-printed JSON output")

    p_ask = sub.add_parser("ask", help="ask questions about a state")
    state_group = p_ask.add_mutually_exclusive_group(required=True)
    state_group.add_argument(
        "--state-file", type=Path, default=None, help="read state from FILE"
    )
    state_group.add_argument("--state", default=None, help="state as inline text/JSON")
    p_ask.add_argument(
        "--question",
        action="append",
        default=None,
        metavar="ID=SPEC",
        help="question spec: noul:<instructions> | choice:<instructions>:k1=desc,k2=... "
        "| score:<instructions>:l1,l2,...",
    )
    p_ask.add_argument("--model", default=None, help="model override (default: jev-latest)")
    add_common(p_ask)
    p_ask.set_defaults(func=_cmd_ask)

    p_models = sub.add_parser("models", help="list available models")
    p_models.add_argument(
        "--pick",
        choices=["latest", "first", "last"],
        default=None,
        help="pick one model instead of listing (default ordering: latest)",
    )
    p_models.add_argument(
        "--contains",
        default=None,
        metavar="STR",
        help="case-insensitive substring filter on model name (with --pick)",
    )
    add_common(p_models)
    p_models.set_defaults(func=_cmd_models)

    p_eval = sub.add_parser(
        "evaluate", help="evaluate a question set over many states"
    )
    p_eval.add_argument(
        "--questions-file",
        type=Path,
        required=True,
        metavar="PATH",
        help="YAML mapping id -> question SPEC string or "
        "{type, instructions, criteria} mapping",
    )
    p_eval.add_argument(
        "--states-file",
        type=Path,
        required=True,
        metavar="PATH",
        help="one state per line (blank lines skipped) or JSON array of strings",
    )
    p_eval.add_argument(
        "--concurrency",
        type=_positive_int,
        default=4,
        metavar="N",
        help="max in-flight model calls (default: 4)",
    )
    p_eval.add_argument("--model", default=None, help="model override (default: jev-latest)")
    p_eval.add_argument(
        "--include-records",
        action="store_true",
        help="include per-state records in the output",
    )
    add_common(p_eval)
    p_eval.set_defaults(func=_cmd_evaluate)

    p_verify = sub.add_parser(
        "docs-verify", help="verify docs/reference against its manifest"
    )
    p_verify.add_argument(
        "--manifest", default=str(DEFAULT_MANIFEST), help="manifest path"
    )
    p_verify.add_argument("--pretty", action="store_true", help="pretty-printed JSON output")
    p_verify.set_defaults(func=_cmd_docs_verify)
    p_serve = sub.add_parser(
        "serve", help="serve the daf-jev MCP server (stdio transport)"
    )
    p_serve.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="MCP transport (only 'stdio' is supported)",
    )
    p_serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse usage error
        return exc.code if isinstance(exc.code, int) else 2

    pretty = getattr(args, "pretty", False)
    try:
        return args.func(args)
    except Exception as exc:  # unexpected runtime failure
        _emit_error({"error": type(exc).__name__, "message": str(exc)}, pretty)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
