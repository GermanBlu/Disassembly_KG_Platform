"""Interference check: which part blocks which along each test direction.

Follows the occlusion method of Prasad et al. (2022, CSPPA). Phase 1 runs it with
pipeline.settings.STANDARD_SETTINGS; the module defaults below differ from the
standard settings and apply to direct callers only.

Stage 1 (this file): AABB bounding-box prefilter.
    stage1[i][j] = 1  iff:
      1. 2D projections (u, v axes perpendicular to extraction direction) overlap, AND
      2. part_j is not entirely behind part_i (j.depth_max > i.depth_min)
  This keeps pairs whose depth ranges overlap without either part lying fully
  behind the other (a shaft running through a holder), so Stage 2 decides them.

Stage 2 (this file): GPU visual occlusion check with a pixel tolerance.
  The moving part is rendered alone and together with the obstacle; the share
  of its pixels that the obstacle covers is the occlusion ratio. A contacting
  pair (liaison == 1) blocks only if the ratio exceeds a tolerance: for exact
  CAD geometry, rasterization at coincident surfaces (shaft in bore, screw in
  threaded hole) covers a few pixels even along the free sliding axis.
    - STANDARD_SETTINGS (every Phase 1 run): tolerance 1 % (pixel_tol = 0.01),
      pixels within 1 px of the silhouette edge not counted (edge_px = 1),
      pixels counted inside the overlap of the two projected bounding boxes
      (count_region = "overlap", Prasad et al. 2022, Section 2.2).
    - Module defaults (direct callers without settings): tolerance 10 %
      (INTERFERENCE_PIXEL_TOLERANCE), no edge tolerance, whole image.
  A view in which the moving part renders no pixel cannot be measured and
  counts as blocked.
  The tolerance applies to CONTACTING pairs only: coincident surfaces exist
  only there. A non-contacting obstacle is real however small its share of the
  moving part's silhouette (a small part in front of a large one occludes only
  a few percent of it). Non-contacting pairs therefore use
  NONCONTACT_PIXEL_TOLERANCE (0: any lost pixel counts).

Symmetrization (non-contacting pairs): for rigid translation, "j blocks i moving
  in +d" and "i blocks j moving in -d" are the same statement. The visual check
  only sees the first form when j is visible from outside i: a part enclosed by
  the moving part (impeller inside the volute casing) is hidden behind the moving
  part's own walls and never reduces its green area, so the casing could be
  pulled sideways off the impeller although the impeller cannot leave the casing
  sideways. check_interference() closes this by setting M[d][i][j] |= M[-d][j][i]
  for non-contacting pairs. Contacting pairs are left as measured: their ratios
  carry the coincident-surface noise above, and mirroring a noise hit would
  lock both parts against each other.

Reverse check (Prasad et al. 2022, Section 2.1, Algorithm 2, "test case 2"): the
  published method declares a pair free along d only if BOTH the green count
  (j in front of i, test case 1) AND the red count in the opposite direction
  (i in front of j, test case 2) are unchanged; Fig. 7 of the paper is exactly the
  enclosed-part case above. Test case 2 for (i, j, d) is the
  test-case-1 measurement of (j, i, -d): the camera, colours and the Stage 1
  condition (j.max_d > i.min_d, lateral overlap) map onto each other under
  d -> -d, i <-> j. Algorithm 2 therefore equals M[d][i][j] |= M[-d][j][i] for
  every pair. Setting interference.reverse_check selects the scope:
    "noncontact" (module default) — the symmetrization above, contacting pairs
                                    as measured
    "all" (STANDARD_SETTINGS)     — Algorithm 2 for every pair (Prasad)
    "off"                         — test case 1 only

Further options of the published method (set in STANDARD_SETTINGS, off in the
module defaults; see pipeline.settings, group "interference"):
  directions="contact"   — test directions from the mating surfaces (Prasad,
                           Section 3): plane normals and axes of revolution of
                           the common surfaces of contacting parts, computed with
                           the Open CASCADE General Fuse (common_surfaces,
                           build_contact_directions).
  count_region="overlap" — count pixels only inside the overlap of the two
                           projected bounding boxes (Prasad, Section 2.2).
  edge_px=k              — ignore green pixels within k px of the silhouette edge
                           (flush line-on-line fits, see EDGE_TOLERANCE_PX).
Motion releases (apply_motion_releases) clear blocking entries for motions the
straight-line test cannot represent (a part that leaves in two steps).

Liaison bypass: if liaison_matrix is provided, all physically contacting
  pairs are forced into Stage 2 regardless of Stage 1. This is a safety net ensuring
  penetrating geometries (screw-through-clearance-hole, shaft-through-holder) always
  reach Stage 2.  NOTE: the bypass sets stage1_matrix[i][j]=1 only — it does NOT
  set the final interference result. Stage 2 still decides the actual value.
"""
import logging

