"""The six structural properties of the AND/OR graph hold for the sample products.

Runs scripts/check_aog_invariants.py on the three product JSON files in
sample_data/ (no database, no CAD kernel) and compares the result with the
stored records and with the graph sizes reported in the paper.
"""
import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "check_aog_invariants", os.path.join(ROOT, "scripts", "check_aog_invariants.py"))
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)

# The six properties in the order of the paper.
PROPERTIES = ["partition", "reduction", "connectedness", "unique_root", "closure",
              "reachability"]

SAMPLES = [
    ("sample_data/ballpoint_pen.json", "Prod_BallpointPen", 9, 13),
    ("sample_data/hypothetical_product.json", "Prod_HypotheticalProduct", 41, 114),
    ("sample_data/Centrifugal Pump/centrifugal_pump_product.json",
     "Prod_CentrifugalPump", 102, 340),
]


def _load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("path,pid,states,transitions", SAMPLES)
def test_invariants_hold_on_sample(path, pid, states, transitions):
    report = inv.check_invariants(_load(path), verbose=False)
    assert report["product"]["id"] == pid
    assert (report["states"], report["arcs"]) == (states, transitions)
    assert report["violations"] == {p: 0 for p in PROPERTIES}
    assert report["root_is_full_assembly"] is True
    assert report["states_without_transition"] == 0
    assert report["states_reached_from_root"] == states
    assert report["additional_checks"] == {"progress": 0}
    assert report["all_hold"] is True


@pytest.mark.parametrize("path,pid,states,transitions", SAMPLES)
def test_stored_record_matches_fresh_run(path, pid, states, transitions):
    report = inv.check_invariants(_load(path), verbose=False)
    assert _load(f"scripts/aog_invariants_{pid}.json") == report


@pytest.mark.parametrize("path,pid,states,transitions", SAMPLES)
def test_equivalence_record_matches_sample_graph(path, pid, states, transitions):
    """The stored equivalence record describes the graph in the sample file."""
    record = _load(f"scripts/aog_equivalence_{pid}.json")
    assert record["product"]["id"] == pid
    assert record["generator"] == {"states": states, "hyper_arcs": transitions,
                                   "transitions": transitions}
    assert record["knowledge_graph"] == {"states": states, "hyper_arcs": transitions}
    assert record["equivalent"] is True and all(record["checks"].values())


def _pen():
    return _load("sample_data/ballpoint_pen.json")


# One failing case per property (1 to 6), then the additional check.

def test_lost_part_violates_partition():
    data = _pen()
    t = data["transitions"][0]
    t["results_in"] = [t["results_in"][0]]
    report = inv.check_invariants(data, verbose=False)
    assert report["violations"]["partition"] == 1
    assert report["additional_checks"]["progress"] == 1
    assert report["all_hold"] is False


def test_result_as_large_as_source_violates_reduction():
    data = _pen()
    t = data["transitions"][0]
    t["results_in"] = [t["from_parts"], t["results_in"][1]]
    report = inv.check_invariants(data, verbose=False)
    assert report["violations"]["reduction"] == 1
    assert report["additional_checks"]["progress"] == 1
    assert report["all_hold"] is False


def test_missing_connections_violate_connectedness():
    data = _pen()
    data["connections"] = []
    report = inv.check_invariants(data, verbose=False)
    assert report["violations"]["connectedness"] == report["states"]
    assert report["all_hold"] is False


def test_root_that_is_not_the_full_assembly_violates_unique_root():
    """One root exists, but a part of the product is in no state."""
    data = _pen()
    data["components"].append({"partId": "Z", "name": "Unused part"})
    report = inv.check_invariants(data, verbose=False)
    assert report["root_is_full_assembly"] is False
    assert report["violations"]["unique_root"] == 1
    assert report["all_hold"] is False


def test_second_root_violates_unique_root():
    data = _pen()
    data["transitions"].append({"id": "TX", "from_parts": "XY",
                                "results_in": ["X", "Y"]})
    report = inv.check_invariants(data, verbose=False)
    assert report["violations"]["unique_root"] == 2
    assert report["all_hold"] is False


def test_state_without_transition_violates_closure():
    """A multi-part result that no transition takes apart fails closure."""
    data = _pen()
    root = data["transitions"][0]["from_parts"]
    data["transitions"] = [t for t in data["transitions"]
                           if t["from_parts"] == root]
    report = inv.check_invariants(data, verbose=False)
    assert report["violations"]["closure"] > 0
    assert report["violations"]["closure"] == report["states_without_transition"]
    assert report["all_hold"] is False


def test_state_off_the_root_violates_reachability():
    """A state that no path of transitions from the complete product reaches."""
    data = _pen()
    data["transitions"].append({"id": "TX", "from_parts": "XY",
                                "results_in": ["X", "Y"]})
    report = inv.check_invariants(data, verbose=False)
    assert report["violations"]["reachability"] == 1
    assert report["states_reached_from_root"] == report["states"] - 1
    # the other five properties except the root count are untouched
    assert report["violations"]["partition"] == 0
    assert report["violations"]["closure"] == 0
    assert report["all_hold"] is False


def test_single_result_fails_the_additional_progress_check():
    data = _pen()
    t = data["transitions"][0]
    t["results_in"] = [t["from_parts"]]
    report = inv.check_invariants(data, verbose=False)
    assert report["additional_checks"]["progress"] == 1
    assert report["violations"]["partition"] == 0
    assert report["violations"]["reduction"] == 1
    assert report["all_hold"] is False
