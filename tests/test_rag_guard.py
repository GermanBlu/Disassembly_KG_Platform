"""The destructive-request guard must not fire on disassembly vocabulary.

"remove" is core domain language in a disassembly knowledge graph — questions
like "which parts can be removed first?" are reads, not graph mutations. The
authoritative protection is _execute_cypher(), which rejects any generated
query containing a write keyword; this pre-filter only catches explicit intent
to mutate the graph itself.

A plain substring blocklist on "remove" would refuse such questions.
"""
import re

import pytest

# The guard is a literal list inside GraphRAGEngine.ask(); read it from source
# so the test needs neither a database nor an API key.
import rag.engine as engine_mod


def _destructive_signals():
    src = open(engine_mod.__file__).read()
    block = re.search(r"destructive_signals\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert block, "destructive_signals list not found in rag/engine.py"
    return [s.lower() for s in re.findall(r'"([^"]*)"', block.group(1))]


def _blocked(question):
    q = question.lower()
    return any(sig in q for sig in _destructive_signals())


DOMAIN_QUESTIONS = [
    "Which parts can be removed first from the fully assembled product?",
    "Which connections must be dissolved to remove the impeller?",
    "Which transitions remove the End plate?",
    "In which order are the M20 bolts removed?",
    "Welche Bauteile werden zuerst entfernt?",
]

GRAPH_MUTATIONS = [
    "Delete the Impeller node",
    "detach delete all transitions",
    "Remove the node Comp_A",
    "Remove all connections from the graph",
    "drop the database",
    "Lösche das Produkt aus dem Graphen",
]


@pytest.mark.parametrize("q", DOMAIN_QUESTIONS)
def test_domain_questions_are_not_blocked(q):
    assert not _blocked(q), f"disassembly question wrongly refused: {q!r}"


@pytest.mark.parametrize("q", GRAPH_MUTATIONS)
def test_graph_mutations_are_blocked(q):
    assert _blocked(q), f"destructive graph request slipped through: {q!r}"


def test_cypher_layer_still_blocks_writes():
    """The real enforcement: no generated query may contain a write keyword."""
    src = open(engine_mod.__file__).read()
    exec_fn = src[src.index("def _execute_cypher"):]
    exec_fn = exec_fn[:exec_fn.index("\n    def ", 1)] if "\n    def " in exec_fn[1:] else exec_fn
    for kw in ("CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP", "DETACH"):
        assert f'"{kw}"' in exec_fn, f"_execute_cypher no longer blocks {kw}"
    # The keywords must be matched on word boundaries, not as substrings —
    # otherwise removed_part (REMOVE) and created_at (CREATE) block reads.
    assert r"\b{kw}\b" in exec_fn, "_execute_cypher lost its word-boundary match"


# ── The authoritative guard: _execute_cypher() ───────────────────────────────
# Exercises the real method rather than re-deriving its regex, so a regression
# in the guard itself is caught. A bare substring test blocks legitimate reads:
# `removed_part` contains REMOVE, `created_at` contains CREATE.

class _FakeResult(list):
    def __iter__(self):
        return iter([])


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher):
        return _FakeResult()


class _FakeDriver:
    def session(self):
        return _FakeSession()


def _engine():
    """A GraphRAGEngine with only the attributes _execute_cypher touches."""
    from rag.engine import GraphRAGEngine
    eng = GraphRAGEngine.__new__(GraphRAGEngine)
    eng.driver = _FakeDriver()
    return eng


READ_QUERIES_WITH_WRITE_SUBSTRINGS = [
    "MATCH (t:Transition) WHERE t.removed_part = 'N' RETURN t.id",
    "MATCH (t:Transition) RETURN t.removed_part, t.id ORDER BY t.id",
    "MATCH (n) WHERE n.created_at IS NOT NULL RETURN n.created_at",
]

REAL_WRITES = [
    "MATCH (n) DETACH DELETE n",
    "MERGE (n:X) RETURN n",
    "MATCH (n) SET n.x = 1 RETURN n",
    "MATCH (n) REMOVE n.x RETURN n",
    "CREATE (n:X) RETURN n",
    "DROP INDEX foo",
]


@pytest.mark.parametrize("cypher", READ_QUERIES_WITH_WRITE_SUBSTRINGS)
def test_read_query_with_write_substring_is_allowed(cypher):
    _rows, err = _engine()._execute_cypher(cypher)
    assert err is None, f"legitimate read was blocked: {cypher} -> {err}"


@pytest.mark.parametrize("cypher", REAL_WRITES)
def test_real_write_is_blocked(cypher):
    rows, err = _engine()._execute_cypher(cypher)
    assert rows is None and err and "blocked" in err.lower(), cypher


