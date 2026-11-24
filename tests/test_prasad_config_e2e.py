"""End-to-end check of the Prasad-faithful interference configuration (Hypothetical Product).

Configuration (all optional settings, defaults unchanged): contact threshold
0.5 mm (the platform's choice), test case 2 for
every pair, test directions from the common mating surfaces, pixels counted in
the bounding-box overlap (Prasad et al. 2022, Sections 2.1-3) and a 1 px
silhouette edge tolerance.

Pins:
  * the six test directions of Prasad's Table 9 (±shaft axis, ±Z, ±tube axis);
  * 34 transitions at 0 %, 1 % and 10 % pixel threshold (threshold-independent);
  * with one motion release for the end plate (it leaves in two steps: along the
    shaft, then sideways) exactly the 114 published reference transitions;
  * the same release derived automatically in Phase 1 (interference.two_step =
    "auto", pipeline.two_step): Phase 1 + Phase 2 with the standard settings
    (pipeline.settings.STANDARD_SETTINGS) give the 114 reference transitions
    without a hand-written rule.
requires_occ + slow (renders the interference pass).
"""
import json
import os
import re

import pytest

from conftest import requires_occ

pytestmark = [pytest.mark.integration, pytest.mark.slow, requires_occ]

_ASSEMBLY = ("sample_data/Hypothetical Product STEP/"
             "Hypothetical_Product_Passungen.step")
_FASTENER_PAT = re.compile(r"\b(screw|bolt|nut|washer|rivet|pin)\b", re.I)
_RELEASE = [{"part": "B", "direction": [0.0, -1.0, 0.0], "ignore": ["D", "E", "G"]}]




def _key(t):
    norm = lambda s: "".join(sorted(s))
    return norm(t["from_parts"]) + "->" + "|".join(sorted(norm(r) for r in t["results_in"]))


@pytest.fixture(scope="module")
def _phase1():
    if not os.path.exists(_ASSEMBLY):
        pytest.skip("Hypothetical assembly STEP not present")
    from models.step_pipeline import run_step_phase1
    p1 = run_step_phase1([os.path.abspath(_ASSEMBLY)], ["Assembly"], settings={
        "contact": {"method": "fixed", "fixed_value": 0.5},
        "interference": {"directions": "contact", "edge_px": 1, "reverse_check": "off",
                         "count_region": "overlap"}})
    assert p1["success"], p1.get("error")
    return p1


def _transitions(p1, tol, releases=()):
    import numpy as np
    from pipeline.interference import _reverse_check, apply_motion_releases
    from pipeline.part_ids import part_id
    from pipeline.semantic import generate_semantic_tables
    labels = p1["parts"]
    lm = np.array(p1["liaison_matrix"])
    vecs = [tuple(v) for v in p1["interference_directions"]]
    ratios = [np.array(r, dtype=float) for r in p1["interference_ratios"]]
    binary = [((r >= 0) & (r > np.where(lm == 1, tol, 0.0))).astype(int) for r in ratios]
    mats = _reverse_check(binary, vecs, lm, "all")
    mats = apply_motion_releases(mats, vecs, list(releases), [part_id(i) for i in range(len(labels))])
    res = generate_semantic_tables(
        fastener_indices=[i for i, l in enumerate(labels) if _FASTENER_PAT.search(l)],
        part_labels=labels, liaison_matrix=lm.tolist(),
        interference_matrices=[m.tolist() for m in mats], precedence_rules={})
    assert res["success"], res.get("error")
    return {_key(t) for t in res["transitions"]}


def test_contact_directions_are_prasads_six(_phase1):
    import numpy as np
    vecs = [np.array(v) for v in _phase1["interference_directions"]]
    tube = np.array([0.0, -0.574319, 0.818631])
    expected = [s * np.array(a) for a in ((0, 1, 0), (0, 0, 1), tube) for s in (1, -1)]
    assert len(vecs) == 6
    assert all(any(np.allclose(v, e, atol=1e-3) for v in vecs) for e in expected)


@pytest.mark.parametrize("tol", [0.0, 0.01, 0.10])
def test_prasad_config_is_threshold_independent(_phase1, tol):
    assert len(_transitions(_phase1, tol)) == 34


def test_end_plate_release_reproduces_reference(_phase1):
    ref = {_key(t) for t in json.load(open("sample_data/hypothetical_product.json"))["transitions"]}
    assert _transitions(_phase1, 0.0, _RELEASE) == ref


@pytest.fixture(scope="module")
def _pipeline():
    if not os.path.exists(_ASSEMBLY):
        pytest.skip("Hypothetical assembly STEP not present")
    from models.step_pipeline import run_step_phase1
    from pipeline.settings import STANDARD_SETTINGS
    p1 = run_step_phase1([os.path.abspath(_ASSEMBLY)], ["Assembly"], settings=STANDARD_SETTINGS)
    assert p1["success"], p1.get("error")
    return p1


def test_two_step_release_is_derived_automatically(_pipeline):
    rel = _pipeline["two_step_releases"]
    assert [(r["part"], r["direction"], r["ignore"]) for r in rel] == [
        (r["part"], r["direction"], r["ignore"]) for r in _RELEASE]
    assert rel[0]["min_shift"] == pytest.approx(15.0, abs=0.1)     # off the shaft end
    assert rel[0]["free_travel"] == pytest.approx(22.0, abs=0.1)   # up to the base plate
    assert rel[0]["second_move"] == [[0.0, 0.0, 1.0]]


def test_sample_assembly_is_overlap_free(_pipeline):
    assert _pipeline["volume_overlaps"] == []


def test_pipeline_reproduces_reference_without_hand_rule(_pipeline):
    from pipeline.semantic import generate_semantic_tables
    ref = {_key(t) for t in json.load(open("sample_data/hypothetical_product.json"))["transitions"]}
    res = generate_semantic_tables(
        fastener_indices=_pipeline["suggested_fasteners"], part_labels=_pipeline["parts"],
        liaison_matrix=_pipeline["liaison_matrix"],
        interference_matrices=_pipeline["interference_matrices"], precedence_rules={})
    assert res["success"], res.get("error")
    assert {_key(t) for t in res["transitions"]} == ref