import numpy as np

logger = logging.getLogger(__name__)

# Module default of the pixel tolerance for contacting pairs: the minimum
# green-pixel reduction fraction that counts as interference. Pixels lost below
# this fraction are treated as rasterization noise from zero-clearance or
# coincident surfaces (shaft in bore, screw in hole). Phase 1 runs with
# STANDARD_SETTINGS, which set 1 % (pixel_tol = 0.01) together with a 1 px
# silhouette edge; this 10 % value applies only to direct callers that pass no
# tolerance.
INTERFERENCE_PIXEL_TOLERANCE = 0.10  # 10 %

# Threshold for pairs WITHOUT contact. No coincident surfaces, so no
# rasterization noise: any green-pixel reduction is an obstacle in the
# extraction path.
NONCONTACT_PIXEL_TOLERANCE = 0.0

# Scope of the reverse check (Prasad test case 2), see the module docstring.
REVERSE_CHECK_SCOPES = ("noncontact", "all", "off")
REVERSE_CHECK_DEFAULT = "noncontact"

# Silhouette edge tolerance in pixels: green pixels within this distance of the
# moving part's silhouette edge are not counted. Flush, line-on-line fits (a tube
# end flush with the plate face around its bore) put the shared outline at equal
# depth, and its pixels go to the obstacle; for a part that is small in the frame
# that one-pixel ring is a large share of its pixels. 0 counts every pixel
# (module default); STANDARD_SETTINGS use 1.
EDGE_TOLERANCE_PX = 0

# Pixel counting region (Prasad et al. 2022, Section 2.2): "image" counts the
# moving part's green pixels in the whole view; "overlap" only inside the
# intersection of the two parts' projected bounding boxes, the only place where
# the obstacle can cover anything. For an exact equality test both decide the
# same; with a tolerance the ratio is taken relative to that region.
COUNT_REGIONS = ("image", "overlap")
COUNT_REGION_DEFAULT = "image"

# Common surfaces smaller than this (model units², mm²) are dropped: the fuzzy
# General Fuse leaves slivers of near-zero area where two contact faces meet at a
# chamfer or edge.
COMMON_SURFACE_MIN_AREA = 1.0

# Test-direction sets, see build_directions() / build_contact_directions().
DIRECTION_MODES = ("cardinal", "contact")
DIRECTION_MODE_DEFAULT = "cardinal"


def _stage1_bbox_overlap(parts):
    """Compute the Stage 1 interference matrix from AABB overlap.

    For each ordered pair (i, j): part_j potentially blocks disassembly of part_i
    if their 2D lateral projections overlap AND part_j has material at or ahead of
    part_i's leading face (j.depth_max > i.depth_min).

    Parts must already have been transformed via project_to_plane(), i.e., they
    carry .p_min, .p_max (2D lateral extents) and .depth_intervall (depth range
    along the extraction direction).

    Returns:
        np.ndarray of shape (N, N) with 0/1 entries.
    """
    N = len(parts)
    matrix = np.zeros((N, N), dtype=int)
    for i in range(N):
        pi = parts[i]
        for j in range(N):
            if i == j:
                continue
            pj = parts[j]
            # 2D lateral overlap (u and v axes)
            u_overlap = (pi.p_min[0] <= pj.p_max[0]) and (pi.p_max[0] >= pj.p_min[0])
            if not u_overlap:
                continue
            v_overlap = (pi.p_min[1] <= pj.p_max[1]) and (pi.p_max[1] >= pj.p_min[1])
            if not v_overlap:
                continue
            # Part j must have material at or ahead of part i's leading face.
            # (If j is entirely behind i, it cannot obstruct i's extraction.)
            if pj.depth_intervall[1] > pi.depth_intervall[0]:
                matrix[i][j] = 1
    return matrix


def _erode(mask, k):
    """Binary erosion by k pixels (4-neighbourhood), pure numpy."""
    out = mask.copy()
    for _ in range(k):
        m = out.copy()
        m[1:, :] &= out[:-1, :]
        m[:-1, :] &= out[1:, :]
        m[:, 1:] &= out[:, :-1]
        m[:, :-1] &= out[:, 1:]
        out = m
    return out


def _mask_bbox(mask):
    """(r0, r1, c0, c1) half-open pixel bounding box of a boolean mask, or None."""
    rows, cols = np.any(mask, axis=1), np.any(mask, axis=0)
    if not rows.any():
        return None
    r = np.flatnonzero(rows)
    c = np.flatnonzero(cols)
    return r[0], r[-1] + 1, c[0], c[-1] + 1


