"""Phase 2 step semantics: fastener joints, duplicates and dissolved connections.

Synthetic assemblies with no geometric blocking, so only the semantic rules
decide. Each test pins one rule on a case reduced from the pump.
"""
import numpy as np

from pipeline.semantic import generate_semantic_tables


def _run(labels, contacts, fasteners, **kw):
    n = len(labels)
    lm = np.zeros((n, n), dtype=int)
    for i, j in contacts:
        lm[i][j] = lm[j][i] = 1
    free = [np.zeros((n, n), dtype=int).tolist() for _ in range(6)]
    res = generate_semantic_tables(fastener_indices=fasteners, part_labels=labels,
                                   liaison_matrix=lm.tolist(), interference_matrices=free,
                                   precedence_rules={}, **kw)
    assert res["success"], res.get("error")
    return res


def test_fastener_joint_is_not_separated_while_a_second_joint_breaks():
    # Plates A and B clamped by screw S; part P sits on both plates directly.
    # Splitting {A, S} from {B, P} pulls B off the screw while S still holds it,
    # and also breaks the direct joint A–P. Mechanically infeasible
    # (Homem de Mello & Sanderson 1991): the screw has to go first.
    labels = ["Plate A (A)", "Plate B (B)", "Screw (C)", "Part P (D)"]
    res = _run(labels, [(0, 1), (0, 2), (1, 2), (0, 3), (1, 3)], fasteners=[2])
    for t in res["transitions"]:
        groups = [set(r) for r in t["results_in"]]
        screw_with_one_plate = any("C" in g and ("A" in g) != ("B" in g) for g in groups)
        assert not screw_with_one_plate, t
    assert res["rule_stats"]["torn_fastener_joints"] > 0


def test_different_removals_breaking_the_same_first_joint_are_both_kept():
    # Three mutually touching parts: taking out X and taking out Y both break
    # the joint X–Y first. They are different steps and must both survive.
    labels = ["X (A)", "Y (B)", "Z (C)"]
    res = _run(labels, [(0, 1), (0, 2), (1, 2)], fasteners=[])
    from_full = {tuple(sorted(t["results_in"])) for t in res["transitions"] if t["from_parts"] == "ABC"}
    assert from_full == {("A", "BC"), ("AC", "B"), ("AB", "C")}
    assert res["rule_stats"]["duplicates"] == 0


def test_a_step_records_every_dissolved_connection():
    labels = ["X (A)", "Y (B)", "Z (C)"]
    res = _run(labels, [(0, 1), (0, 2), (1, 2)], fasteners=[])
    step = next(t for t in res["transitions"]
                if t["from_parts"] == "ABC" and sorted(t["results_in"]) == ["A", "BC"])
    assert sorted(step["broken_connection_ids"]) == ["Conn_AB", "Conn_AC"]
    assert step["broken_connection_id"] == step["broken_connection_ids"][0]


def test_nut_on_threaded_part_via_separation_rule():
    # Nut N screwed on shaft F holds hub H, which also sits on F. Modelled as a
    # plain part plus the rule "F and H not separated while N is present".
    labels = ["Shaft (A)", "Hub (B)", "Nut (C)"]
    res = _run(labels, [(0, 1), (0, 2), (1, 2)], fasteners=[],
               separation_precedence=[{"part1": "A", "part2": "B", "requires_removed": ["C"]}])
    for t in res["transitions"]:
        if "C" in t["from_parts"]:
            groups = [set(r) for r in t["results_in"]]
            assert not any(("A" in g) != ("B" in g) and "C" not in g for g in groups if "A" in g or "B" in g) \
                or ["C"] in [sorted(r) for r in t["results_in"]], t
    first = {tuple(sorted(t["results_in"])) for t in res["transitions"] if t["from_parts"] == "ABC"}
    assert ("AB", "C") in first
