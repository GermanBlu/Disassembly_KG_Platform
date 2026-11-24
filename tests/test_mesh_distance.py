"""Mesh-distance tests: verify the point-to-triangle kernel and the
mesh-vs-exact calibration the mesh path rests on.

The OCC-free unit tests pin _point_triangle_dist2 against analytic geometry
(interior projection, vertex region, edge region, in-plane zero). The OCC test
asserts the actual calibration claim from the docstring: thresholding the mesh
gap matrix reproduces the SAME 9-contact liaison as exact BRepExtrema on the
Hypothetical Product.
"""
import math

import numpy as np
import pytest

from conftest import requires_occ
from pipeline.mesh_distance import _point_triangle_dist2


# Reference triangle in the z=0 plane.
_A = np.array([0.0, 0.0, 0.0])
_B = np.array([1.0, 0.0, 0.0])
_C = np.array([0.0, 1.0, 0.0])


def _d2(point):
    p = np.array([point], dtype=float)
    return float(_point_triangle_dist2(p, _A[None], _B[None], _C[None])[0])


def test_point_above_interior_projects_orthogonally():
    # Above the centroid → closest point is the in-face projection; dist = height.
    assert math.isclose(_d2((0.25, 0.25, 2.0)), 4.0, rel_tol=1e-9)


def test_point_in_plane_inside_is_zero():
    assert _d2((0.25, 0.25, 0.0)) < 1e-12


def test_point_beyond_vertex_a():
    # Down-left of A → closest point is vertex A.
    assert math.isclose(_d2((-1.0, -1.0, 0.0)), 2.0, rel_tol=1e-9)


def test_point_beyond_edge_ab():
    # Below edge AB (y<0, 0<x<1) → closest point on AB at (0.5, 0, 0).
    assert math.isclose(_d2((0.5, -1.0, 0.0)), 1.0, rel_tol=1e-9)


def test_point_beyond_edge_bc_uses_hypotenuse():
    # Outward past the hypotenuse BC (line x+y=1). Point (1,1,0) projects to its
    # midpoint (0.5,0.5,0); distance = sqrt(2)/2 → squared = 0.5.
    assert math.isclose(_d2((1.0, 1.0, 0.0)), 0.5, rel_tol=1e-9)


def test_vectorised_batch_matches_scalar():
    pts = np.array([[0.25, 0.25, 2.0], [-1.0, -1.0, 0.0], [0.5, -1.0, 0.0]])
    a = np.repeat(_A[None], 3, axis=0)
    b = np.repeat(_B[None], 3, axis=0)
    c = np.repeat(_C[None], 3, axis=0)
    out = _point_triangle_dist2(pts, a, b, c)
    assert np.allclose(out, [4.0, 2.0, 1.0])


# ── Calibration: mesh liaison == exact liaison on the golden product (OCC) ────

_HYPO = "sample_data/Hypothetical Product STEP/Hypothetical Product.step"


@requires_occ
def test_mesh_and_exact_agree_on_hypothetical_liaison():
    """The mesh gap matrix, thresholded, must yield the same 9-contact liaison as
    exact BRepExtrema (the calibration the mesh path depends on)."""
    import os
    if not os.path.exists(_HYPO):
        pytest.skip("Hypothetical STEP not present")

    from pipeline.geometry import load_parts_from_assembly
    from pipeline.liaison_matrix import (
        compute_gap_matrix, exact_gap, auto_contact_threshold, characteristic_size,
    )

    parts = [p for p, _, _ in load_parts_from_assembly(_HYPO)]
    n = len(parts)
    assert n == 8

    # Mesh gap matrix + the auto threshold it derives.
    G, cs = compute_gap_matrix(parts)
    tol, _info = auto_contact_threshold(G, cs)
    mesh_lm = [[1 if (i != j and G[i][j] < tol) else 0 for j in range(n)] for i in range(n)]

    # Exact gap matrix at the same threshold.
    exact_lm = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            g = exact_gap(parts[i], parts[j])
            if g < tol:
                exact_lm[i][j] = exact_lm[j][i] = 1

    assert mesh_lm == exact_lm, "mesh vs exact liaison disagree at the auto threshold"
    contacts = sum(sum(row) for row in mesh_lm) // 2
    assert contacts == 9
