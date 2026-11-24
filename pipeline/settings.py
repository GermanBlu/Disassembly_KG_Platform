"""Pipeline settings: schema, resolver and algorithm registry.

A single, OCC-free description of every tunable knob in the STEP→KG pipeline, so
the Flask app, the Phase-1 worker subprocess and the UI can all agree on the same
shape without importing OpenCASCADE.

Design contract
---------------
* The settings object is two levels deep: ``{group: {leaf: value}}`` with the
  groups ``distance`` / ``contact`` / ``interference`` / ``aog`` / ``meta``.
* **Every leaf defaults to ``None``**, and ``None`` means *"use the built-in
  default of the pipeline module"* (:data:`CODE_DEFAULTS`). An all-``None``
  settings object (or ``None`` / ``{}`` at the top) therefore changes nothing
  for a direct function call.
* A platform run (``models.step_pipeline.run_step_phase1``) starts from
  :data:`STANDARD_SETTINGS`; a client overrides single leaves to experiment.
  Over HTTP only the leaves in :data:`CLIENT_SETTINGS` are accepted
  (:func:`client_settings`); the others keep their server value.
* :func:`resolve_settings` deep-merges raw input onto the all-defaults template,
  drops unknown keys (with a warning) and rejects malformed values (non-finite
  floats, out-of-range, wrong enum) by falling back to ``None`` + a warning. It
  never raises on bad input — a bad knob degrades to the default, it does not
  break a pipeline run.

This module imports nothing from OCC or the rest of the pipeline; it is pure
stdlib so it is safe to import from ``app.py`` and ``models/step_worker.py``.
"""
from __future__ import annotations

import copy
import math

from pipeline.interference import COUNT_REGIONS, DIRECTION_MODES, REVERSE_CHECK_SCOPES
from pipeline.two_step import TWO_STEP_MODES


# ── Algorithm registry ───────────────────────────────────────────────────────
# Enumerations of the selectable algorithms per category, with display labels and
# descriptions for the settings dropdowns. Values are metadata only — the
# actual dispatch (mesh vs exact, auto vs fixed) lives in the OCC-aware modules
# (liaison_matrix.compute_gap_matrix / compute_contacts) which look up the key.

ALGORITHMS = {
    "distance": {
        "exact": {
            "label": "Exact (BRepExtrema)",
            "description": "Exact solid-to-solid distance without tessellation; also "
                           "finds fits such as a screw in its bore, where the mesh "
                           "approximation fails.",
            "default": True,
        },
        "mesh": {
            "label": "Mesh (point to triangle)",
            "description": "Tessellates every part once and measures mesh distances. "
                           "Fast on detailed solids, but curved mating faces are "
                           "faceted and then never touch.",
            "default": False,
        },
    },
    "contact_threshold": {
        "auto": {
            "label": "From the gap distribution",
            "description": "Derives the contact threshold from the distribution of "
                           "gaps (independent of scale and units).",
            "default": False,
        },
        "fixed": {
            "label": "Fixed distance",
            "description": "An absolute threshold in model units (standard: 0.5 mm).",
            "default": True,
        },
        "manual": {
            "label": "Manual",
            "description": "Like a fixed distance, but recorded as a manual "
                           "user input.",
            "default": False,
        },
    },
}

# Flat {category: {key: label}} for building dropdowns.
ALGORITHM_LABELS = {
    cat: {key: meta["label"] for key, meta in choices.items()}
    for cat, choices in ALGORITHMS.items()
}


def default_algorithm(category: str) -> str | None:
    """Return the registry key flagged as default for a category (or None)."""
    for key, meta in ALGORITHMS.get(category, {}).items():
        if meta.get("default"):
            return key
    return None


# ── Default settings template (every leaf None = built-in default) ───────────

