"""AOG explosion guards + size estimate (pipeline/semantic + pipeline/aog_generation.py).

Pure-Python (no OpenCASCADE): build_aog and the semantic guards do not touch OCC.
"""
import numpy as np
import pytest

from pipeline.semantic import estimate_aog_complexity, generate_semantic_tables, MAX_PARTS
from pipeline.aog_builder import build_aog
from pipeline.aog_generation import AOGTooLargeError
from pipeline.part_ids import part_id


def star(n):
    G = np.zeros((n, n), int)
    for j in range(1, n):
        G[0][j] = G[j][0] = 1
    return G


def chain(n):
    G = np.zeros((n, n), int)
    for i in range(n - 1):
        G[i][i + 1] = G[i + 1][i] = 1
    return G


def complete(n):
    G = np.ones((n, n), int)
    np.fill_diagonal(G, 0)
    return G


class _P:
    def __init__(self, i):
        self.name = f"P{i}"
        self.id = i


def _labels(n):
    return [f"P{i} ({part_id(i)})" for i in range(n)]


def _no_interference(n):
    return [np.zeros((n, n), int).tolist() for _ in range(6)]


def test_estimate_catches_star_misses_chain():
    k_star, _, t_star = estimate_aog_complexity(star(13))
    assert k_star == 12 and t_star == 12 * 2 ** 11  # 24576 — relay-like
    k_big, _, t_big = estimate_aog_complexity(star(100))
    assert t_big > 200_000  # would be refused
    k_chain, _, t_chain = estimate_aog_complexity(chain(40))
    assert k_chain <= 2  # chains under-estimate (the in-loop cap is the backstop)


def test_build_aog_aborts_on_dense_graph():
    # Complete graph: the star estimate misses it (independent fan = 1), so the
    # in-loop candidate-pair / node cap must catch it.
    n = 25
    parts = [_P(i) for i in range(n)]
    with pytest.raises(AOGTooLargeError):
        build_aog(parts=parts, liaison_matrix=complete(n).tolist(),
                  interference_matrices=[np.zeros((n, n), int) for _ in range(6)],
                  max_candidate_pairs=2_000_000, max_nodes=200_000)


def test_build_aog_small_chain_ok():
    n = 5
    parts = [_P(i) for i in range(n)]
    tree = build_aog(parts=parts, liaison_matrix=chain(n).tolist(),
                     interference_matrices=[np.zeros((n, n), int) for _ in range(6)])
    assert len(tree.nodes) > 0


def test_semantic_refuses_over_62_parts():
    n = 63
    r = generate_semantic_tables(fastener_indices=[], part_labels=[f"P{i}" for i in range(n)],
                                 liaison_matrix=np.zeros((n, n), int).tolist(),
                                 interference_matrices=_no_interference(n))
    assert r["success"] is False
    assert str(MAX_PARTS) in r["error"]


def test_semantic_dense_graph_surfaces_clean_error():
    n = 25
    r = generate_semantic_tables(fastener_indices=[], part_labels=_labels(n),
                                 liaison_matrix=complete(n).tolist(),
                                 interference_matrices=_no_interference(n),
                                 settings={"aog": {"max_candidate_pairs": 2_000_000, "max_nodes": 200_000}})
    assert r["success"] is False
    assert "densely connected" in r["error"]


def test_semantic_small_chain_succeeds_with_ids():
    n = 30  # > 26 → exercises lowercase IDs end to end
    r = generate_semantic_tables(fastener_indices=[], part_labels=_labels(n),
                                 liaison_matrix=chain(n).tolist(),
                                 interference_matrices=_no_interference(n))
    assert r["success"] is True
    assert len(r["transitions"]) > 0
    states = "".join(t["from_parts"] for t in r["transitions"])
    assert any(c in states for c in "abcd")  # lowercase IDs present
