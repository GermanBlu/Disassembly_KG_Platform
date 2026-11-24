"""Read-only DEMO_MODE hardening; test_demo_mode.py covers the basic cases.

Covers:
  1. a whitelist tripwire — fail loudly if the DEMO_MODE write-whitelist grows;
  2. every mutating route (not just a hand-picked few) returns 403 in DEMO_MODE;
  3. GET handlers do not write the library (ensure_library is a no-op in demo).

The 403 is decided in before_request, ahead of any Neo4j call, so these run
without a database.
"""
import re

import app as A


def test_write_whitelist_is_minimal():
    """Tripwire: only the GraphRAG chat may bypass the read-only guard."""
    assert A._DEMO_WRITE_WHITELIST == {"api_chat"}


def _concrete(rule):
    """Turn a URL rule ('/api/products/<product_id>') into a requestable path."""
    return re.sub(r"<[^>]+>", "x", rule.rule)


def test_all_mutating_routes_are_blocked_in_demo(monkeypatch):
    monkeypatch.setattr(A.config, "DEMO_MODE", True)
    client = A.app.test_client()

    checked = 0
    for rule in A.app.url_map.iter_rules():
        write_methods = (rule.methods or set()) & {"POST", "PUT", "PATCH", "DELETE"}
        if not write_methods or rule.endpoint in A._DEMO_WRITE_WHITELIST:
            continue
        path = _concrete(rule)
        for method in sorted(write_methods):
            resp = client.open(path, method=method)
            assert resp.status_code == 403, (
                f"{method} {path} -> {resp.status_code} (expected 403 read-only block)"
            )
            checked += 1
    assert checked > 0, "no mutating routes were exercised"


def test_whitelisted_routes_are_not_blocked_by_the_guard(monkeypatch):
    """The chat must still reach its handler in demo (it may 4xx/5xx for other
    reasons, but NOT the read-only 403)."""
    monkeypatch.setattr(A.config, "DEMO_MODE", True)
    client = A.app.test_client()
    resp = client.post("/api/products/x/chat", json={})
    assert resp.status_code != 403


def test_ensure_library_is_noop_in_demo(monkeypatch):
    """GET handlers must not issue the ensure_library MERGE in DEMO_MODE."""
    calls = []
    monkeypatch.setattr(A, "ensure_library", lambda drv: calls.append("write"))

    monkeypatch.setattr(A.config, "DEMO_MODE", True)
    A._ensure_library_unless_demo()
    assert calls == [], "ensure_library wrote in DEMO_MODE"

    monkeypatch.setattr(A.config, "DEMO_MODE", False)
    monkeypatch.setattr(A, "get_driver", lambda: "driver")
    A._ensure_library_unless_demo()
    assert calls == ["write"], "ensure_library should run when not in demo"
