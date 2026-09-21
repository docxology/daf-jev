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

from daf_jev import docs_verify

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


async def _resource_body(server, uri: str) -> dict:
    """Read a registered resource's BODY (not just its URI) as JSON."""
    manager = getattr(server, "_resource_manager", None)
    if manager is None or not hasattr(manager, "get_resource"):
        pytest.skip("no FastMCP resource manager available")
    resource = await manager.get_resource(uri)
    text = await resource.read()
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return json.loads(text)


def test_build_server_names_and_registers_everything() -> None:
    server = ms.build_server()
    assert server.name == "daf-jev"
    tools = _run(_tool_names(server))
    assert tools >= EXPECTED_TOOLS
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


def test_jev_evaluate_passes_object_and_array_states_through(mcp_stub_env) -> None:
    # Object/array states ride the public evaluate_async() path untouched:
    # the wire body carries them verbatim as the state.
    body = {
        "model": "jev-latest",
        "usage": {"input_tokens": 3, "output_tokens": 1},
        "answers": {
            "tone": {
                "type": "choice",
                "choice": "calm",
                "probabilities": {"calm": 1.0},
                "confidence": 0.9,
            }
        },
    }
    mcp_stub_env.enqueue(body=body)
    mcp_stub_env.enqueue(body=body)
    summary = _run(
        ms.jev_evaluate(
            [{"customer": "acme"}, ["line", "items"]],
            {"tone": "choice:tone?:calm,angry"},
        )
    )
    assert summary["n_states"] == 2
    assert summary["n_errors"] == 0
    assert summary["total_input_tokens"] == 6
    assert mcp_stub_env.hits[0]["json"]["state"] == {"customer": "acme"}
    assert mcp_stub_env.hits[1]["json"]["state"] == ["line", "items"]


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



# ---------------------------------------------- native question dict coverage -
def test_jev_ask_native_choice_and_score_criteria_reach_wire(
    mcp_stub_env,
) -> None:
    mcp_stub_env.enqueue(body=_answers_body())
    questions = {
        "tone": {
            "type": "choice",
            "instructions": "What is the tone?",
            "criteria": {"calm": None, "angry": "hostile"},
        },
        "severity": {
            "type": "score",
            "instructions": "Rate severity",
            "criteria": ["low", "high"],
        },
    }
    result = _run(ms.jev_ask("state text", questions))

    assert result["answers"]["tone"]["choice"] == "angry"
    hit = mcp_stub_env.hits[0]
    assert hit["json"]["questions"]["tone"] == {
        "type": "choice",
        "instructions": "What is the tone?",
        "criteria": {"calm": None, "angry": "hostile"},
    }
    assert hit["json"]["questions"]["severity"] == {
        "type": "score",
        "instructions": "Rate severity",
        "criteria": ["low", "high"],
    }


@pytest.mark.parametrize(
    ("question", "match"),
    [
        (42, "got int"),
        ({"instructions": "hi"}, "requires 'type'"),
        ({"type": "noul"}, "requires 'instructions'"),
        (
            {"type": "noul", "instructions": "h", "criteria": ["a"]},
            "noul criteria must be a mapping",
        ),
        (
            {"type": "choice", "instructions": "h", "criteria": {"calm": 5}},
            "must be a string or null, got int",
        ),
    ],
    ids=[
        "non-mapping",
        "missing-type",
        "missing-instructions",
        "noul-criteria-non-dict",
        "choice-criteria-non-str-value",
    ],
)
def test_jev_ask_native_question_validation_errors(
    mcp_stub_env, question, match
) -> None:
    # Validation happens before any network I/O (via question_from_mapping).
    with pytest.raises(ValueError, match=match):
        _run(ms.jev_ask("state", {"q": question}))
    assert mcp_stub_env.hits == []


# ------------------------------------------------------- composite score edges
def test_jev_composite_score_rejects_bad_probability_values() -> None:
    # A non-numeric probability fails at value conversion...
    with pytest.raises(ValueError, match="probabilities keys must be level"):
        _run(ms.jev_composite_score({"0": "high", "1": 0.5}))
    # ...and a numeric but negative one fails the finite/non-negative gate.
    with pytest.raises(ValueError, match="finite non-negative"):
        _run(ms.jev_composite_score({"0": -0.5, "1": 0.5}))