DEFAULT_PIPELINE_SETTINGS = {
    "distance": {
        "method": None,            # exact | mesh            (None → "exact")
        "deflection": None,        # mesh tessellation deflection, model units
                                   #   (None → auto: max(0.05, min(0.5, 0.01*char_size)))
        "kd_k": None,              # kd-tree candidate neighbours (None → 6)
        "near_bound_factor": None, # near-pair prefilter: near_bound = factor*char_size
                                   #   (None → 2.0)
        "split_tol": None,         # _split_disconnected_solids tolerance (None → 0.1)
    },
    "contact": {
        "method": None,            # auto | fixed | manual   (None → "auto"; standard: "fixed")
        "fixed_value": None,       # absolute threshold when method in {fixed, manual}
        "valley_jump": None,       # auto-threshold valley ratio (None → 3.0)
    },
    "interference": {
        "pixel_tol": None,         # green-pixel reduction fraction, contacting pairs
                                   #   (None → 0.10)
        "pixel_tol_noncontact": None,  # same, pairs without contact (None → 0.0)
        "reverse_check": None,     # Prasad test case 2 scope: noncontact | all | off
                                   #   (None → "noncontact")
        "directions": None,        # test directions: cardinal | contact (Prasad §3)
                                   #   (None → "cardinal")
        "edge_px": None,           # silhouette edge tolerance in pixels (None → 0)
        "count_region": None,      # pixel counting region: image | overlap (Prasad §2.2)
                                   #   (None → "image")
        "two_step": None,          # automatic two-step releases: off | auto
                                   #   (None → "off", see pipeline.two_step)
        "green_threshold": None,   # green channel cutoff 0-255 (None → 200)
        "parallel": None,          # run directions in parallel (None → False; macOS unsafe)
    },
    "aog": {
        "max_transitions": None,   # pre-flight transition cap (None → 5_000_000)
        "max_parts": None,         # part-count cap after grouping (None → 80)
        "max_nodes": None,         # in-loop AOG node backstop (None → 1_000_000)
        "max_candidate_pairs": None,  # per-layer pair backstop (None → 50_000_000)
    },
    "meta": {
        "label": None,             # free-text label of a run
        "notes": None,             # free-text notes
    },
}

# The standard settings of every Phase 1 run. Contact = minimum distance below
# 0.5 mm (a platform parameter); test directions from the surfaces the contacting parts share; both
# visual tests for every pair and pixels counted in the overlap of the projected
# bounding boxes (Prasad et al. 2022); 1 px silhouette edge excluded (flush
# fits); 1 % pixel tolerance for contacting pairs; automatic two-step releases
# (pipeline.two_step). A client may override single leaves to try other
# settings (with_standard_settings); the result echoes the settings it used.
STANDARD_SETTINGS = {
    "contact": {"method": "fixed", "fixed_value": 0.5},
    "interference": {"directions": "contact", "reverse_check": "all", "count_region": "overlap",
                     "edge_px": 1, "pixel_tol": 0.01, "two_step": "auto"},
}


def with_standard_settings(raw=None):
    """STANDARD_SETTINGS with ``raw`` merged on top, leaf by leaf (``raw`` wins).

    Every Phase 1 run starts from the standard settings (run_step_phase1); a
    client that wants to experiment overrides single leaves.
    """
    merged = copy.deepcopy(STANDARD_SETTINGS)
    if isinstance(raw, dict):
        for group, leaves in raw.items():
            if isinstance(leaves, dict) and isinstance(merged.get(group), dict):
                merged[group] = {**merged[group], **leaves}
            else:
                merged[group] = copy.deepcopy(leaves)
    return merged


# Built-in defaults of the pipeline modules, used when a library function is
# called directly without settings. Display-only; never resolve against this.
CODE_DEFAULTS = {
    "distance": {"method": "exact", "deflection": "auto", "kd_k": 6,
                 "near_bound_factor": 2.0, "split_tol": 0.1},
    "contact": {"method": "auto", "fixed_value": None, "valley_jump": 3.0},
    "interference": {"pixel_tol": 0.10, "pixel_tol_noncontact": 0.0,
                     "reverse_check": "noncontact", "directions": "cardinal", "edge_px": 0,
                     "count_region": "image", "two_step": "off",
                     "green_threshold": 200, "parallel": False},
    "aog": {"max_transitions": 5_000_000, "max_parts": 80,
            "max_nodes": 1_000_000, "max_candidate_pairs": 50_000_000},
    "meta": {"label": None, "notes": None},
}


def resolve_standard(raw=None, warn=None):
    """resolve_settings(with_standard_settings(raw), warn), except that a leaf
    the caller set to an invalid value keeps its standard value instead of the
    module default."""
    resolved = resolve_settings(with_standard_settings(raw), warn)
    for group, leaves in STANDARD_SETTINGS.items():
        for leaf, value in leaves.items():
            if resolved[group][leaf] is None:
                resolved[group][leaf] = value
    return resolved


