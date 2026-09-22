"""Provider registry for multi-provider System One dispatch.

Every provider speaks the same wire contract (``POST /v1/systemone`` and
``GET /v1/models`` over noul/choice/score questions), so dispatch is a
registry that parameterizes config resolution, client construction and
CLI/MCP selection — no wire adapters. Built-ins are registered at import
in a fixed order; third parties add their own via
:func:`register_provider`.

Resolution precedence matches :mod:`daf_jev.config`: injected ``env``
mapping > process environment > ``.env`` file. Falsy values are skipped;
unset values fall back to the provider's documented defaults.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping

from daf_jev.config import _lookup

__all__ = [
    "ProviderSpec",
    "get_provider",
    "register_provider",
    "resolve_provider_api_key",
    "resolve_provider_base_url",
    "resolve_provider_model",
]

_KEY_PATTERN = r"[a-z][a-z0-9_-]*"

# Registration-order registry; built-ins are appended at import below.
_REGISTRY: list[ProviderSpec] = []


@dataclasses.dataclass(frozen=True)
class ProviderSpec:
    """Parameters for one System One-compatible provider.

    ``key`` is the unique lowercase identifier (``[a-z][a-z0-9_-]*``). The
    ``*_vars`` tuples list environment variable names in lookup order —
    the provider-specific variable first, ``TYPESAFE_API_KEY`` /
    ``TYPESAFE_BASE_URL`` last for official-SDK compatibility. ``notes``
    carries behavioral caveats in one paragraph.
    """

    key: str
    display_name: str
    default_base_url: str
    api_key_vars: tuple[str, ...]
    base_url_vars: tuple[str, ...]
    default_model: str
    model_vars: tuple[str, ...]
    docs_url: str | None = None
    notes: str | None = None


def register_provider(spec: ProviderSpec) -> None:
    """Register ``spec``, keeping registration order (built-ins first).

    Validates the key pattern, required non-empty fields and key
    uniqueness, raising ``ValueError`` naming the problem otherwise.
    """
    if not isinstance(spec, ProviderSpec):
        raise ValueError(f"spec must be a ProviderSpec, got {type(spec).__name__}")
    key = spec.key
    if not isinstance(key, str) or re.fullmatch(_KEY_PATTERN, key) is None:
        raise ValueError(f"provider key must match {_KEY_PATTERN}, got {key!r}")
    for name in ("display_name", "default_base_url", "default_model"):
        value = getattr(spec, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"provider {name} must be a non-empty string, got {value!r}"
            )
    for name in ("api_key_vars", "base_url_vars", "model_vars"):
        vars_tuple = getattr(spec, name)
        if not isinstance(vars_tuple, tuple) or not all(
            isinstance(var, str) and var for var in vars_tuple
        ):
            raise ValueError(
                f"provider {name} must be a tuple of non-empty strings, "
                f"got {vars_tuple!r}"
            )
    if any(existing.key == spec.key for existing in _REGISTRY):
        raise ValueError(f"duplicate provider key {spec.key!r} is already registered")
    _REGISTRY.append(spec)


def get_provider(key: str) -> ProviderSpec:
    """Return the registered provider for ``key`` (case-insensitive).

    Raises ``ValueError`` listing the available keys otherwise.
    """
    if not isinstance(key, str):
        raise ValueError(f"provider key must be a string, got {key!r}")
    wanted = key.lower()
    for spec in _REGISTRY:
        if spec.key == wanted:
            return spec
    available = ", ".join(spec.key for spec in _REGISTRY)
    raise ValueError(f"unknown provider {key!r}: available: {available}")


def list_providers() -> tuple[ProviderSpec, ...]:
    """All registered providers in registration order (built-ins first)."""
    return tuple(_REGISTRY)


def resolve_provider_api_key(
    spec: ProviderSpec, env: Mapping[str, str] | None = None
) -> str | None:
    """Resolve ``spec``'s API key: provider variable first, then the
    ``TYPESAFE_API_KEY`` fallback; ``None`` when unset."""
    return _lookup(spec.api_key_vars, env)


def resolve_provider_base_url(
    spec: ProviderSpec, env: Mapping[str, str] | None = None
) -> str:
    """Resolve ``spec``'s base URL, defaulting to ``spec.default_base_url``."""
    return _lookup(spec.base_url_vars, env) or spec.default_base_url


def resolve_provider_model(
    spec: ProviderSpec, env: Mapping[str, str] | None = None
) -> str:
    """Resolve ``spec``'s model name, defaulting to ``spec.default_model``."""
    return _lookup(spec.model_vars, env) or spec.default_model


