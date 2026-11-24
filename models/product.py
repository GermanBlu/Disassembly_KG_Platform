"""Product CRUD — manages products in Neo4j.

Every product-specific node carries a `product_id` property that scopes it.
Library nodes (ConnectionType, Skill, Agent, Tool) are shared and have NO product_id.
"""
from math import factorial


def _ordering_counts(node_id, trans_by_from, comp_set, memo):
    """Recursive AND/OR counter of orders of execution, by number of steps.

    Returns {steps: count}: the number of linear orders in which the
    transitions of a complete disassembly sequence from node_id can be
    executed, for every number of transitions `steps` ({} for a dead end).
    Complete sequences from one state can differ in length, because a
    transition may release several parts at once, so the interleaving of the
    parallel sub-sequences is counted for every combination of their lengths.
    """
    if node_id in comp_set:
        return {0: 1}
    if node_id in memo:
        return memo[node_id]

    counts = {}
    for trans in trans_by_from.get(node_id, []):
        # (length of each sub-sequence, ...) -> number of sub-sequence combinations
        combos = {(): 1}
        for r in trans["results_in"]:
            sub = _ordering_counts(r, trans_by_from, comp_set, memo)
            combos = {lengths + (t,): n * k for lengths, n in combos.items() for t, k in sub.items()}
        for lengths, n in combos.items():   # empty when a result is a dead end
            # Multinomial interleaving coefficient: (Σ t_j)! / Π(t_j!)
            # Counts valid orderings of parallel independent sub-sequences
            interleave = factorial(sum(lengths))
            for t in lengths:
                interleave //= factorial(t)
            steps = 1 + sum(lengths)
            counts[steps] = counts.get(steps, 0) + n * interleave

    memo[node_id] = counts
    return counts


def _sequence_count(node_id, trans_by_from, comp_set, memo):
    """Number of complete disassembly sequences from node_id.

    A complete disassembly sequence is a tree of transitions from node_id down
    to single components: one transition is chosen for every state that is
    reached, and every result of a chosen transition is taken apart in turn.
    The order in which independent branches are executed is not counted.
    Returns 0 for a dead end.
    """
    if node_id in comp_set:
        return 1
    if node_id in memo:
        return memo[node_id]
    total = 0
    for trans in trans_by_from.get(node_id, []):
        n = 1
        for r in trans["results_in"]:
            n *= _sequence_count(r, trans_by_from, comp_set, memo)
            if not n:
                break
        total += n
    memo[node_id] = total
    return total


def count_sequences(root_id, trans_by_from, comp_set):
    """Count complete disassembly sequences and their orders of execution.

    trans_by_from maps a state id to its transitions, each a dict with the key
    "results_in" (list of state or component ids); comp_set holds the ids that
    need no further disassembly.

    Returns a dict with
    - sequence_count: complete disassembly sequences (trees of transitions
      from the complete product down to single components),
    - ordering_count: orders of execution (linear orderings of the transitions
      of those sequences),
    - ordering_count_by_steps: {number of transitions: orders of execution},
    - min_steps / max_steps: fewest and most transitions in a complete sequence.
    """
    orderings = _ordering_counts(root_id, trans_by_from, comp_set, {})
    return {
        "sequence_count": _sequence_count(root_id, trans_by_from, comp_set, {}),
        "ordering_count": sum(orderings.values()),
        "ordering_count_by_steps": {str(k): v for k, v in sorted(orderings.items())},
        "min_steps": min(orderings, default=0),
        "max_steps": max(orderings, default=0),
    }


def list_products(driver):
    """Return all products as [{id, name, component_count, transition_count}]."""
    with driver.session() as session:
        result = session.run("""
            MATCH (p:Product)
            OPTIONAL MATCH (p)-[:CONSISTS_OF]->(root:Assembly)-[:CONSISTS_OF]->(c:Component)
            WITH p, count(DISTINCT c) AS compCount
            OPTIONAL MATCH (t:Transition {product_id: p.id})
            RETURN p.id AS id, p.name AS name,
                   compCount AS components,
                   count(DISTINCT t) AS transitions
            ORDER BY p.name
        """)
        return [dict(r) for r in result]


