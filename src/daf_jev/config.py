"""Configuration and environment resolution for daf-jev.

Resolution precedence everywhere: injected ``env`` mapping > process environment
> ``.env`` file. ``JEV_API_KEY`` is preferred over ``TYPESAFE_API_KEY``;
``JEV_BASE_URL`` (then ``TYPESAFE_BASE_URL``) overrides the default base URL.
Retry behavior is resolved by :func:`resolve_retry` from ``JEV_MAX_ATTEMPTS``,
``JEV_BACKOFF_BASE``, ``JEV_BACKOFF_MAX`` and ``JEV_JITTER``; the request
timeout by :func:`resolve_timeout` from ``JEV_TIMEOUT`` (seconds). Unset or
invalid values fall back to the documented defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Optional

from daf_jev._retry import RetryPolicy

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"

API_KEY_VARS = ("JEV_API_KEY", "TYPESAFE_API_KEY")
BASE_URL_VARS = ("JEV_BASE_URL", "TYPESAFE_BASE_URL")
MODEL_VARS = ("JEV_MODEL", "TYPESAFE_DEFAULT_MODEL")
RETRY_MAX_ATTEMPTS_VAR = "JEV_MAX_ATTEMPTS"
RETRY_BACKOFF_BASE_VAR = "JEV_BACKOFF_BASE"
RETRY_BACKOFF_MAX_VAR = "JEV_BACKOFF_MAX"
RETRY_JITTER_VAR = "JEV_JITTER"
TIMEOUT_VAR = "JEV_TIMEOUT"

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "API_KEY_VARS",
    "BASE_URL_VARS",
    "MODEL_VARS",
    "Settings",
    "load_dotenv",
    "resolve_api_key",
    "resolve_base_url",
    "resolve_model",
    "load_settings",
    "resolve_retry",
    "resolve_timeout",
]


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    """Parse a KEY=VALUE ``.env`` file.

    Blank lines and ``#`` comments are ignored. Lines without ``=`` are
    ignored. Never raises on a missing or unreadable file; returns ``{}``.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def _lookup(names: tuple[str, ...], env: Optional[Mapping[str, str]]) -> Optional[str]:
    """First-hit lookup across injected env, process env, then ``.env``."""
    file_env = None
    for name in names:
        if env is not None and env.get(name):
            return env[name]
        value = os.environ.get(name)
        if value:
            return value
        if file_env is None:
            file_env = load_dotenv()
        value = file_env.get(name)
        if value:
            return value
    return None


def resolve_api_key(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Resolve the API key: ``JEV_API_KEY`` then ``TYPESAFE_API_KEY``."""
    return _lookup(API_KEY_VARS, env)


def resolve_base_url(env: Optional[Mapping[str, str]] = None) -> str:
    """Resolve the API base URL, defaulting to ``DEFAULT_BASE_URL``."""
    return _lookup(BASE_URL_VARS, env) or DEFAULT_BASE_URL


def resolve_model(env: Optional[Mapping[str, str]] = None) -> str:
    """Resolve the default model name, defaulting to ``DEFAULT_MODEL``."""
    return _lookup(MODEL_VARS, env) or DEFAULT_MODEL


@dataclass(frozen=True)
class Settings:
    api_key: Optional[str]
    base_url: str
    model: str
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: Optional[float] = None

def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Resolve every setting at once (no I/O beyond a single ``.env`` read)."""
    return Settings(
        api_key=resolve_api_key(env),
        base_url=resolve_base_url(env),
        model=resolve_model(env),
        retry=resolve_retry(env),
        timeout=resolve_timeout(env),
    )


def _resolve_float(
    names: tuple[str, ...], env: Optional[Mapping[str, str]]
) -> Optional[float]:
    """Parse a float-valued setting, returning ``None`` when unset/invalid."""
    raw = _lookup(names, env)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def resolve_retry(env: Optional[Mapping[str, str]] = None) -> RetryPolicy:
    """Resolve a :class:`RetryPolicy` from the environment.

    ``JEV_MAX_ATTEMPTS`` (int >= 1), ``JEV_BACKOFF_BASE`` (float > 0),
    ``JEV_BACKOFF_MAX`` (float) and ``JEV_JITTER`` (float >= 0) override the
    matching ``RetryPolicy`` fields; unset or invalid values keep the
    ``RetryPolicy()`` default for that field.
    """
    defaults = RetryPolicy()
    max_attempts = defaults.max_attempts
    raw_attempts = _lookup((RETRY_MAX_ATTEMPTS_VAR,), env)
    if raw_attempts is not None:
        try:
            parsed = int(raw_attempts)
        except (TypeError, ValueError):
            pass
        else:
            if parsed >= 1:
                max_attempts = parsed
    base = _resolve_float((RETRY_BACKOFF_BASE_VAR,), env)
    if base is not None and base > 0:
        backoff_base = base
    else:
        backoff_base = defaults.backoff_base
    backoff_max = _resolve_float((RETRY_BACKOFF_MAX_VAR,), env)
    if backoff_max is None:
        backoff_max = defaults.backoff_max
    jitter = _resolve_float((RETRY_JITTER_VAR,), env)
    if jitter is None or jitter < 0:
        jitter = defaults.jitter
    return replace(
        defaults,
        max_attempts=max_attempts,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        jitter=jitter,
    )


def resolve_timeout(env: Optional[Mapping[str, str]] = None) -> Optional[float]:
    """Resolve the default request timeout in seconds from ``JEV_TIMEOUT``.

    Must be a positive float; unset or invalid values yield ``None`` (no
    timeout override).
    """
    timeout = _resolve_float((TIMEOUT_VAR,), env)
    if timeout is not None and timeout > 0:
        return timeout
    return None
