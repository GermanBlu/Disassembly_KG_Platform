"""DEMO_MODE server-side read-only enforcement.

The before_request guard fires before the view, so these assert the security
guarantee without needing Neo4j/OpenAI/OCC.
"""
import pytest

import config
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_config_endpoint_reflects_demo_mode(client, monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert client.get("/api/config").get_json()["demo_mode"] is False
    monkeypatch.setattr(config, "DEMO_MODE", True)
    assert client.get("/api/config").get_json()["demo_mode"] is True


WRITE_ENDPOINTS = [
    ("post", "/api/products"),
    ("delete", "/api/products/Prod_X"),
    ("post", "/api/products/Prod_X/structural"),
    ("post", "/api/products/Prod_X/operational"),
    ("patch", "/api/products/Prod_X/nodes/N1/properties"),
    ("delete", "/api/products/Prod_X/nodes/N1/properties/material"),
    ("post", "/api/library/items/Tool"),
    ("post", "/api/library/reset"),
    ("post", "/api/library/ensure"),
    ("post", "/api/step/run"),
    ("post", "/api/step/generate-tables"),
]


@pytest.mark.parametrize("method,path", WRITE_ENDPOINTS, ids=[f"{m}:{p}" for m, p in WRITE_ENDPOINTS])
def test_writes_blocked_in_demo(client, monkeypatch, method, path):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    resp = getattr(client, method)(path)
    assert resp.status_code == 403
    assert "read-only" in resp.get_json()["error"].lower()


def test_chat_is_allowed_in_demo(client, monkeypatch):
    # Whitelisted: the guard must NOT block it. An empty message returns 400 from
    # the view itself (before any Neo4j/OpenAI), proving the request passed the guard.
    monkeypatch.setattr(config, "DEMO_MODE", True)
    resp = client.post("/api/products/Prod_X/chat", json={"message": ""})
    assert resp.status_code != 403
    assert resp.status_code == 400


def test_engine_write_handlers_refuse_in_read_only():
    """The chat endpoint is whitelisted from the HTTP guard, so the engine's own
    read_only gate is the ONLY thing stopping a write via chat. Every route into a
    write handler (keyword detector, rule-14 USE_ENRICHMENT_MODE handoff) lands in
    _handle_mutation / _handle_reassignment — assert they refuse before any LLM
    call, regardless of phrasing or field (a mass-write request can pass the
    keyword detector and still be routed into enrichment by rule 14)."""
    import json
    import types

    from rag.engine import GraphRAGEngine, READ_ONLY_MSG

    llm_calls = []
    stub = types.SimpleNamespace(
        read_only=True,
        debug_log=[],
        _log=lambda *a, **k: None,
        _sse=lambda kind, data: json.dumps({"type": kind, "data": data}),
        _call_responses=lambda *a, **k: llm_calls.append(1),  # must never be reached
    )

    phrasings = [
        "Ändere die Masse von H auf 200 g und speichere das",  # keyword-missed → rule-14 path
        "set the weight of the shaft to 250",
        "entferne es",                                          # ambiguous two-word command
        "change the agent for task T003",
    ]
    def events(raw):  # parse the stub's json-serialised SSE events back to objects
        return [json.loads(e) for e in raw]

    for handler in (GraphRAGEngine._handle_mutation, GraphRAGEngine._handle_reassignment):
        for q in phrasings:
            evs = events(handler(stub, q))
            tokens = [e["data"] for e in evs if e["type"] == "token"]
            # Exactly one token — the refusal — and nothing else (no success message).
            assert tokens == [READ_ONLY_MSG], f"{handler.__name__} did not refuse: {q!r}"
            done = [json.loads(e["data"]) for e in evs if e["type"] == "done"]
            assert done and done[-1].get("mutation") is False and done[-1].get("rows") == 0
    assert not llm_calls, "read-only gate must return before any LLM/Cypher generation"
