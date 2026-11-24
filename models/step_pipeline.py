"""STEP Pipeline orchestrator.

Thin coordinator that calls the focused modules in pipeline/:

  pipeline.geometry     — STEP loading, liaison matrix
  pipeline.interference — two-stage interference check
  pipeline.aog_builder  — AND/OR Graph generation
  pipeline.semantic     — semantic connection tables & transition extraction

External dependencies (pythonocc-core / OpenCASCADE) are required.
"""
import logging
import sys
import time
import traceback

from pipeline.geometry import load_and_extract, volume_overlaps
from pipeline.interference import (check_interference, build_directions,
                                   build_contact_directions, apply_motion_releases)
from pipeline.part_ids import part_id
from pipeline.two_step import derive_two_step_releases
from pipeline.semantic import generate_semantic_tables
from pipeline.fastener_detection import detect_fasteners

logger = logging.getLogger(__name__)


# ── Dependency check ──────────────────────────────────────────────────────────

def check_occ_available():
    """Return (True, None) if OpenCASCADE is importable, else (False, error_msg)."""
    try:
        from OCC.Core.STEPControl import STEPControl_Reader  # noqa: F401
        return True, None
    except ImportError as e:
        return False, str(e)


def _init_cocoa() -> None:
    """Initialize macOS Cocoa before any OCC offscreen rendering.

    macOS-only: OCC's Viewer3d.Create() → InitOffscreen() raises
    Aspect_WindowDefinitionError on macOS unless an NSApplication exists.
    On Windows and Linux this is a no-op (Win32/X11/EGL handle the context
    themselves), so the function returns immediately on non-Darwin platforms.

    Tries pyobjc (AppKit) first; falls back to raw ctypes ObjC runtime
    calls if pyobjc is not installed.  pyobjc-framework-Cocoa should be
    installed in the OCC conda env (`pip install pyobjc-framework-Cocoa`).
    """
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication()
        return
    except ImportError:
        pass
    try:
        import ctypes
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend(
            objc.objc_getClass(b'NSApplication'),
            objc.sel_registerName(b'sharedApplication'),
        )
    except Exception:
        pass


# ── Phase 1: Parts + liaison matrix + interference matrices ───────────────────

def _matrix_to_json(m):
    """numpy/list matrix → JSON-safe nested lists (any non-finite → -1.0 sentinel).

    Replaces inf, -inf and NaN with the -1.0 sentinel so the payload always
    survives json.dumps(allow_nan=False) and the browser's JSON.parse.
    """
    if m is None:
        return None
    import numpy as np
    arr = np.array(m, dtype=float)
    arr = np.where(np.isfinite(arr), arr, -1.0)
    return arr.tolist()


