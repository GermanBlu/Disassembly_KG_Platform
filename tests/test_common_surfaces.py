"""Common surfaces EC = S_i ∩ S_j (pipeline.interference.common_surfaces).

Surface contact counts, line contact does not (Bahubalendruni et al. 2019); a
modelled clearance counts as contact only within the fuzzy value. Boxes built
with Open CASCADE primitives, no STEP file needed.
"""
import pytest

from conftest import requires_occ

pytestmark = [requires_occ]


def _box(x, y, z, dx, dy, dz):
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCC.Core.gp import gp_Pnt
    return BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), dx, dy, dz).Shape()


def _axes(surfaces):
    from pipeline.interference import _surface_axis
    return {tuple(abs(round(c, 6)) for c in _surface_axis(f)) for f, _ in surfaces}


def test_face_contact_gives_the_shared_patch():
    from pipeline.interference import common_surfaces
    base = _box(0, 0, 0, 100, 100, 10)
    block = _box(20, 20, 10, 30, 40, 10)          # sits on the top face
    shared = common_surfaces(base, block, 0.0)
    assert len(shared) == 1
    assert shared[0][1] == pytest.approx(30 * 40)
    assert _axes(shared) == {(0.0, 0.0, 1.0)}


def test_edge_contact_is_not_a_common_surface():
    from pipeline.interference import common_surfaces
    base = _box(0, 0, 0, 100, 100, 10)
    standing = _box(100, 0, 10, 10, 100, 10)       # touches the base along one edge only
    assert common_surfaces(base, standing, 0.5) == []


def test_clearance_counts_only_within_the_fuzzy_value():
    from pipeline.interference import common_surfaces
    base = _box(0, 0, 0, 100, 100, 10)
    hovering = _box(20, 20, 10.05, 30, 40, 10)     # 0.05 mm gap
    assert common_surfaces(base, hovering, 0.0) == []
    shared = common_surfaces(base, hovering, 0.5)
    assert len(shared) >= 1
    assert sum(a for _, a in shared) == pytest.approx(30 * 40, rel=0.01)


# ── Overlap check (pipeline.geometry.volume_overlaps) ─────────────────────────

class _Part:
    def __init__(self, shape):
        self.Shape = shape


def test_overlapping_parts_are_reported_touching_parts_are_not():
    from pipeline.geometry import volume_overlaps
    base = _box(0, 0, 0, 100, 100, 10)
    sitting = _box(20, 20, 10, 30, 40, 10)        # touches the top face
    sunk = _box(60, 60, 8, 10, 10, 10)            # 2 mm into the base
    parts = [_Part(base), _Part(sitting), _Part(sunk)]
    lm = [[0, 1, 1], [1, 0, 0], [1, 0, 0]]
    found = volume_overlaps(parts, lm)
    assert [(i, j) for i, j, _ in found] == [(0, 2)]
    assert found[0][2] == pytest.approx(10 * 10 * 2)
