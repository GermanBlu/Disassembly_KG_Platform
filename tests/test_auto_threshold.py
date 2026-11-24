"""Data-driven contact threshold (pipeline/liaison_matrix.py:auto_contact_threshold).

Synthetic gap matrices only — no OpenCASCADE — so these run fast everywhere and
pin the classification logic that real geometry feeds into.
"""
import numpy as np
import pytest

from pipeline.liaison_matrix import auto_contact_threshold, contacts_from_gap_matrix

INF = np.inf


def mat(n, edges, default):
    """N×N gap matrix: `default` off-diagonal, overridden by `edges` (i,j,gap)."""
    G = np.full((n, n), INF)
    for i in range(n):
        for j in range(i + 1, n):
            G[i][j] = G[j][i] = default
    for i, j, v in edges:
        G[i][j] = G[j][i] = v
    return G


def contacts(G, thr):
    lm = contacts_from_gap_matrix(np.where(np.isinf(G), -1.0, G), thr)
    return int(lm.sum()) // 2


def connected(G, thr):
    lm = contacts_from_gap_matrix(np.where(np.isinf(G), -1.0, G), thr)
    n = len(lm)
    seen, stack = {0}, [0]
    while stack:
        u = stack.pop()
        for v in range(n):
            if lm[u][v] and v not in seen:
                seen.add(v); stack.append(v)
    return len(seen) == n


# (name, gap-matrix, char_size, expected_contacts, expect_warning, expect_connected)
CASES = [
    ("mechanical 9@0",
     mat(8, [(i, i + 1, 0.0) for i in range(7)] + [(0, 2, 0.0), (4, 6, 0.0)], 20.0),
     20.0, 9, False, True),
    ("ecad star 12 leaves",
     mat(13, [(0, k + 1, ([0.0, 0.0, 0.01, 0.01] + [0.05] * 8)[k]) for k in range(12)], 3.0),
     0.47, 12, False, True),
    ("two touching", mat(2, [(0, 1, 0.0)], INF), 1.0, 1, None, True),
    ("two apart 5mm", mat(2, [(0, 1, 5.0)], INF), 1.0, 0, True, False),
    ("all touching n5", mat(5, [], 0.0), 2.0, 10, False, True),
    ("far outlier",
     mat(5, [(0, 1, 0.0), (1, 2, 0.0), (2, 3, 0.0), (0, 3, 0.0)] + [(4, k, 50.0) for k in range(4)], 50.0),
     2.0, None, True, False),
    ("single part", np.full((1, 1), INF), 1.0, 0, None, True),
    # a genuine redundant contact between eps and the valley
    ("redundant contact 0.05",
     mat(5, [(i, i + 1, 0.0) for i in range(4)] + [(0, 4, 0.05)], 2.0), 1.0, 5, False, True),
]


@pytest.mark.parametrize("name,G,cs,exp_c,exp_w,exp_conn", CASES, ids=[c[0] for c in CASES])
def test_auto_threshold_cases(name, G, cs, exp_c, exp_w, exp_conn):
    thr, info = auto_contact_threshold(G, cs)
    if exp_c is not None:
        assert contacts(G, thr) == exp_c
    if exp_conn is not None and len(G) > 1:
        assert connected(G, thr) is exp_conn
    if exp_w is True:
        assert info.get("warning")
    elif exp_w is False:
        assert not info.get("warning")
