"""Library management — shared product-agnostic taxonomy nodes.

The Library contains: ConnectionTypes, DisassemblySkills,
SUITABLE_FOR edges, Agents, and Tools.
These are created once and shared by all products in the same DB.

Scope: disassembly direction only.
"""
import logging

logger = logging.getLogger(__name__)

# ── Cypher label injection whitelists ────────────────────────────────────────
# Labels are interpolated into Cypher via f-strings. Every label that reaches
# Cypher MUST go through a whitelist check. NEVER trust an externally supplied
# label string. These lists are also mirrored in docs/schema.md and must stay
# in sync — see docs/documentation-rules.md.

_ALLOWED_LIBRARY_LABELS = {
    "ConnectionType", "Skill", "DisassemblySkill", "Agent", "Tool",
}

# Sub-type labels applied in addition to the base label
_ALLOWED_SKILL_SUBTYPES = {"AssemblySkill", "DisassemblySkill"}   # the built-in library holds DisassemblySkill only
_ALLOWED_AGENT_SUBTYPES = {"Human", "Robot", "AutomatedStation"}
_ALLOWED_TOOL_SUBTYPES  = {"HandTool", "PowerTool"}


def _validate_label(label: str, allowed: set = _ALLOWED_LIBRARY_LABELS) -> str:
    if label not in allowed:
        raise ValueError(f"Unknown library label: {label!r}")
    return label

# ── Library data (shared by all products) ────────────────────────────────────

CONNECTION_TYPES = [
    {"id": "CT_ScrewJoint",   "name": "Screw Joint",   "destructiveness": "Non-destructive"},
    {"id": "CT_ClampJoint",   "name": "Clamp Joint",   "destructiveness": "Non-destructive"},
    {"id": "CT_PressFit",     "name": "Press Fit",     "destructiveness": "Non-destructive"},
    {"id": "CT_SnapJoint",    "name": "Snap Joint",    "destructiveness": "Non-destructive"},
    {"id": "CT_PinJoint",     "name": "Pin Joint",     "destructiveness": "Semi-destructive"},
    {"id": "CT_KeyJoint",     "name": "Key Joint",     "destructiveness": "Non-destructive"},
    {"id": "CT_AdhesiveBond", "name": "Adhesive Bond", "destructiveness": "Semi-destructive"},
    {"id": "CT_WeldJoint",    "name": "Weld Joint",    "destructiveness": "Destructive"},
    {"id": "CT_SolderJoint",  "name": "Solder Joint",  "destructiveness": "Destructive"},
    {"id": "CT_FlangeJoint",  "name": "Flange Joint",  "destructiveness": "Semi-destructive"},
    {"id": "CT_SeamJoint",    "name": "Seam Joint",    "destructiveness": "Destructive"},
    {"id": "CT_CrimpJoint",   "name": "Crimp Joint",   "destructiveness": "Destructive"},
    {"id": "CT_StakedJoint",  "name": "Staked Joint",  "destructiveness": "Destructive"},
    {"id": "CT_Containment",  "name": "Containment",   "destructiveness": "Non-destructive"},
    {"id": "CT_LooseFit",     "name": "Loose Fit",     "destructiveness": "Non-destructive"},
]

SKILLS = [
    {"id": "Skill_Unscrewing",  "name": "Unscrewing",   "type": "DisassemblySkill"},
    {"id": "Skill_Unclamping",  "name": "Unclamping",   "type": "DisassemblySkill"},
    {"id": "Skill_PullingOff",  "name": "Pulling Off",  "type": "DisassemblySkill"},
    {"id": "Skill_SnappingOut", "name": "Snapping Out", "type": "DisassemblySkill"},
    {"id": "Skill_DrivingOut",  "name": "Driving Out",  "type": "DisassemblySkill"},
    {"id": "Skill_Separating",  "name": "Separating",   "type": "DisassemblySkill"},
    {"id": "Skill_CuttingOff",  "name": "Cutting Off",  "type": "DisassemblySkill"},
    {"id": "Skill_Desoldering", "name": "Desoldering",  "type": "DisassemblySkill"},
    {"id": "Skill_Unbending",   "name": "Unbending",    "type": "DisassemblySkill"},
    {"id": "Skill_RippingSeam", "name": "Ripping Seam", "type": "DisassemblySkill"},
    {"id": "Skill_CuttingOpen", "name": "Cutting Open",  "type": "DisassemblySkill"},
    {"id": "Skill_GrindingOff", "name": "Grinding Off",  "type": "DisassemblySkill"},
    {"id": "Skill_Draining",    "name": "Draining",      "type": "DisassemblySkill"},
    {"id": "Skill_Picking",     "name": "Picking",       "type": "DisassemblySkill"},
]

