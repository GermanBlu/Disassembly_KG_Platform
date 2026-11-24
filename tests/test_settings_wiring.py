"""Settings end-to-end wiring + distance/contact switch.

Verifies that pipeline_settings actually reach the pipeline (not just resolve in
isolation): the algorithms enumeration endpoint, the AOG-cap override tripping
the explosion guard, and (OCC) the distance/contact algorithm switch reproducing
the golden liaison. settings=None must always give the code defaults.
"""
import os

import numpy as np
import pytest

from conftest import requires_occ

_HYPO = "sample_data/Hypothetical Product STEP/Hypothetical Product.step"


def _star(n):
    lm = np.zeros((n, n), dtype=int)
    for i in range(1, n):
        lm[0][i] = lm[i][0] = 1
    return lm.tolist()


def _capture_phase1(monkeypatch):
    import app as A
    seen = {}

    def fake(step_paths, labels, manual_liaison=None, contact_tol=None, pixel_tol=None,
             settings=None):
        seen.update(settings=settings, contact_tol=contact_tol, pixel_tol=pixel_tol)
        return {"success": True}

    monkeypatch.setattr(A, "_run_step_phase1_subprocess", fake)
    return A.app.test_client(), seen


def test_step_run_passes_client_settings(monkeypatch):
    """A client may change single settings; they reach Phase 1 unchanged."""
    import io
    client, seen = _capture_phase1(monkeypatch)
    r = client.post("/api/step/run", content_type="multipart/form-data", data={
        "step_files[]": (io.BytesIO(b"ISO-10303-21;"), "a.step"), "labels[]": "a",
        "pipeline_settings": '{"interference": {"pixel_tol": 0.3}}'})
    assert r.status_code == 200
    assert seen == {"settings": {"interference": {"pixel_tol": 0.3}}, "contact_tol": None, "pixel_tol": None}
    assert r.get_json()["pipeline_settings_ignored"] == []


def test_step_run_drops_settings_a_client_may_not_change(monkeypatch):
    """Only CLIENT_SETTINGS reach Phase 1; internal limits and switches are
    dropped and named in the result."""
    import io
    import json
    client, seen = _capture_phase1(monkeypatch)
    sent = {"interference": {"directions": "cardinal", "parallel": True, "green_threshold": 10},
            "aog": {"max_nodes": 10 ** 9}, "distance": {"method": "mesh", "kd_k": 50}, "meta": "x"}
    r = client.post("/api/step/run", content_type="multipart/form-data", data={
        "step_files[]": (io.BytesIO(b"ISO-10303-21;"), "a.step"), "labels[]": "a",
        "pipeline_settings": json.dumps(sent)})
    assert seen["settings"] == {"interference": {"directions": "cardinal"}, "distance": {"method": "mesh"}}
    assert r.get_json()["pipeline_settings_ignored"] == [
        "aog.max_nodes", "distance.kd_k", "interference.green_threshold", "interference.parallel", "meta"]


def test_generate_tables_ignores_client_graph_caps():
    """The AND/OR graph caps are not client settings: a request cannot lower or
    raise them over HTTP."""
    import app as A
    n = 6
    labels = [f"P{i} ({chr(65 + i)})" for i in range(n)]
    ints = [np.zeros((n, n), dtype=int).tolist() for _ in range(6)]
    r = A.app.test_client().post("/api/step/generate-tables", json={
        "fastener_indices": [], "part_labels": labels, "liaison_matrix": _star(n),
        "interference_matrices": ints, "pipeline_settings": {"aog": {"max_transitions": 1}}})
    j = r.get_json()
    assert j["success"] is True
    assert j["pipeline_settings_ignored"] == ["aog.max_transitions"]


def test_invalid_client_value_keeps_the_standard():
    """An invalid value falls back to the standard value, not the module default."""
    from pipeline.settings import resolve_standard
    warn = []
    resolved = resolve_standard({"interference": {"pixel_tol": 7, "edge_px": "x", "directions": "diagonal"}}, warn)
    assert resolved["interference"]["pixel_tol"] == 0.01
    assert resolved["interference"]["edge_px"] == 1
    assert resolved["interference"]["directions"] == "contact"
    assert len(warn) == 3


def test_client_settings_are_the_studio_rows():
    """The Studio offers exactly the leaves the server accepts."""
    import re
    from pipeline.settings import CLIENT_SETTINGS
    js = open(os.path.join(os.path.dirname(__file__), "..", "static", "js", "studio.js")).read()
    block = js[js.index("const _ST_SETTINGS"):js.index("];", js.index("const _ST_SETTINGS"))]
    rows = set(re.findall(r"\['(\w+)', '(\w+)', '", block))
    assert rows == {(g, l) for g, leaves in CLIENT_SETTINGS.items() for l in leaves}


