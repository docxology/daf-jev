"""Unit tests for daf_jev.config: dotenv parsing and precedence.

Only environment *setup* uses monkeypatch (setenv/delenv/chdir on tmp_path);
daf_jev internals are never patched.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from daf_jev.config import Settings, load_dotenv, load_settings, resolve_api_key, resolve_base_url
from daf_jev._retry import RetryPolicy
from daf_jev.config import resolve_retry, resolve_timeout


@pytest.fixture(autouse=True)
def _clean_key_env(monkeypatch):
    """Keep host env and the real project .env out of these tests."""
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_BASE_URL", raising=False)


# ------------------------------------------------------------ load_dotenv ---


def test_load_dotenv_parses_key_value_pairs(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment line\n"
        "\n"
        "JEV_API_KEY=abc123\n"
        "OTHER_KEY=hello world\n"
        "  \n"
        "SPACED = spaced value\n",
        encoding="utf-8",
    )
    parsed = load_dotenv(env_file)
    assert parsed["JEV_API_KEY"] == "abc123"
    assert parsed["OTHER_KEY"] == "hello world"
    assert parsed["SPACED"] == "spaced value"
    assert "comment" not in " ".join(parsed)


def test_load_dotenv_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / "does-not-exist.env") == {}


# --------------------------------------------------------- resolve_api_key ---


def test_injected_env_beats_process_env(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("JEV_API_KEY=file-key\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JEV_API_KEY", "os-key")
    assert resolve_api_key({"JEV_API_KEY": "injected"}) == "injected"


def test_process_env_beats_dotenv_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("JEV_API_KEY=file-key\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JEV_API_KEY", "os-key")
    assert resolve_api_key(None) == "os-key"


def test_dotenv_file_used_when_env_unset(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("JEV_API_KEY=file-key\n")
    monkeypatch.chdir(tmp_path)
    assert resolve_api_key(None) == "file-key"


def test_typesafe_api_key_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    assert resolve_api_key({"TYPESAFE_API_KEY": "ts-key"}) == "ts-key"
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-os-key")
    assert resolve_api_key(None) == "ts-os-key"


def test_no_key_anywhere_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .env, no process env (cleared by fixture)
    assert resolve_api_key({}) is None
    assert resolve_api_key(None) is None


# -------------------------------------------------------- resolve_base_url ---


def test_base_url_default_and_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_base_url({}) == "https://api.typesafe.ai"
    assert resolve_base_url({"JEV_BASE_URL": "http://127.0.0.1:9"}) == "http://127.0.0.1:9"
    monkeypatch.setenv("JEV_BASE_URL", "http://127.0.0.1:8")
    assert resolve_base_url(None) == "http://127.0.0.1:8"


# ---------------------------------------------------------------- Settings ---


def test_load_settings_defaults_and_overrides(tmp_path: Path) -> None:
    settings = load_settings({"JEV_API_KEY": "k1", "JEV_BASE_URL": "http://x"})
    assert isinstance(settings, Settings)
    assert settings.api_key == "k1"
    assert settings.base_url == "http://x"
    assert settings.model == "jev-latest"


def test_settings_are_frozen() -> None:
    settings = load_settings({"JEV_API_KEY": "k1"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.api_key = "other"  # type: ignore[misc]


def test_load_dotenv_skips_export_prefix_blank_and_malformed_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "export JEV_API_KEY=exported-key\n"
        "# a comment\n"
        "\n"
        "NO_EQUALS_SIGN\n"
        "=no-key-name\n"
        "PLAIN=value\n",
        encoding="utf-8",
    )
    parsed = load_dotenv(env_file)
    assert parsed == {"JEV_API_KEY": "exported-key", "PLAIN": "value"}


# ------------------------------------------- retry/timeout env resolvers -----


def test_resolve_retry_defaults_when_unset() -> None:
    assert resolve_retry({}) == RetryPolicy()


def test_resolve_retry_reads_every_variable() -> None:
    policy = resolve_retry(
        {
            "JEV_MAX_ATTEMPTS": "5",
            "JEV_BACKOFF_BASE": "1.5",
            "JEV_BACKOFF_MAX": "20",
            "JEV_JITTER": "0.25",
        }
    )
    assert policy == RetryPolicy(
        max_attempts=5, backoff_base=1.5, backoff_max=20.0, jitter=0.25
    )


def test_resolve_retry_invalid_values_fall_back_to_defaults() -> None:
    policy = resolve_retry(
        {
            "JEV_MAX_ATTEMPTS": "not-a-number",
            "JEV_BACKOFF_BASE": "-1",
            "JEV_BACKOFF_MAX": "abc",
            "JEV_JITTER": "-0.5",
        }
    )
    assert policy == RetryPolicy()


def test_resolve_retry_rejects_non_positive_attempts_and_nonpositive_backoff_base() -> None:
    assert resolve_retry({"JEV_MAX_ATTEMPTS": "0"}) == RetryPolicy()
    assert resolve_retry({"JEV_BACKOFF_BASE": "0"}) == RetryPolicy()


def test_resolve_retry_explicit_env_beats_process_env(monkeypatch) -> None:
    monkeypatch.setenv("JEV_MAX_ATTEMPTS", "9")
    assert resolve_retry({"JEV_MAX_ATTEMPTS": "2"}).max_attempts == 2


def test_resolve_timeout_set_invalid_and_unset() -> None:
    assert resolve_timeout({"JEV_TIMEOUT": "12.5"}) == 12.5
    assert resolve_timeout({"JEV_TIMEOUT": "0"}) is None
    assert resolve_timeout({"JEV_TIMEOUT": "-3"}) is None
    assert resolve_timeout({"JEV_TIMEOUT": "soon"}) is None
    assert resolve_timeout({}) is None


def test_resolve_timeout_explicit_env_beats_process_env(monkeypatch) -> None:
    monkeypatch.setenv("JEV_TIMEOUT", "99")
    assert resolve_timeout({"JEV_TIMEOUT": "1.5"}) == 1.5


def test_load_settings_populates_retry_and_timeout() -> None:
    settings = load_settings(
        {
            "JEV_API_KEY": "k1",
            "JEV_MAX_ATTEMPTS": "4",
            "JEV_JITTER": "0",
            "JEV_TIMEOUT": "3.5",
        }
    )
    assert settings.retry == RetryPolicy(max_attempts=4, jitter=0.0)
    assert settings.timeout == 3.5


def test_settings_defaults_for_retry_and_timeout() -> None:
    settings = load_settings({"JEV_API_KEY": "k1"})
    assert settings.retry == RetryPolicy()
    assert settings.timeout is None

