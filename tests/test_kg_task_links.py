"""Knowledge-graph Stage 2: transition-to-task links and task names.

DB-free. The links exist only inside build_stage2_operational, so it runs
against a recorder in place of the Neo4j driver; names come from the pure
_prepare_operational. The tests pin two properties on cases reduced from the
pump: a step links to the task of every bundle it dissolves, and a task is
named after a part of its own connection.
"""
from models.kg_builder import _prepare_operational, build_stage2_operational


class _Recorder:
    """Driver, session, transaction and result in one: records every Cypher
    statement with its parameters and reports the Product node as present."""

    def __init__(self):
        self.calls = []

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_write(self, work):
        return work(self)

    def run(self, cypher, **params):
        self.calls.append((cypher, params))
        return self

    def single(self):
        return {"id": "Prod_T"}


def _conn(cid, part1, part2, ct, fastener=None):
    return {"id": cid, "part1": part1, "part2": part2, "connectionType_id": ct,
            "agent_id": "Agent_HumanWorker", "tool_id": "Tool_None", "fastener_id": fastener}


def _product(parts, connections, transitions, fasteners="", **extra):
    return {"product": {"id": "Prod_T", "name": "T"},
            "components": [{"partId": p, "name": n, "type": "Fastener" if p in fasteners else "Part"}
                           for p, n in parts.items()],
            "connections": connections, "transitions": transitions, **extra}


def _disassembled_by(data):
    """{transition id: [task ids]} as Stage 2 writes DISASSEMBLED_BY."""
    rec = _Recorder()
    build_stage2_operational(rec, data)
    links = {}
    for cypher, params in rec.calls:
        if "DISASSEMBLED_BY" in cypher:
            for e in params["edges"]:
                links.setdefault(e["tid"], []).append(e["dtid"])
    created = {t["tid"] for _, params in rec.calls for t in params.get("tasks", [])}
    assert {d for ds in links.values() for d in ds} <= created  # no link to a missing task
    return links


def test_a_step_links_to_the_task_of_every_bundle_it_dissolves():
    """One link per dissolved bundle: not only the first recorded connection's
    task, and not one per connection of the same bundle."""
    # Cover A is bolted onto housing B by bolts E and J (one bundle, one
    # unscrewing); shaft C runs loosely through A and is pressed into B.
    data = _product(
        {"A": "Cover", "B": "Housing", "C": "Shaft", "E": "Bolt_1", "J": "Bolt_2"},
        [_conn("Conn_AB_E", "A", "B", "CT_ScrewJoint", fastener="E"),
         _conn("Conn_AB_J", "A", "B", "CT_ScrewJoint", fastener="J"),
         _conn("Conn_AC", "A", "C", "CT_LooseFit"),
         _conn("Conn_BC", "B", "C", "CT_PressFit")],
        [  # pulling the shaft out dissolves two bundles ...
         {"id": "T01", "from_parts": "ABCEJ", "results_in": ["ABEJ", "C"], "removed_part": "C",
          "broken_connection_id": "Conn_AC", "broken_connection_ids": ["Conn_AC", "Conn_BC"]},
         # ... unscrewing the bolts dissolves two connections of one bundle
         {"id": "T02", "from_parts": "ABEJ", "results_in": ["A", "B", "E", "J"],
          "broken_connection_id": "Conn_AB_E", "broken_connection_ids": ["Conn_AB_E", "Conn_AB_J"]}],
        fasteners="EJ",
        connection_bundles={"Conn_AB_E": ["Conn_AB_E", "Conn_AB_J"],
                            "Conn_AC": ["Conn_AC"], "Conn_BC": ["Conn_BC"]},
    )
    links = _disassembled_by(data)
    assert sorted(links["T01"]) == ["Task_Dis_AC", "Task_Dis_BC"]
    assert links["T02"] == ["Task_Dis_Grp_Bolt"]


def test_task_is_named_after_a_part_of_its_own_connection():
    """The name vote counts only the connection's own parts: a cap nut set free
    in the same step must not name the gland half's task (for example
    "Pick M20 Cap Nut")."""
    # Reduced from the pump (a step of the form BFGIMNT -> N + BIT + FGM):
    # pulling the shaft F with end cap G out of the gland half B leaves the cap
    # nut N behind, loose. Neither side is a single part, so the builder takes
    # the first single-part result as the removed part: N, no endpoint of Conn_BF.
    data = _product(
        {"B": "Stuffing Box Gland Half_1", "F": "Shaft", "G": "Bearing End Cap 2",
         "N": "M20 Cap Nut", "T": "Volute Casing"},
        [_conn("Conn_BF", "B", "F", "CT_LooseFit"),
         _conn("Conn_BT", "B", "T", "CT_LooseFit"),
         _conn("Conn_FG", "F", "G", "CT_LooseFit"),
         _conn("Conn_FN", "F", "N", "CT_ScrewJoint")],
        [{"id": "T01", "from_parts": "BFGNT", "results_in": ["N", "BT", "FG"],
          "broken_connection_id": "Conn_BF", "broken_connection_ids": ["Conn_BF", "Conn_FN"]},
         {"id": "T02", "from_parts": "BFGN", "results_in": ["N", "B", "FG"],
          "broken_connection_id": "Conn_BF", "broken_connection_ids": ["Conn_BF", "Conn_FN"]},
         {"id": "T03", "from_parts": "BFG", "results_in": ["B", "FG"], "removed_part": "B",
          "broken_connection_id": "Conn_BF", "broken_connection_ids": ["Conn_BF"]}],
    )
    prep = _prepare_operational(data)
    for conn in data["connections"]:
        voted = prep["conn_to_removed"].get(conn["id"], conn["part2"])
        assert voted in (conn["part1"], conn["part2"], conn["fastener_id"]), conn["id"]
    assert prep["tasks"]["Conn_BF"]["dis_name"] == "Pick Stuffing Box Gland Half_1"
    assert prep["tasks"]["Conn_FN"]["dis_name"] == "Unscrew M20 Cap Nut"