SKILL_SUITABILITY = {
    "Skill_Unscrewing":  ["CT_ScrewJoint"],
    "Skill_Unclamping":  ["CT_ClampJoint"],
    "Skill_PullingOff":  ["CT_PressFit", "CT_KeyJoint"],
    "Skill_SnappingOut": ["CT_SnapJoint"],
    "Skill_DrivingOut":  ["CT_PinJoint"],
    "Skill_Separating":  ["CT_AdhesiveBond"],
    "Skill_CuttingOff":  ["CT_WeldJoint"],
    "Skill_Desoldering": ["CT_SolderJoint"],
    "Skill_Unbending":   ["CT_FlangeJoint"],
    "Skill_RippingSeam": ["CT_SeamJoint"],
    "Skill_CuttingOpen": ["CT_CrimpJoint"],
    "Skill_GrindingOff": ["CT_StakedJoint"],
    "Skill_Draining":    ["CT_Containment"],
    "Skill_Picking":     ["CT_LooseFit"],
}

AGENTS = [
    {"id": "Agent_HumanWorker",      "name": "Human Worker",      "agentType": "Human",     "description": "Manual assembly/disassembly operator"},
    {"id": "Agent_Robot",            "name": "Assembly Robot",     "agentType": "Robot",     "description": "Robotic arm for automated assembly tasks"},
    {"id": "Agent_AutomatedStation", "name": "Automated Station",  "agentType": "AutomatedStation", "description": "Fully automated processing station"},
]

TOOLS = [
    {"id": "Tool_Tweezers",         "name": "Tweezers",          "toolType": "HandTool", "description": "Precision gripping tool for small components"},
    {"id": "Tool_FlatScrewdriver",   "name": "Flat Screwdriver",  "toolType": "HandTool", "description": "Flat-head screwdriver for prying and levering"},
    {"id": "Tool_AllenKey5mm",       "name": "Allen Key (5mm)",   "toolType": "HandTool", "description": "Hex key for M8 screw joints"},
    {"id": "Tool_PullOffTool",       "name": "Pull-Off Tool",     "toolType": "HandTool", "description": "Specialized tool for press-fit removal"},
    {"id": "Tool_CombinationWrench18mm", "name": "Combination Wrench (18mm)", "toolType": "HandTool", "description": "Combination wrench, 18 mm across flats (M12 hex bolts)"},
    {"id": "Tool_CombinationWrench30mm", "name": "Combination Wrench (30mm)", "toolType": "HandTool", "description": "Combination wrench, 30 mm across flats (M20 hex bolts and nuts)"},
    {"id": "Tool_None",             "name": "No Tool (Manual)",  "toolType": "HandTool", "description": "Task performed by hand without specialized tools"},
]

def build_library(tx):
    """Build all shared Library nodes and edges inside a Neo4j transaction."""
    # ConnectionTypes
    for ct in CONNECTION_TYPES:
        tx.run(
            "MERGE (ct:ConnectionType {id: $id}) "
            "SET ct.name = $name, ct.destructiveness = $destructiveness",
            **ct
        )

    # Skills (idempotent label handling)
    for sk in SKILLS:
        label = _validate_label(sk["type"], _ALLOWED_SKILL_SUBTYPES)
        tx.run(
            f"MERGE (s:Skill {{id: $id}}) SET s.name = $name, s.type = $type, s:{label}",
            id=sk["id"], name=sk["name"], type=label
        )

    # SUITABLE_FOR edges
    for skill_id, ct_ids in SKILL_SUITABILITY.items():
        for ct_id in ct_ids:
            tx.run(
                "MATCH (s:Skill {id: $s}), (ct:ConnectionType {id: $ct}) "
                "MERGE (s)-[:SUITABLE_FOR]->(ct)",
                s=skill_id, ct=ct_id
            )

    # Agents  — base label :Agent + subtype label (:Human / :Robot / :AutomatedStation)
    for ag in AGENTS:
        subtype = _validate_label(ag["agentType"], _ALLOWED_AGENT_SUBTYPES)
        tx.run(
            f"MERGE (a:Agent {{id: $id}}) "
            f"SET a.name = $name, a.agentType = $agentType, a.description = $description, a:{subtype}",
            **ag
        )

    # Tools — base label :Tool + subtype label (:HandTool / :PowerTool)
    for tl in TOOLS:
        subtype = _validate_label(tl.get("toolType", "HandTool"), _ALLOWED_TOOL_SUBTYPES)
        tx.run(
            f"MERGE (t:Tool {{id: $id}}) "
            f"SET t.name = $name, t.toolType = $toolType, t.description = $description, t:{subtype}",
            **tl
        )


def ensure_constraints(driver):
    """Create unique constraints for library nodes."""
    with driver.session() as session:
        # Skill
        session.run("CREATE CONSTRAINT Skill_id_unique IF NOT EXISTS FOR (n:Skill) REQUIRE n.id IS UNIQUE")
        # ConnectionType
        session.run("CREATE CONSTRAINT ConnectionType_id_unique IF NOT EXISTS FOR (n:ConnectionType) REQUIRE n.id IS UNIQUE")
        # Agent
        session.run("CREATE CONSTRAINT Agent_id_unique IF NOT EXISTS FOR (n:Agent) REQUIRE n.id IS UNIQUE")
        # Tool
        session.run("CREATE CONSTRAINT Tool_id_unique IF NOT EXISTS FOR (n:Tool) REQUIRE n.id IS UNIQUE")

