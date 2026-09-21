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

Question SPEC grammar (``\\,``, ``\\:`` and ``\\\\`` escape a literal
comma, colon and backslash):

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
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from daf_jev import config
from daf_jev.docs_verify import DEFAULT_MANIFEST, verify_manifest

__all__ = ["main", "parse_question_spec"]


# ---------------------------------------------------------------- questions


#: Characters a backslash escapes inside a question SPEC.
_ESCAPABLE = (",", "\\", ":")


def _split_unescaped_commas(text: str) -> list[str]:
    """Split on unescaped commas, honoring ``\\,``/``\\:``/``\\\\`` escapes."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in _ESCAPABLE:
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


def _unescape(text: str) -> str:
    """Resolve ``\\,``/``\\:``/``\\\\`` escapes to literal characters.

    A backslash not followed by an escapable character is kept verbatim,
    mirroring :func:`_split_unescaped_commas`.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in _ESCAPABLE:
            out.append(text[i + 1])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _find_unescaped(text: str, target: str, *, last: bool = False) -> int:
    """Index of the first (default) or last unescaped ``target``, or -1.

    ``\\,``/``\\:``/``\\\\`` escape pairs are skipped, so the search
    looks past escaped characters.
    """
    i = 0
    found = -1
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in _ESCAPABLE:
            i += 2
            continue
        if ch == target:
            found = i
            if not last:
                return i
        i += 1
    return found


def parse_question_spec(spec: str) -> Any:
    """Parse a question SPEC into a ``daf_jev`` question object.

    The type is taken before the first unescaped ``:``; for ``choice``/
    ``score`` the criteria segment starts after the last unescaped ``:``,
    so plain colons may appear inside instructions and ``\\:`` escapes a
    literal colon anywhere (instructions, option descriptions, levels).
    Commas in options/levels are escaped as ``\\,``. Raises ``ValueError``
    on malformed specs.
    """
    from daf_jev._types import ChoiceQuestion, NoulQuestion, ScoreQuestion

    type_end = _find_unescaped(spec, ":", last=False)
    if type_end < 1:
        raise ValueError(
            f"invalid question spec {spec!r}: expected 'noul:<instructions>', "
            f"'choice:<instructions>:k1=desc,k2=...' or 'score:<instructions>:l1,l2,...'"
        )
    qtype, rest = spec[:type_end], spec[type_end + 1 :]

    if qtype == "noul":
        if not rest:
            raise ValueError(f"invalid noul spec {spec!r}: instructions required")
        return NoulQuestion(instructions=_unescape(rest))

    criteria_start = _find_unescaped(rest, ":", last=True)
    if criteria_start < 0:
        raise ValueError(
            f"invalid {qtype} spec {spec!r}: expected '<instructions>:<criteria>'"
        )
    instructions = _unescape(rest[:criteria_start])
    criteria_text = rest[criteria_start + 1 :]
    if not instructions:
        raise ValueError(f"invalid {qtype} spec {spec!r}: instructions required")

    if qtype == "choice":
        options: dict[str, str | None] = {}
        for item in _split_unescaped_commas(criteria_text):
            key, _eq, desc = item.partition("=")
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
    """Resolve the ask state: file content or inline text.

    Only JSON objects and arrays are parsed (the wire shapes beyond
    str); scalar JSON such as ``123`` or ``null`` stays raw text, and a
    ``None`` state is never produced.
    """
    text = (
        args.state_file.read_text(encoding="utf-8")
        if args.state_file
        else args.state
    )
    if text is None:
        raise ValueError("ask requires --state TEXT or --state-file FILE")
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(parsed, (dict, list)):
        return parsed
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
    from daf_jev.questions import question_from_mapping

    if isinstance(spec, str):
        return parse_question_spec(spec)
    return question_from_mapping(spec, context=f"questions file {path}")


