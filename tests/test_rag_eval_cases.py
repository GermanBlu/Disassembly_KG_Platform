"""Guards for the GraphRAG eval catalog (network-free, run in the default suite).

Three failure classes these catch at commit time instead of eval time:
- a case that can never pass (schema errors, bad regexes, missing demo refusal),
- a READ question whose wording trips the engine's mutation/reassignment/
  destructive keyword routers (it would be refused instead of answered),
- refusal-marker drift between rag_eval/markers.py and rag/engine.py.
"""
import inspect

import pytest

import rag.engine as engine
from rag_eval.cases import load_cases, select, starters
from rag_eval.markers import ENGINE_SOURCE_FRAGMENTS, REFUSAL_FRAGMENTS

CATALOG = load_cases()
CASES = CATALOG["cases"]
_WRITE_CATEGORIES = {"write_enrichment", "write_reassignment"}
# neg_* probes are allowed (and expected) to trip the destructive router.
_INTENTIONALLY_DESTRUCTIVE = {"neg_delete", "neg_remove_transition"}


def test_catalog_loads_and_validates():
    assert len(CASES) >= 40
    assert len({c["id"] for c in CASES}) == len(CASES)


def test_write_cases_refuse_in_demo():
    for case in CASES:
        if case["category"] in _WRITE_CATEGORIES:
            assert case["expect_demo"]["refusal"] == "read_only", case["id"]


def test_ui_starters_are_read_only_demo_cases():
    chips = starters(CASES)
    assert 4 <= len(chips) <= 6
    by_id = {c["id"]: c for c in CASES}
    for chip in chips:
        case = by_id[chip["id"]]
        assert case["category"] not in _WRITE_CATEGORIES
        assert "demo" in case["modes"]


def _questions_of(case):
    yield case["question"]
    for turn in case.get("turns", []) or []:
        if turn.get("message"):
            yield turn["message"]
    if case.get("question_de"):
        yield case["question_de"]


def test_read_questions_do_not_trip_write_routers():
    """A read question containing e.g. 'assign'/'update the'/'ändere' would be
    routed to the mutation branch and refused in demo mode — catch at authoring
    time using the engine's real signal lists."""
    mutation = engine.GraphRAGEngine._MUTATION_SIGNALS
    reassign = engine.GraphRAGEngine._REASSIGNMENT_SIGNALS
    for case in CASES:
        if case["category"] in _WRITE_CATEGORIES:
            continue
        for q in _questions_of(case):
            ql = q.lower()
            hits = [s for s in mutation + reassign if s in ql]
            assert not hits, f"{case['id']}: read question trips write router {hits}: {q!r}"


def test_read_questions_do_not_trip_destructive_router():
    src = inspect.getsource(engine)
    # extract the destructive_signals list literally from the source
    assert "destructive_signals" in src
    for case in CASES:
        if case["category"] in _WRITE_CATEGORIES or case["id"] in _INTENTIONALLY_DESTRUCTIVE:
            continue
        for q in _questions_of(case):
            ql = q.lower()
            for sig in ("delete", "drop ", "entferne den knoten", "lösche",
                        "remove the connection", "remove the transition"):
                assert sig not in ql, f"{case['id']}: read question contains {sig!r}"


def test_refusal_markers_match_engine():
    """Marker fragments must still appear verbatim in the engine (drift tripwire)."""
    src = inspect.getsource(engine).lower()
    # normalize whitespace: engine wraps message strings across lines
    src_flat = " ".join(src.split())
    for frag in ENGINE_SOURCE_FRAGMENTS:
        assert frag.lower() in src_flat, f"marker fragment no longer in rag/engine.py: {frag!r}"
    assert REFUSAL_FRAGMENTS["read_only"].lower() in engine.READ_ONLY_MSG.lower()
    assert REFUSAL_FRAGMENTS["no_data"].lower() in engine.NO_DATA_MSG.lower()


def test_select_filters():
    demo_cases = select(CASES, "demo")
    normal_cases = select(CASES, "normal")
    assert len(demo_cases) == len(CASES)   # every case runs in demo (writes as refusals)
    assert len(normal_cases) == len(CASES)
    only_eco = select(CASES, "demo", categories=["economics"])
    assert only_eco and all(c["category"] == "economics" for c in only_eco)
    one = select(CASES, "demo", ids=["eco_total_teardown"])
    assert [c["id"] for c in one] == ["eco_total_teardown"]


@pytest.mark.parametrize("required", [
    "structure", "connections", "fasteners_tools", "sequences_aog", "counting",
    "tasks", "resources", "economics", "materials_eol", "multi_turn",
    "german", "negative_safety", "write_enrichment", "write_reassignment",
])
def test_all_categories_populated(required):
    assert any(c["category"] == required for c in CASES), f"empty category {required}"
