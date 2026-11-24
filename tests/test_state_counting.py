"""The exact state-space count rests on this enumerator being correct.

Two independent anchors: closed-form counts for graph families where the
number of connected induced subgraphs is known analytically, and agreement
with the brute-force reference (all 2^n subsets + connectivity test) on
seeded random graphs. The 4,043,349 for the ungrouped pump is this function
on a 25-vertex input; its credibility is pinned here."""
import importlib.util
import os
import random

_SPEC = importlib.util.spec_from_file_location(
    "count_state_space",
    os.path.join(os.path.dirname(__file__), "..", "scripts",
                 "count_state_space.py"))
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

count_fast = _MOD.count_connected_subsets
count_ref = _MOD.count_connected_bruteforce


def _adj_from_edges(n, edges):
    adj = [0] * n
    for a, b in edges:
        adj[a] |= 1 << b
        adj[b] |= 1 << a
    return adj


def _path(n):
    return _adj_from_edges(n, [(i, i + 1) for i in range(n - 1)])


def _cycle(n):
    return _adj_from_edges(n, [(i, (i + 1) % n) for i in range(n)])


def _star(n):
    return _adj_from_edges(n, [(0, i) for i in range(1, n)])


def _complete(n):
    return _adj_from_edges(n, [(i, j) for i in range(n)
                               for j in range(i + 1, n)])


def test_closed_forms():
    for n in range(1, 12):
        assert count_fast(_path(n), n) == (n * (n + 1) // 2, True)
    for n in range(3, 12):
        assert count_fast(_cycle(n), n) == (n * (n - 1) + 1, True)
    for n in range(2, 12):
        assert count_fast(_star(n), n) == (2 ** (n - 1) + (n - 1), True)
    for n in range(1, 12):
        assert count_fast(_complete(n), n) == (2 ** n - 1, True)


def test_edgeless_graph_counts_singletons_only():
    n = 7
    assert count_fast([0] * n, n) == (n, True)


def test_matches_bruteforce_on_random_graphs():
    rng = random.Random(2026)
    for _ in range(120):
        n = rng.randint(2, 11)
        p = rng.choice([0.15, 0.3, 0.5, 0.8])
        edges = [(i, j) for i in range(n) for j in range(i + 1, n)
                 if rng.random() < p]
        adj = _adj_from_edges(n, edges)
        fast, complete = count_fast(adj, n)
        assert complete
        assert fast == count_ref(adj, n)


def test_limit_reports_incomplete():
    n = 6
    count, complete = count_fast(_complete(n), n, limit=10)
    assert not complete and count == 10
