"""Liaison (contact) matrix construction.

compute_contacts(parts) measures the full gap distribution once and derives the
contact threshold from the geometry (no fixed millimetre constant), so it works
across product families (exact-touching mechanical assemblies, ECAD boards whose
components float a few hundredths of a mm above the PCB, …) without per-file
tuning. The threshold can also be supplied explicitly to override the auto value.

The threshold problem in one sentence: a single absolute tolerance is always
right for only one product family (units, scale and modelling convention all
shift it), so we let the geometry pick it — see auto_contact_threshold.
"""
import math

import numpy as np

# Multiplicative jump in the sorted gap distribution that marks the "valley"
# between the touching cluster and the clearly-apart pairs. Both validated
# products show a jump of 8x-infinity here, so the exact value is not delicate.
_VALLEY_JUMP = 3.0

# Gaps below this fraction of the characteristic part size are treated as exact
# contact before the valley search. It has to sit below the smallest designed
# clearance in the model: at 1% a 100 mm assembly gets a 1 mm noise floor, which
# merges a 0.5 mm bolt-hole clearance into the contact cluster and can flatten
# the valley behind it to below _VALLEY_JUMP.
_NOISE_FLOOR_FRACTION = 2e-3


# ── Geometry helpers ──────────────────────────────────────────────────────────

def bbox_gap(part_i, part_j):
    """Analytic distance between two axis-aligned bounding boxes.

    Cheap (no meshing) and a *lower bound* on the true solid-to-solid distance,
    so it is safe as a prefilter: if the bbox gap exceeds a bound, the true gap
    does too.
    """
    ax0, ay0, az0, ax1, ay1, az1 = part_i.BoundingBox.Get()
    bx0, by0, bz0, bx1, by1, bz1 = part_j.BoundingBox.Get()
    dx = max(0.0, ax0 - bx1, bx0 - ax1)
    dy = max(0.0, ay0 - by1, by0 - ay1)
    dz = max(0.0, az0 - bz1, bz0 - az1)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def exact_gap(part_i, part_j):
    """Exact minimum distance between two solids (inf if it cannot be computed)."""
    from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
    d = BRepExtrema_DistShapeShape(part_i.Shape, part_j.Shape)
    return d.Value() if d.IsDone() else float("inf")


def characteristic_size(parts):
    """Median of each part's smallest bounding-box dimension.

    A scale proxy: contacts happen at the scale of the smallest features, so
    this is what relative thresholds and the safety cap are expressed against.
    """
    dims = []
    for p in parts:
        x0, y0, z0, x1, y1, z1 = p.BoundingBox.Get()
        d = min(x1 - x0, y1 - y0, z1 - z0)
        if d > 1e-9:
            dims.append(d)
    return float(np.median(dims)) if dims else 1.0


# ── Gap matrix ─────────────────────────────────────────────────────────────────

def compute_gap_matrix(parts, log_fn=None, settings=None):
    """N×N matrix of inter-part gaps (model units); diagonal is inf.

    Near pairs (bounding boxes within ``near_bound_factor`` × characteristic
    size) are measured by the selected distance algorithm; far pairs keep their
    analytic bbox distance (a lower bound already well beyond any contact).

    Distance algorithm (``settings["distance"]["method"]``, default ``"exact"``):
      * ``"exact"`` — BRepExtrema between the B-Rep solids themselves, for near
        pairs only. No tessellation, so no approximation error.
      * ``"mesh"``  — tessellate each part once, point-to-triangle mesh distance.
        Deflection scales with part size; point-to-triangle (not vertex-only)
        detects flat face-to-face contacts. Tunable: ``deflection`` (None → auto),
        ``kd_k`` (default 6).

    ``exact`` is the default because the mesh path has a systematic blind spot:
    a flat face tessellates exactly, but two curved surfaces in a fit do not —
    both are faceted, the facets never meet, and a real contact reads as a gap of
    roughly the deflection, so the contact of a bolt in its bore can be
    missed. The mesh path is faster per pair on detailed solids; because the
    near-pair prefilter limits the pairs that are measured at all, the
    difference in total run time is small.

    With ``settings=None`` every knob falls back to the documented default.

    Returns (gap_matrix, characteristic_size).
    """
    from pipeline.settings import get

    n = len(parts)
    cs = characteristic_size(parts)
    near_bound = float(get(settings, "distance.near_bound_factor", 2.0)) * cs
    method = get(settings, "distance.method", "exact")
    G = np.full((n, n), np.inf)
    n_near = 0

    if method == "exact":
        for i in range(n):
            for j in range(i + 1, n):
                bg = bbox_gap(parts[i], parts[j])
                if bg <= near_bound:
                    g = exact_gap(parts[i], parts[j])
                    n_near += 1
                else:
                    g = bg  # far pair — lower bound suffices
                G[i][j] = G[j][i] = g
        if log_fn:
            log_fn(f"  Gap matrix [exact]: {n_near} BRepExtrema checks "
                   f"(of {n * (n - 1) // 2} pairs; near-bound {near_bound:.3g})")
        return G, cs

    # mesh (default)
    from pipeline.mesh_distance import tessellate, mesh_min_distance
    kd_k = int(get(settings, "distance.kd_k", 6))
    _defl = get(settings, "distance.deflection", None)
    deflection = float(_defl) if _defl is not None else max(0.05, min(0.5, 0.01 * cs))
    meshes = [tessellate(p.Shape, deflection) for p in parts]
    for i in range(n):
        for j in range(i + 1, n):
            bg = bbox_gap(parts[i], parts[j])
            if bg <= near_bound:
                g = mesh_min_distance(meshes[i], meshes[j], k=kd_k)
                n_near += 1
            else:
                g = bg  # far pair — lower bound suffices
            G[i][j] = G[j][i] = g
    if log_fn:
        log_fn(f"  Gap matrix [mesh]: {n_near} mesh distance checks "
               f"(of {n * (n - 1) // 2} pairs; deflection {deflection:.3g}, "
               f"near-bound {near_bound:.3g})")
    return G, cs