def ensure_library(driver):
    """Ensure Library nodes exist. Only seeds defaults if the database is empty."""
    ensure_constraints(driver)
    with driver.session() as session:
        # Check if any library nodes exist
        result = session.run("MATCH (n) WHERE n:Skill OR n:ConnectionType OR n:Agent OR n:Tool RETURN count(n) AS c")
        count = result.single()["c"]
        if count == 0:
            logger.info("Library is empty. Seeding defaults...")
            session.execute_write(build_library)
        else:
            logger.info("Library already contains %d nodes. Skipping seed.", count)

def get_library_items(driver, label):
    """Fetch all library items for a specific label."""
    label = _validate_label(label)
    with driver.session() as session:
        result = session.run(f"MATCH (n:{label}) RETURN n, labels(n) AS lbls")
        items = []
        for record in result:
            props = dict(record["n"])
            lbls = record["lbls"]
            if label == "Skill" and "type" not in props:
                if "DisassemblySkill" in lbls:
                    props["type"] = "DisassemblySkill"
                elif "AssemblySkill" in lbls:
                    props["type"] = "AssemblySkill"
            items.append(props)
        return items

def save_library_items(driver, label, items):
    """Bulk save/update library items.

    Notes:
    - items is a list of dicts. If an item has no `id`, it is skipped.
    - We use `SET n += $props` (not `SET n = $props`) to preserve protected
      properties (e.g. existing id).
    - The `id` field is stripped from $props so a client cannot rewrite it.
    """
    label = _validate_label(label)
    with driver.session() as session:
        # We use MERGE on ID.
        for item in items:
            if not item.get("id"):
                continue

            # Additional subtype labels for Skills, Agents, and Tools
            extra_label = ""
            if label == "Skill" and item.get("type"):
                extra_label = f":{_validate_label(item['type'], _ALLOWED_SKILL_SUBTYPES)}"
            elif label == "Agent" and item.get("agentType"):
                extra_label = f":{_validate_label(item['agentType'], _ALLOWED_AGENT_SUBTYPES)}"
            elif label == "Tool" and item.get("toolType"):
                extra_label = f":{_validate_label(item['toolType'], _ALLOWED_TOOL_SUBTYPES)}"

            props = {k: v for k, v in item.items() if k != "id"}
            cypher = f"MERGE (n:{label} {{id: $id}}) SET n += $props"
            if extra_label:
                cypher += f", n{extra_label}"

            session.run(cypher, id=item["id"], props=props)


def delete_library_item(driver, label, item_id):
    """Delete a library item and its outgoing relationships."""
    label = _validate_label(label)
    with driver.session() as session:
        session.run(f"MATCH (n:{label} {{id: $id}}) DETACH DELETE n", id=item_id)

def reset_library(driver):
    """Delete ALL nodes in Neo4j and re-ingest base library taxonomy."""
    with driver.session() as session:
        # 1. Wipe everything
        session.run("MATCH (n) DETACH DELETE n")
        # 2. Re-create constraints and seed library
        # (ensure_library handles both)
    ensure_library(driver)


def get_library_stats(driver):
    """Return counts of all Library node types."""
    with driver.session() as session:
        result = session.run("""
            MATCH (ct:ConnectionType) WITH count(ct) AS ctCount
            MATCH (dsk:DisassemblySkill) WITH ctCount, count(dsk) AS dskCount
            MATCH (ag:Agent) WITH ctCount, dskCount, count(ag) AS agCount
            MATCH (tl:Tool)
            RETURN ctCount, dskCount, agCount, count(tl) AS tlCount
        """)
        row = result.single()
        return {
            "connection_types": row["ctCount"],
            "disassembly_skills": row["dskCount"],
            "agents": row["agCount"],
            "tools": row["tlCount"],
        }


def get_library_graph(driver):
    """Return full Library subgraph as {nodes, edges} for visualization."""
    with driver.session() as session:
        nodes = []
        edges = []
        # Nodes
        for rec in session.run(
            "MATCH (n) WHERE n:ConnectionType OR n:Skill OR n:Agent OR n:Tool "
            "RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props"
        ):
            nodes.append({
                "id": rec["eid"], "labels": rec["labels"],
                "display": rec["props"].get("name", rec["props"].get("id", "")),
                "properties": dict(rec["props"])
            })
        # Edges
        for rec in session.run(
            "MATCH (a)-[r]->(b) "
            "WHERE (a:Skill OR a:ConnectionType OR a:Agent OR a:Tool) "
            "AND   (b:Skill OR b:ConnectionType OR b:Agent OR b:Tool) "
            "RETURN elementId(a) AS src, elementId(b) AS tgt, type(r) AS rel, "
            "       properties(r) AS props"
        ):
            edges.append({"source": rec["src"], "target": rec["tgt"], "type": rec["rel"],
                          "properties": dict(rec["props"] or {})})
        return {"nodes": nodes, "edges": edges}