# ── Write guards of the two write paths ──────────────────────────────────────
# check_enrichment_query() and check_reassignment_query() are the code checks
# that every generated write query passes before it reaches Neo4j.

from rag.engine import check_enrichment_query, check_reassignment_query

PID = "Prod_X"

ENRICHMENT_ALLOWED = [
    # the two enrichment queries of the recorded evaluation runs (H30, H31)
    "MATCH (dt:DisassemblyTask {product_id: 'Prod_EvalScratchHP'})\n"
    "WHERE toLower(dt.name) CONTAINS 'end plate'\n"
    "SET dt.estimated_duration_seconds = 45\n"
    "RETURN dt.id AS id, dt.name AS name, properties(dt) AS props",
    "MATCH (n:Component {product_id: 'Prod_EvalScratchHP'})\n"
    "WHERE toLower(n.name) CONTAINS 'holder'\n"
    "SET n.material = 'aluminum'\n"
    "RETURN n.id AS id, n.name AS name, properties(n) AS props",
    # several assignments in one clause
    f"MATCH (n:Component {{product_id: '{PID}'}}) WHERE toLower(n.name) CONTAINS 'tube'\n"
    "SET n.toxicity = 'high', n.recyclable = false\nRETURN n.id AS id",
    # map form with literal keys
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n += {{mass_g: 140, material: 'PP'}} RETURN n.id",
    # bulk form of the enrichment prompt
    "UNWIND [\n  {partId: 'D', props: {mass_g: 140, material: 'PP'}},\n"
    "  {partId: 'A', props: {mass_g: 240, material: 'Al'}}\n] AS row\n"
    f"MATCH (n:Component {{product_id: '{PID}'}})\nWHERE n.partId = row.partId\n"
    "SET n += row.props\nRETURN n.id AS id, n.name AS name, properties(n) AS props",
    # protected names inside values or as part of longer keys are no violation
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.note = 'SET n.id = 5; DELETE' RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.supplier_name = 'ACME', n.created_by = 'x' RETURN n.id",
    f"MATCH (t:Transition {{product_id: '{PID}'}})-[:TRANSFORMS]->(a:Assembly {{product_id: '{PID}', isRoot: true}})\n"
    "SET t.estimated_duration_seconds = 30\nRETURN t.id AS id",
]

ENRICHMENT_REJECTED = [
    # protected properties, in every spelling of the assignment
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.id = 'X' RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.id='X' RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}})\nSET\n  n . name = 'X' RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.`partId` = 'Z' RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.material = 'PP', n.product_id = 'Other' RETURN n.id",
    f"MATCH (n:Assembly {{product_id: '{PID}'}}) SET n.isRoot = true RETURN n.id",
    f"MATCH (n:Assembly {{product_id: '{PID}'}}) SET n.isState = false RETURN n.id",
    f"MATCH (n:DisassemblyTask {{product_id: '{PID}'}}) SET n.taskType = 'Assembly' RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n += {{material: 'PP', name: 'X'}} RETURN n.id",
    "UNWIND [{partId: 'D', props: {material: 'PP', id: 'Comp_Z'}}] AS row\n"
    f"MATCH (n:Component {{product_id: '{PID}'}}) WHERE n.partId = row.partId SET n += row.props RETURN n.id",
    # forms whose keys cannot be read, or that replace all properties
    f"UNWIND [{{partId: 'D', material: 'PP'}}] AS row MATCH (n:Component {{product_id: '{PID}'}}) SET n += row RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n += $props RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n = {{material: 'PP'}} RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n:Agent RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n['id'] = 'X' RETURN n.id",
    # shared library nodes and relationships
    "MATCH (a:Agent) WHERE a.id = 'Agent_Human' SET a.cost = 1 RETURN a.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[:USES_TOOL]->(x:Tool) SET x.cost = 1 RETURN x.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[:PERFORMED_BY]->(x) SET x.cost = 1 RETURN x.id",
    f"MATCH (x)<-[:REQUIRES]-(t:DisassemblyTask {{product_id: '{PID}'}}) SET x.level = 2 RETURN x.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:USES_TOOL]->(:Tool) SET r.since = 1 RETURN t.id",
    # structural operations and queries without SET
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.material = 'PP' WITH n DETACH DELETE n",
    f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.material = 'PP' CREATE (m:Component) RETURN n.id",
    f"MERGE (n:Component {{product_id: '{PID}', id: 'Comp_New'}}) SET n.material = 'PP' RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) REMOVE n.material RETURN n.id",
    f"MATCH (n:Component {{product_id: '{PID}'}}) RETURN n.id",
]

