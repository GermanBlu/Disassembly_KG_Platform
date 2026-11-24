"""Few-shot examples for Cypher generation — product-agnostic templates.

These use placeholders that get filled with product-specific values at runtime.
The `build_examples()` function generates concrete examples for a given product.
"""


def build_examples(product_id, product_name, part_names, root_assembly_id):
    """Generate few-shot examples scoped to a specific product."""
    return [
        {
            "tag": "R1 — Structural Completeness",
            "question": f"Welche Baugruppen und Einzelteile sind im Produkt {product_name} enthalten?",
            "cypher": f"""MATCH (p:Product {{id: '{product_id}'}})-[:CONSISTS_OF]->(root:Assembly)-[:CONSISTS_OF]->(c:Component)
OPTIONAL MATCH (conn:Connection {{product_id: '{product_id}'}})-[:CONNECTS]->(c)
OPTIONAL MATCH (conn)-[:OF_TYPE]->(ct:ConnectionType)
WITH p, root, c, collect(DISTINCT conn.name) AS connections,
     collect(DISTINCT ct.name) AS connectionTypes
ORDER BY c.partId
RETURN p.name AS product, root.id AS rootAssembly,
       c.partId AS partId, c.name AS component,
       connections, connectionTypes"""
        },
        {
            "tag": "First step — root-anchored",
            "question": "What is the first step to disassemble this product?",
            "cypher": f"""MATCH (trans:Transition {{product_id: '{product_id}'}})-[:TRANSFORMS]->(root:Assembly {{product_id: '{product_id}', isRoot: true}})
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, root.id AS fromAssembly, task.name AS task,
       agent.name AS agent, tool.name AS tool,
       collect(DISTINCT coalesce(output.name, output.id)) AS results
ORDER BY transition"""
        },
        {
            "tag": "Remove one specific part — chain from the root",
            "question": "How do I remove the Shaft?",
            "cypher": f"""MATCH p = (root:Assembly {{product_id: '{product_id}', isRoot: true}})
      (()<-[:TRANSFORMS]-(:Transition)-[:RESULTS_IN]->()){{0,24}}
      (a:Assembly)<-[:TRANSFORMS]-(t:Transition)-[:RESULTS_IN]->(target:Component)
WHERE toLower(target.name) CONTAINS 'shaft'
WITH p LIMIT 1
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:TRANSFORMS]->(inputAsm:Assembly)
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask)
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, inputAsm.id AS fromAssembly,
       task.name AS task, skill.name AS skill, agent.name AS agent,
       tool.name AS tool,
       collect(DISTINCT CASE WHEN output:Component THEN output.name ELSE output.id END) AS results
ORDER BY size(inputAsm.id) DESC"""
        },
        {
            "tag": "R2 + R3 — AND/OR Branching & Complete Disassembly",
            "question": f"Generiere eine vollstaendige Demontagesequenz fuer {product_name}.",
            "cypher": f"""MATCH p = (root:Assembly {{product_id: '{product_id}', isRoot: true}})
      (()<-[:TRANSFORMS]-(t:Transition WHERE NOT EXISTS {{
          MATCH (t2:Transition)-[:TRANSFORMS]->(a:Assembly)<-[:TRANSFORMS]-(t)
          WHERE ((toInteger(substring(t2.id, 1)) + 424242) * 2654435761) % 2147483648
              < ((toInteger(substring(t.id, 1))  + 424242) * 2654435761) % 2147483648
      }})-[:RESULTS_IN]->()){{1,24}}
      (x)
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:TRANSFORMS]->(inputAsm:Assembly)
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask)
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, inputAsm.id AS fromAssembly,
       task.name AS task, skill.name AS skill, agent.name AS agent,
       tool.name AS tool,
       collect(DISTINCT coalesce(output.name, output.id)) AS results
ORDER BY size(inputAsm.id) DESC, transition"""
        },
        {
            "tag": "R5 — Agent & Tool Extensibility",
            "question": "Welches Werkzeug und welcher Akteur werden fuer die Demontage benoetigt?",
            "cypher": f"""MATCH (trans:Transition {{product_id: '{product_id}'}})-[:DISASSEMBLED_BY]->(task:DisassemblyTask)
MATCH (trans)-[:RESULTS_IN]->(output)
MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
MATCH (task)-[:USES_TOOL]->(tool:Tool)
MATCH (task)-[:REQUIRES]->(skill:Skill)
RETURN task.name AS task,
       agent.name AS agent,
       agent.agentType AS agentType,
       tool.name AS tool,
       skill.name AS skill,
       collect(CASE WHEN output:Assembly THEN output.id
                    ELSE 'Comp_' + output.partId END) AS outputs
ORDER BY task.name"""
        },
        {
            "tag": "R5/R1 — Fastener Query (Zero Hallucination)",
            "question": f"Welche Verbindungsschrauben (Fastener) werden in {product_name} verwendet?",
            "cypher": f"""MATCH (f:Fastener {{product_id: '{product_id}'}})
OPTIONAL MATCH (conn:Connection)-[:USES_FASTENER]->(f)
OPTIONAL MATCH (conn)-[:OF_TYPE]->(ct:ConnectionType)
RETURN f.partId AS partId, f.name AS fastener,
       conn.name AS usedInConnection, ct.name AS connectionType
ORDER BY f.partId"""
        },
        {
            "tag": "General — State Count",
            "question": f"How many assembly states does {product_name} have?",
            "cypher": f"""MATCH (asm:Assembly {{product_id: '{product_id}'}})
WITH count(DISTINCT asm) AS totalStates
MATCH (p:Product {{id: '{product_id}'}})-[:CONSISTS_OF]->(root:Assembly)-[:CONSISTS_OF]->(c:Component)
RETURN totalStates, count(DISTINCT c) AS componentCount,
       collect(DISTINCT c.partId + '=' + c.name) AS components"""
        },
        {
            "tag": "General — Connection Types",
            "question": "What connection types are used?",
            "cypher": f"""MATCH (conn:Connection {{product_id: '{product_id}'}})-[:OF_TYPE]->(ct:ConnectionType)
MATCH (conn)-[:CONNECTS]->(c:Component)
RETURN conn.name AS connection, ct.name AS connectionType,
       ct.destructiveness AS destructiveness,
       collect(c.name) AS connectedParts
ORDER BY conn.name"""
        },
        {
            "tag": "Count Connections by Type (Zero Hallucination)",
            "question": "How many screw joint connections are there?",
            "cypher": f"""MATCH (conn:Connection {{product_id: '{product_id}'}})-[:OF_TYPE]->(ct:ConnectionType)
WITH ct.name AS connectionType, count(DISTINCT conn) AS connectionCount
RETURN connectionType, connectionCount
ORDER BY connectionCount DESC"""
        },
        {
            "tag": "Assembly Contains Part",
            "question": f"Which assembly states contain the Shaft (part H) in {product_name}?",
            "cypher": f"""MATCH (asm:Assembly {{product_id: '{product_id}', isState: true}})
WHERE asm.id CONTAINS 'H'
RETURN asm.id AS assemblyId, asm.name AS assemblyName,
       asm.isRoot AS isRoot
ORDER BY size(asm.id) DESC, assemblyId"""
        },
        {
            "tag": "Fastener → Tool Traversal",
            "question": f"Which tool is needed to unscrew the screws in {product_name}?",
            "cypher": f"""MATCH (f:Fastener {{product_id: '{product_id}'}})
MATCH (conn:Connection {{product_id: '{product_id}'}})-[:USES_FASTENER]->(f)
MATCH (task:DisassemblyTask {{product_id: '{product_id}'}})-[:ACTS_ON]->(conn)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
RETURN f.partId AS fastenerPartId, f.name AS fastener,
       task.name AS task, tool.name AS tool,
       agent.name AS agent, agent.agentType AS agentType
ORDER BY f.partId"""
        },
        {
            "tag": "AND-Arc Decompositions",
            "question": "Which transitions decompose an assembly into multiple parts simultaneously?",
            "cypher": f"""MATCH (trans:Transition {{product_id: '{product_id}'}})-[:TRANSFORMS]->(inAsm:Assembly)
MATCH (trans)-[:RESULTS_IN]->(out)
WITH trans, inAsm, collect(out) AS outputs, count(out) AS outCount
WHERE outCount >= 3
RETURN inAsm.id AS fromAssembly,
       trans.name AS transition,
       outCount AS outputCount,
       [o IN outputs | CASE WHEN o:Assembly THEN o.id
                            ELSE 'Comp_' + o.partId END] AS outputs
ORDER BY outCount DESC, fromAssembly"""
        },
        {
            # Canonical "how do I remove part X". Fetch ALL transitions (with a
            # producesTarget flag), not just the ones that yield X: the earliest
            # legal removal of X often starts mid-graph (a rule forbids it from
            # the full assembly), and the answer must present the REAL steps
            # from the complete assembly down to it — those prerequisite
            # transitions have to be in the data.
            "tag": "Remove a specific part (path from the complete assembly)",
            "question": "How do I remove the End plate?",
            "cypher": f"""MATCH (trans:Transition {{product_id: '{product_id}'}})-[:TRANSFORMS]->(fromAsm:Assembly)
MATCH (trans)-[:RESULTS_IN]->(out)
MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask)
OPTIONAL MATCH (task)-[:ACTS_ON]->(conn:Connection)-[:OF_TYPE]->(ct:ConnectionType)
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
WITH trans, fromAsm, task, conn, ct, skill, agent, tool,
     collect(CASE WHEN out:Assembly THEN out.id ELSE 'Comp_' + out.partId END) AS outputs,
     any(o IN collect(out) WHERE o:Component AND toLower(o.name) CONTAINS 'end plate') AS producesTarget
RETURN fromAsm.id AS fromAssembly, trans.name AS transition,
       task.name AS task, conn.name AS connection, ct.name AS connectionType,
       skill.name AS skill, agent.name AS agent, tool.name AS tool,
       outputs, producesTarget
ORDER BY producesTarget DESC, size(fromAsm.id) DESC"""
        },
    ]