def get_product(driver, product_id):
    """Return full product info including stats."""
    with driver.session() as session:
        result = session.run("""
            MATCH (p:Product {id: $pid})
            OPTIONAL MATCH (p)-[:CONSISTS_OF]->(root:Assembly)-[:CONSISTS_OF]->(c:Component)
            WITH p, root, collect(DISTINCT {partId: c.partId, name: c.name, id: c.id}) AS components
            OPTIONAL MATCH (conn:Connection {product_id: $pid})
            WITH p, root, components, count(DISTINCT conn) AS connCount
            OPTIONAL MATCH (t:Transition {product_id: $pid})
            WITH p, root, components, connCount, count(DISTINCT t) AS transCount
            OPTIONAL MATCH (task:Task {product_id: $pid})
            RETURN p.id AS id, p.name AS name,
                   root.id AS rootAssembly,
                   components,
                   connCount AS connections,
                   transCount AS transitions,
                   count(DISTINCT task) AS tasks,
                   p.input_data AS inputData,
                   p.liaison_matrix AS liaisonMatrix,
                   p.pipeline_settings AS pipelineSettings
        """, pid=product_id)
        row = result.single()
        if row is None:
            return None
        out = dict(row)
        # Parse the stored pipeline_settings JSON back into a dict so the gear
        # panel can be pre-filled; absent/invalid → None.
        if out.get("pipelineSettings"):
            import json
            try:
                out["pipelineSettings"] = json.loads(out["pipelineSettings"])
            except (ValueError, TypeError):
                out["pipelineSettings"] = None
        return out


def delete_product(driver, product_id):
    """Delete a product and ALL its product-specific nodes/edges."""
    with driver.session() as session:
        # Delete all nodes with this product_id (cascades edges)
        session.run(
            "MATCH (n {product_id: $pid}) DETACH DELETE n",
            pid=product_id
        )
        # Delete the Product node itself
        session.run(
            "MATCH (p:Product {id: $pid}) DETACH DELETE p",
            pid=product_id
        )


# One Cypher per UI graph view. Module-level so tests can assert every view the
# frontends offer actually has a query.
_VIEW_QUERIES = {
        "full": """
            MATCH (n {product_id: $pid})
            WITH collect(DISTINCT n) AS pnodes
            MATCH (p:Product {id: $pid})
            WITH pnodes + [p] AS productNodes
            UNWIND productNodes AS pn
            WITH collect(DISTINCT pn) AS pnList
            UNWIND pnList AS pn
            OPTIONAL MATCH (pn)--(lib)
            WHERE lib:ConnectionType OR lib:Skill OR lib:DisassemblySkill
                  OR lib:Agent OR lib:Tool
            WITH pnList, collect(DISTINCT lib) AS libNodes
            WITH [x IN pnList + libNodes WHERE x IS NOT NULL] AS allNodes
            UNWIND allNodes AS n
            RETURN collect(DISTINCT n) AS nodes
        """,
        "structure": """
            MATCH (p:Product {id: $pid})-[:CONSISTS_OF]->(root:Assembly)
            MATCH (root)-[:CONSISTS_OF]->(c:Component)
            WITH p, root, collect(c) AS comps
            UNWIND [p, root] + comps AS n
            RETURN collect(DISTINCT n) AS nodes
        """,
        "precedence": """
            MATCH (t:Transition {product_id: $pid})-[:TRANSFORMS]->(a:Assembly)
            MATCH (t)-[:RESULTS_IN]->(out)
            WITH collect(DISTINCT t) + collect(DISTINCT a) + collect(DISTINCT out) AS allN
            UNWIND allN AS n
            WITH n WHERE n IS NOT NULL
            RETURN collect(DISTINCT n) AS nodes
        """,
        "tasks": """
            MATCH (t:Transition {product_id: $pid})-[r1:DISASSEMBLED_BY]->(task:Task)
            MATCH (task)-[r2:ACTS_ON]->(conn:Connection)
            WITH collect(DISTINCT t) + collect(DISTINCT task) + collect(DISTINCT conn) AS allN
            UNWIND allN AS n
            WITH n WHERE n IS NOT NULL
            RETURN collect(DISTINCT n) AS nodes
        """,
        "resources": """
            MATCH (task:Task {product_id: $pid})
            OPTIONAL MATCH (task)-[:PERFORMED_BY]->(ag:Agent)
            OPTIONAL MATCH (task)-[:USES_TOOL]->(tl:Tool)
            OPTIONAL MATCH (task)-[:REQUIRES]->(sk:Skill)
            WITH collect(DISTINCT task) + collect(DISTINCT ag) + collect(DISTINCT tl) + collect(DISTINCT sk) AS allN
            UNWIND allN AS n
            WITH n WHERE n IS NOT NULL
            RETURN collect(DISTINCT n) AS nodes
        """,
        "connections": """
            MATCH (conn:Connection {product_id: $pid})-[:CONNECTS]->(c:Component)
            OPTIONAL MATCH (conn)-[:OF_TYPE]->(ct:ConnectionType)
            WITH collect(DISTINCT conn) + collect(DISTINCT c) + collect(DISTINCT ct) AS allN
            UNWIND allN AS n
            WITH n WHERE n IS NOT NULL
            RETURN collect(DISTINCT n) AS nodes
        """,
        # Same topology as precedence; get_product_graph additionally annotates
        # every Transition with the destructiveness of the connection it breaks,
        # which the frontend colors (green/amber/red).
        "reversibility": """
            MATCH (t:Transition {product_id: $pid})-[:TRANSFORMS]->(a:Assembly)
            MATCH (t)-[:RESULTS_IN]->(out)
            WITH collect(DISTINCT t) + collect(DISTINCT a) + collect(DISTINCT out) AS allN
            UNWIND allN AS n
            WITH n WHERE n IS NOT NULL
            RETURN collect(DISTINCT n) AS nodes
        """,
}

