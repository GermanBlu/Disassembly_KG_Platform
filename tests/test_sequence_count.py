"""Counting complete disassembly sequences and their orders of execution.

A complete disassembly sequence is a tree of transitions from the complete
product down to single components (models.product._sequence_count). Its
transitions can be executed in several linear orders when branches are
independent (models.product._ordering_counts). A transition may release several
parts at once, so complete sequences from one state can differ in length; the
interleaving of parallel sub-sequences is counted per length combination.
"""
import json
import os

import pytest

from models.product import _ordering_counts, _sequence_count, count_sequences

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _by_from(transitions):
    out = {}
    for t in transitions:
        out.setdefault("".join(sorted(t["from_parts"])), []).append(
            {"results_in": ["".join(sorted(r)) for r in t["results_in"]]})
    return out


def _sample(path):
    data = json.load(open(os.path.join(ROOT, path)))
    comps = {c["partId"] for c in data["components"]}
    return _by_from(data["transitions"]), comps, "".join(sorted(comps))


def test_parallel_branches_of_different_length():
    # AB comes apart in one step; CDE either in one step or in two (CDE -> C + DE -> D + E).
    trans = _by_from([
        {"from_parts": "ABCDE", "results_in": ["AB", "CDE"]},
        {"from_parts": "AB", "results_in": ["A", "B"]},
        {"from_parts": "CDE", "results_in": ["C", "D", "E"]},
        {"from_parts": "CDE", "results_in": ["C", "DE"]},
        {"from_parts": "DE", "results_in": ["D", "E"]},
    ])
    comps = set("ABCDE")
    # 3 steps: 2 orderings of {AB split, CDE split}; 4 steps: 3 orderings of AB split among CDE's two steps
    assert _ordering_counts("ABCDE", trans, comps, {}) == {3: 2, 4: 3}
    # two trees: CDE in one step, or CDE in two steps
    assert _sequence_count("ABCDE", trans, comps, {}) == 2
    assert count_sequences("ABCDE", trans, comps) == {
        "sequence_count": 2, "ordering_count": 5,
        "ordering_count_by_steps": {"3": 2, "4": 3}, "min_steps": 3, "max_steps": 4}


def test_dead_end_counts_nothing():
    # BC has no transition, so the only transition of the root leads nowhere.
    trans = _by_from([{"from_parts": "ABC", "results_in": ["A", "BC"]}])
    result = count_sequences("ABC", trans, set("ABC"))
    assert result["sequence_count"] == 0
    assert result["ordering_count"] == 0


SAMPLES = (
    # path, complete sequences, orders of execution, transitions per sequence
    ("sample_data/ballpoint_pen.json", 6, 12, 5),
    ("sample_data/hypothetical_product.json", 284, 360, 6),
    ("sample_data/Centrifugal Pump/centrifugal_pump_product.json", 124_693, 8_883_888, 13),
)


@pytest.mark.parametrize("path,sequences,orderings,steps", SAMPLES)
def test_sample_products(path, sequences, orderings, steps):
    trans, comps, root = _sample(path)
    result = count_sequences(root, trans, comps)
    assert result["sequence_count"] == sequences
    assert result["ordering_count"] == orderings
    assert result["ordering_count_by_steps"] == {str(steps): orderings}
    assert result["min_steps"] == result["max_steps"] == steps