def test_step_run_without_settings_uses_the_standard(monkeypatch):
    """No client settings: Phase 1 receives None and starts from STANDARD_SETTINGS."""
    import io
    from pipeline.settings import STANDARD_SETTINGS, resolve_settings, with_standard_settings
    client, seen = _capture_phase1(monkeypatch)
    r = client.post("/api/step/run", content_type="multipart/form-data", data={
        "step_files[]": (io.BytesIO(b"ISO-10303-21;"), "a.step"), "labels[]": "a"})
    assert r.status_code == 200
    assert seen["settings"] is None
    resolved = resolve_settings(with_standard_settings(None))
    assert resolved["contact"]["fixed_value"] == STANDARD_SETTINGS["contact"]["fixed_value"] == 0.5
    assert resolved["interference"]["pixel_tol"] == 0.01


def test_client_values_override_single_standard_leaves():
    from pipeline.settings import resolve_settings, with_standard_settings
    resolved = resolve_settings(with_standard_settings({"interference": {"directions": "cardinal"}}))
    assert resolved["interference"]["directions"] == "cardinal"
    assert resolved["interference"]["reverse_check"] == "all"      # untouched standard leaf
    assert resolved["contact"]["method"] == "fixed"


def test_algorithms_endpoint_enumerates_registry():
    import app as A
    client = A.app.test_client()
    r = client.get("/api/pipeline/algorithms")
    assert r.status_code == 200
    j = r.get_json()
    assert set(j["algorithms"]["distance"]) == {"mesh", "exact"}
    assert set(j["algorithms"]["contact_threshold"]) == {"auto", "fixed", "manual"}
    assert "distance" in j["defaults"]
    assert j["code_defaults"]["interference"]["pixel_tol"] == 0.10
    assert j["standard"]["interference"]["pixel_tol"] == 0.01
    assert j["standard"]["contact"] == {"method": "fixed", "fixed_value": 0.5, "valley_jump": 3.0}


def test_aog_cap_override_reaches_engine():
    """A tightened aog.max_transitions must trip the explosion guard that the
    default would pass — proving the setting reaches generate_semantic_tables."""
    from pipeline.semantic import generate_semantic_tables
    n = 6
    labels = [f"P{i} ({chr(65 + i)})" for i in range(n)]
    ints = [np.zeros((n, n), dtype=int).tolist() for _ in range(6)]

    base = generate_semantic_tables([], labels, _star(n), ints, settings=None)
    assert base["success"] is True
    assert len(base["transitions"]) > 0

    capped = generate_semantic_tables([], labels, _star(n), ints,
                                      settings={"aog": {"max_transitions": 1}})
    assert capped["success"] is False
    assert "too large" in (capped.get("error") or "").lower()


def test_aog_candidate_pairs_cap_reaches_engine():
    """A tightened aog.max_candidate_pairs trips the in-loop AOG backstop (the
    cap behind the 'would generate N candidate pairs' message)."""
    from pipeline.semantic import generate_semantic_tables
    n = 6
    labels = [f"P{i} ({chr(65 + i)})" for i in range(n)]
    ints = [np.zeros((n, n), dtype=int).tolist() for _ in range(6)]
    res = generate_semantic_tables([], labels, _star(n), ints,
                                   settings={"aog": {"max_candidate_pairs": 1}})
    assert res["success"] is False
    assert "candidate pairs" in (res.get("error") or "").lower()


def test_invalid_setting_is_ignored_not_fatal():
    """A malformed setting must degrade to default, never crash the run."""
    from pipeline.semantic import generate_semantic_tables
    n = 4
    labels = [f"P{i} ({chr(65 + i)})" for i in range(n)]
    ints = [np.zeros((n, n), dtype=int).tolist() for _ in range(6)]
    res = generate_semantic_tables([], labels, _star(n), ints,
                                   settings={"aog": {"max_transitions": "lots"}})
    assert res["success"] is True  # bad value ignored, default cap applies


@requires_occ
def test_distance_switch_reproduces_golden():
    if not os.path.exists(_HYPO):
        pytest.skip("Hypothetical STEP not present")
    from pipeline.geometry import load_parts_from_assembly
    from pipeline.liaison_matrix import compute_contacts

    parts = [p for p, _, _ in load_parts_from_assembly(_HYPO)]
    mesh = compute_contacts(parts, settings={"distance": {"method": "mesh"}})
    exact = compute_contacts(parts, settings={"distance": {"method": "exact"}})
    default = compute_contacts(parts, settings=None)

    assert int(default["liaison_matrix"].sum()) // 2 == 9
    assert int(mesh["liaison_matrix"].sum()) // 2 == 9
    assert np.array_equal(mesh["liaison_matrix"], exact["liaison_matrix"])

    fixed = compute_contacts(parts, settings={"contact": {"method": "fixed",
                                                          "fixed_value": 0.5}})
    assert fixed["info"]["mode"] == "fixed"
    assert int(fixed["liaison_matrix"].sum()) // 2 == 9
