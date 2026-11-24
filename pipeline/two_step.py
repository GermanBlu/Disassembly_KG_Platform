"""Automatic two-step releases: parts that leave in two straight moves.

The interference test (pipeline.interference) asks whether a part can be
translated along a test direction d to infinity. A part that first has to slide a
short way along d to clear its mating parts and can then leave sideways (the end
plate of the Hypothetical Product: 15 mm along the shaft, then up) is reported as
blocked along d by whatever lies further along d. derive_two_step_releases()
finds such motions from the geometry and returns them in the release format of
pipeline.interference.apply_motion_releases().

For every part i and test direction d1, on the interference matrices after the
reverse check:
  1. Candidate: i is blocked along d1, and only by parts it does not touch.
  2. Minimum shift d_min: i has to leave the bounding boxes of its contact
     partners along d1.
  3. Free travel d_max: the smallest shift along d1 at which i overlaps one of the
     blockers with positive volume (Open CASCADE B-rep, sampled search;
     free_travel()).
  4. If d_min < d_max, i is moved to the midpoint of the interval (our choice of
     the turning point in the sense of Yu & Wang 2013), and the interference
     test (Prasad test cases 1 and 2, same counting region and edge; the shifted
     part touches nothing, so every pair uses the non-contact threshold) is
     repeated from there for every test direction except ±d1 against all other
     parts. If some d2 is free, the release {"part": i, "direction": d1,
     "ignore": blockers} is returned; applying it clears the d1 entries of i
     against these blockers.

Checked for single parts against the complete assembly; fewer parts can only
block less. The release acts on the matrix entries, so a subassembly that
contains i and moves along d1 is released from the same blockers; the second
move is verified for i alone.
"""
import logging

import numpy as np

from pipeline.interference import (COUNT_REGION_DEFAULT, EDGE_TOLERANCE_PX,
                                   NONCONTACT_PIXEL_TOLERANCE, _unit)

logger = logging.getLogger(__name__)

TWO_STEP_MODES = ("off", "auto")
TWO_STEP_DEFAULT = "off"

# free_travel(): translational collision search on the exact B-rep.
VOL_EPS = 0.01       # mm³ — an overlap below this counts as touching
DIST_EPS = 0.01      # mm — below this the parts count as touching
STEP = 0.1           # mm — volume test spacing while the parts slide along each other
RESOLUTION = 0.05    # mm — head-on probe on arrival and bisection resolution


def _bbox(shape):
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    box = Bnd_Box()
    brepbndlib.Add(shape, box)
    return np.array(box.Get())


def _extent(bb, d):
    """(min, max) of an axis-aligned box (xmin, ymin, zmin, xmax, ymax, zmax) along d."""
    corners = np.array([[x, y, z] for x in (bb[0], bb[3])
                        for y in (bb[1], bb[4]) for z in (bb[2], bb[5])])
    s = corners @ d
    return s.min(), s.max()


def _shift(shape, d, t):
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCC.Core.gp import gp_Trsf, gp_Vec
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(*(np.asarray(d) * t)))
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def _overlap_volume(a, b):
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    common = BRepAlgoAPI_Common(a, b)
    if not common.IsDone():
        raise RuntimeError("boolean common failed")
    props = GProp_GProps()
    brepgprop.VolumeProperties(common.Shape(), props)
    return abs(props.Mass())


def _distance(a, b):
    from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
    ext = BRepExtrema_DistShapeShape(a, b)
    if not ext.IsDone():
        raise RuntimeError("distance computation failed")
    return ext.Value()


def _box_contact_interval(bi, bj, d):
    """Shifts t >= 0 at which box i, moved by t·d, intersects box j (None if never)."""
    lo, hi = 0.0, np.inf
    for k in range(3):
        a0, a1, b0, b1 = bi[k], bi[k + 3], bj[k], bj[k + 3]
        if abs(d[k]) < 1e-12:
            if a1 < b0 or b1 < a0:
                return None
            continue
        t0, t1 = sorted(((b0 - a1) / d[k], (b1 - a0) / d[k]))
        lo, hi = max(lo, t0), min(hi, t1)
    return (lo, hi) if lo <= hi else None


def free_travel(shape_i, shape_j, d):
    """Shift along d at which shape_i first overlaps shape_j with positive volume.

    Conservative advancement: while the parts are a distance δ apart, i cannot
    hit j within the next δ of travel, so the shift jumps by δ (BRepExtrema).
    When i arrives at j (and at the start, if they already touch), the overlap is
    tested RESOLUTION further on, so a head-on collision is found even with thin
    parts. While they slide along each other the overlap volume is tested every
    STEP. The first overlap is refined by bisection to RESOLUTION. Touching
    without volume overlap is no collision. Expects parts that do not overlap at
    rest. A sampled search: a feature that i passes completely within one STEP
    while sliding (combined thickness along d below STEP) can be missed.

    Returns:
        float shift in model units, or None if shape_i never hits shape_j.
    """
    d = _unit(d)
    window = _box_contact_interval(_bbox(shape_i), _bbox(shape_j), d)
    if window is None or window[1] <= 0:
        return None

    def hits(t):
        return _overlap_volume(_shift(shape_i, d, t), shape_j) > VOL_EPS

    def refine(lo, hi):
        while hi - lo > RESOLUTION:
            mid = 0.5 * (lo + hi)
            if hits(mid):
                hi = mid
            else:
                lo = mid
        return hi

    t = prev = max(window[0], 0.0)
    arrived = True
    while t <= window[1]:
        gap = _distance(_shift(shape_i, d, t), shape_j)
        if gap > DIST_EPS:
            prev, t, arrived = t, t + gap, True
            continue
        if t > 0 and hits(t):
            return refine(prev, t)
        if arrived:
            arrived = False
            if hits(t + RESOLUTION):
                return refine(t, t + RESOLUTION)
        prev, t = t, t + STEP
    return None