# Transition id -> destructiveness of the connection type its task separates.
_DESTRUCTIVENESS_QUERY = """
    MATCH (t:Transition {product_id: $pid})-[:DISASSEMBLED_BY]->(:Task)
          -[:ACTS_ON]->(:Connection)-[:OF_TYPE]->(ct:ConnectionType)
    RETURN t.id AS tid, ct.destructiveness AS d
"""

# State-graph views only show the transition structure. Without this filter
# every one of the ~41 assembly states drags its CONSISTS_OF edges into the
# picture (~180 extra edges) and the layered layout collapses into a hairball.
_STATE_GRAPH_VIEWS = ("precedence", "reversibility")
_STATE_GRAPH_RELS = {"TRANSFORMS", "RESULTS_IN"}


def condense_transitions(nodes, edges):
    """Collapse "remove one leaf part" transitions into synthetic REMOVES edges.

    A transition with exactly two RESULTS_IN outputs of which exactly one is a
    Component turns into the edge  bigAssembly -[REMOVES]-> otherResult, labeled
    with the removed part; the transition node and its TRANSFORMS/RESULTS_IN
    edges disappear. Transitions with >= 3 outputs — AND-arcs — or two Component
    outputs keep their node so the AND semantics stay visible.

    Expects raw (unflipped) edge directions (TRANSFORMS: transition -> larger
    assembly). Purely view-layer: the database and the golden invariants are
    untouched. Nodes left without any edge (parts that only ever appear as the
    removed leaf) are dropped — their name lives on the REMOVES edges.
    """
    by_id = {n["id"]: n for n in nodes}
    trans_ids = {n["id"] for n in nodes if "Transition" in (n.get("labels") or [])}

    outs = {}  # transition id -> {"big": eid|None, "results": [eid, ...]}
    for e in edges:
        if e["source"] in trans_ids:
            io = outs.setdefault(e["source"], {"big": None, "results": []})
            if e["type"] == "TRANSFORMS":
                io["big"] = e["target"]
            elif e["type"] == "RESULTS_IN":
                io["results"].append(e["target"])

    condensed = {}  # transition id -> REMOVES edge
    for tid, io in outs.items():
        if io["big"] is None or len(io["results"]) != 2:
            continue
        comps = [rid for rid in io["results"]
                 if "Component" in (by_id.get(rid, {}).get("labels") or [])]
        if len(comps) != 1:
            continue
        removed_id = comps[0]
        survivor = next(rid for rid in io["results"] if rid != removed_id)
        tprops = by_id[tid].get("properties", {})
        part = by_id.get(removed_id, {})
        part_name = part.get("display") or part.get("properties", {}).get("name", "")
        props = {
            "transition_id": tprops.get("id"),
            "transition_name": tprops.get("name"),
            "removed_part": part_name,
            "removed_id": part.get("properties", {}).get("id"),
        }
        if tprops.get("destructiveness"):  # reversibility annotation, if present
            props["destructiveness"] = tprops["destructiveness"]
        condensed[tid] = {"source": io["big"], "target": survivor, "type": "REMOVES",
                          "label": f"− {part_name}", "properties": props}

    kept_edges = [e for e in edges
                  if e["source"] not in condensed and e["target"] not in condensed]
    kept_edges += list(condensed.values())
    used = {e["source"] for e in kept_edges} | {e["target"] for e in kept_edges}
    kept_nodes = [n for n in nodes if n["id"] in used]
    return kept_nodes, kept_edges


