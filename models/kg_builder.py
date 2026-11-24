"""Staged KG Builder — builds product-specific nodes into shared Neo4j DB.

Supports a 3-stage population strategy with a directed layered architecture
and incremental enrichment:

  Stage 1 — Structural Foundation:
    Product, Assembly, Component, Fastener, Connection, Transition nodes
    Relationships: CONSISTS_OF, CONNECTS, OF_TYPE, USES_FASTENER, TRANSFORMS, RESULTS_IN

  Stage 2 — Operational Enrichment:
    DisassemblyTask nodes
    Relationships: ACTS_ON, PERFORMED_BY, USES_TOOL, REQUIRES, DISASSEMBLED_BY

  Stage 3 — Property Enrichment:
    additional properties on existing nodes; set through the natural language
    interface (rag/engine.py), build_stage3_properties has no automatic step

CRITICAL: Every product-specific node uses `product_id` in its MERGE key
to prevent cross-product contamination. Two products can both have a part "A"
(id: Comp_A) but they are DISTINCT nodes because their product_id differs.

Library nodes are NOT touched here (see library.py).

Scope: Disassembly direction only (assembly tasks are out of scope).

Input format (JSON dict or Python dict):
{
  "product":      {"id": "Prod_X", "name": "Product Name"},
  "components":   [{"partId": "A", "name": "Body", "type": "Part"}, ...],
  "connections":  [{"id": "Conn_FA", "part1": "F", "part2": "A",
                    "connectionType_id": "CT_PressFit",
                    "agent_id": "Agent_HumanWorker", "tool_id": "Tool_None",
                    "fastener_id": null}, ...],
  "transitions":  [{"id": "T01", "from_parts": "ABCDEF", "removed_part": "F"}, ...]
}
"""
import copy
import re

from pipeline.part_ids import part_id, is_valid_part_id


def _derive_assembly_id(parts_str: str) -> str:
    """Derive Assembly node ID from sorted part letters. 'ABCDEF' → 'Asm_ABCDEF'."""
    return "Asm_" + "".join(sorted(parts_str))


# Disassembly skill mapping — one skill per ConnectionType
_DIS_SKILLS = {
    "CT_ScrewJoint": "Skill_Unscrewing", "CT_ClampJoint": "Skill_Unclamping",
    "CT_PressFit": "Skill_PullingOff", "CT_SnapJoint": "Skill_SnappingOut",
    "CT_PinJoint": "Skill_DrivingOut", "CT_KeyJoint": "Skill_PullingOff",
    "CT_AdhesiveBond": "Skill_Separating", "CT_WeldJoint": "Skill_CuttingOff",
    "CT_SolderJoint": "Skill_Desoldering", "CT_FlangeJoint": "Skill_Unbending",
    "CT_SeamJoint": "Skill_RippingSeam", "CT_CrimpJoint": "Skill_CuttingOpen",
    "CT_StakedJoint": "Skill_GrindingOff", "CT_Containment": "Skill_Draining",
    "CT_LooseFit": "Skill_Picking",
}

# Disassembly skill name lookup for task naming
_SKILL_NAMES = {
    "Skill_Unscrewing": "Unscrew", "Skill_Unclamping": "Unclamp",
    "Skill_PullingOff": "Pull Off", "Skill_SnappingOut": "Snap Out",
    "Skill_DrivingOut": "Drive Out", "Skill_Separating": "Separate",
    "Skill_CuttingOff": "Cut Off", "Skill_Desoldering": "Desolder",
    "Skill_Unbending": "Unbend", "Skill_RippingSeam": "Rip Seam",
    "Skill_CuttingOpen": "Cut Open", "Skill_GrindingOff": "Grind Off",
    "Skill_Draining": "Drain", "Skill_Picking": "Pick",
}


# ── Prep helpers (pure Python, no Neo4j) ─────────────────────────────────────

def _prepare_structural(data: dict) -> dict:
    """Prepare in-memory indexes needed by Stage 1.

    Returns dict with keys: pid, pname, comp_map, conn_map, root_parts, assemblies.
    """
    pid = data["product"]["id"]
    pname = data["product"]["name"]
    comp_map = {c["partId"]: c for c in data["components"]}
    conn_map = {c["id"]: c for c in data["connections"]}
    root_parts = "".join(sorted(comp_map.keys()))

    # Derive assemblies from transitions
    assemblies = set()
    for tr in data["transitions"]:
        from_parts = tr.get("from_parts") or tr.get("from_state")
        if not from_parts:
            continue
        assemblies.add(from_parts)
        if "results_in" in tr:
            for res in tr["results_in"]:
                if len(res) > 1:
                    assemblies.add(res)
        else:
            removed = tr.get("removed_part") or tr.get("removed_parts")
            if not removed:
                continue
            remaining = "".join(sorted(set(from_parts) - {removed}))
            if len(remaining) > 1:
                assemblies.add(remaining)

    return {
        "pid": pid, "pname": pname, "comp_map": comp_map,
        "conn_map": conn_map, "root_parts": root_parts,
        "assemblies": assemblies,
    }