def _mst_bottleneck(G):
    """Largest edge of the minimum spanning tree = smallest threshold that
    connects every part. inf if the graph cannot be connected from known gaps."""
    n = len(G)
    if n < 2:
        return 0.0
    in_tree = [False] * n
    in_tree[0] = True
    dist = G[0].copy()
    bottleneck = 0.0
    for _ in range(n - 1):
        d, k = min((dist[k], k) for k in range(n) if not in_tree[k])
        if not np.isfinite(d):
            return float("inf")  # disconnected with the gaps we have
        bottleneck = max(bottleneck, d)
        in_tree[k] = True
        for m in range(n):
            if not in_tree[m] and G[k][m] < dist[m]:
                dist[m] = G[k][m]
    return bottleneck


def auto_contact_threshold(G, cs, valley_jump=None):
    """Derive a contact threshold from the gap distribution — no magic constant.

    The touching pairs of a real assembly form a tight cluster of small gaps,
    separated from the clearly-apart pairs by an order-of-magnitude "valley".
    We find that valley directly:

      1. Collapse the noise floor: every gap below eps (0.2% of the characteristic
         part size) is treated as the same as exact contact, so a pair that sits
         at literally 0 mm cannot create a spurious "0 → first real gap" jump.
         The fraction must stay well below the smallest designed clearance in the
         model. At 1% a 100 mm assembly gets a 1 mm noise floor, which swallows a
         0.5 mm bolt-hole clearance — and with it the very valley this function
         is looking for.
      2. The valley is the largest multiplicative jump between consecutive sorted
         gaps whose lower side is within the contact-plausible range (≤ cap = the
         characteristic part size). The threshold is the geometric mean of the
         two gaps bounding that jump.
      3. Connectivity: an assembly is connected by definition, so the threshold
         is nudged to at least include the MST bottleneck edge (the loosest gap
         needed to connect every part). If the parts cannot be connected within
         the characteristic size, that is reported as a warning and the threshold
         is capped instead of bridging the gap.

    This is scale- and unit-independent (everything is relative to cs).
    tests/test_auto_threshold.py covers a set of gap distributions.

    Returns (threshold, info dict).
    """
    n = len(G)
    jump = _VALLEY_JUMP if valley_jump is None else float(valley_jump)
    eps = max(1e-9, _NOISE_FLOOR_FRACTION * cs)
    cap = cs
    info = {"mode": "auto", "char_size": cs, "eps": eps, "cap": cap, "warning": None}

    if n < 2:
        info["mode"] = "trivial"
        return 0.0, info

    bn = _mst_bottleneck(G)
    connected = np.isfinite(bn) and bn <= cap
    if not connected:
        info["warning"] = ("parts do not form a connected contact graph within "
                            "the characteristic size; using a relative threshold")

    # Sorted unique gaps with the sub-eps cluster collapsed to a single point.
    gaps = sorted({round(max(float(v), eps), 9)
                   for v in G[np.triu_indices(n, 1)] if np.isfinite(v)})

    # Dominant valley = largest ratio jump whose lower side is contact-plausible.
    best_lo, best_hi, best_ratio = None, None, 1.0
    for k in range(1, len(gaps)):
        a, b = gaps[k - 1], gaps[k]
        if a > cap:
            break
        r = b / a
        if r > best_ratio:
            best_lo, best_hi, best_ratio = a, b, r

    if best_lo is not None and best_ratio >= jump:
        thr = math.sqrt(best_lo * best_hi)
        cluster_top, valley_to = best_lo, best_hi
    else:
        # No separation to be found. Opening up to the characteristic part size
        # would call everything within a whole part's dimension a contact, which
        # on a large assembly produces a densely connected liaison matrix and an
        # unusable AND/OR graph. Open only as far as connectivity demands — the
        # MST bottleneck — since an assembly is connected by definition.
        thr = min(cap, max(eps, float(bn) + eps)) if connected else min(cap, eps)
        cluster_top, valley_to = (gaps[-1] if gaps else eps), None
        if len(gaps) > 1:   # a real spread with no valley is genuinely ambiguous;
            info["warning"] = ("no clear gap valley found; opened only as far as "
                               "connectivity requires")
        # (a single gap cluster just means every part touches — not a warning)

    # Connectivity: include the MST bottleneck edge (a strict "< thr" test would
    # otherwise drop the edge whose gap equals bn and disconnect the graph).
    if connected:
        thr = max(thr, bn + eps)
        thr = min(thr, max(cap, bn + eps))
    else:
        thr = min(thr, cap)

    info.update({"bottleneck": float(bn) if np.isfinite(bn) else None,
                 "cluster_top": float(cluster_top),
                 "valley_to": float(valley_to) if valley_to is not None else None,
                 "threshold": float(thr)})
    return thr, info