def _occlusion_ratio(green_before, green_after, edge_px=EDGE_TOLERANCE_PX,
                     obstacle_alone=None):
    """Fraction of the moving part's green pixels lost when the obstacle is added.

    With edge_px > 0 only pixels more than edge_px inside the silhouette count.
    A part too thin to keep any interior pixel falls back to the full count, so
    thin parts seen edge-on are never declared free just because they vanished.
    With obstacle_alone (mask of the obstacle rendered without the moving part)
    only pixels inside the intersection of both silhouettes' bounding boxes count
    (Prasad Section 2.2); no intersection means nothing can be covered (0.0).
    Returns -1.0 if the part is not visible at all.
    """
    before = np.asarray(green_before, dtype=bool)
    after = np.asarray(green_after, dtype=bool)
    if not before.any():
        return -1.0
    core = _erode(before, edge_px) if edge_px else before
    if not core.any():
        core = before
    if obstacle_alone is not None:
        bi, bj = _mask_bbox(before), _mask_bbox(np.asarray(obstacle_alone, dtype=bool))
        if bj is None:
            return 0.0
        r0, r1 = max(bi[0], bj[0]), min(bi[1], bj[1])
        c0, c1 = max(bi[2], bj[2]), min(bi[3], bj[3])
        if r0 >= r1 or c0 >= c1:
            return 0.0
        region = np.zeros_like(core)
        region[r0:r1, c0:c1] = True
        core = core & region
        if not core.any():
            return 0.0
    n = int(core.sum())
    if n == 0:
        return -1.0
    return int((core & ~after).sum()) / n


def _visual_check_with_tolerance(shape_i, shape_j, direction, offscreen_renderer,
                                 edge_px=EDGE_TOLERANCE_PX,
                                 count_region=COUNT_REGION_DEFAULT):
    """Visual interference check with zero-clearance tolerance.

    Occlusion test after Prasad et al. (2022) with a relative pixel-count
    threshold instead of a binary comparison.

    Returns 1 (interference) only when part_j reduces the visible green area of
    part_i by more than INTERFERENCE_PIXEL_TOLERANCE. Smaller reductions are
    treated as rasterization noise from exact-fit / zero-clearance geometry.

    Args:
        shape_i:             TopoDS_Shape — the part being extracted (rendered green).
        shape_j:             TopoDS_Shape — the potential obstacle (rendered red).
        direction:           gp_Dir — extraction direction.
        offscreen_renderer:  Viewer3d instance (reused across calls).
        edge_px:             Silhouette edge tolerance in pixels (see
                             EDGE_TOLERANCE_PX and _occlusion_ratio).
        count_region:        "image" or "overlap" (see COUNT_REGIONS).

    Returns:
        float — green-pixel reduction ratio in [0, 1] (the caller compares it to
        the pixel tolerance), or -1.0 if the part is not visible from this
        direction (interference cannot be measured).
    """
    from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCC.Core.AIS import AIS_Shape
    from OCC.Core.Graphic3d import Graphic3d_BufferType
    from OCC.Core.gp import gp_Dir

    ais_i = AIS_Shape(shape_i)
    ais_j = AIS_Shape(shape_j)
    ais_i.SetColor(Quantity_Color(0.0, 1.0, 0.0, Quantity_TOC_RGB))  # green = moving part
    ais_j.SetColor(Quantity_Color(1.0, 0.0, 0.0, Quantity_TOC_RGB))  # red  = obstacle
    ais_i.Attributes().SetShadingModel(0)
    ais_j.Attributes().SetShadingModel(0)

    offscreen_renderer.Context.Display(ais_i, True)
    offscreen_renderer.Context.Display(ais_j, True)

    # SetProj(v) puts the eye on the +v side, looking along -v. The eye must sit
    # AHEAD of the moving part (on the +direction side): only then does an
    # obstacle in the extraction path lie between eye and part and occlude it.
    # This is the side _stage1_bbox_overlap() selects (j.depth_max > i.depth_min).
    # Seen from the other side, a one-sided obstacle (a cover in front of an
    # impeller, an end plate in front of a shaft) hides behind the moving part
    # and never blocks it.
    proj_dir = gp_Dir(direction.X(), direction.Y(), direction.Z())
    offscreen_renderer.View.SetProj(proj_dir.X(), proj_dir.Y(), proj_dir.Z())
    offscreen_renderer.View.FitAll()
    offscreen_renderer.View.SetZoom(1.0)

    # --- Render shape_i alone, count green pixels ---
    offscreen_renderer.Context.Erase(ais_j, True)
    offscreen_renderer.Context.Remove(ais_j, True)
    offscreen_renderer.View.Redraw()

    width, height = offscreen_renderer.GetSize()
    GREEN_THRESHOLD = 200

    img_before = np.frombuffer(
        offscreen_renderer.GetImageData(width, height, Graphic3d_BufferType.Graphic3d_BT_RGB),
        dtype=np.uint8,
    ).reshape((height, width, 3))
    green_before = img_before[:, :, 1] > GREEN_THRESHOLD

    # --- Add shape_j, count green pixels again ---
    offscreen_renderer.Context.Display(ais_j, True)
    offscreen_renderer.Context.UpdateCurrentViewer()
    offscreen_renderer.View.Redraw()

    img_after = np.frombuffer(
        offscreen_renderer.GetImageData(width, height, Graphic3d_BufferType.Graphic3d_BT_RGB),
        dtype=np.uint8,
    ).reshape((height, width, 3))
    green_after = img_after[:, :, 1] > GREEN_THRESHOLD

    # --- Prasad 2.2: obstacle alone, for its projected bounding box ---
    obstacle_alone = None
    if count_region == "overlap":
        offscreen_renderer.Context.Erase(ais_i, True)
        offscreen_renderer.View.Redraw()
        img_j = np.frombuffer(
            offscreen_renderer.GetImageData(width, height, Graphic3d_BufferType.Graphic3d_BT_RGB),
            dtype=np.uint8,
        ).reshape((height, width, 3))
        obstacle_alone = ((img_j[:, :, 0] > GREEN_THRESHOLD) & (img_j[:, :, 1] < 100)
                          & (img_j[:, :, 2] < 100))

    # --- Cleanup ---
    offscreen_renderer.Context.Erase(ais_i, True)
    offscreen_renderer.Context.Remove(ais_i, True)
    offscreen_renderer.Context.Erase(ais_j, True)
    offscreen_renderer.Context.Remove(ais_j, True)
    offscreen_renderer.View.Redraw()

    # --- Reduction ratio (binary decision is made by the caller against the
    #     pixel tolerance, so the raw ratio can be re-thresholded later).
    #     -1.0: part not visible in this direction, interference not measurable.
    return _occlusion_ratio(green_before, green_after, edge_px, obstacle_alone)


