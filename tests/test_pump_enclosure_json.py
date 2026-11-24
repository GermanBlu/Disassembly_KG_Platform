"""Centrifugal pump: no transition separates the impeller from the closed casing.

Checks the transition list of the shipped product file
sample_data/Centrifugal Pump/centrifugal_pump_product.json. The casing is
closed while the volute casing cover is mounted. For every transition that
starts from a state containing the impeller, the volute casing and the cover,
the result that contains the impeller must also contain the volute casing.

This is the same condition as in tests/test_pump_enclosure.py, which derives
the transitions from the pump STEP file. This test needs neither the STEP file
nor a CAD kernel.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRODUCT = os.path.join(ROOT, "sample_data", "Centrifugal Pump",
                        "centrifugal_pump_product.json")


def _load():
    with open(_PRODUCT, encoding="utf-8") as f:
        data = json.load(f)
    letter = {c["name"]: c["partId"] for c in data["components"]}
    return data, letter["Impeller"], letter["Volute Casing"], letter["Volute Casing Cover"]


def test_no_transition_separates_impeller_from_closed_casing():
    data, impeller, casing, cover = _load()
    assert len(data["transitions"]) == 340

    closed = [t for t in data["transitions"]
              if all(p in t["from_parts"] for p in (impeller, casing, cover))]
    # 108 of the 340 transitions start from a state with impeller, casing and cover.
    assert len(closed) == 108

    separating = []
    for t in closed:
        side = next(r for r in t["results_in"] if impeller in r)
        if casing not in side:
            separating.append(t["id"])
    assert separating == []


def test_impeller_leaves_the_casing_only_after_the_cover():
    """The check above is not vacuous: the impeller does leave the casing,
    in transitions that start from a state without the cover."""
    data, impeller, casing, cover = _load()
    leaving = [t for t in data["transitions"]
               if impeller in t["from_parts"] and casing in t["from_parts"]
               and casing not in next(r for r in t["results_in"] if impeller in r)]
    assert leaving
    assert all(cover not in t["from_parts"] for t in leaving)