def compute_contacts(parts, tol=None, log_fn=None, settings=None):
    """Full contact computation.

    Measures the gap matrix once (via the selected distance algorithm), then
    classifies into contacts. The threshold is chosen in this precedence order:
      1. an explicit ``tol`` argument (direct override),
      2. ``settings["contact"]["method"] == "fixed"|"manual"`` with a
         ``fixed_value``,
      3. otherwise derived automatically (auto_contact_threshold, with the
         optional ``valley_jump`` from settings).

    With ``tol=None`` and ``settings=None`` the threshold is derived automatically.

    Returns dict: liaison_matrix (int N×N), gap_matrix (float N×N, inf on the
    diagonal), threshold (float), info (dict), char_size (float).
    """
    from pipeline.settings import get

    n = len(parts)
    G, cs = compute_gap_matrix(parts, log_fn=log_fn, settings=settings)

    contact_method = get(settings, "contact.method", "auto")
    fixed_value = get(settings, "contact.fixed_value", None)
    valley = get(settings, "contact.valley_jump", None)

    if tol is not None:
        tol = float(tol)
        info = {"mode": "manual", "char_size": cs, "threshold": tol, "warning": None}
        if log_fn:
            log_fn(f"  Manual contact threshold: {tol:.4g}")
    elif contact_method in ("fixed", "manual") and fixed_value is not None:
        tol = float(fixed_value)
        info = {"mode": contact_method, "char_size": cs, "threshold": tol, "warning": None}
        if log_fn:
            log_fn(f"  {contact_method.capitalize()} contact threshold: {tol:.4g}")
    else:
        tol, info = auto_contact_threshold(G, cs, valley_jump=valley)
        if log_fn:
            log_fn(f"  Auto contact threshold: {tol:.4g} (char_size {cs:.3g}, "
                   f"valley_to {info.get('valley_to')})")

    lm = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(i + 1, n):
            if G[i][j] < tol:
                lm[i][j] = lm[j][i] = 1
    return {"liaison_matrix": lm, "gap_matrix": G, "threshold": float(tol),
            "info": info, "char_size": cs}


def contacts_from_gap_matrix(gap_matrix, tol):
    """Re-threshold a precomputed gap matrix into a binary liaison matrix.

    Pure classification (no geometry), so re-thresholding after a manual slider
    change is free. Mirrors the JS the UI runs client-side. -1 sentinels (used
    for the diagonal / non-applicable entries in transit) never count as contact.
    """
    G = np.array(gap_matrix, dtype=float)
    n = G.shape[0]
    lm = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(i + 1, n):
            g = G[i][j]
            if 0.0 <= g < tol:
                lm[i][j] = lm[j][i] = 1
    return lm