def _stage2_with_tolerance(parts, stage1_matrix, direction,
                           pixel_tol=INTERFERENCE_PIXEL_TOLERANCE,
                           liaison_matrix=None,
                           pixel_tol_noncontact=NONCONTACT_PIXEL_TOLERANCE,
                           edge_px=EDGE_TOLERANCE_PX,
                           count_region=COUNT_REGION_DEFAULT):
    """Stage 2 interference check using the tolerance-aware visual check.

    Creates one offscreen renderer per call and reuses it across all pairs
    flagged by stage1_matrix.

    Args:
        parts:         List of Part objects with .Shape attribute.
        stage1_matrix: N×N array — only pairs where entry==1 are evaluated.
        direction:     gp_Dir — extraction direction.
        pixel_tol:     Green-pixel reduction fraction above which a pair counts
                       as interference (default INTERFERENCE_PIXEL_TOLERANCE).
        liaison_matrix: Optional N×N contact matrix. Pairs without contact are
                       decided against pixel_tol_noncontact instead; without a
                       liaison matrix every pair uses pixel_tol.
        pixel_tol_noncontact: Threshold for non-contacting pairs (default
                       NONCONTACT_PIXEL_TOLERANCE).
        edge_px:       Silhouette edge tolerance in pixels (EDGE_TOLERANCE_PX).
        count_region:  Pixel counting region (COUNT_REGIONS).

    Returns:
        (binary_matrix, ratio_matrix): both N×N np.ndarrays. binary_matrix is a
        copy of stage1_matrix with the Stage 2 decision substituted for flagged
        pairs; ratio_matrix carries the raw green-pixel reduction ratio per
        evaluated pair (-1.0 where not evaluated / not measurable), so the
        decision can be re-thresholded later without re-rendering. A pair that
        is not measurable (the moving part renders no pixel) is blocked.
    """
    from OCC.Display.OCCViewer import Viewer3d
    from copy import deepcopy

    N = len(parts)
    stage2_matrix = deepcopy(stage1_matrix)
    ratio_matrix = np.full((N, N), -1.0)

    # ── macOS compatibility ──────────────────────────────────────────────
    # OCC's Viewer3d requires a Cocoa NSApplication before creating any
    # OpenGL context.  The caller (step_pipeline.py → _init_cocoa()) handles
    # this via pyobjc's AppKit.NSApplication.sharedApplication().
    #
    # CRITICAL: Do NOT initialize tkinter here — on macOS 15+ it conflicts
    # with the already-running NSApplication and causes an immediate SIGSEGV.
    #
    # When invoked from Flask, the entire Phase 1 runs inside a subprocess
    # (models/step_worker.py) so that OCC's Cocoa/OpenGL state is fully
    # isolated from the web server process.  See app.py →
    # _run_step_phase1_subprocess() for the subprocess protocol.
    # ───────────────────────────────────────────────────────────────────────

    offscreen_renderer = Viewer3d()
    offscreen_renderer.Create(display_glinfo=False)
    offscreen_renderer.SetModeShaded()

    unmeasured = 0
    for i in range(N):
        for j in range(N):
            if stage1_matrix[i][j] == 1:
                ratio = _visual_check_with_tolerance(
                    shape_i=parts[i].Shape,
                    shape_j=parts[j].Shape,
                    direction=direction,
                    offscreen_renderer=offscreen_renderer,
                    edge_px=edge_px,
                    count_region=count_region,
                )
                ratio_matrix[i][j] = ratio
                in_contact = liaison_matrix is None or liaison_matrix[i][j] == 1
                tol = pixel_tol if in_contact else pixel_tol_noncontact
                # A part that renders no pixel cannot be measured (-1.0): it is
                # counted as blocked, never as free.
                stage2_matrix[i][j] = 1 if ratio > tol or ratio < 0 else 0
                unmeasured += ratio < 0
    if unmeasured:
        logger.warning("interference: %d pair(s) not measurable along %s (part not "
                       "visible), counted as blocked", unmeasured,
                       (round(direction.X(), 3), round(direction.Y(), 3), round(direction.Z(), 3)))
    return stage2_matrix, ratio_matrix


