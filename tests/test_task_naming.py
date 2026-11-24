"""Task-naming rules of models/kg_builder._prepare_operational (DB-free).

The Holder↔Shaft task of the pipeline product must be named after the Shaft,
the moving part, not "Pull Off Holder". The removed part of the FIRST
transition breaking the connection is not a reliable source (for pipeline data
that can be the final "AH → A + H" split, whose removed_part is arbitrary).
Naming uses a MAJORITY vote over all breaking transitions, with an explicit
`task_name` on the connection as the human override (Studio review step).
"""
from models.kg_builder import _prepare_operational


def _data(connections, transitions):
    return {
        "product": {"id": "Prod_T", "name": "T"},
        "components": [
            {"partId": "A", "name": "Holder", "type": "Part"},
            {"partId": "B", "name": "End plate", "type": "Part"},
            {"partId": "H", "name": "Shaft", "type": "Part"},
        ],
        "connections": connections,
        "transitions": transitions,
    }


def _conn_ah(**extra):
    return {"id": "Conn_AH", "part1": "A", "part2": "H",
            "connectionType_id": "CT_PressFit",
            "agent_id": "Agent_HumanWorker", "tool_id": "Tool_None",
            "fastener_id": None, **extra}


def test_majority_vote_beats_first_transition():
    """First breaker removes A (final split), but the majority removes H —
    the task must be named after the Shaft."""
    transitions = [
        {"id": "T01", "from_parts": "AH", "results_in": ["A", "H"],
         "removed_part": "A", "broken_connection_id": "Conn_AH"},
        {"id": "T02", "from_parts": "ABH", "results_in": ["AB", "H"],
         "removed_part": "H", "broken_connection_id": "Conn_AH"},
        {"id": "T03", "from_parts": "ACH", "results_in": ["AC", "H"],
         "removed_part": "H", "broken_connection_id": "Conn_AH"},
    ]
    prep = _prepare_operational(_data([_conn_ah()], transitions))
    assert prep["conn_to_removed"]["Conn_AH"] == "H"
    assert prep["tasks"]["Conn_AH"]["dis_name"] == "Pull Off Shaft"


def test_tie_prefers_part2():
    transitions = [
        {"id": "T01", "removed_part": "A", "broken_connection_id": "Conn_AH", "results_in": []},
        {"id": "T02", "removed_part": "H", "broken_connection_id": "Conn_AH", "results_in": []},
    ]
    prep = _prepare_operational(_data([_conn_ah()], transitions))
    assert prep["conn_to_removed"]["Conn_AH"] == "H"  # part2 wins the tie


def test_fastener_priority_unchanged():
    conn = _conn_ah(id="Conn_AH_B", connectionType_id="CT_ScrewJoint", fastener_id="B")
    transitions = [
        {"id": "T01", "removed_part": "A", "broken_connection_id": "Conn_AH_B", "results_in": []},
    ]
    prep = _prepare_operational(_data([conn], transitions))
    assert prep["tasks"]["Conn_AH_B"]["dis_name"] == "Unscrew End plate"


def test_part2_fallback_without_transitions():
    prep = _prepare_operational(_data([_conn_ah()], []))
    assert prep["tasks"]["Conn_AH"]["dis_name"] == "Pull Off Shaft"


def test_explicit_task_name_override_wins():
    conn = _conn_ah(task_name="Pull Shaft out of Holder")
    transitions = [
        {"id": "T01", "removed_part": "A", "broken_connection_id": "Conn_AH", "results_in": []},
    ]
    prep = _prepare_operational(_data([conn], transitions))
    assert prep["tasks"]["Conn_AH"]["dis_name"] == "Pull Shaft out of Holder"


def test_authored_seed_names_stay_stable():
    """The seeded demo JSON authors removed_part=H on every Conn_AH breaker —
    majority voting gives the name of that part."""
    transitions = [
        {"id": f"T{i:03d}", "removed_part": "H", "broken_connection_id": "Conn_AH", "results_in": []}
        for i in range(1, 6)
    ]
    conn = _conn_ah(connectionType_id="CT_LooseFit")
    prep = _prepare_operational(_data([conn], transitions))
    assert prep["tasks"]["Conn_AH"]["dis_name"] == "Pick Shaft"


def test_auto_task_names_ignore_the_manual_name():
    """The Studio shows the automatic name as the suggestion, so a manual name
    on the connection must not leak into it (and the input stays untouched)."""
    from models.kg_builder import auto_task_names
    transitions = [{"id": "T01", "from_parts": "ABH", "results_in": ["AB", "H"],
                    "removed_part": "H", "broken_connection_id": "Conn_AH"}]
    data = _data([_conn_ah(task_name="Knock Out Shaft")], transitions)
    assert auto_task_names(data) == {"Conn_AH": "Pull Off Shaft"}
    assert data["connections"][0]["task_name"] == "Knock Out Shaft"


def test_task_names_endpoint():
    import app as A
    transitions = [{"id": "T01", "from_parts": "ABH", "results_in": ["AB", "H"],
                    "removed_part": "H", "broken_connection_id": "Conn_AH"}]
    client = A.app.test_client()
    r = client.post("/api/step/task-names", json=_data([_conn_ah()], transitions))
    assert r.status_code == 200
    assert r.get_json() == {"task_names": {"Conn_AH": "Pull Off Shaft"}}
    assert client.post("/api/step/task-names", json={"connections": [{"id": "X"}]}).status_code == 400
