"""End-to-end golden test for the Hypothetical Product.

Runs the FULL Phase-1→Phase-2 chain on the assembly STEP exactly as the platform
does (Phase 1 with STANDARD_SETTINGS: contacts, test directions from the contact
surfaces, both test cases, two-step removals; then fastener semantics, AOG and
pruning) and pins the counts:

    Phase 1  → 8 parts, 9 contacts, 2 fasteners, 6 test directions, 1 two-step
               removal (the end plate)
    Phase 2  → 6 connections, 114 transitions and 41 assembly states without
               any precedence rule. The geometric AND/OR graph before the
               semantic checks has 70 nodes (8 single parts and 62
               subassemblies); the log line "AOG: 70 reachable nodes" reports
               that number.
    The separation rule (H and A separate only after B) prunes nothing.

Mirrors seed_benchmark.py so the documented 114 invariant has a real guard.
requires_occ + slow (runs the GPU interference pass).
"""
import os
import re

import pytest

from conftest import requires_occ

pytestmark = [pytest.mark.integration, pytest.mark.slow, requires_occ]

_ASSEMBLY = ("sample_data/Hypothetical Product STEP/"
             "Hypothetical_Product_Passungen.step")
_FASTENER_PAT = re.compile(r"\b(screw|bolt|nut|washer|rivet|pin)\b", re.I)


@pytest.fixture(scope="module")
def _phase1():
    if not os.path.exists(_ASSEMBLY):
        pytest.skip("Hypothetical assembly STEP not present")
    from models.step_pipeline import run_step_phase1
    p1 = run_step_phase1([os.path.abspath(_ASSEMBLY)], ["Assembly"])
    assert p1["success"], p1.get("error")
    fasteners = [i for i, l in enumerate(p1["parts"]) if _FASTENER_PAT.search(l)]
    return p1, fasteners


def _generate(p1, fasteners, **kw):
    from pipeline.semantic import generate_semantic_tables
    res = generate_semantic_tables(fastener_indices=fasteners, part_labels=p1["parts"],
                                   liaison_matrix=p1["liaison_matrix"],
                                   interference_matrices=p1["interference_matrices"], **kw)
    assert res["success"], res.get("error")
    return res


def test_phase1_geometry_golden(_phase1):
    p1, fasteners = _phase1
    assert len(p1["parts"]) == 8
    assert sum(sum(row) for row in p1["liaison_matrix"]) // 2 == 9
    # The two M8 cap screws (C, F) are the auto-detected fasteners.
    assert len(fasteners) == 2
    assert len(p1["interference_directions"]) == 6
    assert [r["part"] for r in p1["two_step_releases"]] == ["B"]
    assert p1["volume_overlaps"] == []


def test_phase2_without_rules_is_114(_phase1):
    """THE Golden invariant: 114 transitions, no precedence rule."""
    p1, fasteners = _phase1
    res = _generate(p1, fasteners, precedence_rules={})
    assert len(res["transitions"]) == 114
    assert len(res["connections"]) == 6
    aog_nodes = next((int(m.group(1)) for m in
                      (re.search(r"AOG: (\d+) reachable nodes", line)
                       for line in res["log"]) if m), None)
    assert aog_nodes == 70


def test_end_plate_separation_rule_prunes_nothing(_phase1):
    p1, fasteners = _phase1
    res = _generate(p1, fasteners,
                    separation_precedence=[{"part1": "H", "part2": "A", "requires_removed": ["B"]}])
    assert len(res["transitions"]) == 114
