"""Unit tests for the daf-jev MCP server (daf_jev.mcp_server).

No network: the tools are pointed at the shared local stub server through
process environment (JEV_API_KEY / JEV_BASE_URL), never by patching daf_jev.
Behavior is exercised by calling the module-level tool functions directly
(they are plain async functions taking the contract args); one structural
test checks registration on the FastMCP instance, tolerating whichever
introspection API the installed mcp SDK exposes.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json

import pytest

pytest.importorskip("mcp")

ms = pytest.importorskip("daf_jev.mcp_server")

EXPECTED_TOOLS = frozenset(
    {
        "jev_ask",
        "jev_evaluate",
        "jev_models",
        "jev_composite_score",
        "jev_confidence_gate",
        "jev_tiered_gate",
        "jev_docs_verify",
    }
)
SNAPSHOT_RESOURCE = "jev://docs/snapshot"


# ----------------------------------------------------------------- fixtures ---
@pytest.fixture
def mcp_stub_env(stub, monkeypatch):
    """Point the MCP tools' settings resolution at the stub server."""
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    monkeypatch.setenv("JEV_BASE_URL", stub.base_url)
    for var in (
        "TYPESAFE_API_KEY",
        "TYPESAFE_BASE_URL",
        "JEV_MODEL",
        "TYPESAFE_DEFAULT_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    return stub


@pytest.fixture
def no_key_env(monkeypatch, tmp_path):
    """No API key anywhere: env cleared and the project `.env` out of reach."""
    for var in ("JEV_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # the `.env` fallback is resolved relative to CWD
    return None


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------ shared bodies ---
def _answers_body() -> dict:
    return {
        "model": "jev-latest",
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
                "name": "jev-latest",
                "description": "newest",
                "release_date": "2026-02-01",
            },
            {
                "name": "jev-mini",
                "description": "small",
                "release_date": "2025-06-01",
            },
        ]
    }