# The leaves a client (Studio, REST API) may change to try other settings: the
# alternatives of the method itself. Internal limits and switches (graph caps,
# distance prefilters, render cutoffs, threading) keep their server values.
CLIENT_SETTINGS = {
    "contact": ("method", "fixed_value"),
    "interference": ("directions", "reverse_check", "count_region", "edge_px",
                     "pixel_tol", "pixel_tol_noncontact", "two_step"),
    "distance": ("method",),
}


def client_settings(raw):
    """Keep only the :data:`CLIENT_SETTINGS` leaves of a client's settings object.

    Returns ``(kept, ignored)``: ``kept`` is a settings dict or ``None`` when
    nothing is left, ``ignored`` the sorted ``group.leaf`` names that were dropped.
    """
    if not isinstance(raw, dict):
        return None, []
    kept, ignored = {}, []
    for group, leaves in raw.items():
        allowed = CLIENT_SETTINGS.get(group, ())
        if not isinstance(leaves, dict):
            ignored.append(str(group))
            continue
        for leaf, value in leaves.items():
            if leaf in allowed:
                kept.setdefault(group, {})[leaf] = value
            else:
                ignored.append(f"{group}.{leaf}")
    return (kept or None), sorted(ignored)


def standard_values():
    """Every leaf with the value a platform run uses when the client sets nothing:
    the module defaults with STANDARD_SETTINGS on top (for UI hints)."""
    merged = copy.deepcopy(CODE_DEFAULTS)
    for group, leaves in STANDARD_SETTINGS.items():
        merged[group].update(leaves)
    return merged


# ── Validation helpers ───────────────────────────────────────────────────────

def _opt_float(value, name, warn, *, lo=None, hi=None, allow_zero=True):
    """Validate an optional float leaf. Returns the float or None (+warning)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        warn.append(f"{name}: not a number ({value!r}) — using default")
        return None
    if not math.isfinite(v):
        warn.append(f"{name}: non-finite ({value!r}) — using default")
        return None
    if not allow_zero and v == 0:
        warn.append(f"{name}: must be non-zero — using default")
        return None
    if lo is not None and v < lo:
        warn.append(f"{name}: {v} below minimum {lo} — using default")
        return None
    if hi is not None and v > hi:
        warn.append(f"{name}: {v} above maximum {hi} — using default")
        return None
    return v


def _opt_int(value, name, warn, *, lo=None, hi=None):
    """Validate an optional int leaf. Returns the int or None (+warning)."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        warn.append(f"{name}: expected an integer, got a boolean — using default")
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        warn.append(f"{name}: not an integer ({value!r}) — using default")
        return None
    if lo is not None and v < lo:
        warn.append(f"{name}: {v} below minimum {lo} — using default")
        return None
    if hi is not None and v > hi:
        warn.append(f"{name}: {v} above maximum {hi} — using default")
        return None
    return v


def _opt_bool(value, name, warn):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    warn.append(f"{name}: expected true/false ({value!r}) — using default")
    return None


def _opt_enum(value, name, warn, choices):
    if value is None:
        return None
    if value in choices:
        return value
    warn.append(f"{name}: unknown option {value!r} (expected one of "
                f"{sorted(choices)}) — using default")
    return None


def _opt_str(value, name, warn):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    warn.append(f"{name}: expected a string ({value!r}) — using default")
    return None


