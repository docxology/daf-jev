"""Configuration and environment resolution for daf-jev.

Resolution precedence everywhere: injected ``env`` mapping > process environment
> ``.env`` file. ``JEV_API_KEY`` is preferred over ``TYPESAFE_API_KEY``;
``JEV_BASE_URL`` (then ``TYPESAFE_BASE_URL``) overrides the default base URL.
Retry behavior is resolved by :func:`resolve_retry` from ``JEV_MAX_ATTEMPTS``,
``JEV_BACKOFF_BASE``, ``JEV_BACKOFF_MAX`` and ``JEV_JITTER``; the request
timeout by :func:`resolve_timeout` from ``JEV_TIMEOUT`` (seconds). Unset or
invalid values fall back to the documented defaults. Per-provider resolution
(``load_settings(provider=...)``) and the provider registry live in
:mod:`daf_jev.providers`; the module-level resolvers here are the ``jev``
compatibility surface.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from daf_jev._retry import RetryPolicy

if TYPE_CHECKING:
    from daf_jev.providers import ProviderSpec

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
    "API_KEY_VARS",
    "BASE_URL_VARS",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "MODEL_VARS",
    "Settings",
    "load_dotenv",
    "load_settings",
    "resolve_api_key",
    "resolve_base_url",
    "resolve_model",
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


def _lookup(
    names: tuple[str, ...],
    env: Mapping[str, str] | None,
    file_env: Mapping[str, str] | None = None,
) -> str | None:
    """First-hit lookup across injected env, process env, then ``.env``.

    Values are stripped before the truthiness check, so whitespace-only
    values count as unset at every layer. ``file_env`` may carry an
    already-parsed ``.env`` mapping so callers can avoid re-reading the
    file on every lookup.
    """
    for name in names:
        if env is not None:
            value = env.get(name)
            if value is not None:
                value = value.strip()
                if value:
                    return value
        value = os.environ.get(name)
        if value is not None:
            value = value.strip()
            if value:
                return value
        if file_env is None:
            file_env = load_dotenv()
        value = file_env.get(name)
        if value is not None:
            value = value.strip()
            if value:
                return value
    return None


def _provider_spec(provider: str | ProviderSpec) -> ProviderSpec:
    """Normalize a provider argument to its :class:`ProviderSpec`.

    Imports :mod:`daf_jev.providers` lazily: that module imports this one
    at module level, so this module must not import it eagerly.
    """
    from daf_jev.providers import ProviderSpec, get_provider

    if isinstance(provider, ProviderSpec):
        return provider
    return get_provider(provider)


def resolve_api_key(env: Mapping[str, str] | None = None) -> str | None:
    """Resolve the ``jev`` API key: ``JEV_API_KEY`` then ``TYPESAFE_API_KEY``.

    The ``jev`` compatibility surface, delegating to the ``jev`` spec in
    :mod:`daf_jev.providers`.
    """
    return _lookup(_provider_spec("jev").api_key_vars, env)


def resolve_base_url(env: Mapping[str, str] | None = None) -> str:
    """Resolve the ``jev`` API base URL, defaulting to ``DEFAULT_BASE_URL``.

    The ``jev`` compatibility surface, delegating to the ``jev`` spec in
    :mod:`daf_jev.providers`.
    """
    return _lookup(_provider_spec("jev").base_url_vars, env) or DEFAULT_BASE_URL


def resolve_model(env: Mapping[str, str] | None = None) -> str:
    """Resolve the ``jev`` default model, defaulting to ``DEFAULT_MODEL``.

    The ``jev`` compatibility surface, delegating to the ``jev`` spec in
    :mod:`daf_jev.providers`.
    """
    return _lookup(_provider_spec("jev").model_vars, env) or DEFAULT_MODEL


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    model: str
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: float | None = None
    provider: str = "jev"

def load_settings(
    env: Mapping[str, str] | None = None,
    provider: str | ProviderSpec | None = None,
) -> Settings:
    """Resolve every setting at once, reading ``.env`` once and sharing the
    parsed mapping with every resolver.

    ``provider`` (key or :class:`ProviderSpec`) selects which provider's
    env variables and defaults resolve ``api_key`` / ``base_url`` /
    ``model``; the default ``None`` keeps the ``jev`` behavior. Retry and
    timeout always resolve from the ``JEV_*`` variables. The returned
    ``Settings.provider`` is the resolved provider key.
    """
    file_env = load_dotenv()
    if provider is None:
        return Settings(
            api_key=_lookup(API_KEY_VARS, env, file_env),
            base_url=_lookup(BASE_URL_VARS, env, file_env) or DEFAULT_BASE_URL,
            model=_lookup(MODEL_VARS, env, file_env) or DEFAULT_MODEL,
            retry=_resolve_retry(env, file_env),
            timeout=_resolve_timeout(env, file_env),
        )
    spec = _provider_spec(provider)
    return Settings(
        api_key=_lookup(spec.api_key_vars, env, file_env),
        base_url=(
            _lookup(spec.base_url_vars, env, file_env) or spec.default_base_url
        ),
        model=_lookup(spec.model_vars, env, file_env) or spec.default_model,
        retry=_resolve_retry(env, file_env),
        timeout=_resolve_timeout(env, file_env),
        provider=spec.key,
    )


def _resolve_float(
    names: tuple[str, ...],
    env: Mapping[str, str] | None,
    file_env: Mapping[str, str] | None = None,
) -> float | None:
    """Parse a float-valued setting, returning ``None`` when unset/invalid."""
    raw = _lookup(names, env, file_env)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _resolve_retry(
    env: Mapping[str, str] | None, file_env: Mapping[str, str] | None
) -> RetryPolicy:
    """Shared retry resolver over the private lookup path."""
    defaults = RetryPolicy()
    max_attempts = defaults.max_attempts
    raw_attempts = _lookup((RETRY_MAX_ATTEMPTS_VAR,), env, file_env)
    if raw_attempts is not None:
        try:
            parsed = int(raw_attempts)
        except (TypeError, ValueError):
            pass
        else:
            if parsed >= 1:
                max_attempts = parsed
    base = _resolve_float((RETRY_BACKOFF_BASE_VAR,), env, file_env)
    backoff_base = base if base is not None and base > 0 else defaults.backoff_base
    backoff_max = _resolve_float((RETRY_BACKOFF_MAX_VAR,), env, file_env)
    if backoff_max is None:
        backoff_max = defaults.backoff_max
    jitter = _resolve_float((RETRY_JITTER_VAR,), env, file_env)
    if jitter is None or jitter < 0:
        jitter = defaults.jitter
    return replace(
        defaults,
        max_attempts=max_attempts,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        jitter=jitter,
    )


def _resolve_timeout(
    env: Mapping[str, str] | None, file_env: Mapping[str, str] | None
) -> float | None:
    """Shared timeout resolver over the private lookup path."""
    timeout = _resolve_float((TIMEOUT_VAR,), env, file_env)
    if timeout is not None and timeout > 0:
        return timeout
    return None


def resolve_retry(env: Mapping[str, str] | None = None) -> RetryPolicy:
    """Resolve a :class:`RetryPolicy` from the environment.

    ``JEV_MAX_ATTEMPTS`` (int >= 1), ``JEV_BACKOFF_BASE`` (float > 0),
    ``JEV_BACKOFF_MAX`` (float) and ``JEV_JITTER`` (float >= 0) override the
    matching ``RetryPolicy`` fields; unset or invalid values keep the
    ``RetryPolicy()`` default for that field.
    """
    return _resolve_retry(env, None)


def resolve_timeout(env: Mapping[str, str] | None = None) -> float | None:
    """Resolve the default request timeout in seconds from ``JEV_TIMEOUT``.

    Must be a positive float; unset or invalid values yield ``None`` (no
    timeout override).
    """
    return _resolve_timeout(env, None)
