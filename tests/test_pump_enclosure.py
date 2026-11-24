"""Centrifugal pump: the impeller cannot leave a closed volute casing.

Guards two properties of the pump graph:

  * in every test direction the impeller is blocked by the volute casing or by
    its cover, and no transition separates the impeller from the volute casing
    while the cover is still mounted;
  * with the two fastener groups and the cap-nut rule the pump has 340
    transitions.

The test directions come from the mating surfaces (pipeline.settings.
STANDARD_SETTINGS); for the pump they are +-Y (shaft axis) and +-Z.

The pump STEP file is not distributed (GrabCAD terms of use, see
sample_data/Centrifugal Pump/MODEL_CHANGES.md); without it the tests are skipped.

requires_occ + slow: runs the full Phase 1 on the pump STEP.
"""
import os

import pytest

from conftest import requires_occ

pytestmark = [pytest.mark.integration, pytest.mark.slow, requires_occ]

_PUMP = "sample_data/Centrifugal Pump/centrifugal_pump.stp"


@pytest.fixture(scope="module")
def _phase1():
    if not os.path.exists(_PUMP):
        pytest.skip("the pump STEP file is not distributed "
                    "(see sample_data/Centrifugal Pump/MODEL_CHANGES.md)")
    from models.step_pipeline import check_occ_available, run_step_phase1
    available, err = check_occ_available()
    if not available:
        pytest.skip(f"OCC unavailable: {err}")
    res = run_step_phase1([_PUMP], ["Assembly"])
    assert res["success"], res.get("error")
    return res


def _idx(res, name):
    return next(i for i, l in enumerate(res["parts"]) if l.rsplit(" (", 1)[0] == name)


def _dir(res, vec):
    return [tuple(v) for v in res["interference_directions"]].index(vec)


def test_impeller_is_enclosed_by_casing_and_cover(_phase1):
    imp = _idx(_phase1, "Impeller")
    casing = _idx(_phase1, "Volute Casing")
    cover = _idx(_phase1, "Volute Casing Cover")
    ims = _phase1["interference_matrices"]
    assert sorted(map(tuple, _phase1["interference_directions"])) == sorted(
        [(0.0, 1.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)])
    for d, vec in enumerate(_phase1["interference_directions"]):
        assert ims[d][imp][casing] or ims[d][imp][cover], f"impeller free towards {vec}"
    # The cover sits on the +Y side of the impeller and must block it there.
    assert ims[_dir(_phase1, (0.0, 1.0, 0.0))][imp][cover] == 1
    # Test case 2: the casing cannot be pulled sideways off the enclosed impeller.
    for lateral in ((0.0, 0.0, 1.0), (0.0, 0.0, -1.0)):
        assert ims[_dir(_phase1, lateral)][casing][imp] == 1, lateral


def test_no_transition_separates_impeller_from_closed_casing(_phase1):
    from pipeline.fastener_detection import suggest_fastener_groups
    from pipeline.semantic import generate_semantic_tables

    labels, lm = _phase1["parts"], _phase1["liaison_matrix"]
    letter = {l.split(" (")[0]: l.rsplit("(", 1)[1].rstrip(")") for l in labels}
    cap_nut = next(i for i, l in enumerate(labels) if "Cap Nut" in l)
    # Configuration of the paper: the ten bolts are fasteners; the cap nut is a part,
    # held by the rule that shaft and impeller stay together while it is in place.
    fasteners = [i for i in _phase1["suggested_fasteners"] if i != cap_nut]
    groups = suggest_fastener_groups(fasteners, labels, lm)
    assert sorted(len(g["members"]) for g in groups) == [4, 6]   # 4x M12, 6x M20
    res = generate_semantic_tables(
        fastener_indices=fasteners, part_labels=labels, liaison_matrix=lm,
        interference_matrices=_phase1["interference_matrices"],
        precedence_rules={}, fastener_groups=groups,
        separation_precedence=[{"part1": letter["Shaft"], "part2": letter["Impeller"],
                                "requires_removed": [letter["M20 Cap Nut"]]}])
    assert res["success"], res.get("error")

    family = []
    for t in res["transitions"]:
        if all(p in t["from_parts"] for p in "ITA"):
            side = next(r for r in t["results_in"] if "I" in r)
            if "T" not in side:
                family.append(t)
    assert family == []
    # Two fastener groups, cap nut as a part with its rule: 340 transitions.
    assert len(res["transitions"]) == 340
