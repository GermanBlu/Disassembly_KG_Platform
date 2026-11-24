"""Unit tests for pipeline.settings: schema, resolver and registry.

Pure Python, no OpenCASCADE: runs in any environment. The core guarantee under
test is the *None-means-default* contract — an empty/None/all-None settings
object must round-trip to all defaults, so the Golden invariants can only move
when a caller sets a real value.
"""
import math

from pipeline.settings import (
    DEFAULT_PIPELINE_SETTINGS,
    ALGORITHMS,
    ALGORITHM_LABELS,
    resolve_settings,
    default_algorithm,
    get,
    is_default,
)


# ── The defaults contract ────────────────────────────────────────────────────

def test_none_empty_and_defaults_are_equal():
    assert resolve_settings(None) == DEFAULT_PIPELINE_SETTINGS
    assert resolve_settings({}) == DEFAULT_PIPELINE_SETTINGS
    assert resolve_settings(None) == resolve_settings({})


def test_all_leaves_default_to_none():
    resolved = resolve_settings(None)
    for group, leaves in resolved.items():
        for leaf, value in leaves.items():
            assert value is None, f"{group}.{leaf} should default to None"


def test_resolve_returns_independent_deepcopy():
    a = resolve_settings(None)
    a["distance"]["method"] = "exact"
    # mutating the result must not leak into the template or a fresh resolve
    assert DEFAULT_PIPELINE_SETTINGS["distance"]["method"] is None
    assert resolve_settings(None)["distance"]["method"] is None


def test_is_default():
    assert is_default(None)
    assert is_default({})
    assert is_default({"distance": {"method": None}})
    assert not is_default({"distance": {"method": "exact"}})


# ── Deep-merge / partial overrides ───────────────────────────────────────────

def test_partial_override_sets_only_that_leaf():
    resolved = resolve_settings({"distance": {"method": "exact"}})
    assert resolved["distance"]["method"] == "exact"
    # everything else stays None
    assert resolved["distance"]["deflection"] is None
    assert resolved["contact"]["method"] is None
    assert resolved["interference"]["pixel_tol"] is None


def test_multiple_groups():
    resolved = resolve_settings({
        "distance": {"method": "exact", "kd_k": 8},
        "interference": {"pixel_tol": 0.2, "parallel": True},
        "meta": {"label": "run B"},
    })
    assert resolved["distance"]["method"] == "exact"
    assert resolved["distance"]["kd_k"] == 8
    assert resolved["interference"]["pixel_tol"] == 0.2
    assert resolved["interference"]["parallel"] is True
    assert resolved["meta"]["label"] == "run B"


# ── Unknown keys ─────────────────────────────────────────────────────────────

def test_unknown_group_is_dropped_with_warning():
    warn = []
    resolved = resolve_settings({"bogus": {"x": 1}}, warn)
    assert resolved == DEFAULT_PIPELINE_SETTINGS
    assert any("bogus" in w for w in warn)


def test_unknown_leaf_is_dropped_with_warning():
    warn = []
    resolved = resolve_settings({"distance": {"nope": 5}}, warn)
    assert resolved["distance"]["nope"] if False else True  # leaf not added
    assert "nope" not in resolved["distance"]
    assert any("distance.nope" in w for w in warn)


def test_non_dict_raw_falls_back_to_defaults():
    warn = []
    assert resolve_settings(5, warn) == DEFAULT_PIPELINE_SETTINGS
    assert any("expected an object" in w for w in warn)


def test_non_dict_group_is_ignored():
    warn = []
    resolved = resolve_settings({"distance": "not-a-dict"}, warn)
    assert resolved == DEFAULT_PIPELINE_SETTINGS
    assert any("distance" in w for w in warn)


# ── Value validation ─────────────────────────────────────────────────────────

def test_invalid_enum_falls_back():
    warn = []
    resolved = resolve_settings({"distance": {"method": "quantum"}}, warn)
    assert resolved["distance"]["method"] is None
    assert any("quantum" in w for w in warn)