def _check_single_direction(parts, direction, liaison_matrix,
                            pixel_tol=INTERFERENCE_PIXEL_TOLERANCE,
                            pixel_tol_noncontact=NONCONTACT_PIXEL_TOLERANCE,
                            edge_px=EDGE_TOLERANCE_PX,
                            count_region=COUNT_REGION_DEFAULT):
    """Check interference for a single extraction direction.

    Encapsulates the full Stage 1 + Stage 2 pipeline for one direction.
    Designed to be called independently (potentially in parallel).

    Args:
        parts:           List of Part objects (with bbox corners pre-computed).
        direction:       gp_Dir — extraction direction.
        liaison_matrix:  Optional N×N numpy array for liaison bypass.
        pixel_tol:       Green-pixel reduction fraction for the Stage 2 decision
                         (contacting pairs).
        pixel_tol_noncontact: Stage 2 threshold for non-contacting pairs.
        edge_px:         Silhouette edge tolerance in pixels.
        count_region:    Pixel counting region (COUNT_REGIONS).

    Returns:
        (binary_matrix, ratio_matrix): N×N numpy arrays for this direction.
    """
    from pipeline.bbox_projection import (
        calculate_transformation_matrix,
        project_to_plane,
    )
    from copy import deepcopy

    N = len(parts)

    # Deep-copy parts so projection mutations don't affect other directions
    local_parts = deepcopy(parts)

    transform_matrix = calculate_transformation_matrix(direction=direction)
    local_parts = project_to_plane(parts=local_parts,
                                    transformation_matrix=transform_matrix)

    # Stage 1: AABB overlap
    stage1 = _stage1_bbox_overlap(local_parts)

    # Liaison bypass
    if liaison_matrix is not None:
        for i in range(N):
            for j in range(N):
                if i != j and liaison_matrix[i][j] == 1:
                    stage1[i][j] = 1

    # Stage 2: GPU visual occlusion with tolerance
    stage2, ratios = _stage2_with_tolerance(
        parts=local_parts, stage1_matrix=stage1, direction=direction, pixel_tol=pixel_tol,
        liaison_matrix=liaison_matrix, pixel_tol_noncontact=pixel_tol_noncontact,
        edge_px=edge_px, count_region=count_region,
    )
    return stage2, ratios


