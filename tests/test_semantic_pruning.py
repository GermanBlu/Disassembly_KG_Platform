"""Phase-2 semantic pruning + reachability set-identity tests (OCC-free).

The golden tests check the 4-layer pruning and the reachability BFS in
pipeline/semantic.py as a black box (counts). These tests assert WHICH
transitions survive and cover the precedence / separation-precedence branches.
The hand-traced micro-assemblies pin the exact transition SET so
a regression in connectivity / single-break / disintegration / precedence logic
is caught immediately. No geometry — pure liaison + zero interference.
"""
import numpy as np

from pipeline.semantic import generate_semantic_tables


def _labels(n):
    return [f"P{i} ({chr(65 + i)})" for i in range(n)]


def _zero_interference(n):
    return [np.zeros((n, n), dtype=int).tolist() for _ in range(6)]


def _run(liaison, fastener_indices=(), precedence_rules=None, separation_precedence=None):
    n = len(liaison)
    return generate_semantic_tables(
        fastener_indices=list(fastener_indices),
        part_labels=_labels(n),
        liaison_matrix=liaison,
        interference_matrices=_zero_interference(n),
        precedence_rules=precedence_rules,
        separation_precedence=separation_precedence,
    )


def _keyset(transitions):
    return {
        (tuple(sorted(t["from_parts"])),
         tuple(sorted(tuple(sorted(r)) for r in t["results_in"])))
        for t in transitions
    }


# Liaison helpers (letters A=0, B=1, ...)
def _chain(n):
    """Path graph A-B-C-... (n parts, n-1 edges)."""
    lm = np.zeros((n, n), dtype=int)
    for i in range(n - 1):
        lm[i][i + 1] = lm[i + 1][i] = 1
    return lm.tolist()


def _star(n):
    """Star with hub A and n-1 leaves (no leaf-leaf edges)."""
    lm = np.zeros((n, n), dtype=int)
    for i in range(1, n):
        lm[0][i] = lm[i][0] = 1
    return lm.tolist()


# ── Linear chain: exact transition set ───────────────────────────────────────

def test_chain3_exact_set():
    """A-B-C, free interference → exactly 4 transitions, the connected single cuts."""
    res = _run(_chain(3))
    assert res["success"], res.get("error")
    got = _keyset(res["transitions"])
    expected = {
        (("A", "B", "C"), (("A",), ("B", "C"))),   # cut A-B
        (("A", "B", "C"), (("A", "B"), ("C",))),   # cut B-C
        (("A", "B"), (("A",), ("B",))),
        (("B", "C"), (("B",), ("C",))),
    }
    assert got == expected, f"unexpected set: {got ^ expected}"


def test_chain4_count_is_ten():
    """Path of 4 → sum of internal edges over all reachable sub-paths = 10."""
    res = _run(_chain(4))
    assert res["success"], res.get("error")
    assert len(res["transitions"]) == 10
    # every from-state must be a contiguous sub-path (connected)
    states = {t["from_parts"] for t in res["transitions"]}
    assert states == {"ABCD", "ABC", "BCD", "AB", "BC", "CD"}


def test_no_disconnected_split_is_emitted():
    """In a chain, a split whose side is disconnected (e.g. {B}|{A,C}) is never a
    transition — both AND-arc children must be connected."""
    res = _run(_chain(3))
    for t in res["transitions"]:
        for grp in t["results_in"]:
            # each result group is connected by construction of a chain cut:
            # a contiguous letter run. {A,C} (gap) must never appear.
            letters = sorted(grp)
            idxs = [ord(c) - 65 for c in letters]
            assert idxs == list(range(idxs[0], idxs[0] + len(idxs))), \
                f"disconnected result group leaked: {grp}"


# ── Star topology ────────────────────────────────────────────────────────────

def test_star_hub_removals():
    """Hub A with leaves B,C,D: from full state, each leaf detaches (single cut);
    no leaf-leaf connection exists so the only connections are A-leaf."""
    res = _run(_star(4))
    assert res["success"], res.get("error")
    full = [t for t in res["transitions"] if t["from_parts"] == "ABCD"]
    # three leaves → three single-leaf detachments from the full assembly
    removed = sorted(t.get("removed_part") for t in full)
    assert removed == ["B", "C", "D"]


# ── Precedence rule prunes specific transitions ──────────────────────────────

def test_precedence_rule_reduces_set():
    """precedence_rules {'C': ['A']} (C must stay with A unless A is removed alone)
    must prune at least one transition vs. the unconstrained run, and never add any."""
    base = _keyset(_run(_chain(3))["transitions"])
    ruled = _keyset(_run(_chain(3), precedence_rules={"C": ["A"]})["transitions"])
    assert ruled <= base                 # rules only remove, never add
    assert len(ruled) < len(base)        # and they remove something here


def test_separation_precedence_blocks_split():
    """separation_precedence: A and C may not separate while B present. In A-B-C
    the only states splitting A from C have B present, so all are blocked → the
    full assembly cannot disassemble and the reachable set collapses."""
    res = _run(
        _chain(3),
        separation_precedence=[{"part1": "A", "part2": "C", "requires_removed": ["B"]}],
    )
    assert res["success"], res.get("error")
    # ABCDEF? no — ABC: every cut separates A from C while B is present → all blocked
    from_full = [t for t in res["transitions"] if t["from_parts"] == "ABC"]
    assert from_full == [], "separation precedence failed to block A|C splits in ABC"


# ── Reachability filter ──────────────────────────────────────────────────────

def test_reachability_prunes_unreachable_states():
    """A transition whose from-state cannot be reached from the full assembly via
    valid transitions must be pruned. With separation precedence fully blocking
    ABC, no sub-state is reachable, so the transition list is empty."""
    res = _run(
        _chain(3),
        separation_precedence=[{"part1": "A", "part2": "C", "requires_removed": ["B"]}],
    )
    assert res["success"], res.get("error")
    assert res["transitions"] == []


# ── Fastener semantics ───────────────────────────────────────────────────────

def test_fastener_two_contact_makes_screwjoint():
    """A fastener F (index 2) touching exactly A and B yields one ScrewJoint
    connection A<->B with fastener=C, and suppresses a direct A-B PressFit."""
    # A-F, B-F contacts, plus a direct A-B contact that must be suppressed.
    lm = np.zeros((3, 3), dtype=int)
    A, B, F = 0, 1, 2
    lm[A][F] = lm[F][A] = 1
    lm[B][F] = lm[F][B] = 1
    lm[A][B] = lm[B][A] = 1
    res = _run(lm.tolist(), fastener_indices=[F])
    assert res["success"], res.get("error")
    screw = [c for c in res["connections"] if c["connectionType_id"] == "CT_ScrewJoint"]
    assert len(screw) == 1
    assert screw[0]["fastener_id"] == "C"
    assert {screw[0]["part1"], screw[0]["part2"]} == {"A", "B"}
    # no direct PressFit between the two secured parts
    pressfit_ab = [c for c in res["connections"]
                   if c["connectionType_id"] == "CT_PressFit"
                   and {c["part1"], c["part2"]} == {"A", "B"}]
    assert pressfit_ab == []