def _prepare_operational(data: dict) -> dict:
    """Prepare in-memory indexes needed by Stage 2.

    Contains auto-deduction of removed_part / broken_connection_id and task
    naming ("<skill verb> <part name>") with strict priority for the part:
      0. conn["task_name"]   — explicit human override (Studio review step)
      A. conn["fastener_id"] — fastener joints are named after the fastener
      B. majority vote       — the endpoint that leaves in MOST transitions
                               breaking this connection (tie → part2)
      C. part2               — leaf fallback when no transition data exists
    Example (B): Holder↔Shaft is broken by 13 transitions removing the Shaft
    and one final "AH → A + H" split removing the Holder → "Pull Off Shaft".

    Returns dict with keys: pid, comp_map, conn_to_removed, tasks.
    """
    pid = data["product"]["id"]
    comp_map = {c["partId"]: c for c in data["components"]}

    # AUTO-DEDUCTION: Enrich transitions with missing removed_part / broken_connection_id
    # For naming, count which endpoint actually LEAVES across ALL transitions
    # breaking a connection (majority vote). The first transition in list order
    # is not a reliable source: the first breaker of Holder↔Shaft can be the
    # final "AH → A + H" split, whose removed_part is arbitrarily the Holder,
    # while in the other removals the Shaft is the moving part.
    removed_counts = {}  # conn_id -> {part_id: count}
    conn_by_id = {c["id"]: c for c in data.get("connections", [])}
    for tr in data.get("transitions", []):
        results = tr.get("results_in", [])
        removed = tr.get("removed_part")

        if not removed:
            for chunk in results:
                if len(chunk) == 1:
                    removed = chunk
                    tr["removed_part"] = removed
                    break

        conn_id = tr.get("broken_connection_id")
        if removed and not conn_id:
            for conn in data.get("connections", []):
                if conn.get("fastener_id") == removed:
                    conn_id = conn["id"]
                    break
                elif removed in [conn.get("part1"), conn.get("part2")]:
                    other_part = conn["part2"] if conn["part1"] == removed else conn["part1"]
                    if any(other_part in chunk for chunk in results if chunk != removed):
                        conn_id = conn["id"]
                        break
            if conn_id:
                tr["broken_connection_id"] = conn_id

        # Vote only for a part of the connection itself: in a step that releases
        # several parts, the first single-part result can belong to another
        # joint.
        conn_ids = tr.get("broken_connection_ids") or ([conn_id] if conn_id else [])
        for cid in conn_ids:
            conn = conn_by_id.get(cid)
            if not conn or not removed:
                continue
            if removed not in (conn["part1"], conn["part2"], conn.get("fastener_id")):
                continue
            counts = removed_counts.setdefault(cid, {})
            counts[removed] = counts.get(removed, 0) + 1

    conn_to_removed = {}
    for conn in data.get("connections", []):
        counts = removed_counts.get(conn["id"])
        if not counts:
            continue
        # majority vote; ties resolved toward part2 (the fallback of priority C)
        best = max(counts, key=lambda p: (counts[p], p == conn.get("part2")))
        conn_to_removed[conn["id"]] = best

    # A group of identical fasteners dissolves as a single operation, and a
    # screwed joint clamping three parts breaks three connections at once. Both
    # are ONE task, so tasks are keyed by bundle rather than by connection —
    # otherwise "which tasks are needed?" over-reports, and the extra tasks are
    # unreachable from any transition. Products with no bundle map (hypothetical
    # product, ballpoint pen) fall back to one bundle per connection, i.e.
    # one task per connection.
    bundles = data.get("connection_bundles") or {}
    canonical_of = {}
    for canon, members in bundles.items():
        for m in members:
            canonical_of[m] = canon

    # Task naming: each connection bundle generates one DisassemblyTask, named
    # by a fixed priority (override, fastener, majority vote, part2).
    tasks = {}  # canonical conn_id → {dis_task_id, dis_skill, acts_on, ...}
    for conn in data.get("connections", []):
        if bundles and conn["id"] not in canonical_of:
            # Interior to a unit that is never split, so no operation can
            # dissolve it. A task here could never be performed; the connection
            # stays in the structural layer, which is where it belongs.
            continue
        if canonical_of.get(conn["id"], conn["id"]) != conn["id"]:
            continue        # a non-canonical member — the canonical task covers it
        ct_id = conn["connectionType_id"]
        dis_skill_id = _DIS_SKILLS.get(ct_id)
        conn_id = conn["id"]

        if conn.get("fastener_id"):
            removed_pid = conn["fastener_id"]       # Priority A: fastener joint
        elif conn_id in conn_to_removed:
            removed_pid = conn_to_removed[conn_id]  # Priority B: majority over transitions
        else:
            removed_pid = conn["part2"]             # Priority C: leaf-part fallback

        # Descriptive group name if removed part belongs to a fastener group
        part_name = comp_map[removed_pid]["name"]
        for fg in data.get("fastener_groups", []):
            rep_letter = part_id(fg["members"][0]) if fg.get("members") else None
            if rep_letter and removed_pid == rep_letter:
                # Compose the label rather than reusing the internal group name:
                # that one is lower-cased and carries a "*3" multiplicity marker
                # meant for the pipeline, which has no place in a work
                # instruction shown to a technician.
                singular = re.sub(r"[_ ]\d+$", "", comp_map[removed_pid]["name"])
                part_name = f"{len(fg['members'])}x {singular}"
                break
        # Priority 0: an explicit human-supplied name on the connection wins
        # (set in the Studio's review step; auto-naming can't know which side
        # "moves" in every geometry).
        custom = (conn.get("task_name") or "").strip()
        dis_name = custom or f"{_SKILL_NAMES.get(dis_skill_id, 'Remove')} {part_name}"

        # ID convention. A task dissolving a single connection is named after it
        # (Task_Dis_BF). A task dissolving a bundle is named after the thing
        # removed, not after one arbitrarily chosen member — "Task_Dis_AT_E" for
        # the six-bolt flange is opaque and implies the task belongs to bolt E
        # alone. Grouped fasteners and multi-part screwed joints therefore get
        # Task_Dis_Grp_<removed part>.
        members = bundles.get(conn_id, [conn_id])
        if len(members) > 1:
            base = re.sub(r"[_ ]\d+$", "", comp_map[removed_pid]["name"])
            slug = re.sub(r"[^A-Za-z0-9]", "", base) or removed_pid
            dis_task_id = f"Task_Dis_Grp_{slug}"
        else:
            dis_task_id = f"Task_Dis_{conn_id.replace('Conn_', '')}"

        tasks[conn_id] = {
            "dis_task_id": dis_task_id,
            "dis_name": dis_name,
            "dis_skill": dis_skill_id,
            "agent_id": conn["agent_id"], "tool_id": conn["tool_id"],
            # every connection this one operation dissolves
            "acts_on": bundles.get(conn_id, [conn_id]),
        }

    return {
        "pid": pid, "comp_map": comp_map,
        "conn_to_removed": conn_to_removed, "tasks": tasks,
    }