# Per-leaf validators. Each is called as validator(raw_value, dotted_name, warn).
_VALIDATORS = {
    ("distance", "method"): lambda v, n, w: _opt_enum(v, n, w, ALGORITHMS["distance"]),
    ("distance", "deflection"): lambda v, n, w: _opt_float(v, n, w, lo=0, allow_zero=False),
    ("distance", "kd_k"): lambda v, n, w: _opt_int(v, n, w, lo=1),
    ("distance", "near_bound_factor"): lambda v, n, w: _opt_float(v, n, w, lo=0, allow_zero=False),
    ("distance", "split_tol"): lambda v, n, w: _opt_float(v, n, w, lo=0),
    ("contact", "method"): lambda v, n, w: _opt_enum(v, n, w, ALGORITHMS["contact_threshold"]),
    ("contact", "fixed_value"): lambda v, n, w: _opt_float(v, n, w, lo=0, allow_zero=False),
    ("contact", "valley_jump"): lambda v, n, w: _opt_float(v, n, w, lo=1.0),
    ("interference", "pixel_tol"): lambda v, n, w: _opt_float(v, n, w, lo=0.0, hi=1.0),
    ("interference", "pixel_tol_noncontact"): lambda v, n, w: _opt_float(v, n, w, lo=0.0, hi=1.0),
    ("interference", "reverse_check"): lambda v, n, w: _opt_enum(v, n, w, REVERSE_CHECK_SCOPES),
    ("interference", "directions"): lambda v, n, w: _opt_enum(v, n, w, DIRECTION_MODES),
    ("interference", "edge_px"): lambda v, n, w: _opt_int(v, n, w, lo=0, hi=10),
    ("interference", "count_region"): lambda v, n, w: _opt_enum(v, n, w, COUNT_REGIONS),
    ("interference", "two_step"): lambda v, n, w: _opt_enum(v, n, w, TWO_STEP_MODES),
    ("interference", "green_threshold"): lambda v, n, w: _opt_int(v, n, w, lo=0, hi=255),
    ("interference", "parallel"): lambda v, n, w: _opt_bool(v, n, w),
    ("aog", "max_transitions"): lambda v, n, w: _opt_int(v, n, w, lo=1),
    ("aog", "max_parts"): lambda v, n, w: _opt_int(v, n, w, lo=1),
    ("aog", "max_nodes"): lambda v, n, w: _opt_int(v, n, w, lo=1),
    ("aog", "max_candidate_pairs"): lambda v, n, w: _opt_int(v, n, w, lo=1),
    ("meta", "label"): lambda v, n, w: _opt_str(v, n, w),
    ("meta", "notes"): lambda v, n, w: _opt_str(v, n, w),
}


# ── Resolver ─────────────────────────────────────────────────────────────────

def resolve_settings(raw, warn=None):
    """Deep-merge ``raw`` onto the all-defaults template and validate every leaf.

    Args:
        raw:  ``None``, ``{}`` or a (partial) settings dict. Extra groups/leaves
              are ignored with a warning; malformed values fall back to ``None``.
        warn: optional list; warning strings are appended to it. When omitted, a
              fresh list is used and discarded (warnings are still never raised).

    Returns:
        A fully-shaped settings dict (same structure as DEFAULT_PIPELINE_SETTINGS).
        ``resolve_settings(None) == resolve_settings({}) == DEFAULT_PIPELINE_SETTINGS``.
    """
    if warn is None:
        warn = []
    resolved = copy.deepcopy(DEFAULT_PIPELINE_SETTINGS)

    if raw is None:
        return resolved
    if not isinstance(raw, dict):
        warn.append(f"pipeline_settings: expected an object, got {type(raw).__name__} "
                    "— using all defaults")
        return resolved

    for group, leaves in raw.items():
        if group not in DEFAULT_PIPELINE_SETTINGS:
            warn.append(f"unknown settings group {group!r} — ignored")
            continue
        if not isinstance(leaves, dict):
            warn.append(f"settings group {group!r}: expected an object — ignored")
            continue
        for leaf, value in leaves.items():
            if leaf not in DEFAULT_PIPELINE_SETTINGS[group]:
                warn.append(f"unknown setting {group}.{leaf} — ignored")
                continue
            validator = _VALIDATORS[(group, leaf)]
            resolved[group][leaf] = validator(value, f"{group}.{leaf}", warn)

    return resolved


def get(resolved, dotted, default):
    """Read ``group.leaf`` from a resolved settings dict, applying ``default``
    when the leaf is ``None`` or missing. Convenience for the OCC-side callers,
    so they can write ``get(s, "distance.method", "mesh")`` instead of repeating
    the ``... if ... is not None else ...`` dance."""
    group, _, leaf = dotted.partition(".")
    val = (resolved or {}).get(group, {}).get(leaf)
    return default if val is None else val


def is_default(resolved) -> bool:
    """True if the resolved settings carry no overrides (every leaf is None)."""
    return resolve_settings(None) == resolve_settings(resolved)
