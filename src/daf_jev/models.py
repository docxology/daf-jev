"""Model-card selection helpers over the models listing.

``pick_model`` filters and picks from the ``ModelCard`` list returned by
``JevClient.models()`` / ``AsyncJevClient.models()``. Pure logic; no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence

from daf_jev.client import ModelCard

__all__ = ["pick_model"]

_PREFER_CHOICES = ("latest", "first", "last")


def pick_model(
    cards: Sequence[ModelCard],
    *,
    contains: str | None = None,
    prefer: str = "latest",
) -> ModelCard:
    """Pick one :class:`ModelCard` from ``cards``.

    ``contains`` is a case-insensitive substring filter on the model name.
    ``prefer="latest"`` returns the card with the max ``release_date``
    (ISO-8601 strings compare lexicographically; ``None`` dates sort last,
    ties resolve to the first card in input order); ``"first"``/``"last"``
    use input order.

    Raises ``ValueError`` on empty input, no match after filtering, or an
    unknown ``prefer`` value.
    """
    if not cards:
        raise ValueError("cards must be a nonempty sequence of ModelCard")
    if prefer not in _PREFER_CHOICES:
        raise ValueError(
            f"unknown prefer {prefer!r}; expected one of {list(_PREFER_CHOICES)}"
        )
    if contains is not None:
        needle = contains.lower()
        cards = [c for c in cards if needle in c.name.lower()]
        if not cards:
            raise ValueError(f"no model name contains {contains!r}")
    if prefer == "first":
        return cards[0]
    if prefer == "last":
        return cards[-1]
    best, best_date = cards[0], cards[0].release_date
    for card in cards[1:]:
        date = card.release_date
        if date is not None and (best_date is None or date > best_date):
            best, best_date = card, date
    return best