def _reverse_check(matrices, direction_vectors, liaison_matrix=None,
                   scope=REVERSE_CHECK_DEFAULT):
    """Combine test case 1 with the reverse test case 2 (Prasad Algorithm 2).

    M[d][i][j] |= M[-d][j][i] for the pairs selected by scope, wherever the
    direction list contains -d. Pure numpy (no OCC), so it is unit-testable.

    Args:
        matrices:          list of N×N binary arrays, one per direction.
        direction_vectors: list of (x, y, z) tuples, aligned with matrices.
        liaison_matrix:    N×N contact matrix; required for scope "noncontact".
        scope:             "noncontact", "all" or "off" (see module docstring).

    Returns:
        New list of N×N int arrays; the input is not modified.
    """
    if scope not in REVERSE_CHECK_SCOPES:
        raise ValueError(f"reverse_check scope must be one of {REVERSE_CHECK_SCOPES}, "
                         f"got {scope!r}")
    n = len(matrices[0]) if matrices else 0
    if scope == "off":
        return [np.array(m, dtype=int) for m in matrices]
    if scope == "all":
        mask = np.ones((n, n), dtype=bool)
    else:
        mask = (np.asarray(liaison_matrix) == 0)
    np.fill_diagonal(mask, False)
    vecs = [tuple(round(c, 9) for c in v) for v in direction_vectors]
    out = []
    for d, m in enumerate(matrices):
        m = np.array(m, dtype=int)
        opp = tuple(-c + 0.0 for c in vecs[d])
        if opp in vecs:
            mirrored = np.array(matrices[vecs.index(opp)], dtype=int).T
            m = np.where(mask & (mirrored == 1), 1, m)
        out.append(m)
    return out


def _symmetrize_noncontact(matrices, direction_vectors, liaison_matrix):
    """Mirror blocking across opposite directions for non-contacting pairs.

    Shorthand for _reverse_check(..., scope="noncontact").
    """
    return _reverse_check(matrices, direction_vectors, liaison_matrix, "noncontact")