def get_product_graph(driver, product_id, view="full", mode=None):
    """Return product subgraph as {nodes, edges} for visualization.

    view options:
      - "full"          : everything
      - "structure"     : Product → Assembly → Component (CONSISTS_OF only)
      - "precedence"    : Assembly/Component nodes + Transitions (TRANSFORMS/RESULTS_IN)
      - "reversibility" : precedence topology, annotated with destructiveness
      - "tasks"         : Transitions + Tasks + Connections
      - "resources"     : Tasks + Agent/Tool/Skill
      - "connections"   : Connections + Components + ConnectionTypes

    mode="condensed" (state-graph views only) collapses single-part-removal
    transitions into REMOVES edges via condense_transitions().
    """
    cypher = _VIEW_QUERIES.get(view, _VIEW_QUERIES["full"])
    with driver.session() as session:
        nodes_result = session.run(cypher, pid=product_id)
        row = nodes_result.single()
        if not row:
            return {"nodes": [], "edges": []}

        raw_nodes = row["nodes"]
        node_eids = set()
        nodes = []
        for n in raw_nodes:
            eid = n.element_id
            if eid in node_eids:
                continue
            node_eids.add(eid)
            nodes.append({
                "id": eid,
                "labels": list(n.labels),
                "display": n.get("name", n.get("id", "")),
                "properties": dict(n)
            })

        if view == "reversibility":
            # A transition breaking several connections gets the worst rating.
            severity = {"Non-destructive": 0, "Semi-destructive": 1, "Destructive": 2}
            dmap = {}
            for r in session.run(_DESTRUCTIVENESS_QUERY, pid=product_id):
                cur = dmap.get(r["tid"])
                if cur is None or severity.get(r["d"], 0) > severity.get(cur, 0):
                    dmap[r["tid"]] = r["d"]
            for n in nodes:
                if "Transition" in n["labels"]:
                    d = dmap.get(n["properties"].get("id"))
                    if d:
                        n["properties"]["destructiveness"] = d

        # Now get edges between these nodes
        if not node_eids:
            return {"nodes": nodes, "edges": []}

        edge_result = session.run("""
            MATCH (a)-[r]->(b)
            WHERE elementId(a) IN $eids AND elementId(b) IN $eids
            RETURN DISTINCT elementId(a) AS src, elementId(b) AS tgt, type(r) AS rel,
                   properties(r) AS props
        """, eids=list(node_eids))

        edges = []
        state_edges = []  # raw (unflipped) TRANSFORMS/RESULTS_IN for state views
        for r in edge_result:
            rel = r["rel"]
            props = dict(r["props"] or {})
            if view in _STATE_GRAPH_VIEWS:
                if rel not in _STATE_GRAPH_RELS:
                    continue
                state_edges.append({"source": r["src"], "target": r["tgt"],
                                    "type": rel, "properties": props})
            else:
                edges.append({"source": r["src"], "target": r["tgt"],
                              "type": rel, "properties": props})

        if view in _STATE_GRAPH_VIEWS:
            if mode == "condensed":
                nodes, state_edges = condense_transitions(nodes, state_edges)
            for e in state_edges:
                if e["type"] == "TRANSFORMS":
                    # Flip: render Assembly → Transition so dagre places the input
                    # assembly ABOVE the transition node (top-down disassembly flow).
                    # In Neo4j the edge is Transition→Assembly_big.
                    edges.append({**e, "source": e["target"], "target": e["source"]})
                else:
                    edges.append(e)

        return {"nodes": nodes, "edges": edges}


def get_product_part_names(driver, product_id):
    """Return {partId: name} mapping for a product — used by frontend humanizer."""
    with driver.session() as session:
        result = session.run("""
            MATCH (p:Product {id: $pid})-[:CONSISTS_OF]->(:Assembly)-[:CONSISTS_OF]->(c:Component)
            RETURN c.partId AS partId, c.name AS name
            ORDER BY c.partId
        """, pid=product_id)
        return {r["partId"]: r["name"] for r in result}


# ── Node Property Enrichment ─────────────────────────────────────────────────