@pytest.fixture
def manifest_dir(tmp_path):
    """A docs manifest plus one page whose hash/size match."""
    content = b"<html>page one</html>"
    (tmp_path / "page.html").write_bytes(content)
    manifest = {
        "snapshot_id": "snap-1",
        "scraped_at": "2026-09-16T00:00:00Z",
        "index_sha256": "0" * 64,
        "pages": {
            "page.html": {
                "url": "https://docs.example.com/page.html",
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        },
    }
    path = tmp_path / "MANIFEST.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


# -------------------------------------------------------- structural checks ---
async def _tool_names(server) -> set[str]:
    for attr in ("list_tools", "_list_tools"):
        fn = getattr(server, attr, None)
        if callable(fn):
            result = fn()
            if inspect.isawaitable(result):
                result = await result
            return {tool.name for tool in result}
    manager = getattr(server, "_tool_manager", None)
    if manager is not None and hasattr(manager, "list_tools"):
        return {tool.name for tool in manager.list_tools()}
    pytest.skip("no FastMCP tool introspection API available")


async def _resource_uris(server) -> set[str]:
    for attr in ("list_resources", "_list_resources"):
        fn = getattr(server, attr, None)
        if callable(fn):
            result = fn()
            if inspect.isawaitable(result):
                result = await result
            return {str(resource.uri) for resource in result}
    manager = getattr(server, "_resource_manager", None)
    if manager is not None and hasattr(manager, "list_resources"):
        return {str(resource.uri) for resource in manager.list_resources()}
    pytest.skip("no FastMCP resource introspection API available")


def test_build_server_names_and_registers_everything() -> None:
    server = ms.build_server()
    assert server.name == "daf-jev"
    tools = _run(_tool_names(server))
    assert EXPECTED_TOOLS <= tools
    resources = _run(_resource_uris(server))
    assert SNAPSHOT_RESOURCE in resources


# --------------------------------------------------------------- jev_ask ------
def test_jev_ask_spec_string_questions(mcp_stub_env) -> None:
    mcp_stub_env.enqueue(
        body=_answers_body(), headers={"x-typesafe-request-id": "req-42"}
    )
    questions = {
        "billing": "noul:Is this about billing?",
        "tone": "choice:What is the tone?:calm,angry=hostile",
        "severity": "score:Rate severity:low,high",
    }
    result = _run(ms.jev_ask("I was charged twice.", questions))

    assert result["model"] == "jev-latest"
    assert result["request_id"] == "req-42"
    assert result["usage"] == {"input_tokens": 120, "output_tokens": 45}
    assert result["answers"]["billing"]["type"] == "noul"
    assert result["answers"]["billing"]["noul"] == pytest.approx(0.87)
    assert result["answers"]["tone"]["choice"] == "angry"
    assert result["answers"]["severity"]["score"] == pytest.approx(0.4)

    assert len(mcp_stub_env.hits) == 1
    hit = mcp_stub_env.hits[0]
    assert hit["json"]["state"] == "I was charged twice."
    assert hit["json"]["model"] == "jev-latest"
    assert hit["json"]["questions"]["billing"]["type"] == "noul"
    assert "calm" in hit["json"]["questions"]["tone"]["criteria"]
    assert "low" in hit["json"]["questions"]["severity"]["criteria"]


def test_jev_ask_accepts_dict_state_and_native_question_dicts(mcp_stub_env) -> None:
    mcp_stub_env.enqueue(body=_answers_body())
    questions = {
        "billing": {"type": "noul", "instructions": "Is this about billing?"}
    }
    result = _run(ms.jev_ask({"text": "I was charged twice."}, questions))

    assert result["answers"]["billing"]["noul"] == pytest.approx(0.87)
    hit = mcp_stub_env.hits[0]
    assert hit["json"]["state"] == {"text": "I was charged twice."}
    assert hit["json"]["questions"]["billing"]["type"] == "noul"


def test_jev_ask_requires_api_key(no_key_env) -> None:
    with pytest.raises(ValueError):
        _run(ms.jev_ask("state", {"billing": "noul:Is this about billing?"}))


# ---------------------------------------------------------- jev_evaluate ------
def test_jev_evaluate_returns_summary_only(mcp_stub_env) -> None:
    body = {
        "model": "jev-latest",
        "usage": {"input_tokens": 10, "output_tokens": 2},
        "answers": {
            "tone": {
                "type": "choice",
                "choice": "angry",
                "probabilities": {"calm": 0.2, "angry": 0.8},
                "confidence": 0.8,
            }
        },
    }
    for _ in range(4):
        mcp_stub_env.enqueue(body=body)
    states = ["s0", "s1", "s2", "s3"]
    questions = {"tone": "choice:What is the tone?:calm,angry"}

    summary = _run(ms.jev_evaluate(states, questions, concurrency=2))

    assert summary["n_states"] == 4
    assert summary["n_errors"] == 0
    assert summary["total_input_tokens"] == 40
    assert summary["total_output_tokens"] == 8
    assert summary["questions"]["tone"]["kind"] == "choice"
    assert summary["questions"]["tone"]["counts"] == {"angry": 4}
    assert summary["questions"]["tone"]["mode"] == "angry"
    assert "records" not in summary
    assert len(mcp_stub_env.hits) == 4


# ------------------------------------------------------------ jev_models ------
def test_jev_models_returns_cards_as_dicts(mcp_stub_env) -> None:
    mcp_stub_env.enqueue(body=_models_body())
    cards = _run(ms.jev_models())
    assert [card["name"] for card in cards] == ["jev-latest", "jev-mini"]
    assert cards[0]["description"] == "newest"
    assert cards[0]["release_date"] == "2026-02-01"


def test_jev_models_contains_filter_applies_pick_model(mcp_stub_env) -> None:
    # Each models call is one GET; the stub serves one queued program each.
    mcp_stub_env.enqueue(body=_models_body())
    mcp_stub_env.enqueue(body=_models_body())
    # pick_model prefer=latest: jev-latest has the max release_date.
    picked = _run(ms.jev_models(contains="jev"))
    assert [card["name"] for card in picked] == ["jev-latest"]

    picked = _run(ms.jev_models(contains="mini"))
    assert [card["name"] for card in picked] == ["jev-mini"]


def test_jev_models_pick_prefers_first_or_last(mcp_stub_env) -> None:
    # Two models calls, one queued program each.
    mcp_stub_env.enqueue(body=_models_body())
    mcp_stub_env.enqueue(body=_models_body())
    assert [card["name"] for card in _run(ms.jev_models(pick="first"))] == [
        "jev-latest"
    ]
    assert [card["name"] for card in _run(ms.jev_models(pick="last"))] == [
        "jev-mini"
    ]


def test_jev_models_no_match_raises(mcp_stub_env) -> None:
    mcp_stub_env.enqueue(body=_models_body())
    with pytest.raises(ValueError, match="nomatch"):
        _run(ms.jev_models(contains="nomatch"))


# ------------------------------------------------- pure decision helpers ------
def test_jev_composite_score_reweighted_math() -> None:
    # p=[0.25, 0.75], w=[1, 3] -> q=[0.1, 0.9] -> 0.9 (same as compose.py).
    assert _run(ms.jev_composite_score({"0": 0.25, "1": 0.75}, [1, 3])) == (
        pytest.approx(0.9)
    )
    assert _run(ms.jev_composite_score({"0": 0.2, "1": 0.3, "2": 0.5})) == (
        pytest.approx(1.3)
    )


def test_jev_composite_score_requires_two_levels() -> None:
    with pytest.raises(ValueError):
        _run(ms.jev_composite_score({"0": 1.0}))

def test_jev_confidence_gate_dispatch() -> None:
    assert _run(ms.jev_confidence_gate("escalate", 0.9, 0.8)) == "escalate"
    assert _run(ms.jev_confidence_gate("auto_reply", 0.4, 0.8)) == "review"
    assert _run(
        ms.jev_confidence_gate("auto_reply", 0.4, 0.8, below="human")
    ) == "human"


def test_jev_tiered_gate_dispatch() -> None:
    assert _run(ms.jev_tiered_gate("calm", 0.9)) == "automate"
    assert _run(ms.jev_tiered_gate("calm", 0.7)) == "review"
    assert _run(ms.jev_tiered_gate("calm", 0.3)) == "escalate"
    assert _run(
        ms.jev_tiered_gate(
            "calm",
            0.7,
            high=0.95,
            low=0.5,
            high_label="go",
            middle_label="check",
            low_label="human",
        )
    ) == "check"


# --------------------------------------------------------- jev_docs_verify ----
def test_jev_docs_verify_ok(manifest_dir) -> None:
    result = _run(ms.jev_docs_verify(str(manifest_dir / "MANIFEST.json")))
    assert result["ok"] is True
    assert result["pages"] == 1
    assert result["missing"] == []
    assert result["drifted"] == []


def test_jev_docs_verify_reports_drift(manifest_dir) -> None:
    (manifest_dir / "page.html").write_bytes(b"<html>edited</html>")
    result = _run(ms.jev_docs_verify(str(manifest_dir / "MANIFEST.json")))
    assert result["ok"] is False
    assert result["drifted"] == ["page.html"]
    assert result["missing"] == []


def test_jev_docs_verify_missing_manifest_is_error_string(tmp_path) -> None:
    result = _run(ms.jev_docs_verify(str(tmp_path / "absent.json")))
    assert result["ok"] is False
    assert result.get("error") or result.get("message")
