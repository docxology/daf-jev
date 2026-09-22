"""Unit tests for multi-provider dispatch.

Covers the provider registry (built-ins, validation, error messages),
per-provider config resolution, client construction wiring, CLI dispatch,
MCP provider plumbing, wire tolerance for extra top-level response fields
(kev ``latency_ms``), and Settings.provider.

The no-mock convention holds: the network stand-in is the REAL
ThreadingHTTPServer fixture from tests/conftest.py and requests ride the
real HttpxTransport; daf_jev internals are never patched. Production
modules are imported lazily inside tests so this file collects cleanly
regardless of lane completion order.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

# Registry keys in the pinned built-in registration order.
SIX_KEYS = ("jev", "jeff", "kev", "localjev", "openthai-systemone", "openrouter")

# Per-provider primary credential variables (the var the keyless error names).
PRIMARY_KEY_VARS = {
    "jev": "JEV_API_KEY",
    "jeff": "JEFF_API_KEY",
    "kev": "KEV_API_KEY",
    "localjev": "LOCALJEV_API_KEY",
    "openthai-systemone": "OPENTHAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

_PROVIDER_ENV_VARS = (
    "JEV_API_KEY",
    "JEV_BASE_URL",
    "JEV_MODEL",
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "TYPESAFE_DEFAULT_MODEL",
    "JEFF_API_KEY",
    "JEFF_BASE_URL",
    "JEFF_MODEL",
    "KEV_API_KEY",
    "KEV_BASE_URL",
    "KEV_MODEL",
    "LOCALJEV_API_KEY",
    "LOCALJEV_BASE_URL",
    "LOCALJEV_MODEL",
    "OPENTHAI_API_KEY",
    "OPENTHAI_BASE_URL",
    "OPENTHAI_MODEL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "DAF_JEV_PROVIDER",
)


def run_cli(argv: list[str]) -> int:
    """main() returns an exit code; argparse usage errors raise SystemExit(2)."""
    from daf_jev.cli import main

    try:
        code = main(argv)
    except SystemExit as exc:
        code = exc.code
    return 0 if code is None else int(code)


def _providers_module():
    import daf_jev.providers as providers

    return providers


def _mcp_server_module():
    pytest.importorskip("mcp")
    pytest.importorskip("daf_jev.mcp_server")
    from daf_jev import mcp_server

    return mcp_server


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clean_provider_env(monkeypatch, tmp_path: Path):
    """Isolate provider resolution from the host env and the repo `.env`."""
    for name in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # the `.env` fallback resolves relative to CWD
    return monkeypatch


# ------------------------------------------------------------- shared bodies --


def _answers_body(model: str = "jev-latest") -> dict:
    return {
        "model": model,
        "usage": {"input_tokens": 120, "output_tokens": 45},
        "answers": {
            "billing": {"type": "noul", "noul": 0.87},
            "tone": {
                "type": "choice",
                "choice": "angry",
                "probabilities": {"calm": 0.2, "angry": 0.8},
                "confidence": 0.76,
            },
            "severity": {
                "type": "score",
                "score": 0.4,
                "legend": {"0": "low", "1": "high"},
                "probabilities": {"0": 0.6, "1": 0.4},
                "confidence": 0.9,
            },
        },
    }


def _models_body() -> dict:
    return {
        "models": [
            {
                "name": "kev-latest",
                "description": "flagship",
                "release_date": "2026-01-01",
            },
            {
                "name": "kev-mini",
                "description": "small",
                "release_date": "2026-06-01",
            },
        ]
    }


def _spec(key: str = "acme", **overrides):
    """A fully valid ProviderSpec for registration-error tests."""
    from daf_jev.providers import ProviderSpec

    kwargs: dict = {
        "key": key,
        "display_name": "Acme (self-hosted System One)",
        "default_base_url": "http://localhost:9001",
        "api_key_vars": ("ACME_API_KEY", "TYPESAFE_API_KEY"),
        "base_url_vars": ("ACME_BASE_URL", "TYPESAFE_BASE_URL"),
        "default_model": "acme-latest",
        "model_vars": ("ACME_MODEL",),
    }
    kwargs.update(overrides)
    return ProviderSpec(**kwargs)


# -------------------------------------------------- §6.1 registry + validation


def test_registry_builtin_order() -> None:
    providers = _providers_module()
    specs = providers.list_providers()
    assert isinstance(specs, tuple)
    assert [spec.key for spec in specs] == list(SIX_KEYS)


def test_builtin_spec_pinned_facts() -> None:
    providers = _providers_module()
    by_key = {spec.key: spec for spec in providers.list_providers()}

    jev = by_key["jev"]
    assert jev.display_name == "TypeSafe Jev (System One)"
    assert jev.default_base_url == "https://api.typesafe.ai"
    assert jev.default_model == "jev-latest"
    assert jev.api_key_vars == ("JEV_API_KEY", "TYPESAFE_API_KEY")
    assert jev.base_url_vars == ("JEV_BASE_URL", "TYPESAFE_BASE_URL")
    assert jev.model_vars == ("JEV_MODEL", "TYPESAFE_DEFAULT_MODEL")
    assert isinstance(jev.docs_url, str) and jev.docs_url.startswith("https://")

    jeff = by_key["jeff"]
    assert jeff.display_name == "Jeff (self-hosted System One)"
    assert jeff.default_base_url == "http://localhost:8000"
    assert jeff.default_model == "jev-latest"
    assert jeff.api_key_vars == ("JEFF_API_KEY", "TYPESAFE_API_KEY")
    assert jeff.base_url_vars == ("JEFF_BASE_URL", "TYPESAFE_BASE_URL")
    assert jeff.model_vars == ("JEFF_MODEL",)
    assert jeff.notes is not None
    assert "GLiFormer" in jeff.notes
    assert "https://github.com/logan-markewich/jeff" in jeff.notes

    kev = by_key["kev"]
    assert kev.display_name == "Kev (self-hosted System One)"
    assert kev.default_base_url == "http://localhost:8009"
    assert kev.default_model == "kev-latest"
    assert kev.api_key_vars == ("KEV_API_KEY", "TYPESAFE_API_KEY")
    assert kev.base_url_vars == ("KEV_BASE_URL", "TYPESAFE_BASE_URL")
    assert kev.model_vars == ("KEV_MODEL",)
    assert kev.notes is not None
    assert "Qwen3.5" in kev.notes
    assert "latency_ms" in kev.notes
    assert "https://github.com/jaredpalmer/kev" in kev.notes

    localjev = by_key["localjev"]
    assert localjev.default_base_url == "http://127.0.0.1:8080"
    assert localjev.default_model == "localjev-latest"
    assert localjev.api_key_vars[0] == "LOCALJEV_API_KEY"
    assert localjev.model_vars == ("LOCALJEV_MODEL",)
    assert isinstance(localjev.display_name, str) and localjev.display_name

    openthai = by_key["openthai-systemone"]
    assert openthai.default_base_url == "http://localhost:8077"
    assert openthai.default_model == "openthai-latest"
    assert openthai.api_key_vars[0] == "OPENTHAI_API_KEY"
    assert isinstance(openthai.display_name, str) and openthai.display_name
    assert isinstance(openthai.notes, str) and openthai.notes

    openrouter = by_key["openrouter"]
    assert openrouter.default_base_url == "https://openrouter.ai/api"
    assert openrouter.default_model == "jev-latest"
    assert openrouter.api_key_vars[0] == "OPENROUTER_API_KEY"
    assert openrouter.model_vars == ("OPENROUTER_MODEL",)


def test_get_provider_is_case_insensitive() -> None:
    providers = _providers_module()
    assert providers.get_provider("JEV").key == "jev"
    assert providers.get_provider("Jeff").key == "jeff"
    assert providers.get_provider("KEV").key == "kev"
    assert providers.get_provider("LocalJev").key == "localjev"
    assert providers.get_provider("OPENTHAI-SystemOne").key == "openthai-systemone"
    assert providers.get_provider("OpenRouter").key == "openrouter"


def test_unknown_provider_message_lists_all_six_keys() -> None:
    providers = _providers_module()
    with pytest.raises(ValueError) as excinfo:
        providers.get_provider("bogus")
    assert str(excinfo.value) == (
        "unknown provider 'bogus': available: "
        + ", ".join(SIX_KEYS)
    )


def test_register_provider_rejects_duplicate_key() -> None:
    providers = _providers_module()
    with pytest.raises(ValueError, match="jev"):
        providers.register_provider(_spec(key="jev"))
    # Fail-closed registration: the failed attempt leaves the registry alone.
    assert [spec.key for spec in providers.list_providers()] == list(SIX_KEYS)


def test_register_provider_rejects_invalid_key_pattern() -> None:
    providers = _providers_module()
    for bad_key in ("", "1abc", "UPPER", "has space", "-leading"):
        with pytest.raises(ValueError):
            providers.register_provider(_spec(key=bad_key))
    assert [spec.key for spec in providers.list_providers()] == list(SIX_KEYS)


def test_register_provider_rejects_blank_required_fields() -> None:
    providers = _providers_module()
    for field in ("display_name", "default_base_url", "default_model"):
        with pytest.raises(ValueError):
            providers.register_provider(_spec(**{field: ""}))
    assert [spec.key for spec in providers.list_providers()] == list(SIX_KEYS)


def test_package_exports_provider_surface() -> None:
    import daf_jev

    for name in (
        "ProviderSpec",
        "register_provider",
        "get_provider",
        "list_providers",
        "open_client",
        "open_async_client",
    ):
        assert hasattr(daf_jev, name)
        assert name in daf_jev.__all__


# --------------------------------------------- §6.2 per-provider resolution ---


def test_resolve_api_key_precedence_per_provider() -> None:
    providers = _providers_module()
    kev = providers.get_provider("kev")
    # provider env var beats the TYPESAFE_* fallback
    assert (
        providers.resolve_provider_api_key(
            kev, {"KEV_API_KEY": "k", "TYPESAFE_API_KEY": "ts"}
        )
        == "k"
    )
    # TYPESAFE_* fallback honored (last var for every provider)
    assert providers.resolve_provider_api_key(kev, {"TYPESAFE_API_KEY": "ts"}) == "ts"
    assert (
        providers.resolve_provider_api_key(
            providers.get_provider("openrouter"), {"TYPESAFE_API_KEY": "ts"}
        )
        == "ts"
    )
    # nothing anywhere -> None
    assert providers.resolve_provider_api_key(kev, {}) is None
    # every built-in honors its own primary var
    for key, var in PRIMARY_KEY_VARS.items():
        spec = providers.get_provider(key)
        assert providers.resolve_provider_api_key(spec, {var: "primary-key"}) == (
            "primary-key"
        )


def test_resolve_api_key_skips_falsy_env_values() -> None:
    providers = _providers_module()
    kev = providers.get_provider("kev")
    assert (
        providers.resolve_provider_api_key(
            kev, {"KEV_API_KEY": "", "TYPESAFE_API_KEY": "ts"}
        )
        == "ts"
    )
    # whitespace-only counts as unset, same as the existing _lookup semantics
    assert (
        providers.resolve_provider_api_key(
            kev, {"KEV_API_KEY": "   ", "TYPESAFE_API_KEY": "ts"}
        )
        == "ts"
    )
    assert providers.resolve_provider_api_key(kev, {"KEV_API_KEY": "  "}) is None


def test_resolve_base_url_and_model_precedence() -> None:
    providers = _providers_module()
    kev = providers.get_provider("kev")
    assert providers.resolve_provider_base_url(kev, {"KEV_BASE_URL": "http://s"}) == (
        "http://s"
    )
    assert providers.resolve_provider_base_url(kev, {"TYPESAFE_BASE_URL": "http://t"}) == (
        "http://t"
    )
    assert providers.resolve_provider_base_url(kev, {}) == "http://localhost:8009"
    assert providers.resolve_provider_model(kev, {"KEV_MODEL": "kev-4b"}) == "kev-4b"
    assert providers.resolve_provider_model(kev, {}) == "kev-latest"

    jev = providers.get_provider("jev")
    assert providers.resolve_provider_model(jev, {"TYPESAFE_DEFAULT_MODEL": "x"}) == "x"
    assert providers.resolve_provider_base_url(jev, {}) == "https://api.typesafe.ai"

    # steering-added built-ins honor their own env names
    localjev = providers.get_provider("localjev")
    assert (
        providers.resolve_provider_base_url(localjev, {"LOCALJEV_BASE_URL": "http://s"})
        == "http://s"
    )
    assert providers.resolve_provider_base_url(localjev, {}) == "http://127.0.0.1:8080"
    assert providers.resolve_provider_model(localjev, {"LOCALJEV_MODEL": "localjev-9b"}) == (
        "localjev-9b"
    )
    assert providers.resolve_provider_model(localjev, {}) == "localjev-latest"

    openthai = providers.get_provider("openthai-systemone")
    assert (
        providers.resolve_provider_base_url(
            openthai, {"OPENTHAI_BASE_URL": "http://s"}
        )
        == "http://s"
    )
    assert providers.resolve_provider_base_url(openthai, {}) == "http://localhost:8077"
    assert providers.resolve_provider_model(openthai, {"OPENTHAI_MODEL": "openthai-4b"}) == (
        "openthai-4b"
    )
    assert providers.resolve_provider_model(openthai, {}) == "openthai-latest"

    # openrouter resolves its model through OPENROUTER_MODEL
    openrouter = providers.get_provider("openrouter")
    assert providers.resolve_provider_model(openrouter, {}) == "jev-latest"
    assert (
        providers.resolve_provider_model(
            openrouter, {"OPENROUTER_MODEL": "openrouter/custom"}
        )
        == "openrouter/custom"
    )
    assert providers.resolve_provider_base_url(openrouter, {}) == (
        "https://openrouter.ai/api"
    )


def test_jev_compat_resolvers_delegate_to_jev_spec() -> None:
    providers = _providers_module()
    from daf_jev.config import resolve_api_key, resolve_base_url, resolve_model

    env = {"JEV_API_KEY": "a", "JEV_BASE_URL": "http://j", "JEV_MODEL": "jev-x"}
    jev = providers.get_provider("jev")
    assert resolve_api_key(env) == providers.resolve_provider_api_key(jev, env)
    assert resolve_base_url(env) == providers.resolve_provider_base_url(jev, env)
    assert resolve_model(env) == providers.resolve_provider_model(jev, env)


# ------------------------------------------------- §6.7 Settings.provider -----


def test_settings_provider_field_defaults_to_jev() -> None:
    from daf_jev.config import load_settings

    settings = load_settings({"JEV_API_KEY": "k1", "JEV_BASE_URL": "http://x"})
    assert settings.provider == "jev"
    assert settings.api_key == "k1"
    assert settings.base_url == "http://x"
    assert settings.model == "jev-latest"


def test_load_settings_provider_kev_resolves_kev_surfaces() -> None:
    from daf_jev.config import load_settings

    settings = load_settings(
        {
            "KEV_API_KEY": "k2",
            "KEV_BASE_URL": "http://kev-host:8009",
            "KEV_MODEL": "kev-4b",
        },
        provider="kev",
    )
    assert settings.provider == "kev"
    assert settings.api_key == "k2"
    assert settings.base_url == "http://kev-host:8009"
    assert settings.model == "kev-4b"
    # defaults when the kev env vars are silent
    plain = load_settings({"KEV_API_KEY": "k2"}, provider="kev")
    assert plain.base_url == "http://localhost:8009"
    assert plain.model == "kev-latest"


def test_load_settings_accepts_provider_spec_instance() -> None:
    from daf_jev.config import load_settings

    spec = _providers_module().get_provider("OpenRouter")
    settings = load_settings({"OPENROUTER_API_KEY": "or-key"}, provider=spec)
    assert settings.provider == "openrouter"
    assert settings.api_key == "or-key"
    assert settings.model == "jev-latest"
    assert settings.base_url == "https://openrouter.ai/api"


# ------------------------------------------------- §6.3 client wiring ---------


def test_for_provider_kev_uses_kev_env_and_default_model(stub) -> None:
    from daf_jev import JevClient, NoulQuestion, RetryPolicy

    stub.enqueue(body=_answers_body(model="kev-latest"))
    client = JevClient.for_provider(
        "kev",
        env={"KEV_API_KEY": "kev-key", "KEV_BASE_URL": stub.base_url},
        retry=RetryPolicy(jitter=0.0),
    )
    try:
        resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    finally:
        client.close()
    assert resp.nouls["billing"].noul == 0.87
    hit = stub.hits[0]
    # default model came from the kev spec (no KEV_MODEL env anywhere)
    assert hit["json"]["model"] == "kev-latest"
    assert hit["headers"]["authorization"] == "Bearer kev-key"


def test_for_provider_jeff_uses_jeff_env(stub) -> None:
    from daf_jev import JevClient, NoulQuestion, RetryPolicy

    stub.enqueue(body=_answers_body())
    client = JevClient.for_provider(
        "jeff",
        env={"JEFF_API_KEY": "jeff-key", "JEFF_BASE_URL": stub.base_url},
        retry=RetryPolicy(jitter=0.0),
    )
    try:
        resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    finally:
        client.close()
    assert resp.nouls["billing"].noul == 0.87
    hit = stub.hits[0]
    assert hit["json"]["model"] == "jev-latest"  # jeff default model
    assert hit["headers"]["authorization"] == "Bearer jeff-key"


def test_for_provider_localjev_and_openthai_wiring(stub) -> None:
    from daf_jev import JevClient, NoulQuestion, RetryPolicy

    for key, key_var, base_var, default_model in (
        ("localjev", "LOCALJEV_API_KEY", "LOCALJEV_BASE_URL", "localjev-latest"),
        (
            "openthai-systemone",
            "OPENTHAI_API_KEY",
            "OPENTHAI_BASE_URL",
            "openthai-latest",
        ),
    ):
        stub.enqueue(body=_answers_body(model=default_model))
        client = JevClient.for_provider(
            key,
            env={key_var: "wire-key", base_var: stub.base_url},
            retry=RetryPolicy(jitter=0.0),
        )
        try:
            resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
        finally:
            client.close()
        assert resp.nouls["billing"].noul == 0.87
        hit = stub.hits[-1]
        assert hit["json"]["model"] == default_model
        assert hit["headers"]["authorization"] == "Bearer wire-key"


def test_for_provider_keyless_error_names_provider_primary_var(clean_provider_env) -> None:
    from daf_jev import JevClient
    from daf_jev._errors import TypeSafeError

    for key, var in PRIMARY_KEY_VARS.items():
        with pytest.raises(TypeSafeError) as excinfo:
            JevClient.for_provider(key, env={})
        assert str(excinfo.value) == (
            "No API key found: pass api_key, set "
            f"{var} (or TYPESAFE_API_KEY), or inject a transport."
        )


def test_for_provider_injected_transport_removes_key_requirement(stub) -> None:
    from daf_jev import JevClient, NoulQuestion, RetryPolicy
    from daf_jev._http import HttpxTransport

    stub.enqueue(body=_answers_body())
    transport = HttpxTransport(base_url=stub.base_url, timeout=5.0)
    client = JevClient.for_provider("jeff", transport=transport, retry=RetryPolicy(jitter=0.0))
    try:
        resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    finally:
        client.close()
        transport.close()
    assert resp.nouls["billing"].noul == 0.87
    assert len(stub.hits) == 1


def test_client_explicit_args_beat_provider_env(stub) -> None:
    from daf_jev import JevClient, NoulQuestion, RetryPolicy

    stub.enqueue(body=_answers_body(model="explicit-model"))
    client = JevClient.for_provider(
        "kev",
        api_key="explicit-key",
        base_url=stub.base_url,
        model="explicit-model",
        env={"KEV_API_KEY": "env-key", "KEV_MODEL": "kev-4b"},
        retry=RetryPolicy(jitter=0.0),
    )
    try:
        resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    finally:
        client.close()
    assert resp.nouls["billing"].noul == 0.87
    hit = stub.hits[0]
    assert hit["headers"]["authorization"] == "Bearer explicit-key"
    assert hit["json"]["model"] == "explicit-model"


def test_open_client_forwards_provider_and_kwargs(stub) -> None:
    from daf_jev import RetryPolicy, open_client

    stub.enqueue(body=_models_body())
    client = open_client(
        provider="kev",
        env={"KEV_API_KEY": "kev-key", "KEV_BASE_URL": stub.base_url},
        retry=RetryPolicy(jitter=0.0),
    )
    try:
        cards = client.models()
    finally:
        client.close()
    assert [card.name for card in cards] == ["kev-latest", "kev-mini"]
    assert stub.hits[0]["method"] == "GET"
    # default provider is jev; explicit args route through the same path
    stub.enqueue(body=_models_body())
    client = open_client(
        api_key="jev-key", base_url=stub.base_url, retry=RetryPolicy(jitter=0.0)
    )
    try:
        cards = client.models()
    finally:
        client.close()
    assert [card.name for card in cards] == ["kev-latest", "kev-mini"]


def test_open_async_client_forwards_provider(stub) -> None:
    from daf_jev import NoulQuestion, RetryPolicy, open_async_client

    stub.enqueue(body=_answers_body(model="kev-latest"))

    async def flow():
        client = open_async_client(
            provider="kev",
            env={"KEV_API_KEY": "kev-key", "KEV_BASE_URL": stub.base_url},
            retry=RetryPolicy(jitter=0.0),
        )
        try:
            return await client.ask(
                "state", {"billing": NoulQuestion(instructions="q")}
            )
        finally:
            await client.close()

    resp = asyncio.run(flow())
    assert resp.nouls["billing"].noul == 0.87
    assert stub.hits[0]["json"]["model"] == "kev-latest"
    assert stub.hits[0]["headers"]["authorization"] == "Bearer kev-key"


# ------------------------------------------------------- §6.4 CLI dispatch ----


def test_cli_providers_subcommand_json_shape(stub, clean_provider_env, capsys) -> None:
    assert run_cli(["providers"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload[0]["key"] == "jev"
    required = {
        "key",
        "display_name",
        "default_base_url",
        "default_model",
        "api_key_env",
        "base_url_env",
        "model_env",
        "docs_url",
        "notes",
    }
    for entry in payload:
        assert required <= set(entry)
    jev = payload[0]
    assert jev["display_name"] == "TypeSafe Jev (System One)"
    assert jev["default_base_url"] == "https://api.typesafe.ai"
    assert jev["default_model"] == "jev-latest"
    assert jev["api_key_env"] == "JEV_API_KEY"
    assert jev["base_url_env"] == "JEV_BASE_URL"
    assert jev["model_env"] == "JEV_MODEL"
    assert isinstance(jev["docs_url"], str) and jev["docs_url"]
    # openrouter's model var resolves through OPENROUTER_MODEL
    openrouter = payload[-1]
    assert openrouter["key"] == "openrouter"
    assert openrouter["api_key_env"] == "OPENROUTER_API_KEY"
    assert openrouter["default_base_url"] == "https://openrouter.ai/api"
    assert openrouter["default_model"] == "jev-latest"
    assert openrouter["model_env"] == "OPENROUTER_MODEL"
    assert stub.hits == []  # keyless, no network


def test_cli_providers_order_matches_six_key_registry(
    stub, clean_provider_env, capsys
) -> None:
    assert run_cli(["providers"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [entry["key"] for entry in payload] == list(SIX_KEYS)
    assert stub.hits == []


def test_cli_provider_kev_models_keyless_names_kev_api_key(
    stub, clean_provider_env, capsys
) -> None:
    assert run_cli(["--provider", "kev", "models", "--base-url", stub.base_url]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "TypeSafeError"
    assert "KEV_API_KEY" in payload["message"]
    assert stub.hits == []  # the client is never constructed


def test_cli_unknown_provider_flag_exits_two(clean_provider_env) -> None:
    assert run_cli(["--provider", "bogus", "models"]) == 2


def test_cli_daf_jev_provider_env_selects_provider(
    stub, clean_provider_env, capsys
) -> None:
    clean_provider_env.setenv("DAF_JEV_PROVIDER", "kev")
    assert run_cli(["models", "--base-url", stub.base_url]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert "KEV_API_KEY" in payload["message"]


def test_cli_provider_flag_beats_daf_jev_provider_env(
    stub, clean_provider_env, capsys
) -> None:
    clean_provider_env.setenv("DAF_JEV_PROVIDER", "kev")
    assert run_cli(["--provider", "jeff", "models", "--base-url", stub.base_url]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert "JEFF_API_KEY" in payload["message"]


# -------------------------------------------------------- §6.5 MCP dispatch ---


def test_mcp_tools_plumb_provider_arg_kev(stub, clean_provider_env) -> None:
    ms = _mcp_server_module()
    clean_provider_env.setenv("KEV_API_KEY", "kev-key")
    clean_provider_env.setenv("KEV_BASE_URL", stub.base_url)
    stub.enqueue(body=_models_body())
    result = _run(ms.jev_models(provider="kev"))
    assert stub.hits[0]["path"] == "/v1/models"
    json.dumps(result)  # tool output stays JSON-safe across the wire
    stub.enqueue(body=_answers_body(model="kev-latest"))
    result = _run(
        ms.jev_ask(
            "state",
            {"billing": "noul:Is this about billing?"},
            provider="kev",
        )
    )
    assert stub.hits[1]["json"]["model"] == "kev-latest"
    json.dumps(result)


def test_mcp_default_provider_is_jev(stub, clean_provider_env) -> None:
    ms = _mcp_server_module()
    clean_provider_env.setenv("JEV_API_KEY", "test-key")
    clean_provider_env.setenv("JEV_BASE_URL", stub.base_url)
    stub.enqueue(body=_models_body())
    result = _run(ms.jev_models())
    assert stub.hits[0]["path"] == "/v1/models"
    json.dumps(result)


def test_mcp_unknown_provider_is_json_safe_error(stub, clean_provider_env) -> None:
    ms = _mcp_server_module()
    try:
        result = _run(ms.jev_models(provider="bogus"))
    except ValueError as exc:
        text = str(exc)
    else:
        text = json.dumps(result)
    assert "unknown provider" in text
    for key in SIX_KEYS:
        assert key in text
    assert stub.hits == []  # rejected before any client construction


# -------------------------------------------- §6.6 wire tolerance (kev) -------


def test_parse_response_tolerates_extra_top_level_latency_ms() -> None:
    from daf_jev._types import parse_response

    body = {**_answers_body(), "latency_ms": 123}
    resp = parse_response(body)
    assert resp.model == "jev-latest"
    assert resp.nouls["billing"].noul == 0.87
    assert resp.scores["severity"].score == 0.4


def test_client_ask_tolerates_kev_latency_ms_field(stub) -> None:
    from daf_jev import JevClient, NoulQuestion, RetryPolicy

    stub.enqueue(body={**_answers_body(), "latency_ms": 123})
    client = JevClient(
        api_key="k",
        base_url=stub.base_url,
        retry=RetryPolicy(jitter=0.0),
        sleep=lambda _seconds: None,
    )
    try:
        resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    finally:
        client.close()
    assert resp.nouls["billing"].noul == 0.87
    assert resp.scores["severity"].score == 0.4
    assert stub.hits[0]["json"]["model"] == "jev-latest"
def _composed_url(base_url: str) -> str:
    """Mirror the transport's URL composition (trailing-slash merge of the
    relative /v1/systemone path onto the base) — pins each provider's default
    against the documented endpoint."""
    # httpx enforces a trailing slash on the client base URL, then merges the
    # relative request path (leading slash stripped) by raw-path concatenation.
    base = base_url if base_url.endswith("/") else base_url + "/"
    return base + "v1/systemone"


def test_default_base_urls_compose_to_documented_endpoints():
    expected = {
        "jev": "https://api.typesafe.ai/v1/systemone",
        "jeff": "http://localhost:8000/v1/systemone",
        "kev": "http://localhost:8009/v1/systemone",
        "localjev": "http://127.0.0.1:8080/v1/systemone",
        "openthai-systemone": "http://localhost:8077/v1/systemone",
        "openrouter": "https://openrouter.ai/api/v1/systemone",
    }
    from daf_jev import list_providers

    for spec in list_providers():
        composed = _composed_url(spec.default_base_url)
        assert composed == expected[spec.key], (spec.key, composed)
        assert "/v1/v1/" not in composed