register_provider(
    ProviderSpec(
        key="jev",
        display_name="TypeSafe Jev (System One)",
        default_base_url="https://api.typesafe.ai",
        api_key_vars=("JEV_API_KEY", "TYPESAFE_API_KEY"),
        base_url_vars=("JEV_BASE_URL", "TYPESAFE_BASE_URL"),
        default_model="jev-latest",
        model_vars=("JEV_MODEL", "TYPESAFE_DEFAULT_MODEL"),
        docs_url="https://docs.typesafe.ai/concepts/system-one.md",
    )
)
register_provider(
    ProviderSpec(
        key="jeff",
        display_name="Jeff (self-hosted System One)",
        default_base_url="http://localhost:8000",
        api_key_vars=("JEFF_API_KEY", "TYPESAFE_API_KEY"),
        base_url_vars=("JEFF_BASE_URL", "TYPESAFE_BASE_URL"),
        default_model="jev-latest",
        model_vars=("JEFF_MODEL",),
        notes=(
            "Self-hosted GLiFormer server "
            "(https://github.com/logan-markewich/jeff) with drop-in wire "
            "compatibility; behavioral caveats: probabilities are "
            "temperature-scaled and output token counts are nominal."
        ),
    )
)
register_provider(
    ProviderSpec(
        key="kev",
        display_name="Kev (self-hosted System One)",
        default_base_url="http://localhost:8009",
        api_key_vars=("KEV_API_KEY", "TYPESAFE_API_KEY"),
        base_url_vars=("KEV_BASE_URL", "TYPESAFE_BASE_URL"),
        default_model="kev-latest",
        model_vars=("KEV_MODEL",),
        notes=(
            "Self-hosted Qwen3.5 0.8B/4B/9B server "
            "(https://github.com/jaredpalmer/kev) with drop-in wire "
            "compatibility; responses add an extra top-level latency_ms "
            "field, which the strict parser tolerates and ignores."
        ),
    )
)
register_provider(
    ProviderSpec(
        key="localjev",
        display_name="LocalJev (GitHub Next)",
        default_base_url="http://127.0.0.1:8080",
        api_key_vars=("LOCALJEV_API_KEY", "TYPESAFE_API_KEY"),
        base_url_vars=("LOCALJEV_BASE_URL", "TYPESAFE_BASE_URL"),
        default_model="localjev-latest",
        model_vars=("LOCALJEV_MODEL",),
        docs_url="https://github.com/githubnext/localjev",
        notes=(
            "TypeScript/Bun server (MIT) that proxies any OpenAI-compatible "
            "chat endpoint into the System One wire contract with "
            "entropy-based confidence; accepts the model aliases "
            "jev-latest, localjev-latest and localjev-0.2."
        ),
    )
)
register_provider(
    ProviderSpec(
        key="openthai-systemone",
        display_name="OpenThai System One",
        default_base_url="http://localhost:8077",
        api_key_vars=("OPENTHAI_API_KEY", "TYPESAFE_API_KEY"),
        base_url_vars=("OPENTHAI_BASE_URL", "TYPESAFE_BASE_URL"),
        default_model="openthai-latest",
        model_vars=("OPENTHAI_MODEL",),
        docs_url="https://github.com/iapp-technology/openthai-systemone",
        notes=(
            "Auth-free Thai/English Qwen3.5-0.8B server (Apache-2.0) using "
            "a 256-way slot-softmax with an abstain slot. It exposes no "
            "/v1/models, so the models listing is unsupported through this "
            "provider, and it performs no auth — pass any non-empty "
            "api_key to satisfy the client's key check."
        ),
    )
)
register_provider(
    ProviderSpec(
        key="openrouter",
        display_name="OpenRouter (hosted System One proxy)",
        default_base_url="https://openrouter.ai/api",
        api_key_vars=("OPENROUTER_API_KEY", "TYPESAFE_API_KEY"),
        base_url_vars=("OPENROUTER_BASE_URL", "TYPESAFE_BASE_URL"),
        default_model="jev-latest",
        model_vars=(),
        docs_url="https://openrouter.ai/docs",
        notes=(
            "Hosted proxy of the official System One API billed to an "
            "OpenRouter account. Responses add extra top-level id/provider "
            "fields and usage.cost, which the strict parser tolerates and "
            "ignores; /v1/models returns the OpenRouter listing shape, so "
            "the models command is unsupported through this provider."
        ),
    )
)