def check_interference(directions, parts, liaison_matrix=None, parallel=False,
                       return_ratios=False, pixel_tol=None, pixel_tol_noncontact=None,
                       reverse_check=None, edge_px=None, count_region=None):
    """Run two-stage interference check for all given extraction directions.

    Args:
        directions:      List of gp_Dir test directions (build_contact_directions
                         or build_directions).
        parts:           List of Part objects with OCC geometry (.BoundingBox set).
        liaison_matrix:  Optional N×N array-like. If provided, all contacting pairs
                         (entry == 1) are forced into Stage 2 regardless of Stage 1
                         outcome. This is the liaison bypass — it does NOT set
                         interference=1; Stage 2 still evaluates each pair visually.
        parallel:        If True, process directions concurrently using threads.
                         Defaults to False: OCC's Viewer3d creates Cocoa NSWindow
                         objects, which macOS requires on the main thread. Worker
                         threads trigger SIGABRT. Only set True on Linux/headless.
        return_ratios:   If True, also return the per-pair green-pixel reduction
                         ratios so the decision can be re-thresholded later.
        pixel_tol:       Override the Stage 2 pixel tolerance for contacting
                         pairs (default INTERFERENCE_PIXEL_TOLERANCE).
        pixel_tol_noncontact: Override the threshold for non-contacting pairs
                         (default NONCONTACT_PIXEL_TOLERANCE). Only used when a
                         liaison matrix is given.
        reverse_check:   Scope of the reverse check (Prasad test case 2), one of
                         REVERSE_CHECK_SCOPES (default REVERSE_CHECK_DEFAULT).
        edge_px:         Silhouette edge tolerance in pixels (default
                         EDGE_TOLERANCE_PX).
        count_region:    "image" or "overlap" (default COUNT_REGION_DEFAULT,
                         see COUNT_REGIONS).

    The binary matrices are combined with the reverse check (see _reverse_check
    and the module docstring): scope "noncontact" mirrors non-contacting pairs
    and needs a liaison matrix, "all" mirrors every pair, "off" leaves test
    case 1 as measured. The ratio matrices always stay as measured.

    Returns:
        If return_ratios is False: list of N×N numpy arrays (binary), one per
        direction — entry [i][j] == 1 means part_j visually occludes part_i.
        If True: (matrices, ratio_matrices), each a list of N×N arrays; ratio
        entries carry the raw reduction ratio (-1.0 where not evaluated).
    """
    from pipeline.bbox_projection import calc_other_Bbox_points

    scope = REVERSE_CHECK_DEFAULT if reverse_check is None else reverse_check
    if scope not in REVERSE_CHECK_SCOPES:
        raise ValueError(f"reverse_check scope must be one of {REVERSE_CHECK_SCOPES}, "
                         f"got {scope!r}")
    eff_edge = EDGE_TOLERANCE_PX if edge_px is None else int(edge_px)
    eff_region = COUNT_REGION_DEFAULT if count_region is None else count_region
    if eff_region not in COUNT_REGIONS:
        raise ValueError(f"count_region must be one of {COUNT_REGIONS}, got {eff_region!r}")
    lm = np.array(liaison_matrix) if liaison_matrix is not None else None
    eff_tol = INTERFERENCE_PIXEL_TOLERANCE if pixel_tol is None else pixel_tol
    eff_tol_nc = (NONCONTACT_PIXEL_TOLERANCE if pixel_tol_noncontact is None
                  else pixel_tol_noncontact)

    # Pre-compute bounding box corner points (mutates parts in-place, idempotent).
    parts = calc_other_Bbox_points(parts=parts)

    if parallel and len(directions) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        logger.info("Running %d directions in parallel...", len(directions))
        t0 = time.time()

        # NOTE: parallel=True crashes on macOS (Cocoa NSWindow main-thread
        # requirement). Only safe on Linux/headless where Viewer3d uses X11/EGL.
        results = [None] * len(directions)
        with ThreadPoolExecutor(max_workers=min(6, len(directions))) as executor:
            future_to_idx = {
                executor.submit(_check_single_direction, parts, d, lm, eff_tol,
                                eff_tol_nc, eff_edge, eff_region): i
                for i, d in enumerate(directions)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()

        elapsed = time.time() - t0
        logger.info("Parallel check done in %.2fs", elapsed)
        matrices = [r[0] for r in results]
        ratios = [r[1] for r in results]
    else:
        # Sequential fallback
        matrices, ratios = [], []
        for direction in directions:
            matrix, ratio = _check_single_direction(parts, direction, lm, eff_tol,
                                                    eff_tol_nc, eff_edge, eff_region)
            matrices.append(matrix)
            ratios.append(ratio)

    if scope == "all" or (scope == "noncontact" and lm is not None):
        matrices = _reverse_check(
            matrices, [(d.X(), d.Y(), d.Z()) for d in directions], lm, scope)

    return (matrices, ratios) if return_ratios else matrices


def build_directions():
    """Return the 6 cardinal extraction directions as gp_Dir objects.

    This is the direction set of the mode "cardinal" (module default). Phase 1
    with STANDARD_SETTINGS uses the mode "contact" (build_contact_directions),
    which derives the directions from the common surfaces of contacting parts
    (Prasad et al. 2022, Section 3).
    """
    from OCC.Core.gp import gp_Dir
    return [
        gp_Dir(1, 0, 0),   # +X
        gp_Dir(-1, 0, 0),  # -X
        gp_Dir(0, 1, 0),   # +Y
        gp_Dir(0, -1, 0),  # -Y
        gp_Dir(0, 0, 1),   # +Z
        gp_Dir(0, 0, -1),  # -Z
    ]


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def _add_direction(vecs, v, atol=1e-3):
    """Append ±v to vecs unless an (almost) identical vector is already there."""
    v = _unit(v)
    for s in (1.0, -1.0):
        w = tuple(float(round(c, 6)) + 0.0 for c in s * v)
        if not any(np.allclose(w, u, atol=atol) for u in vecs):
            vecs.append(w)


def _surface_axis(face):
    """Normal of a planar face or axis of a surface of revolution, else None."""
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
                                  GeomAbs_Torus, GeomAbs_SurfaceOfRevolution)
    s = BRepAdaptor_Surface(face)
    t = s.GetType()
    if t == GeomAbs_Plane:
        a = s.Plane().Axis().Direction()
    elif t == GeomAbs_Cylinder:
        a = s.Cylinder().Axis().Direction()
    elif t == GeomAbs_Cone:
        a = s.Cone().Axis().Direction()
    elif t == GeomAbs_Torus:
        a = s.Torus().Axis().Direction()
    elif t == GeomAbs_SurfaceOfRevolution:
        a = s.AxeOfRevolution().Direction()
    else:
        return None
    return (a.X(), a.Y(), a.Z())


