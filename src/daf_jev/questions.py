"""Shared question normalization (no I/O).

``parse_question_spec`` owns the escaped SPEC grammar; ``question_from_mapping``
owns strict native ``{type, instructions, criteria}`` validation.
``question_from_value`` selects between them for CLI YAML and MCP inputs,
returning the same typed questions with the caller's native-mapping context.
The public ``daf_jev.cli.parse_question_spec`` import remains available.
"""

from __future__ import annotations

from collections.abc import Mapping

from daf_jev._types import ChoiceQuestion, NoulQuestion, Question, ScoreQuestion

__all__ = ["parse_question_spec", "question_from_mapping", "question_from_value"]


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


def parse_question_spec(spec: str) -> Question:
    """Parse a question SPEC into a ``daf_jev`` question object.

    The type is taken before the first unescaped ``:``; for ``choice``/
    ``score`` the criteria segment starts after the last unescaped ``:``,
    so plain colons may appear inside instructions and ``\\:`` escapes a
    literal colon anywhere (instructions, option descriptions, levels).
    Commas in options/levels are escaped as ``\\,``. Raises ``ValueError``
    on malformed specs.
    """

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


def _require_str_or_none(context: str, kind: str, key: object, value: object) -> None:
    """Reject criteria description values that are neither str nor None."""
    if value is not None and not isinstance(value, str):
        raise ValueError(
            f"{context}: {kind} criteria value for {key!r} must be a string "
            f"or null, got {type(value).__name__}"
        )


def question_from_mapping(value: object, *, context: str = "question") -> Question:
    """Build a question object from a native ``{type, instructions, criteria}`` mapping.

    ``context`` prefixes every error message (e.g.
    ``"questions file questions.yaml"``) so callers can say where the
    mapping came from. Raises ``ValueError`` with an actionable message
    when ``value`` is not a mapping, when ``type`` is missing or unknown,
    when ``instructions`` is missing, or when ``criteria`` has the wrong
    shape or values:

    - ``noul``: optional mapping (``{"true": str|null, "false": str|null}``)
      whose values are strings or null,
    - ``choice``: non-empty mapping of option name -> description (str|null),
    - ``score``: list of >= 2 non-empty level-name strings.
    """
    if not isinstance(value, Mapping):
        raise ValueError(
            f"{context}: question must be a {{type, instructions, criteria}} "
            f"mapping, got {type(value).__name__}"
        )
    qtype = value.get("type")
    instructions = value.get("instructions")
    criteria = value.get("criteria")
    if not qtype:
        raise ValueError(f"{context}: native question mapping requires 'type'")
    if instructions is None:
        raise ValueError(
            f"{context}: native question mapping requires 'instructions'"
        )
    if not isinstance(instructions, str):
        raise ValueError(
            f"{context}: 'instructions' must be a string, got "
            f"{type(instructions).__name__}"
        )

    if qtype == "noul":
        if criteria is not None and not isinstance(criteria, Mapping):
            raise ValueError(
                f"{context}: noul criteria must be a mapping with optional "
                f"'true'/'false' keys"
            )
        if criteria:
            for key, desc in criteria.items():
                if key not in ("true", "false"):
                    raise ValueError(
                        f"{context}: noul criteria keys must be 'true' or "
                        f"'false', got {key!r}"
                    )
                _require_str_or_none(context, "noul", key, desc)
        return NoulQuestion(
            instructions=instructions, criteria=dict(criteria) if criteria else None
        )

    if qtype == "choice":
        if not isinstance(criteria, Mapping) or not criteria:
            raise ValueError(
                f"{context}: choice criteria must be a non-empty mapping of "
                f"option -> description"
            )
        options: dict[str, str | None] = {}
        for key, desc in criteria.items():
            _require_str_or_none(context, "choice", key, desc)
            name = str(key)
            if not name.strip():
                raise ValueError(f"{context}: choice option name must be non-empty")
            if name in options:
                raise ValueError(f"{context}: duplicate option {name!r}")
            options[name] = desc
        return ChoiceQuestion(instructions=instructions, criteria=options)

    if qtype == "score":
        if not isinstance(criteria, list):
            raise ValueError(
                f"{context}: score criteria must be a list of >= 2 non-empty "
                f"level names"
            )
        bad = [
            index
            for index, level in enumerate(criteria)
            if not isinstance(level, str) or not level
        ]
        if len(criteria) < 2 or bad:
            raise ValueError(
                f"{context}: score criteria must be a list of >= 2 non-empty "
                f"level names"
            )
        return ScoreQuestion(instructions=instructions, criteria=list(criteria))

    raise ValueError(
        f"{context}: unknown question type {qtype!r} "
        f"(expected noul, choice or score)"
    )


def question_from_value(value: object, *, context: str = "question") -> Question:
    """Normalize a SPEC string or native mapping, preserving parser errors."""
    if isinstance(value, str):
        return parse_question_spec(value)
    return question_from_mapping(value, context=context)
