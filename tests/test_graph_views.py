"""Guards for the graph-view API layer (DB-free).

Covers three properties:
- every UI view has a backend query (a view without one would silently fall
  back to "full"),
- condense_transitions() is pure post-processing and must preserve the AND/OR
  semantics exactly (only binary one-leaf removals collapse),
- the ?mode= query parameter must reach get_product_graph.
"""
import app as app_module
from models.product import _VIEW_QUERIES, condense_transitions

# Must match the tab list in static/app.html.
UI_VIEWS = {"structure", "precedence", "tasks", "resources", "connections",
            "reversibility", "full"}


def test_view_queries_cover_all_ui_views():
    missing = UI_VIEWS - set(_VIEW_QUERIES)
    assert not missing, (
        f"UI offers views without a backend query (would silently render 'full'): {missing}"
    )


# ── condense_transitions fixtures ────────────────────────────────────────────

def _node(eid, labels, name, **props):
    return {"id": eid, "labels": labels, "display": name,
            "properties": {"id": eid, "name": name, **props}}


def _edge(src, tgt, typ):
    return {"source": src, "target": tgt, "type": typ, "properties": {}}


def test_condense_binary_leaf_removal():
    """ABC -T1-> AB + C  (C is a Component)  becomes  ABC -REMOVES('C')-> AB."""
    nodes = [
        _node("abc", ["Assembly"], "ABC"),
        _node("ab", ["Assembly"], "AB"),
        _node("c", ["Component"], "Screw C"),
        _node("t1", ["Transition"], "ABC → AB + C"),
    ]
    edges = [
        _edge("t1", "abc", "TRANSFORMS"),
        _edge("t1", "ab", "RESULTS_IN"),
        _edge("t1", "c", "RESULTS_IN"),
    ]
    out_nodes, out_edges = condense_transitions(nodes, edges)

    assert [e["type"] for e in out_edges] == ["REMOVES"]
    rem = out_edges[0]
    assert rem["source"] == "abc" and rem["target"] == "ab"
    assert rem["label"] == "− Screw C"
    assert rem["properties"]["removed_part"] == "Screw C"
    assert rem["properties"]["removed_id"] == "c"
    assert rem["properties"]["transition_id"] == "t1"
    ids = {n["id"] for n in out_nodes}
    assert "t1" not in ids
    assert "c" not in ids, "orphaned removed leaf must be dropped"
    assert {"abc", "ab"} <= ids


def test_condense_keeps_and_arcs():
    """A transition with three results (AND-arc) keeps its node and edges."""
    nodes = [
        _node("abc", ["Assembly"], "ABC"),
        _node("a", ["Component"], "A"),
        _node("b", ["Component"], "B"),
        _node("c", ["Component"], "C"),
        _node("t1", ["Transition"], "ABC → A + B + C"),
    ]
    edges = [
        _edge("t1", "abc", "TRANSFORMS"),
        _edge("t1", "a", "RESULTS_IN"),
        _edge("t1", "b", "RESULTS_IN"),
        _edge("t1", "c", "RESULTS_IN"),
    ]
    out_nodes, out_edges = condense_transitions(nodes, edges)
    assert len(out_nodes) == 5 and len(out_edges) == 4
    assert {e["type"] for e in out_edges} == {"TRANSFORMS", "RESULTS_IN"}


def test_condense_keeps_both_leaf_split():
    """GH -> G + H (both Components) keeps its transition node."""
    nodes = [
        _node("gh", ["Assembly"], "GH"),
        _node("g", ["Component"], "G"),
        _node("h", ["Component"], "H"),
        _node("t1", ["Transition"], "GH → G + H"),
    ]
    edges = [
        _edge("t1", "gh", "TRANSFORMS"),
        _edge("t1", "g", "RESULTS_IN"),
        _edge("t1", "h", "RESULTS_IN"),
    ]
    out_nodes, out_edges = condense_transitions(nodes, edges)
    assert len(out_nodes) == 4 and len(out_edges) == 3


def test_condense_carries_destructiveness():
    """A reversibility annotation on the transition lands on the REMOVES edge."""
    nodes = [
        _node("abc", ["Assembly"], "ABC"),
        _node("ab", ["Assembly"], "AB"),
        _node("c", ["Component"], "C"),
        _node("t1", ["Transition"], "ABC → AB + C", destructiveness="Non-destructive"),
    ]
    edges = [
        _edge("t1", "abc", "TRANSFORMS"),
        _edge("t1", "ab", "RESULTS_IN"),
        _edge("t1", "c", "RESULTS_IN"),
    ]
    _, out_edges = condense_transitions(nodes, edges)
    assert out_edges[0]["properties"]["destructiveness"] == "Non-destructive"


def test_condense_ignores_fastener_survivor_pairing():
    """Fastener carries a Component label too — removing it must condense."""
    nodes = [
        _node("abc", ["Assembly"], "ABC"),
        _node("ab", ["Assembly"], "AB"),
        _node("f", ["Component", "Fastener"], "M8 screw"),
        _node("t1", ["Transition"], "ABC → AB + F"),
    ]
    edges = [
        _edge("t1", "abc", "TRANSFORMS"),
        _edge("t1", "ab", "RESULTS_IN"),
        _edge("t1", "f", "RESULTS_IN"),
    ]
    _, out_edges = condense_transitions(nodes, edges)
    assert [e["type"] for e in out_edges] == ["REMOVES"]
    assert out_edges[0]["properties"]["removed_part"] == "M8 screw"


def test_api_graph_passes_view_and_mode(monkeypatch):
    """?view= and ?mode= must be forwarded to get_product_graph."""
    seen = {}

    def fake_graph(driver, product_id, view="full", mode=None):
        seen.update(product_id=product_id, view=view, mode=mode)
        return {"nodes": [], "edges": []}

    monkeypatch.setattr(app_module, "get_product_graph", fake_graph)
    monkeypatch.setattr(app_module, "get_driver", lambda: None)

    client = app_module.app.test_client()
    resp = client.get("/api/products/P1/graph?view=precedence&mode=condensed")
    assert resp.status_code == 200
    assert seen == {"product_id": "P1", "view": "precedence", "mode": "condensed"}