def common_surfaces(shape_i, shape_j, fuzzy, min_area=COMMON_SURFACE_MIN_AREA):
    """Common surfaces EC = S_i ∩ S_j of two touching parts, as a list of faces.

    Bahubalendruni et al. (2019) define the envelope of contact as the mating
    surfaces common to both parts; only surface contact counts, point and line
    contacts do not. The Open CASCADE General Fuse (BRepAlgoAPI_BuilderAlgo)
    splits both parts against each other, and coinciding face regions come out
    as one face shared by both: exactly S_i ∩ S_j. Faces that touch only along an
    edge share no face. The fuzzy value lets faces within that distance count as
    coinciding (modelled clearances). If the Boolean fails, it is retried with
    half the fuzzy value down to exact coincidence.

    Returns:
        list of (face, area) with area >= min_area.
    """
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_BuilderAlgo
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer, topexp
    from OCC.Core.TopoDS import topods
    from OCC.Core.TopTools import (TopTools_IndexedMapOfShape, TopTools_ListIteratorOfListOfShape,
                                   TopTools_ListOfShape)

    def faces(shape):
        ex = TopExp_Explorer(shape, TopAbs_FACE)
        while ex.More():
            yield topods.Face(ex.Current())
            ex.Next()

    fz = max(float(fuzzy or 0.0), 0.0)
    while True:
        args = TopTools_ListOfShape()
        args.Append(shape_i)
        args.Append(shape_j)
        builder = BRepAlgoAPI_BuilderAlgo()
        builder.SetArguments(args)
        builder.SetNonDestructive(True)
        if fz > 0:
            builder.SetFuzzyValue(fz)
        builder.Build()
        if builder.IsDone():
            break
        if fz < 1e-3:
            return []
        fz = fz / 2 if fz / 2 >= 1e-3 else 0.0

    result_faces = TopTools_IndexedMapOfShape()
    topexp.MapShapes(builder.Shape(), TopAbs_FACE, result_faces)

    def image_indices(shape):
        out = set()
        for f in faces(shape):
            it = TopTools_ListIteratorOfListOfShape(builder.Modified(f))
            images = []
            while it.More():
                images.append(it.Value())
                it.Next()
            if not images and not builder.IsDeleted(f):
                images = [f]
            out.update(k for k in (result_faces.FindIndex(g) for g in images) if k)
        return out

    shared = []
    for k in sorted(image_indices(shape_i) & image_indices(shape_j)):
        face = topods.Face(result_faces.FindKey(k))
        props = GProp_GProps()
        brepgprop.SurfaceProperties(face, props)
        if props.Mass() >= min_area:
            shared.append((face, props.Mass()))
    return shared


def build_contact_directions(parts, liaison_matrix, contact_tol, include_cardinal=False):
    """Test directions from the mating surfaces (Prasad et al. 2022, Section 3).

    For every contacting pair, each common surface (common_surfaces, fuzzy value
    = the contact threshold) contributes, after Bahubalendruni et al. (2019):
      plane                         → its normal (both senses)
      cylinder / cone / torus /
      surface of revolution         → its axis of revolution (both senses)
    Spheres and free-form faces contribute nothing. Prasad derives the directions
    from the mating surfaces only; include_cardinal adds the six cardinal
    directions in front of them.

    Not implemented from Section 3: the extra normal through the centre of an
    incomplete surface of revolution (half shells) and the centroid normal of a
    curved ruled surface.

    Returns:
        (directions, vectors): list of gp_Dir and the matching (x, y, z) tuples.
    """
    from OCC.Core.gp import gp_Dir

    vecs = [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
            (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)] if include_cardinal else []
    lm = np.asarray(liaison_matrix)
    n = len(parts)
    for i in range(n):
        for j in range(i + 1, n):
            if lm[i][j] != 1:
                continue
            for face, _ in common_surfaces(parts[i].Shape, parts[j].Shape, contact_tol):
                axis = _surface_axis(face)
                if axis is not None:
                    _add_direction(vecs, axis)
    return [gp_Dir(*v) for v in vecs], vecs


def apply_motion_releases(matrices, direction_vectors, releases, part_ids,
                          atol=1e-3):
    """Release motions the straight-line test cannot represent (working title).

    The interference test asks whether a part can be translated along d to
    infinity. A part that leaves in two steps (slide a few millimetres off a
    shaft end, then sideways) is blocked by whatever lies further along d. A
    release names such a motion explicitly:

        {"part": "B", "direction": [0, -1, 0], "ignore": ["D", "E", "G"]}

    sets M[d][part][o] = 0 and, for the same relative motion, M[-d][o][part] = 0
    for every o in "ignore". Applied after the reverse check.

    Args:
        matrices:          list of N×N binary arrays, aligned with direction_vectors.
        direction_vectors: list of (x, y, z) tuples.
        releases:          list of release dicts as above.
        part_ids:          list of the part IDs ("A", "B", ...) in matrix order.

    Returns:
        New list of N×N int arrays; the input is not modified.

    Raises:
        ValueError: unknown part ID, or a direction that is not in the set.
    """
    out = [np.array(m, dtype=int) for m in matrices]
    vecs = [_unit(v) for v in direction_vectors]
    idx = {p: k for k, p in enumerate(part_ids)}

    def find(v):
        u = _unit(v)
        for k, w in enumerate(vecs):
            if np.allclose(u, w, atol=atol):
                return k
        raise ValueError(f"release direction {tuple(v)} is not among the test directions")

    for rel in releases or []:
        if rel["part"] not in idx or any(o not in idx for o in rel["ignore"]):
            raise ValueError(f"unknown part ID in release {rel!r}")
        d = find(rel["direction"])
        opp = find(-_unit(rel["direction"]))
        p = idx[rel["part"]]
        for o in rel["ignore"]:
            out[d][p][idx[o]] = 0
            out[opp][idx[o]][p] = 0
    return out
