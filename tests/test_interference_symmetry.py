"""Enclosure handling in the interference matrices and in disintegration (OCC-free).

Pins the two mechanisms that keep the pump's impeller from leaving the closed
casing:

  * _symmetrize_noncontact — the visual check cannot see a part enclosed by the
    moving part, so "impeller blocks casing moving +X" is never measured while
    "casing blocks impeller moving -X" is. For non-contacting pairs the two are
    mirrored; contacting pairs stay as measured (raster noise).
  * has_trapped_component — a part that falls loose after its fastener is gone
    (impeller behind its cap nut) may only become its own result if it can
    geometrically leave the rest of its side.
"""
import numpy as np

import pytest

from pipeline.interference import (_erode, _occlusion_ratio, _reverse_check, _symmetrize_noncontact,
                                   apply_motion_releases)
from pipeline.semantic import generate_semantic_tables, has_trapped_component

_DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]


def _empty(n):
    return [np.zeros((n, n), dtype=int) for _ in _DIRS]


# ── _symmetrize_noncontact ───────────────────────────────────────────────────

def test_noncontact_block_is_mirrored_to_opposite_direction():
    """j=0 blocks i=1 moving +X (casing around impeller) → impeller blocks
    casing moving -X."""
    ims = _empty(2)
    ims[0][1][0] = 1                              # +X: 0 blocks 1
    out = _symmetrize_noncontact(ims, _DIRS, [[0, 0], [0, 0]])
    assert out[1][0][1] == 1                      # -X: 1 blocks 0
    assert sum(int(m.sum()) for m in out) == 2    # nothing else invented


def test_contacting_pair_is_not_mirrored():
    ims = _empty(2)
    ims[0][1][0] = 1
    out = _symmetrize_noncontact(ims, _DIRS, [[0, 1], [1, 0]])
    assert out[1][0][1] == 0
    assert sum(int(m.sum()) for m in out) == 1


def test_input_matrices_are_not_mutated():
    ims = _empty(2)
    ims[2][0][1] = 1
    _symmetrize_noncontact(ims, _DIRS, [[0, 0], [0, 0]])
    assert int(ims[3].sum()) == 0


def test_direction_without_opposite_is_left_alone():
    ims = [np.array([[0, 0], [1, 0]])]
    out = _symmetrize_noncontact(ims, [(1, 0, 0)], [[0, 0], [0, 0]])
    assert out[0].tolist() == [[0, 0], [1, 0]]


# ── _reverse_check (Prasad test case 2) ──────────────────────────────────────

def test_reverse_check_all_mirrors_contacting_pairs():
    """Scope "all" (Prasad Algorithm 2): shaft blocked +X by holder → holder
    blocked -X by shaft, contact or not."""
    ims = _empty(2)
    ims[0][1][0] = 1
    out = _reverse_check(ims, _DIRS, [[0, 1], [1, 0]], scope="all")
    assert out[1][0][1] == 1
    assert sum(int(m.sum()) for m in out) == 2


def test_reverse_check_all_needs_no_liaison_matrix():
    ims = _empty(2)
    ims[4][0][1] = 1                              # +Z: 1 blocks 0
    out = _reverse_check(ims, _DIRS, None, scope="all")
    assert out[5][1][0] == 1                      # -Z: 0 blocks 1


def test_reverse_check_off_leaves_matrices_unchanged():
    ims = _empty(2)
    ims[0][1][0] = 1
    out = _reverse_check(ims, _DIRS, [[0, 0], [0, 0]], scope="off")
    assert [m.tolist() for m in out] == [m.tolist() for m in ims]


def test_reverse_check_unknown_scope_raises():
    with pytest.raises(ValueError):
        _reverse_check(_empty(2), _DIRS, [[0, 0], [0, 0]], scope="both")


def test_reverse_check_does_not_mutate_input():
    ims = _empty(2)
    ims[0][1][0] = 1
    for scope in ("all", "noncontact", "off"):
        _reverse_check(ims, _DIRS, [[0, 1], [1, 0]], scope=scope)
    assert int(ims[1].sum()) == 0
    assert sum(int(m.sum()) for m in ims) == 1


# ── _occlusion_ratio (silhouette edge tolerance) ────────────────────────────

def _disc(n, r, cx, cy):
    yy, xx = np.mgrid[:n, :n]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r


def test_edge_ring_loss_is_ignored_with_edge_tolerance():
    """Flush fit: the obstacle takes only the outermost pixel ring."""
    before = _disc(40, 10, 20, 20)
    after = _erode(before, 1)                     # obstacle takes the 1-px outline
    assert _occlusion_ratio(before, after, 0) > 0.10
    assert _occlusion_ratio(before, after, 1) == 0.0


def test_interior_loss_survives_edge_tolerance():
    before = _disc(40, 10, 20, 20)
    after = before.copy()
    after[15:25, 15:25] = False                   # obstacle covers the middle
    assert _occlusion_ratio(before, after, 1) > 0.2


def test_thin_part_falls_back_to_full_count():
    before = np.zeros((10, 10), dtype=bool)
    before[5, 2:8] = True                         # one pixel thick, eroded away
    after = before.copy()
    after[5, 2:5] = False
    assert _occlusion_ratio(before, after, 1) == 0.5