def run_step_phase1(step_files, part_labels, manual_liaison=None,
                    contact_tol=None, pixel_tol=None, settings=None):
    """Load parts, compute liaison matrix and interference matrices.

    Stops before AOG generation. The caller presents the fastener-identification
    UI, then passes the result (with user fastener selections) to
    generate_semantic_tables().

    Args:
        step_files:      List of STEP file paths (one assembly OR one file per part).
        part_labels:     Corresponding human-readable part labels.
        manual_liaison:  Optional N×N list-of-lists to use as liaison matrix.
        contact_tol:     Explicit contact gap threshold (model units), a direct
                         override: wins over settings when set; None → the
                         threshold follows from the settings.
        pixel_tol:       Explicit interference pixel tolerance, a direct
                         override: wins over settings when set.
        settings:        Optional pipeline_settings dict (see pipeline.settings),
                         merged over the standard settings; None → standard. The
                         resolved settings are echoed back as
                         ``pipeline_settings_resolved``.

    Returns:
        dict with keys:
          success, parts (list[str]), liaison_matrix, gap_matrix,
          contact_threshold, contact_info, contacts, interference_matrices,
          interference_ratios, interference_directions, two_step_releases,
          volume_overlaps, suggested_fasteners, fastener_detections,
          pipeline_settings_resolved, pipeline_settings_warnings, timing, log, error
    """
    from pipeline.settings import get, resolve_standard
    # Phase 1 starts from the standard settings; explicit settings override
    # single leaves (pipeline.settings.resolve_standard).
    settings_warnings = []
    resolved = resolve_standard(settings, settings_warnings)
    eff_pixel_tol = pixel_tol if pixel_tol is not None else get(resolved, "interference.pixel_tol", None)
    eff_pixel_tol_nc = get(resolved, "interference.pixel_tol_noncontact", None)
    eff_reverse_check = get(resolved, "interference.reverse_check", None)
    eff_directions = get(resolved, "interference.directions", None) or "cardinal"
    eff_edge_px = get(resolved, "interference.edge_px", None)
    eff_count_region = get(resolved, "interference.count_region", None)
    eff_two_step = get(resolved, "interference.two_step", None) or "off"

    result = {
        "success": False,
        "parts": [],
        "liaison_matrix": [],
        "gap_matrix": [],
        "contact_threshold": None,
        "contact_info": None,
        "contacts": [],
        "interference_matrices": [],
        "interference_ratios": [],
        "interference_directions": [],
        "two_step_releases": [],
        "volume_overlaps": [],
        "suggested_fasteners": [],
        "fastener_detections": [],
        "pipeline_settings_resolved": resolved,
        "pipeline_settings_warnings": settings_warnings,
        "timing": {},
        "log": [],
        "error": None,
    }

    def log(msg):
        result["log"].append(msg)
        logger.info("Phase1: %s", msg)

    available, err = check_occ_available()
    if not available:
        result["error"] = f"OpenCASCADE not available: {err}"
        return result

    _init_cocoa()

    try:
        t_total = time.time()

        # ── Geometry & liaison ────────────────────────────────────────────────
        geo = load_and_extract(
            step_files=step_files,
            part_labels=part_labels,
            manual_liaison=manual_liaison,
            contact_tol=contact_tol,
            log_fn=log,
            settings=resolved,
        )
        parts = geo["parts"]
        active_labels = geo["part_labels"]
        liaison_matrix = geo["liaison_matrix"]

        result["parts"] = active_labels
        result["liaison_matrix"] = (
            liaison_matrix.tolist()
            if hasattr(liaison_matrix, 'tolist')
            else liaison_matrix
        )
        result["gap_matrix"] = _matrix_to_json(geo.get("gap_matrix"))
        result["contact_threshold"] = geo.get("contact_threshold")
        result["contact_info"] = geo.get("contact_info")
        result["contacts"] = geo["contacts"]
        result["timing"].update(geo["timing"])

        # ── Overlap check: the interference check needs an overlap-free model ──
        t_ov = time.time()
        overlaps = volume_overlaps(parts, liaison_matrix)
        result["volume_overlaps"] = [
            {"part1": active_labels[i], "part2": active_labels[j], "volume": round(v, 2)}
            for i, j, v in overlaps]
        result["timing"]["overlap_check"] = round(time.time() - t_ov, 2)
        if overlaps:
            log("WARNING: overlapping parts — "
                + "; ".join(f"{active_labels[i]} / {active_labels[j]}: {v:.1f}" for i, j, v in overlaps)
                + ". Overlapping parts block each other in every direction; correct the CAD "
                  "model (e.g. threads without overlap) before relying on the result.")
        else:
            log("Overlap check: no overlapping parts")

        # ── Interference check ────────────────────────────────────────────────
        log("Phase 1: Interference Check (two-stage)...")
        t0 = time.time()
        if eff_directions == "contact":
            directions, _ = build_contact_directions(
                parts, liaison_matrix, geo.get("contact_threshold"))
        else:
            directions = build_directions()
        result["timing"]["directions"] = round(time.time() - t0, 2)
        result["interference_directions"] = [
            [round(d.X(), 6), round(d.Y(), 6), round(d.Z(), 6)] for d in directions]
        log(f"Interference directions: {len(directions)} ({eff_directions})")
        t0 = time.time()
        int_matrices, int_ratios = check_interference(
            directions=directions,
            parts=parts,
            liaison_matrix=liaison_matrix,   # liaison bypass: contacting pairs go to Stage 2
            return_ratios=True,
            pixel_tol=eff_pixel_tol,
            pixel_tol_noncontact=eff_pixel_tol_nc,
            reverse_check=eff_reverse_check,
            edge_px=eff_edge_px,
            count_region=eff_count_region,
        )
        t_int = round(time.time() - t0, 2)
        result["timing"]["interference"] = t_int
        log(f"Interference check done in {t_int:.2f}s")

        # ── Two-step releases (pipeline.two_step) ─────────────────────────────
        if eff_two_step == "auto":
            log("Phase 1: Two-step releases (parts that leave in two straight moves)...")
            t_ts = time.time()
            vecs = [(d.X(), d.Y(), d.Z()) for d in directions]
            releases = derive_two_step_releases(
                parts, int_matrices, vecs, liaison_matrix,
                pixel_tol=eff_pixel_tol_nc, edge_px=eff_edge_px,
                count_region=eff_count_region, log_fn=log)
            int_matrices = apply_motion_releases(
                int_matrices, vecs, releases, [part_id(i) for i in range(len(parts))])
            result["two_step_releases"] = releases
            result["timing"]["two_step"] = round(time.time() - t_ts, 2)
            log(f"Two-step releases: {len(releases)} in {result['timing']['two_step']:.2f}s")

        result["interference_matrices"] = [
            m.tolist() if hasattr(m, 'tolist') else [list(row) for row in m]
            for m in int_matrices
        ]
        result["interference_ratios"] = [_matrix_to_json(r) for r in int_ratios]

        # ── Fastener auto-detection ──────────────────────────────────────────
        log("Auto-detecting fasteners from part names and geometry...")
        t_fd = time.time()
        fd_result = detect_fasteners(parts, active_labels)
        result["suggested_fasteners"] = fd_result["fastener_indices"]
        result["fastener_detections"] = fd_result["detections"]
        result["timing"]["fastener_detection"] = round(time.time() - t_fd, 2)
        for msg in fd_result["log"]:
            log(msg)
        log(f"Suggested {len(fd_result['fastener_indices'])} fasteners "
            f"(user can override in UI)")

        result["timing"]["total"] = round(time.time() - t_total, 2)
        result["success"] = True
        log("Phase 1 complete. Ready for fastener tagging.")

    except Exception as e:
        result["error"] = f"Phase 1 error: {str(e)}"
        result["log"].append(f"ERROR: {traceback.format_exc()}")
        logger.exception("step phase1 failed")

    return result