# Protected system keys that cannot be overwritten via the property editor
_PROTECTED_KEYS = {"id", "product_id", "partId", "isRoot", "isState", "taskType", "name"}


def update_node_properties(driver, product_id, node_id, new_props):
    """Append properties to a node non-destructively. Protected keys are rejected.

    Uses SET n += $props which adds/overwrites only the specified keys,
    leaving all other existing properties intact.

    Returns (updated_props_dict, error_string). One of the two is always None.
    """
    violations = set(new_props.keys()) & _PROTECTED_KEYS
    if violations:
        return None, f"Cannot modify protected properties: {', '.join(sorted(violations))}"

    with driver.session() as session:
        result = session.run(
            "MATCH (n {id: $nid}) "
            "WHERE n.product_id = $pid OR n.product_id IS NULL "
            "SET n += $props "
            "RETURN properties(n) AS props",
            nid=node_id, pid=product_id, props=new_props
        )
        record = result.single()
        if not record:
            return None, "Node not found"
        return dict(record["props"]), None


def remove_node_property(driver, product_id, node_id, key):
    """Remove a single custom property from a node. Protected keys cannot be removed."""
    if key in _PROTECTED_KEYS:
        return None, f"Cannot remove protected property: {key}"

    with driver.session() as session:
        result = session.run(
            "MATCH (n {id: $nid}) "
            "WHERE n.product_id = $pid OR n.product_id IS NULL "
            f"REMOVE n.`{key}` "
            "RETURN properties(n) AS props",
            nid=node_id, pid=product_id
        )
        record = result.single()
        if not record:
            return None, "Node not found"
        return dict(record["props"]), None


# ── Disassembly Sequence Counting ────────────────────────────────────────────

def count_disassembly_sequences(driver, product_id):
    """Count the complete disassembly sequences of a product stored in the KG.

    Reads the AND/OR graph encoded in the KG (TRANSFORMS / RESULTS_IN) and
    counts with count_sequences().

    Returns {"count": int (complete disassembly sequences, same value as
    "sequence_count"), "sequence_count": int, "ordering_count": int (orders of
    execution), "ordering_count_by_steps": {steps: count}, "min_steps": int,
    "max_steps": int, "steps_per_sequence": int (same as max_steps),
    "root_assembly_id": str} or None if the product does not exist.
    """
    with driver.session() as session:
        trans_rows = list(session.run("""
            MATCH (t:Transition {product_id: $pid})-[:TRANSFORMS]->(a:Assembly)
            OPTIONAL MATCH (t)-[:RESULTS_IN]->(res)
            RETURN t.id AS tid, a.id AS from_id, collect(res.id) AS result_ids
        """, pid=product_id))

        comp_rows = list(session.run("""
            MATCH (c:Component {product_id: $pid})
            RETURN c.id AS cid
        """, pid=product_id))

        root_row = session.run("""
            MATCH (a:Assembly {product_id: $pid, isRoot: true})
            RETURN a.id AS root_id LIMIT 1
        """, pid=product_id).single()

    if not root_row:
        return None

    # Build adjacency: assembly_id → [{tid, results_in: [id, ...]}]
    trans_by_from = {}
    for row in trans_rows:
        trans_by_from.setdefault(row["from_id"], []).append({
            "tid": row["tid"],
            "results_in": [r for r in row["result_ids"] if r]
        })

    comp_set = {row["cid"] for row in comp_rows}
    root_id = root_row["root_id"]

    # Terminal single-component Assembly nodes (appear in RESULTS_IN but have no
    # outgoing TRANSFORMS edge, and contain exactly 1 component). Treat as leaves.
    with driver.session() as session:
        terminal_asm_rows = list(session.run("""
            MATCH (t:Transition {product_id: $pid})-[:RESULTS_IN]->(res:Assembly)
            WHERE NOT (:Transition {product_id: $pid})-[:TRANSFORMS]->(res)
            MATCH (res)-[:CONSISTS_OF]->(c:Component)
            WITH res, count(c) AS compCount
            WHERE compCount = 1
            RETURN res.id AS aid
        """, pid=product_id))
    comp_set.update(row["aid"] for row in terminal_asm_rows)

    result = count_sequences(root_id, trans_by_from, comp_set)
    result["count"] = result["sequence_count"]
    result["steps_per_sequence"] = result["max_steps"]
    result["root_assembly_id"] = root_id
    return result