def test_non_finite_float_rejected():
    for bad in (float("nan"), float("inf"), float("-inf")):
        warn = []
        resolved = resolve_settings({"distance": {"deflection": bad}}, warn)
        assert resolved["distance"]["deflection"] is None
        assert any("deflection" in w for w in warn)


def test_float_out_of_range_rejected():
    # pixel_tol must be in [0, 1]
    assert resolve_settings({"interference": {"pixel_tol": 1.5}})["interference"]["pixel_tol"] is None
    assert resolve_settings({"interference": {"pixel_tol": -0.1}})["interference"]["pixel_tol"] is None
    # in-range is kept
    assert resolve_settings({"interference": {"pixel_tol": 0.25}})["interference"]["pixel_tol"] == 0.25


def test_valley_jump_must_exceed_one():
    assert resolve_settings({"contact": {"valley_jump": 0.5}})["contact"]["valley_jump"] is None
    assert resolve_settings({"contact": {"valley_jump": 3.0}})["contact"]["valley_jump"] == 3.0


def test_two_step_mode_is_an_enum():
    assert resolve_settings({"interference": {"two_step": "auto"}})["interference"]["two_step"] == "auto"
    assert resolve_settings({"interference": {"two_step": "always"}})["interference"]["two_step"] is None


def test_green_threshold_byte_range():
    assert resolve_settings({"interference": {"green_threshold": 300}})["interference"]["green_threshold"] is None
    assert resolve_settings({"interference": {"green_threshold": 200}})["interference"]["green_threshold"] == 200


def test_int_leaf_rejects_bool():
    warn = []
    resolved = resolve_settings({"distance": {"kd_k": True}}, warn)
    assert resolved["distance"]["kd_k"] is None
    assert any("kd_k" in w for w in warn)


def test_bool_leaf_rejects_string():
    warn = []
    resolved = resolve_settings({"interference": {"parallel": "yes"}}, warn)
    assert resolved["interference"]["parallel"] is None
    assert any("parallel" in w for w in warn)


def test_fixed_value_must_be_nonzero_positive():
    assert resolve_settings({"contact": {"fixed_value": 0}})["contact"]["fixed_value"] is None
    assert resolve_settings({"contact": {"fixed_value": -1}})["contact"]["fixed_value"] is None
    assert resolve_settings({"contact": {"fixed_value": 1.5}})["contact"]["fixed_value"] == 1.5


def test_split_tol_allows_zero():
    # split_tol lo=0, allow_zero default True
    assert resolve_settings({"distance": {"split_tol": 0}})["distance"]["split_tol"] == 0.0


def test_numeric_string_is_coerced():
    # JSON sometimes carries numbers as strings from form posts
    assert resolve_settings({"distance": {"kd_k": "8"}})["distance"]["kd_k"] == 8
    assert resolve_settings({"interference": {"pixel_tol": "0.3"}})["interference"]["pixel_tol"] == 0.3


# ── get() helper ─────────────────────────────────────────────────────────────

def test_get_applies_default_when_none():
    resolved = resolve_settings(None)
    assert get(resolved, "distance.method", "mesh") == "mesh"
    assert get(resolved, "interference.pixel_tol", 0.10) == 0.10


def test_get_returns_override():
    resolved = resolve_settings({"distance": {"method": "exact"}})
    assert get(resolved, "distance.method", "mesh") == "exact"


def test_get_handles_missing_gracefully():
    assert get(None, "distance.method", "mesh") == "mesh"
    assert get({}, "distance.method", "mesh") == "mesh"


# ── Registry ─────────────────────────────────────────────────────────────────

def test_registry_distance_choices():
    assert set(ALGORITHMS["distance"]) == {"mesh", "exact"}
    assert set(ALGORITHMS["contact_threshold"]) == {"auto", "fixed", "manual"}


def test_default_algorithm():
    assert default_algorithm("distance") == "exact"
    assert default_algorithm("contact_threshold") == "fixed"   # the standard: 0.5 mm
    assert default_algorithm("nonexistent") is None


def test_labels_cover_all_choices():
    for cat, choices in ALGORITHMS.items():
        assert set(ALGORITHM_LABELS[cat]) == set(choices)
        for key in choices:
            assert isinstance(ALGORITHM_LABELS[cat][key], str)