# ── Full pipeline ─────────────────────────────────────────────────────────────

def run_step_pipeline(step_files, part_labels, manual_liaison=None, precedence_rules=None):
    """Run the full STEP → transitions pipeline without fastener-tagging UI.

    Assumes no fasteners (all contacts treated as PressFit). For the full
    fastener-aware workflow use run_step_phase1() + generate_semantic_tables().

    Returns:
        dict — same schema as run_step_phase1 plus: transitions, aog_stats.
    """
    result = {
        "success": False,
        "parts": [],
        "liaison_matrix": [],
        "contacts": [],
        "interference_summary": [],
        "transitions": [],
        "aog_stats": {},
        "timing": {},
        "error": None,
        "log": [],
    }

    def log(msg):
        result["log"].append(msg)
        logger.info("Pipeline: %s", msg)

    available, err = check_occ_available()
    if not available:
        result["error"] = f"OpenCASCADE not available: {err}"
        return result

    _init_cocoa()

    try:
        import numpy as np
        t_total = time.time()

        # ── Phase 1: geometry + interference ─────────────────────────────────
        phase1 = run_step_phase1(step_files, part_labels, manual_liaison)
        if not phase1["success"]:
            result.update(phase1)
            return result

        for key in ("parts", "liaison_matrix", "contacts", "timing"):
            result[key] = phase1[key]
        result["log"] = phase1["log"]

        # Interference summary, one entry per test direction
        result["interference_summary"] = [
            {"direction": d, "count": int(np.array(m).sum())}
            for m, d in zip(phase1["interference_matrices"], phase1["interference_directions"])
        ]

        # ── Phase 2: semantic tables + transitions ────────────────────────────
        log("Phase 2: Generating semantic tables...")
        semantic = generate_semantic_tables(
            fastener_indices=[],                        # no fasteners in full-auto mode
            part_labels=phase1["parts"],
            liaison_matrix=phase1["liaison_matrix"],
            interference_matrices=phase1["interference_matrices"],
            precedence_rules=precedence_rules or {},
        )
        result["log"].extend(semantic.get("log", []))
        if not semantic["success"]:
            result["error"] = semantic.get("error", "Semantic tables failed")
            return result

        result["transitions"] = semantic["transitions"]
        log(f"Extracted {len(semantic['transitions'])} transitions")

        result["timing"]["total"] = round(time.time() - t_total, 2)
        result["success"] = True
        log(f"Pipeline complete in {result['timing']['total']:.2f}s")

    except Exception as e:
        result["error"] = f"Pipeline error: {str(e)}"
        result["log"].append(f"ERROR: {traceback.format_exc()}")
        logger.exception("step pipeline failed")

    return result