# ------------------------------------------------------------ docs verify extra
def test_jev_docs_verify_reports_url_mapping_drift(tmp_path) -> None:
    content = b"<html>page one</html>"
    (tmp_path / "page.html").write_bytes(content)
    manifest = {
        "pages": {
            "page.html": {
                # The URL maps elsewhere: drift even though the bytes match.
                "url": "https://docs.example.com/other.html",
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        }
    }
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    result = _run(ms.jev_docs_verify(str(tmp_path / "MANIFEST.json")))
    assert result["ok"] is False
    assert result["drifted"] == ["page.html (url maps to 'other.html')"]
    assert result["missing"] == []


def test_jev_docs_verify_lists_missing_page_files(tmp_path) -> None:
    content = b"<html>page one</html>"
    (tmp_path / "page.html").write_bytes(content)
    manifest = {
        "pages": {
            "page.html": {
                "url": "https://docs.example.com/page.html",
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            },
            "absent.html": {
                "url": "https://docs.example.com/absent.html",
                "sha256": "0" * 64,
                "bytes": 1,
            },
        }
    }
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    result = _run(ms.jev_docs_verify(str(tmp_path / "MANIFEST.json")))
    assert result["missing"] == ["absent.html"]
    assert result["drifted"] == []
    assert result["ok"] is False


# ---------------------------------------------------------- snapshot resource -
def test_docs_snapshot_resource_body_exposes_manifest_fields() -> None:
    server = ms.build_server()
    body = _run(_resource_body(server, SNAPSHOT_RESOURCE))
    assert isinstance(body, dict)
    assert "page_count" in body
    assert "snapshot_id" in body
    # Values agree with the repo's shipped snapshot manifest.
    manifest = json.loads(
        docs_verify.DEFAULT_MANIFEST.read_text(encoding="utf-8")
    )
    assert body["snapshot_id"] == manifest["snapshot_id"]
    assert body["page_count"] == manifest["page_count"]


def test_docs_snapshot_resource_error_shape_when_manifest_missing(
    monkeypatch, tmp_path
) -> None:
    # Input relocation, not behavior patching: point the resource at a
    # manifest path that does not exist so its error branch runs.
    monkeypatch.setattr(ms, "DEFAULT_MANIFEST", tmp_path / "absent.json")
    server = ms.build_server()
    body = _run(_resource_body(server, SNAPSHOT_RESOURCE))
    assert set(body) == {"error", "message", "ok"}
    assert body["ok"] is False
    assert body["error"]
    assert body["message"]


# -------------------------------------------------------------- JSON safety ---
def test_every_tool_output_is_json_serializable(mcp_stub_env) -> None:
    # MCP tools hand their results to a JSON wire: every tool's output
    # must survive json.dumps() -> json.loads() unchanged.
    mcp_stub_env.enqueue(body=_answers_body())
    asked = _run(
        ms.jev_ask("state", {"billing": "noul:Is this about billing?"})
    )
    mcp_stub_env.enqueue(body=_models_body())
    cards = _run(ms.jev_models())
    body = {
        "model": "jev-latest",
        "usage": {"input_tokens": 4, "output_tokens": 1},
        "answers": {
            "tone": {
                "type": "choice",
                "choice": "calm",
                "probabilities": {"calm": 1.0},
                "confidence": 0.9,
            }
        },
    }
    mcp_stub_env.enqueue(body=body)
    mcp_stub_env.enqueue(body=body)
    summary = _run(
        ms.jev_evaluate(
            ["s0", "s1"],
            {"tone": "choice:tone?:calm,angry"},
            concurrency=1,
        )
    )
    verified = _run(ms.jev_docs_verify())
    snapshot = _run(_resource_body(ms.build_server(), SNAPSHOT_RESOURCE))
    composite = _run(ms.jev_composite_score({"0": 0.5, "1": 0.5}))
    gated = _run(ms.jev_confidence_gate("calm", 0.9, 0.8))
    tiered = _run(ms.jev_tiered_gate("calm", 0.4))

    for label, payload in (
        ("jev_ask", asked),
        ("jev_models", cards),
        ("jev_evaluate", summary),
        ("jev_docs_verify", verified),
        ("jev://docs/snapshot", snapshot),
        ("jev_composite_score", composite),
        ("jev_confidence_gate", gated),
        ("jev_tiered_gate", tiered),
    ):
        assert json.loads(json.dumps(payload)) == payload, label
    assert len(mcp_stub_env.hits) == 4  # ask + models + 2 evaluate posts


# ---------------------------------------------------------- evaluate guarding -
def test_jev_evaluate_rejects_empty_states() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _run(ms.jev_evaluate([], {"tone": "choice:tone?:calm,angry"}))


@pytest.mark.parametrize("item", [42, None, 3.14])
def test_jev_evaluate_rejects_non_string_state_items(
    mcp_stub_env, item
) -> None:
    with pytest.raises(ValueError, match=r"states\[0\] must be a string"):
        _run(ms.jev_evaluate([item], {"tone": "choice:tone?:calm,angry"}))
    assert mcp_stub_env.hits == []


# ------------------------------------------------------------- models edges ---
def test_jev_models_empty_contains_is_no_filter(mcp_stub_env) -> None:
    mcp_stub_env.enqueue(body=_models_body())
    cards = _run(ms.jev_models(contains=""))
    assert [card["name"] for card in cards] == ["jev-latest", "jev-mini"]


def test_jev_models_invalid_pick_is_a_tool_error(mcp_stub_env) -> None:
    mcp_stub_env.enqueue(body=_models_body())
    with pytest.raises(ValueError, match="unknown prefer"):
        _run(ms.jev_models(pick="newest"))