REASSIGNMENT_ALLOWED = [
    # the pattern of the reassignment prompt
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(:Agent)\n"
    "WHERE toLower(t.name) CONTAINS 'snap out button'\n"
    "MATCH (new_a:Agent) WHERE toLower(new_a.name) CONTAINS 'robot'\n"
    "DELETE r\nWITH t, new_a\nCREATE (t)-[:PERFORMED_BY]->(new_a)\n"
    "RETURN t.id AS task_id, t.name AS task_name, new_a.id AS agent_id, new_a.name AS agent_name",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})\n  WHERE toLower(t.name) CONTAINS 'drain ink'\n"
    "MATCH (t)-[r:USES_TOOL]->(:Tool)\nDELETE r\nWITH t\n"
    "MATCH (tool:Tool {id: 'Tool_Tweezers'})\nCREATE (t)-[:USES_TOOL]->(tool)\n"
    "RETURN t.id AS id, t.name AS name",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:REQUIRES]->(:Skill) MATCH (s:Skill {{id: 'Skill_Pull'}}) "
    "DELETE r WITH t, s CREATE (t)-[:REQUIRES]->(s) RETURN t.id",
]

REASSIGNMENT_REJECTED = [
    # an allowed name somewhere in the query is not enough
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:ACTS_ON]->(c) DELETE r RETURN t.id // PERFORMED_BY",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(:Agent), (t)-[x:ACTS_ON]->() "
    "DELETE r, x RETURN t.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(a:Agent) MATCH (c:Connection {{product_id: '{PID}'}}) "
    "DELETE r WITH t, c CREATE (t)-[:ACTS_ON]->(c) RETURN t.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r]->(a:Agent) DELETE r RETURN t.id",
    # nodes are neither deleted nor created
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(a:Agent) DELETE r, a RETURN t.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(a:Agent) DELETE t RETURN a.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(:Agent) DELETE r WITH t "
    "CREATE (t)-[:PERFORMED_BY]->(n:Agent {id: 'Agent_New', name: 'New'}) RETURN t.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(:Agent) DELETE r WITH t "
    "CREATE (t)-[:PERFORMED_BY]->(fresh) RETURN t.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(:Agent) DELETE r WITH t "
    "CREATE (x:Agent {id: 'Agent_New'}) RETURN t.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(a:Agent) DETACH DELETE a RETURN t.id",
    # other write clauses
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(a:Agent) DELETE r SET t.name = 'X' RETURN t.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[r:PERFORMED_BY]->(:Agent) MATCH (a:Agent {{id: 'Agent_Robot'}}) "
    "DELETE r MERGE (t)-[:PERFORMED_BY]->(a) RETURN t.id",
    f"MATCH (t:DisassemblyTask {{product_id: '{PID}'}})-[:PERFORMED_BY]->(a:Agent) MATCH (b:Agent {{id: 'Agent_Robot'}}) "
    "CREATE (t)-[:PERFORMED_BY]->(b) RETURN t.id",
]


@pytest.mark.parametrize("cypher", ENRICHMENT_ALLOWED)
def test_enrichment_query_is_accepted(cypher):
    assert check_enrichment_query(cypher) is None, cypher


@pytest.mark.parametrize("cypher", ENRICHMENT_REJECTED)
def test_enrichment_query_is_rejected(cypher):
    assert check_enrichment_query(cypher), cypher


@pytest.mark.parametrize("cypher", REASSIGNMENT_ALLOWED)
def test_reassignment_query_is_accepted(cypher):
    assert check_reassignment_query(cypher) is None, cypher


@pytest.mark.parametrize("cypher", REASSIGNMENT_REJECTED)
def test_reassignment_query_is_rejected(cypher):
    assert check_reassignment_query(cypher), cypher


def test_write_paths_run_the_checks_before_the_database():
    """A rejected query never reaches the driver."""
    class _NoDriver:
        def session(self):
            raise AssertionError("rejected query reached the database")
    eng = _engine()
    eng.driver = _NoDriver()
    rows, err = eng._execute_mutation(f"MATCH (n:Component {{product_id: '{PID}'}}) SET n.id = 'X' RETURN n.id")
    assert rows is None and "protected" in err
    rows, err = eng._execute_reassignment(REASSIGNMENT_REJECTED[0])
    assert rows is None and err


def test_recorded_enrichment_queries_are_accepted():
    """Every write query stored in the evaluation records passes the check."""
    import glob
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    seen = 0
    for path in sorted(glob.glob(os.path.join(root, "scripts", "*_eval_run*_results.json"))):
        for case in json.load(open(path)):
            for cypher in case.get("cyphers") or []:
                if re.search(r"\b(SET|CREATE|DELETE|MERGE|REMOVE)\b", cypher):
                    assert case.get("mutation") is True, (path, case["id"])
                    assert check_enrichment_query(cypher) is None, (path, case["id"])
                    seen += 1
    assert seen == 4   # H30 and H31 in both runs of the hypothetical product