def auto_task_names(data: dict) -> dict:
    """Task names Stage 2 writes when no manual name is given.

    Pure (no database), on a copy of the build payload: the Studio shows these
    as the suggestion next to the manual-name field.

    Returns:
        {connection_id: task name}; connections dissolved by one bundled task
        share its name.
    """
    data = copy.deepcopy(data)
    for conn in data.get("connections", []):
        conn.pop("task_name", None)
    tasks = _prepare_operational(data)["tasks"]
    return {cid: t["dis_name"] for t in tasks.values() for cid in t["acts_on"]}


# ── Stage 1: Structural Foundation ───────────────────────────────────────────

def build_stage1_structural(driver, data: dict) -> dict:
    """Stage 1 — Structural Foundation. Separate write transaction.

    Creates: Product, Root Assembly, Components, Assembly States,
             Connections, Transitions.
    Relationships: CONSISTS_OF, CONNECTS, OF_TYPE, USES_FASTENER,
                   TRANSFORMS, RESULTS_IN.

    Returns summary dict with stage info and entity counts.
    """
    ctx = _prepare_structural(data)
    pid, pname = ctx["pid"], ctx["pname"]
    comp_map, root_parts, assemblies = ctx["comp_map"], ctx["root_parts"], ctx["assemblies"]

    # Rebuilding a product REPLACES it: the product's nodes are deleted before
    # anything is written. Every write below is a MERGE, and transition ids
    # (T01…) are assigned after filtering, so the same id can name a different
    # physical transition in two runs. Merging a second run into an existing
    # graph would keep RESULTS_IN edges of the first run on such a node and
    # mix two graphs. The deletion is scoped strictly to this product; the
    # shared library (Skills, Tools, Agents, ConnectionTypes) and every other
    # product are untouched.
    with driver.session() as session:
        session.run(
            "MATCH (n {product_id: $pid}) DETACH DELETE n", pid=pid)

    with driver.session() as session:
        def _build_structural(tx):
            # ──────────────────────────────────────────────────────────────
            # IMPORTANT: Every MERGE for product-specific nodes uses BOTH
            # `id` AND `product_id` as the composite match key.
            # Uses UNWIND for batch operations (fewer round trips than per-row writes).
            # ──────────────────────────────────────────────────────────────

            import json
            liaison_str = json.dumps(data.get("liaison_matrix", []))
            input_str = json.dumps({
                "components": data.get("components", []),
                "connections": data.get("connections", []),
                "transitions": data.get("transitions", [])
            })
            # The pipeline_settings used to derive this product (mesh/exact, contact
            # mode, AOG caps...). Stored as JSON so the gear panel can be pre-filled
            # when the product is reopened. None → the property is left unset.
            _ps = data.get("pipeline_settings")
            pipeline_settings_str = json.dumps(_ps) if _ps is not None else None

            # 1. Product node
            tx.run(
                "MERGE (p:Product {id: $pid, product_id: $pid}) "
                "SET p.name = $name, "
                "    p.input_data = $input_data, p.liaison_matrix = $liaison_matrix, "
                "    p.pipeline_settings = $pipeline_settings",
                pid=pid, name=pname, input_data=input_str, liaison_matrix=liaison_str,
                pipeline_settings=pipeline_settings_str
            )

            # 2. Root assembly node
            root_aid = _derive_assembly_id(root_parts)
            tx.run(
                "MERGE (a:Assembly {id: $aid, product_id: $pid}) "
                "SET a.name = $name, a.isRoot = true, a.isState = true",
                aid=root_aid, name=root_parts, pid=pid
            )
            tx.run(
                "MATCH (p:Product {id: $pid, product_id: $pid}), "
                "      (a:Assembly {id: $aid, product_id: $pid}) "
                "MERGE (p)-[:CONSISTS_OF]->(a)",
                pid=pid, aid=root_aid
            )

            # 3. Components (batch)
            regular_comps = [
                {"cid": f"Comp_{c['partId']}", "name": c["name"], "partId": c["partId"]}
                for c in data["components"] if c.get("type", "Part") != "Fastener"
            ]
            fastener_comps = [
                {"cid": f"Comp_{c['partId']}", "name": c["name"], "partId": c["partId"]}
                for c in data["components"] if c.get("type", "Part") == "Fastener"
            ]
            if regular_comps:
                tx.run("""
                    UNWIND $comps AS comp
                    MERGE (c:Component {id: comp.cid, product_id: $pid})
                    SET c.name = comp.name, c.partId = comp.partId
                    WITH c, comp
                    MATCH (root:Assembly {id: $root_id, product_id: $pid})
                    MERGE (root)-[:CONSISTS_OF]->(c)
                """, comps=regular_comps, pid=pid, root_id=root_aid)
            if fastener_comps:
                tx.run("""
                    UNWIND $comps AS comp
                    MERGE (c:Component:Fastener {id: comp.cid, product_id: $pid})
                    SET c.name = comp.name, c.partId = comp.partId
                    WITH c, comp
                    MATCH (root:Assembly {id: $root_id, product_id: $pid})
                    MERGE (root)-[:CONSISTS_OF]->(c)
                """, comps=fastener_comps, pid=pid, root_id=root_aid)

            # 4. Assembly state nodes (batch)
            asm_list = [
                {"aid": _derive_assembly_id(ps), "name": ps, "letters": list(ps)}
                for ps in assemblies if ps != root_parts
            ]
            if asm_list:
                # Create intermediate assembly states. These are reachable via
                # Transitions (TRANSFORMS/RESULTS_IN), NOT directly from Product —
                # per the schema, Product has exactly one CONSISTS_OF edge (to root).
                tx.run("""
                    UNWIND $asms AS asm
                    MERGE (a:Assembly {id: asm.aid, product_id: $pid})
                    SET a.name = asm.name, a.isState = true
                """, asms=asm_list, pid=pid)
                # Assembly → Component CONSISTS_OF edges
                asm_comp_edges = [
                    {"aid": a["aid"], "cid": f"Comp_{letter}"}
                    for a in asm_list for letter in a["letters"]
                ]
                if asm_comp_edges:
                    tx.run("""
                        UNWIND $edges AS e
                        MATCH (a:Assembly {id: e.aid, product_id: $pid}),
                              (c:Component {id: e.cid, product_id: $pid})
                        MERGE (a)-[:CONSISTS_OF]->(c)
                    """, edges=asm_comp_edges, pid=pid)

            # 4b. FastenerGroup labels on group assemblies
            fg_list = []
            for fg in data.get("fastener_groups", []):
                member_letters = "".join(sorted(part_id(m) for m in fg["members"]))
                fg_list.append({
                    "aid": _derive_assembly_id(member_letters),
                    "gname": fg.get("name", ""),
                })
            if fg_list:
                tx.run("""
                    UNWIND $groups AS g
                    MATCH (a:Assembly {id: g.aid, product_id: $pid})
                    SET a:FastenerGroup, a.groupName = g.gname
                """, groups=fg_list, pid=pid)

            # 5. Connections (batch)
            conn_list = []
            conn_edges = []   # CONNECTS edges
            conn_types = []   # OF_TYPE edges
            conn_fasteners = []  # USES_FASTENER edges
            for conn in data["connections"]:
                cid = conn["id"]
                conn_list.append({
                    "cid": cid,
                    "name": f"{comp_map[conn['part1']]['name']} ↔ {comp_map[conn['part2']]['name']}",
                    "ctid": conn["connectionType_id"],
                })
                for endpoint_pid in [conn["part1"], conn["part2"]]:
                    conn_edges.append({"cid": cid, "compId": f"Comp_{endpoint_pid}"})
                conn_types.append({"cid": cid, "ctid": conn["connectionType_id"]})
                if conn.get("fastener_id"):
                    raw_fid = conn["fastener_id"]
                    fid = raw_fid if raw_fid.startswith("Comp_") else f"Comp_{raw_fid}"
                    conn_fasteners.append({"cid": cid, "fid": fid})

            if conn_list:
                tx.run("""
                    UNWIND $conns AS conn
                    MERGE (c:Connection {id: conn.cid, product_id: $pid})
                    SET c.name = conn.name
                """, conns=conn_list, pid=pid)
            if conn_edges:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (c:Connection {id: e.cid, product_id: $pid}),
                          (comp:Component {id: e.compId, product_id: $pid})
                    MERGE (c)-[:CONNECTS]->(comp)
                """, edges=conn_edges, pid=pid)
            if conn_types:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (c:Connection {id: e.cid, product_id: $pid}),
                          (ct:ConnectionType {id: e.ctid})
                    MERGE (c)-[:OF_TYPE]->(ct)
                """, edges=conn_types, pid=pid)
            if conn_fasteners:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (c:Connection {id: e.cid, product_id: $pid}),
                          (f:Fastener {id: e.fid, product_id: $pid})
                    MERGE (c)-[:USES_FASTENER]->(f)
                """, edges=conn_fasteners, pid=pid)

            # 6. Transitions (batch — structural edges only, NO DISASSEMBLED_BY)
            trans_list = []
            trans_results_asm = []   # RESULTS_IN → Assembly
            trans_results_comp = []  # RESULTS_IN → Component
            for tr in data["transitions"]:
                from_parts = tr.get("from_parts") or tr.get("from_state")
                if not from_parts:
                    continue

                if "results_in" in tr:
                    results = tr["results_in"]
                    removed = tr.get("removed_part") or tr.get("removed_parts")
                    if not removed:
                        single_components = [res for res in results if len(res) == 1]
                        removed = single_components[0] if single_components else ""
                    trans_name = f"{from_parts} → {' + '.join(results)}"
                else:
                    removed = tr.get("removed_part") or tr.get("removed_parts")
                    if not removed:
                        continue
                    remaining = "".join(sorted(set(from_parts) - {removed}))
                    results = [removed]
                    if remaining:
                        results.append(remaining)
                    trans_name = f"{from_parts} → {remaining} + {removed}"

                from_asm_id = _derive_assembly_id(from_parts)
                trans_id = tr.get("id", f"Trans_{pid}_{from_parts}_{removed}")

                trans_list.append({
                    "tid": trans_id,
                    "name": trans_name,
                    "from_asm_id": from_asm_id,
                })
                for res in results:
                    if len(res) > 1:
                        trans_results_asm.append({
                            "tid": trans_id,
                            "aid": _derive_assembly_id(res),
                        })
                    elif len(res) == 1:
                        trans_results_comp.append({
                            "tid": trans_id,
                            "cid": f"Comp_{res}",
                        })

            if trans_list:
                tx.run("""
                    UNWIND $trans AS tr
                    MERGE (t:Transition {id: tr.tid, product_id: $pid})
                    SET t.name = tr.name
                    WITH t, tr
                    MATCH (a:Assembly {id: tr.from_asm_id, product_id: $pid})
                    MERGE (t)-[:TRANSFORMS]->(a)
                """, trans=trans_list, pid=pid)
            if trans_results_asm:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (t:Transition {id: e.tid, product_id: $pid}),
                          (a:Assembly {id: e.aid, product_id: $pid})
                    MERGE (t)-[:RESULTS_IN]->(a)
                """, edges=trans_results_asm, pid=pid)
            if trans_results_comp:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (t:Transition {id: e.tid, product_id: $pid}),
                          (c:Component {id: e.cid, product_id: $pid})
                    MERGE (t)-[:RESULTS_IN]->(c)
                """, edges=trans_results_comp, pid=pid)

        session.execute_write(_build_structural)

    return {
        "product_id": pid,
        "product_name": pname,
        "stage": "structural",
        "components": len(data["components"]),
        "connections": len(data["connections"]),
        "transitions": len(data["transitions"]),
        "assemblies": len(assemblies),
    }


# ── Structural Validation ────────────────────────────────────────────────────

def validate_structural_layer(driver, product_id):
    """Validate that the structural layer is complete and independently queryable.

    Called after Stage 1, before Stage 2. Checks that the structural layer can
    be queried on its own, without operational or resource data.

    Returns:
        dict with is_valid, counts, errors
    """
    errors = []
    counts = {}

    with driver.session() as session:
        # Query 1: All assemblies and components
        r1 = session.run("""
            MATCH (p:Product {id: $pid})-[:CONSISTS_OF*]->(n)
            WHERE n:Assembly OR n:Component OR n:Fastener
            RETURN labels(n) AS labels, count(n) AS cnt
        """, pid=product_id)
        for record in r1:
            label_key = "+".join(sorted(record["labels"]))
            counts[label_key] = record["cnt"]

        # Query 2: All transitions with RESULTS_IN connections
        r2 = session.run("""
            MATCH (t:Transition {product_id: $pid})
            OPTIONAL MATCH (t)-[:RESULTS_IN]->(target)
            RETURN count(DISTINCT t) AS transitions,
                   count(DISTINCT target) AS result_targets
        """, pid=product_id)
        rec2 = r2.single()
        counts["transitions"] = rec2["transitions"]
        counts["result_targets"] = rec2["result_targets"]
        if rec2["transitions"] > 0 and rec2["result_targets"] == 0:
            errors.append("Transitions exist but none have RESULTS_IN edges")

        # Query 3: All connections
        r3 = session.run("""
            MATCH (conn:Connection {product_id: $pid})
            OPTIONAL MATCH (conn)-[:CONNECTS]->(part)
            OPTIONAL MATCH (conn)-[:OF_TYPE]->(ct:ConnectionType)
            RETURN count(DISTINCT conn) AS connections,
                   count(DISTINCT part) AS connected_parts,
                   count(DISTINCT ct) AS connection_types
        """, pid=product_id)
        rec3 = r3.single()
        counts["connections"] = rec3["connections"]
        counts["connected_parts"] = rec3["connected_parts"]
        if rec3["connections"] > 0 and rec3["connected_parts"] == 0:
            errors.append("Connections exist but none have CONNECTS edges")

    return {
        "is_valid": len(errors) == 0,
        "counts": counts,
        "errors": errors,
    }


# ── Stage 2: Operational Enrichment ──────────────────────────────────────────

def build_stage2_operational(driver, data: dict) -> dict:
    """Stage 2 — Operational Enrichment. Separate write transaction.

    Creates: DisassemblyTask nodes.
    Relationships: ACTS_ON, PERFORMED_BY, USES_TOOL, REQUIRES, DISASSEMBLED_BY.

    Uses MERGE to anchor onto existing structural nodes — never modifies them.
    Returns summary dict with stage info, task counts, and warnings.
    """
    ctx = _prepare_operational(data)
    pid, tasks = ctx["pid"], ctx["tasks"]
    warnings = []

    # Soft check: does the Product node exist?
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Product {id: $pid, product_id: $pid}) RETURN p.id AS id",
            pid=pid
        )
        if not result.single():
            warnings.append(
                "Product node not found — operational nodes created but edges "
                "to structural nodes may be incomplete. Run Stage 1 first."
            )

    with driver.session() as session:
        def _build_operational(tx):
            # ──────────────────────────────────────────────────────────────
            # Tasks (batch: one DisassemblyTask per connection)
            # ──────────────────────────────────────────────────────────────
            task_list = []
            task_acts_on = []
            task_performed_by = []
            task_uses_tool = []
            task_requires = []

            for conn_id, t in tasks.items():
                task_list.append({
                    "tid": t["dis_task_id"],
                    "name": t["dis_name"],
                })
                for cid in t.get("acts_on", [conn_id]):
                    task_acts_on.append({
                        "tid": t["dis_task_id"],
                        "cid": cid,
                    })
                task_performed_by.append({
                    "tid": t["dis_task_id"],
                    "agid": t["agent_id"],
                })
                task_uses_tool.append({
                    "tid": t["dis_task_id"],
                    "tlid": t["tool_id"],
                })
                if t["dis_skill"]:
                    task_requires.append({
                        "tid": t["dis_task_id"],
                        "sid": t["dis_skill"],
                    })

            if task_list:
                tx.run("""
                    UNWIND $tasks AS t
                    MERGE (dt:Task:DisassemblyTask {id: t.tid, product_id: $pid})
                    SET dt.name = t.name, dt.taskType = 'Disassembly'
                """, tasks=task_list, pid=pid)
            if task_acts_on:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (dt:Task {id: e.tid, product_id: $pid}),
                          (c:Connection {id: e.cid, product_id: $pid})
                    MERGE (dt)-[:ACTS_ON]->(c)
                """, edges=task_acts_on, pid=pid)
            if task_performed_by:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (tk:Task {id: e.tid, product_id: $pid}),
                          (ag:Agent {id: e.agid})
                    MERGE (tk)-[:PERFORMED_BY]->(ag)
                """, edges=task_performed_by, pid=pid)
            if task_uses_tool:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (tk:Task {id: e.tid, product_id: $pid}),
                          (tl:Tool {id: e.tlid})
                    MERGE (tk)-[:USES_TOOL]->(tl)
                """, edges=task_uses_tool, pid=pid)
            if task_requires:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (tk:Task {id: e.tid, product_id: $pid}),
                          (s:Skill {id: e.sid})
                    MERGE (tk)-[:REQUIRES]->(s)
                """, edges=task_requires, pid=pid)

            # ──────────────────────────────────────────────────────────────
            # DISASSEMBLED_BY edges (batch: Transition → DisassemblyTask)
            # ──────────────────────────────────────────────────────────────
            dis_by_edges = []
            for tr in data["transitions"]:
                from_parts = tr.get("from_parts") or tr.get("from_state")
                if not from_parts:
                    continue

                removed = tr.get("removed_part") or tr.get("removed_parts")
                if not removed:
                    if "results_in" in tr:
                        single_components = [r for r in tr["results_in"] if len(r) == 1]
                        removed = single_components[0] if single_components else ""
                    else:
                        continue

                trans_id = tr.get("id", f"Trans_{pid}_{from_parts}_{removed}")

                # A step dissolves every connection between its two sides, so it
                # links to the task of each dissolved bundle (broken_connection_ids);
                # without that list, broken_connection_id names the single connection.
                canonical_of = {m: k for k, ms in (data.get("connection_bundles") or {}).items() for m in ms}
                linked = []
                for cid in (tr.get("broken_connection_ids") or []):
                    key = canonical_of.get(cid, cid)
                    if key in tasks and tasks[key]["dis_task_id"] not in linked:
                        linked.append(tasks[key]["dis_task_id"])
                if linked:
                    dis_by_edges.extend({"tid": trans_id, "dtid": d} for d in linked)
                    continue

                matching_conn = tr.get("broken_connection_id")
                if matching_conn and matching_conn not in tasks:
                    matching_conn = canonical_of.get(matching_conn, matching_conn)
                if not matching_conn:
                    for conn in data["connections"]:
                        if removed in [conn["part1"], conn["part2"]]:
                            other = conn["part2"] if conn["part1"] == removed else conn["part1"]
                            if other in from_parts:
                                matching_conn = conn["id"]
                                break

                if matching_conn and matching_conn in tasks:
                    t_info = tasks[matching_conn]
                    dis_by_edges.append({
                        "tid": trans_id,
                        "dtid": t_info["dis_task_id"],
                    })

            if dis_by_edges:
                tx.run("""
                    UNWIND $edges AS e
                    MATCH (tr:Transition {id: e.tid, product_id: $pid}),
                          (dt:DisassemblyTask {id: e.dtid, product_id: $pid})
                    MERGE (tr)-[:DISASSEMBLED_BY]->(dt)
                """, edges=dis_by_edges, pid=pid)

        session.execute_write(_build_operational)

    return {
        "product_id": pid,
        "stage": "operational",
        "tasks": len(tasks),
        "warnings": warnings,
    }


# ── Stage 3: Property Enrichment ─────────────────────────────────────────────

def build_stage3_properties(driver, data: dict) -> dict:
    """Stage 3 — Property Enrichment.

    Properties such as material, weight or duration are set on existing nodes
    through the natural language interface (enrichment queries in
    rag/engine.py). This builder function has no automatic step: it writes
    nothing and returns a summary with properties_set = 0.
    """
    pid = data["product"]["id"]
    return {
        "product_id": pid,
        "stage": "properties",
        "properties_set": 0,
    }


# ── Convenience wrapper ──────────────────────────────────────────────────────

def build_product_kg(driver, data: dict) -> dict:
    """Build the full product KG by calling all 3 stages sequentially.

    Takes the product JSON and returns the combined result with a 'stages'
    key that holds the per-stage details.

    Safe to re-run: Stage 1 deletes the product-scoped graph of this product
    and creates it again; all writes use MERGE with composite keys.
    """
    s1 = build_stage1_structural(driver, data)
    s2 = build_stage2_operational(driver, data)
    s3 = build_stage3_properties(driver, data)

    _, _, warnings = validate_input(data)

    return {
        "product_id": s1["product_id"],
        "product_name": s1["product_name"],
        "components": s1["components"],
        "connections": s1["connections"],
        "transitions": s1["transitions"],
        "tasks": s2["tasks"],
        "assemblies": s1["assemblies"],
        "warnings": warnings + s2.get("warnings", []),
        "stages": [s1, s2, s3],
    }


# ── Validation & helpers ─────────────────────────────────────────────────────

def _find_dead_end_assemblies(transitions):
    """Return set of multi-part assembly strings that are produced by transitions
    but have no outgoing transitions (incomplete AND/OR paths)."""
    from_parts_set = {tr.get("from_parts") or tr.get("from_state") for tr in transitions}
    from_parts_set = {f for f in from_parts_set if f}
    output_assemblies = set()
    for tr in transitions:
        from_parts = tr.get("from_parts") or tr.get("from_state")
        if "results_in" in tr:
            for child in tr["results_in"]:
                if len(child) > 1:
                    output_assemblies.add(child)
        else:
            removed = tr.get("removed_part") or tr.get("removed_parts")
            if not from_parts or not removed:
                continue
            remaining = "".join(sorted(set(from_parts) - {removed}))
            if len(remaining) > 1:
                output_assemblies.add(remaining)
    return output_assemblies - from_parts_set


def validate_input(data: dict) -> tuple[bool, list[str], list[str]]:
    """Validate input data structure. Returns (ok, errors, warnings)."""
    errors = []
    if "product" not in data or "id" not in data.get("product", {}):
        errors.append("Missing product.id")
    if "product" not in data or "name" not in data.get("product", {}):
        errors.append("Missing product.name")
    if not data.get("components"):
        errors.append("No components provided")
    if not data.get("connections"):
        errors.append("No connections provided")
    if not data.get("transitions"):
        errors.append("No transitions provided")

    # Check component partIds are single characters from the part alphabet (A-Z, a-z, 0-9)
    part_ids = set()
    for c in data.get("components", []):
        pid = c.get("partId")
        if not pid:
            errors.append(f"Component missing partId: {c}")
        elif not is_valid_part_id(pid):
            errors.append(
                f"Component partId must be a single character from the part "
                f"alphabet (A-Z, a-z, 0-9), got {pid!r}: {c}"
            )
        else:
            part_ids.add(pid)

    # Check connections reference valid parts
    for conn in data.get("connections", []):
        for key in ["part1", "part2"]:
            if conn.get(key) not in part_ids:
                errors.append(f"Connection {conn.get('id')} references unknown part: {conn.get(key)}")

    # Check transitions reference valid parts
    for tr in data.get("transitions", []):
        from_parts = tr.get("from_parts") or tr.get("from_state") or ""
        for ch in from_parts:
            if ch not in part_ids:
                errors.append(f"Transition {tr.get('id')} references unknown part in from_parts: {ch}")

        if "results_in" in tr:
            for child in tr["results_in"]:
                for ch in child:
                    if ch not in part_ids:
                        errors.append(f"Transition {tr.get('id')} references unknown part in results_in: {ch}")
        else:
            removed = tr.get("removed_part") or tr.get("removed_parts")
            if removed not in part_ids:
                errors.append(f"Transition {tr.get('id')} references unknown removed_part: {removed}")

    # AND/OR graph completeness check (non-blocking warnings)
    warnings = []
    dead_ends = _find_dead_end_assemblies(data.get("transitions", []))
    for d in sorted(dead_ends):
        warnings.append(
            f"Dead-end assembly '{d}': produced by a transition but has no outgoing transitions. "
            f"This branch cannot be fully disassembled."
        )

    return (len(errors) == 0, errors, warnings)
