"""Bundle semantics of find_broken_connection (fasteners securing 2 and 3 parts).

A screwed joint dissolves only by unscrewing: the fastener on one side, every
still-present secured part together on the other. One physical unscrewing is
recorded against exactly one connection, and a fastener travelling with one of
its flanks dissolves nothing.
"""
from pipeline.semantic import find_broken_connection

# Fastener F clamps A, B and C (three pairwise connections, as the 3-contact
# branch creates them); fastener G secures exactly D and E (classic case).
CONNS = [
    {"id": "Conn_AB_F", "part1": "A", "part2": "B", "fastener_id": "F"},
    {"id": "Conn_AC_F", "part1": "A", "part2": "C", "fastener_id": "F"},
    {"id": "Conn_BC_F", "part1": "B", "part2": "C", "fastener_id": "F"},
    {"id": "Conn_DE_G", "part1": "D", "part2": "E", "fastener_id": "G"},
    {"id": "Conn_AD",   "part1": "A", "part2": "D", "fastener_id": None},
]
CANON = {"F": "Conn_AB_F", "G": "Conn_DE_G"}


def brk(s1, s2, canonical=CANON):
    return find_broken_connection(set(s1), set(s2), CONNS, canonical)


def test_unscrewing_three_part_bundle_is_one_connection():
    assert brk("F", "ABC") == "Conn_AB_F"
    assert brk("ABC", "F") == "Conn_AB_F"


def test_fastener_travelling_with_a_flank_dissolves_nothing():
    # {F,A} | {B,C}: F was not unscrewed — it still clamps A.
    assert brk("FA", "BC") is None
    assert brk("FB", "AC") is None
    assert brk("FC", "AB") is None


def test_bundle_with_absent_member_still_dissolves():
    # C already removed from the state: unscrewing F frees the remaining pair.
    assert brk("F", "AB") is None or brk("F", "AB") == "Conn_AB_F"
    assert brk("F", "AB") == "Conn_AB_F"


def test_two_part_fastener_matches_classic_rule():
    assert brk("G", "DE") == "Conn_DE_G"
    assert brk("GD", "E") is None
    assert brk("GE", "D") is None


def test_canonical_falls_back_to_smallest_id():
    assert find_broken_connection({"F"}, {"A", "B", "C"}, CONNS) == "Conn_AB_F"


def test_direct_joint_unchanged():
    assert brk("A", "D") == "Conn_AD"
    assert brk("AD", "E") is None


def test_unrelated_companion_on_fastener_side_is_allowed():
    # X is not part of F's joint; its presence beside F does not veto the
    # unscrewing (matches the classic rule's permissiveness).
    assert brk("FX", "ABC") == "Conn_AB_F"


# ── Fasteners clamping four or more parts ────────────────────────────────────
# There is no pairwise decomposition the bundle rule could attribute, so the
# pipeline must refuse the model rather than silently emit no connection and
# let the AOG pull the clamped parts apart.

def _star(n_clamped):
    """One fastener (A) touching `n_clamped` non-fastener parts."""
    n = n_clamped + 1
    labels = ["Bolt (A)"] + [f"Part{i} ({chr(66 + i)})" for i in range(n_clamped)]
    lm = [[0] * n for _ in range(n)]
    for j in range(1, n):
        lm[0][j] = lm[j][0] = 1
    return labels, lm, [[[0] * n for _ in range(n)] for _ in range(6)]


def _run(n_clamped):
    from pipeline.semantic import generate_semantic_tables
    labels, lm, ints = _star(n_clamped)
    return generate_semantic_tables(fastener_indices=[0], part_labels=labels,
                                    liaison_matrix=lm, interference_matrices=ints,
                                    estimate_only=True)


def test_fastener_clamping_four_parts_is_refused():
    res = _run(4)
    assert not res["success"]
    assert "contacts 4 non-fastener parts" in res["error"]
    assert res["connections"] == []


def test_error_names_the_fastener_and_the_parts():
    err = _run(5)["error"]
    assert "Bolt" in err
    assert "Part0" in err and "Part4" in err


def test_three_clamped_parts_still_accepted():
    """The boundary: 3 is the bundle rule's supported maximum."""
    res = _run(3)
    assert res["error"] is None
    assert len(res["connections"]) == 3
