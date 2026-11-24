"""Ballpoint Pen semantic verification, runs WITHOUT OpenCASCADE.

The Ballpoint is JSON-only KG data (no STEP geometry), so it exercises the
Phase-2 semantic engine, not the geometry path. Its 13 transitions are
hand-authored after Iwase (2025, Fig. 10) and encode the pen's physical disassembly *precedence* (cap and
button come off before the nested cartridge/ink can move).

Key fact established here: that precedence is NOT recoverable from the 5
connections alone — feeding the contact graph with free (zero) interference
yields a 44-transition SUPERSET. So the right invariant for the Ballpoint is
*consistency*: every authored transition must be a valid output of the semantic
engine (13 ⊆ engine output). If the engine's connectivity / single-break /
disintegration logic regresses, one of the 13 drops out and this fails.

(Reproducing exactly the 13 transitions requires the pen's interference and
precedence information, which is not part of the connection list.)
"""
import json
import os

import numpy as np

from pipeline.semantic import generate_semantic_tables

_BALLPOINT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "sample_data", "ballpoint_pen.json")


def _load():
    with open(_BALLPOINT) as f:
        return json.load(f)


def _transition_key(from_parts, results_in):
    return (tuple(sorted(from_parts)),
            tuple(sorted(tuple(sorted(r)) for r in results_in)))


def _authored_keys(data):
    keys = set()
    for t in data["transitions"]:
        fp = t["from_parts"]
        results = t.get("results_in")
        if not results:
            removed = t.get("removed_part", "")
            remaining = "".join(sorted(set(fp) - set(removed)))
            results = [remaining, removed] if remaining else [removed]
        keys.add(_transition_key(fp, results))
    return keys


def _run_engine(data):
    comps = data["components"]
    letters = [c["partId"] for c in comps]
    idx = {L: i for i, L in enumerate(letters)}
    n = len(comps)
    part_labels = [f"{c['name']} ({c['partId']})" for c in comps]

    lm = np.zeros((n, n), dtype=int)
    for conn in data["connections"]:
        i, j = idx[conn["part1"]], idx[conn["part2"]]
        lm[i][j] = lm[j][i] = 1

    interference = [np.zeros((n, n), dtype=int).tolist() for _ in range(6)]
    return generate_semantic_tables(
        fastener_indices=[],
        part_labels=part_labels,
        liaison_matrix=lm.tolist(),
        interference_matrices=interference,
    )


def test_ballpoint_data_shape():
    """Sanity: the fixture is the expected 6/5/13 ballpoint."""
    data = _load()
    assert data["product"]["id"] == "Prod_BallpointPen"
    assert len(data["components"]) == 6
    assert len(data["connections"]) == 5
    assert len(data["transitions"]) == 13


def test_ballpoint_authored_transitions_are_engine_valid():
    """Every hand-authored transition is a valid semantic-engine output.

    This is the consistency invariant: the engine, fed the ballpoint contact
    graph, must consider each of the 13 authored disassembly steps a legal
    (connected, single-connection-breaking) transition. 13 ⊆ engine output.
    """
    data = _load()
    res = _run_engine(data)
    assert res["success"], res.get("error")

    engine_keys = {
        _transition_key(t["from_parts"], t["results_in"]) for t in res["transitions"]
    }
    authored = _authored_keys(data)
    assert len(authored) == 13

    missing = authored - engine_keys
    assert not missing, (
        f"{len(missing)} authored ballpoint transition(s) are NOT producible by the "
        f"semantic engine — connectivity/disintegration logic regressed: {sorted(missing)}"
    )


def test_ballpoint_free_interference_is_strict_superset():
    """Connections alone over-generate.

    With zero interference the engine produces strictly more than 13 (the 13 are
    a precedence-pruned subset). This pins the behaviour so a future change that
    silently collapses it is noticed.
    """
    data = _load()
    res = _run_engine(data)
    assert res["success"], res.get("error")
    assert len(res["transitions"]) > 13


def test_ballpoint_authored_transitions_are_self_consistent():
    """Each authored transition must be internally consistent with its OWN
    connections: the broken_connection_id is exactly the joint severed by the
    split, and results_in are the connected components after the break.

    Validates the hand-authored JSON against the same helpers the pipeline uses
    (find_broken_connection / get_connected_components).
    """
    from pipeline.semantic import find_broken_connection, get_connected_components

    data = _load()
    conns = data["connections"]

    for t in data["transitions"]:
        from_parts = set(t["from_parts"])
        results = t.get("results_in")
        if not results:  # single-part-removal shorthand
            removed = set(t.get("removed_part", ""))
            results = ["".join(sorted(from_parts - removed)), "".join(sorted(removed))]

        # the from-state is one connected component
        assert len(get_connected_components(from_parts, conns)) == 1, \
            f"{t['from_parts']} is not semantically connected"

        # split into the first result group vs the rest
        side1 = set(results[0])
        side2 = from_parts - side1
        broken = find_broken_connection(side1, side2, conns)
        assert broken == t.get("broken_connection_id"), (
            f"{t['from_parts']} split {sorted(side1)}|{sorted(side2)}: "
            f"engine sees broken={broken}, JSON says {t.get('broken_connection_id')}"
        )

        # results_in are exactly the connected components of the two sides
        comps = get_connected_components(side1, conns) + get_connected_components(side2, conns)
        engine_groups = sorted("".join(sorted(c)) for c in comps)
        authored_groups = sorted("".join(sorted(r)) for r in results)
        assert engine_groups == authored_groups, (
            f"{t['from_parts']}: components {engine_groups} != results_in {authored_groups}"
        )