def test_count_region_restricts_to_bbox_overlap():
    """Prasad 2.2: only pixels inside both bounding boxes count."""
    before = np.zeros((20, 40), dtype=bool)
    before[5:15, 2:38] = True                     # long part, 360 px
    obstacle = np.zeros_like(before)
    obstacle[0:20, 30:40] = True                  # obstacle over its right end
    after = before & ~obstacle
    whole = _occlusion_ratio(before, after, 0)
    region = _occlusion_ratio(before, after, 0, obstacle)
    assert round(whole, 3) == round(80 / 360, 3)
    assert region == 1.0                          # everything in the overlap is covered


def test_count_region_without_overlap_is_free():
    before = np.zeros((10, 10), dtype=bool)
    before[0:3, 0:3] = True
    obstacle = np.zeros_like(before)
    obstacle[6:9, 6:9] = True
    assert _occlusion_ratio(before, before, 0, obstacle) == 0.0


def test_invisible_part_is_not_measurable():
    empty = np.zeros((5, 5), dtype=bool)
    assert _occlusion_ratio(empty, empty, 1) == -1.0


# ── apply_motion_releases ────────────────────────────────────────────────────

def test_release_clears_entry_and_its_mirror():
    ims = _empty(3)
    ims[3][1][2] = 1                              # -Y: 2 blocks 1
    ims[2][2][1] = 1                              # +Y: 1 blocks 2 (same motion)
    ims[0][1][0] = 1                              # +X: untouched
    out = apply_motion_releases(ims, _DIRS, [{"part": "B", "direction": [0, -1, 0],
                                              "ignore": ["C"]}], ["A", "B", "C"])
    assert out[3][1][2] == 0 and out[2][2][1] == 0
    assert out[0][1][0] == 1
    assert ims[3][1][2] == 1                      # input not mutated


def test_release_with_unknown_direction_raises():
    with pytest.raises(ValueError):
        apply_motion_releases(_empty(2), _DIRS, [{"part": "A", "direction": [1, 1, 0],
                                                  "ignore": ["B"]}], ["A", "B"])


def test_release_with_unknown_part_raises():
    with pytest.raises(ValueError):
        apply_motion_releases(_empty(2), _DIRS, [{"part": "Z", "direction": [1, 0, 0],
                                                  "ignore": ["B"]}], ["A", "B"])


# ── has_trapped_component ────────────────────────────────────────────────────

def _bitmasks(blocked, n):
    """blocked: {(d, i, j)} → AOG-style [direction][part] → blocker bitmask."""
    bms = [[0] * n for _ in _DIRS]
    for d, i, j in blocked:
        bms[d][i] |= 1 << j
    return bms


def test_part_enclosed_in_all_directions_is_trapped():
    # casing 0 blocks impeller 1 in every direction (and, mirrored, vice versa)
    blocked = {(d, 1, 0) for d in range(6)} | {(d ^ 1, 0, 1) for d in range(6)}
    bms = _bitmasks(blocked, 2)
    assert has_trapped_component([["A"], ["B"]], {"A": 0, "B": 1}, bms)


def test_part_with_one_free_direction_is_not_trapped():
    blocked = {(d, 1, 0) for d in range(6) if d != 2}       # +Y left open
    blocked |= {(d ^ 1, 0, 1) for d in range(6) if d != 2}
    bms = _bitmasks(blocked, 2)
    assert not has_trapped_component([["A"], ["B"]], {"A": 0, "B": 1}, bms)


def test_peeling_order_is_found():
    # B can only leave after C is gone; C is free. B is not trapped.
    blocked = {(d, 1, 0) for d in range(6) if d != 2} | {(2, 1, 2)}
    blocked |= {(d ^ 1, 0, 1) for d in range(6) if d != 2} | {(3, 2, 1)}
    bms = _bitmasks(blocked, 3)
    assert not has_trapped_component([["A"], ["B"], ["C"]],
                                     {"A": 0, "B": 1, "C": 2}, bms)


def test_components_sharing_a_group_representative_form_one_unit():
    # Two loose bolts of one merged group map to the same AOG index — one unit.
    bms = _bitmasks({(d, 0, 0) for d in range(6)}, 1)
    assert not has_trapped_component([["E"], ["J"]], {"E": 0, "J": 0}, bms)


# ── End to end: the cap-nut case ─────────────────────────────────────────────

def test_unscrewing_the_nut_does_not_release_an_enclosed_impeller():
    """Casing A, impeller B, nut C (fastener on shaft D and impeller B), cover E.

    The casing encloses the impeller except towards +Y, where the cover closes
    it. The nut is free to go. Unscrewing the nut leaves the impeller
    semantically loose; it may come out as a separate result only once the
    cover is gone.
    """
    labels = ["Casing (A)", "Impeller (B)", "Cap nut (C)", "Shaft (D)", "Cover (E)"]
    lm = [[0, 0, 0, 1, 1],
          [0, 0, 1, 1, 0],
          [0, 1, 0, 1, 0],
          [1, 1, 1, 0, 0],
          [1, 0, 0, 0, 0]]
    ims = _empty(5)
    for d in range(6):
        blocker = 4 if d == 2 else 0          # cover closes +Y, casing the rest
        ims[d][1][blocker] = 1
        ims[d ^ 1][blocker][1] = 1            # and the mirror
    res = generate_semantic_tables(fastener_indices=[2], part_labels=labels,
                                   liaison_matrix=lm,
                                   interference_matrices=[m.tolist() for m in ims])
    assert res["success"], res.get("error")
    released = [t for t in res["transitions"] if "B" in t["results_in"]]
    assert released, "the impeller must still come out once the cover is off"
    assert all("E" not in t["from_parts"] for t in released)
    assert res["rule_stats"]["trapped_components"] >= 1