def _load_questions_file(path: Path) -> dict[str, Any]:
    """Load a YAML mapping of id -> SPEC string or native question mapping.

    Duplicate question ids are rejected (both literal duplicate YAML keys
    and keys that collide once cast to ``str``); YAML's default silently
    keeps the last one.
    """
    import yaml

    class _UniqueKeyLoader(yaml.SafeLoader):
        """SafeLoader that rejects duplicate mapping keys."""

        def construct_mapping(self, node: Any, deep: bool = False) -> Any:
            if isinstance(node, yaml.MappingNode):
                self.flatten_mapping(node)
                seen: set[Any] = set()
                for key_node, _value_node in node.value:
                    key = self.construct_object(key_node, deep=True)
                    try:
                        hash(key)
                    except TypeError:
                        key = str(key)
                    if key in seen:
                        raise yaml.constructor.ConstructorError(
                            "while constructing a mapping",
                            node.start_mark,
                            f"duplicate key {key!r} in questions file {path}",
                            key_node.start_mark,
                        )
                    seen.add(key)
            return super().construct_mapping(node, deep=deep)

    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ValueError(
            f"questions file {path} must be a non-empty YAML mapping of "
            f"id -> question spec"
        )
    questions: dict[str, Any] = {}
    for qid, spec in data.items():
        key = str(qid)
        if key in questions:
            raise ValueError(
                f"questions file {path}: duplicate question id {key!r}"
            )
        questions[key] = _question_from_yaml(spec, path)
    return questions


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


def _questions_from_flags(entries: Sequence[str]) -> dict[str, Any]:
    """Parse repeated ``--question ID=SPEC`` flags into a question mapping.

    Raises ``ValueError`` on a malformed entry or a duplicated id.
    """
    questions: dict[str, Any] = {}
    for entry in entries:
        qid, sep, spec = entry.partition("=")
        if not sep or not qid:
            raise ValueError(f"invalid --question {entry!r}: expected 'ID=SPEC'")
        if qid in questions:
            raise ValueError(
                f"duplicate question id {qid!r}: --question given more than "
                f"once for the same id"
            )
        questions[qid] = parse_question_spec(spec)
    return questions


def _cmd_ask(args: argparse.Namespace) -> int:
    from daf_jev._errors import TypeSafeError

    try:
        if not args.question:
            raise ValueError("ask requires at least one --question ID=SPEC flag")
        questions = _questions_from_flags(args.question)
        state = _state_from_args(args)
    except (ValueError, OSError) as exc:
        return _usage_error(exc, args.pretty)

    try:
        with _make_client(args) as client:
            response = client.ask(state, questions)
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


def _cmd_docs_verify(args: argparse.Namespace) -> int:
    try:
        summary = verify_manifest(Path(args.manifest))
    except ValueError as exc:
        _emit_error({"error": type(exc).__name__, "message": str(exc)}, args.pretty)
        return 1
    _emit(summary, args.pretty)
    return 0 if summary["ok"] else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        from daf_jev.mcp_server import main as serve_main
    except ImportError as exc:
        _emit_error(
            {
                "error": type(exc).__name__,
                "message": f"the MCP server needs the optional 'mcp' "
                f"dependency: install it with 'uv sync --extra mcp' ({exc})",
            },
            getattr(args, "pretty", False),
        )
        return 1
    serve_main(transport=args.transport)
    return 0


# ------------------------------------------------------------------- parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daf-jev", description="TypeSafe Jev (System One) client."
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add_common(p: argparse.ArgumentParser, *, base_url: bool = True) -> None:
        if base_url:
            p.add_argument(
                "--base-url",
                default=None,
                help="API base URL (default: resolved from config, e.g. JEV_BASE_URL).",
            )
        output = p.add_mutually_exclusive_group()
        output.add_argument(
            "--json", action="store_true", help="compact JSON output (default)"
        )
        output.add_argument(
            "--pretty", action="store_true", help="pretty-printed JSON output"
        )

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
        help="case-insensitive substring filter on model name",
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
    add_common(p_verify, base_url=False)
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


def main(argv: Sequence[str] | None = None) -> int:
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
