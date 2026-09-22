"""Shared native question-mapping builder (no I/O).

:func:`daf_jev.questions.question_from_mapping` builds
:class:`~daf_jev._types.NoulQuestion` / :class:`~daf_jev._types.ChoiceQuestion`
/ :class:`~daf_jev._types.ScoreQuestion` objects from a native
``{type, instructions, criteria}`` mapping, with strict validation and
actionable ``ValueError`` messages. The CLI (``evaluate
--questions-file``) and the MCP server (``jev_ask`` / ``jev_evaluate``)
route native mappings through it so validation is defined exactly once;
spec strings keep using :func:`daf_jev.cli.parse_question_spec`.
"""

from __future__ import annotations

from collections.abc import Mapping

from daf_jev._types import ChoiceQuestion, NoulQuestion, Question, ScoreQuestion

__all__ = ["question_from_mapping"]


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