def _may_block(bi, bj, d):
    """Stage 1 bounding-box prefilter (pipeline.interference._stage1_bbox_overlap) on two boxes."""
    u = np.cross(d, [1.0, 0.0, 0.0] if abs(d[0]) < 0.9 else [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    for axis in (u, np.cross(d, u)):
        a0, a1 = _extent(bi, axis)
        b0, b1 = _extent(bj, axis)
        if a1 < b0 or b1 < a0:
            return False
    return _extent(bj, d)[1] > _extent(bi, d)[0]


def _blocked(shape_i, others, d, view, tol, edge_px, count_region):
    """Test cases 1 and 2 for shape_i moving along d against every other shape."""
    from OCC.Core.gp import gp_Dir
    from pipeline.interference import _visual_check_with_tolerance
    d = _unit(d)
    ahead, back = gp_Dir(*map(float, d)), gp_Dir(*map(float, -d))
    bi = _bbox(shape_i)
    def covered(a, b, look):
        ratio = _visual_check_with_tolerance(a, b, look, view, edge_px, count_region)
        return ratio > tol or ratio < 0          # not measurable counts as blocked

    for shape_j, bj in others:
        if _may_block(bi, bj, d) and covered(shape_i, shape_j, ahead):
            return True
        if _may_block(bj, bi, -d) and covered(shape_j, shape_i, back):
            return True
    return False


def _fmt(v):
    return "(" + ", ".join(f"{c:.3g}" for c in v) + ")"


def derive_two_step_releases(parts, matrices, direction_vectors, liaison_matrix,
                             pixel_tol=None, edge_px=None, count_region=None,
                             log_fn=None):
    """Find parts that leave in two straight moves (see the module docstring).

    Args:
        parts:             list of Part objects with .Shape.
        matrices:          N×N binary interference matrices after the reverse
                           check, aligned with direction_vectors.
        direction_vectors: list of (x, y, z) test directions.
        liaison_matrix:    N×N contact matrix.
        pixel_tol:         pixel threshold of the second-move test (the moved part
                           touches nothing; None → NONCONTACT_PIXEL_TOLERANCE).
        edge_px, count_region: pixel settings of the interference check.
        log_fn:            optional callable(str) for progress lines.

    Returns:
        list of release dicts for apply_motion_releases(): part, direction and
        ignore, plus min_shift, free_travel, shift and second_move for the record.
    """
    from OCC.Display.OCCViewer import Viewer3d
    from pipeline.part_ids import part_id

    log = log_fn or logger.info
    tol = NONCONTACT_PIXEL_TOLERANCE if pixel_tol is None else pixel_tol
    edge = EDGE_TOLERANCE_PX if edge_px is None else int(edge_px)
    region = COUNT_REGION_DEFAULT if count_region is None else count_region
    n = len(parts)
    lm = np.asarray(liaison_matrix)
    shapes = [p.Shape for p in parts]
    boxes = [_bbox(s) for s in shapes]
    vecs = [_unit(v) for v in direction_vectors]
    view = None
    releases = []
    for i in range(n):
        partners = [j for j in range(n) if j != i and lm[i][j] == 1]
        for k, d1 in enumerate(vecs):
            blockers = [j for j in range(n) if j != i and matrices[k][i][j]]
            if not blockers or any(lm[i][j] == 1 for j in blockers):
                continue
            name = f"{part_id(i)} along {_fmt(d1)}, blocked by {[part_id(j) for j in blockers]}"
            lo_i = _extent(boxes[i], d1)[0]
            d_min = max([max(0.0, _extent(boxes[j], d1)[1] - lo_i) for j in partners],
                        default=0.0)
            travel = [free_travel(shapes[i], shapes[j], d1) for j in blockers]
            if any(t is None for t in travel):
                log(f"Two-step {name}: a blocker is never hit on the exact geometry, no release")
                continue
            d_max = min(travel)
            if d_min >= d_max:
                log(f"Two-step {name}: minimum shift {d_min:.1f} >= free travel {d_max:.1f}, "
                    f"no release")
                continue
            shift = 0.5 * (d_min + d_max)
            if view is None:
                view = Viewer3d()
                view.Create(display_glinfo=False)
                view.SetModeShaded()
            moved = _shift(shapes[i], d1, shift)
            others = [(shapes[j], boxes[j]) for j in range(n) if j != i]
            second = [d2 for d2 in vecs if abs(abs(d2 @ d1) - 1.0) > 1e-6
                      and not _blocked(moved, others, d2, view, tol, edge, region)]
            log(f"Two-step {name}: minimum shift {d_min:.1f}, free travel {d_max:.1f}, "
                f"second move from {shift:.1f} free along "
                f"{[_fmt(d2) for d2 in second] or 'none'}")
            if second:
                releases.append({
                    "part": part_id(i),
                    "direction": [round(float(c), 6) for c in d1],
                    "ignore": [part_id(j) for j in blockers],
                    "min_shift": round(float(d_min), 3),
                    "free_travel": round(float(d_max), 3),
                    "shift": round(float(shift), 3),
                    "second_move": [[round(float(c), 6) for c in d2] for d2 in second],
                })
    return releases
