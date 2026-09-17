"""Unit tests for daf_jev.models.pick_model: pure model selection logic.

No I/O: ModelCard values are constructed inline, mirroring the shape parsed
from the models listing in client._parse_models.
"""

from __future__ import annotations

import pytest

from daf_jev.client import ModelCard
from daf_jev.models import pick_model


def _card(name: str, release: "str | None" = None, description: str = "") -> ModelCard:
    return ModelCard(name=name, description=description, release_date=release)


CARDS = [
    _card("jev-latest", "2026-03-01", "flagship"),
    _card("jev-mini-preview", "2026-05-15", "small and fast"),
    _card("jev-classic", "2025-11-20", "previous generation"),
    _card("jev-legacy", None, "retired"),
]


# ------------------------------------------------------------ error inputs ---


def test_empty_cards_raise() -> None:
    with pytest.raises(ValueError):
        pick_model([])
    with pytest.raises(ValueError):
        pick_model([], contains="jev")


def test_contains_no_match_raises() -> None:
    with pytest.raises(ValueError):
        pick_model(CARDS, contains="opus")


def test_unknown_prefer_raises() -> None:
    with pytest.raises(ValueError):
        pick_model(CARDS, prefer="cheapest")


# ---------------------------------------------------------------- contains ---


def test_contains_filters_case_insensitively_on_name() -> None:
    assert pick_model(CARDS, contains="MINI") is CARDS[1]
    assert pick_model(CARDS, contains="Latest") is CARDS[0]
    assert pick_model(CARDS, contains="classic") is CARDS[2]


def test_contains_filters_before_preferring() -> None:
    cards = [
        _card("jev-mini-1", "2025-01-01"),
        _card("jev-mini-2", "2026-01-01"),
        _card("jev-big", "2026-06-01"),
    ]
    # latest within the filtered subset, not across all cards
    assert pick_model(cards, contains="mini", prefer="latest") is cards[1]
    assert pick_model(cards, contains="MINI", prefer="first") is cards[0]
    assert pick_model(cards, contains="mini", prefer="last") is cards[1]


# ------------------------------------------------------------------ prefer ---


def test_default_prefer_is_latest() -> None:
    assert pick_model(CARDS) is CARDS[1]  # 2026-05-15 beats 2026-03-01


def test_latest_picks_max_release_date() -> None:
    assert pick_model(CARDS, prefer="latest") is CARDS[1]


def test_none_release_date_sorts_last_for_latest() -> None:
    mixed = [_card("no-date", None), _card("dated", "2025-01-01")]
    assert pick_model(mixed).name == "dated"
    reversed_mixed = [_card("dated", "2025-01-01"), _card("no-date", None)]
    assert pick_model(reversed_mixed).name == "dated"


def test_latest_tie_keeps_first_in_input_order() -> None:
    tied = [_card("original", "2026-01-01"), _card("second", "2026-01-01")]
    assert pick_model(tied) is tied[0]


def test_all_none_release_dates_tie_keeps_first() -> None:
    undated = [_card("a", None), _card("b", None), _card("c", None)]
    assert pick_model(undated) is undated[0]


def test_prefer_first_and_last_follow_input_order() -> None:
    # input order, not release order: CARDS[0] is not the newest release
    assert pick_model(CARDS, prefer="first") is CARDS[0]
    assert pick_model(CARDS, prefer="last") is CARDS[3]
