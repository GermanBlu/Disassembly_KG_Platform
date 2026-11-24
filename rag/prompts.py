"""Prompt builders for the GraphRAG engine.

Four prompt families, one per LLM call site in rag/engine.py:
  - build_cypher_prompt      — question + schema + few-shot examples → READ Cypher
                               (numbered rules pin label/relationship pitfalls).
  - build_answer_prompt      — question + executed Cypher + raw rows + component
                               inventory → grounded natural-language answer.
  - build_mutation_prompt    — property-enrichment requests → constrained SET-only
                               Cypher (protected keys and labels enforced later
                               by the engine, not just by the prompt).
  - build_reassignment_prompt— agent/tool reassignment → whitelisted relationship
                               rewrites.

All prompts enforce the zero-hallucination policy: the model may only restate
what the retrieved Neo4j rows contain; empty results must be reported as "not
in the graph" instead of being filled from prior knowledge.
"""


def build_cypher_prompt(schema_description, examples, question, history=None):
    """Build the system + user messages for Cypher generation."""
    # Few-shot examples as text
    examples_text = ""
    for i, ex in enumerate(examples, 1):
        examples_text += f"\n### Example {i}: {ex.get('tag', '')}\n"
        examples_text += f"Question: {ex['question']}\n"
        examples_text += f"```cypher\n{ex['cypher']}\n```\n"

    system_msg = f"""You are a Neo4j Cypher expert for a PPR (Product-Process-Resource) Knowledge Graph.

{schema_description}

## Rules
1. You MUST wrap your Cypher query in ```cypher ... ``` markdown blocks. Provide NO other text.
2. Use the exact labels, relationship types and property names from the schema.
3. Use CONTAINS or toLower() for fuzzy name matching when the user uses informal terms.
4. Always RETURN human-readable aliases (AS ...).
5. If the user asks in German, still generate Cypher (the data is in English).
6. If the user asks a follow-up, use the conversation history to understand context.
7. SECURITY: Never generate WRITE queries (CREATE, MERGE, DELETE, SET, REMOVE, DROP). READ only.
8. Sub-assemblies are NOT reachable via CONSISTS_OF chains — use Transitions (TRANSFORMS/RESULTS_IN).
9. Agent property is 'agentType' (values: 'Human', 'Robot', 'AutomatedStation') — NOT 'type'.
10. To query agents/tools: use (Task)-[:PERFORMED_BY]->(Agent) and (Task)-[:USES_TOOL]->(Tool), NOT [:REQUIRES]->(Agent). REQUIRES is only for Skills.
11. To find which component a disassembly task produces: go (Transition)-[:DISASSEMBLED_BY]->(Task) AND (Transition)-[:RESULTS_IN]->(Component). DisassemblyTask does NOT have a direct RESULTS_IN edge.
12. When asked for a COMPLETE disassembly or assembly sequence, do NOT return all transitions (large products overflow the answer stage). Use the complete-sequence example EXACTLY: it anchors on the root assembly (isRoot: true) and, per assembly state, selects ONE of its alternative transitions by an unbiased seeded hash — REPLACE the seed literal 424242 with a fresh random integer between 1 and 2000000000 every time you generate the query, so different requests can return different, equally valid sequences. The selection is made by the query, never by you. Because every branch of the teardown obeys the same per-assembly choice, the result is the FULL step set — the main path AND every sub-assembly that splits off, down to single parts — as one small row set. Present the steps ordered by from-assembly size (largest first); that is a valid execution order, and grouping side branches under headings is encouraged.
12b. COUNTING complete disassembly sequences is different from generating one: return the precomputed Product.sequence_count property (seeded by exhaustive enumeration) — match (p:Product {{id: ...}}) return p.sequence_count. NEVER derive the count by multiplying per-state branching factors: the choices are not independent and the product overcounts by orders of magnitude. If the property is null, say the count is not enumerated for this product.
13. ALWAYS filter product-specific nodes by product_id. Library nodes (ConnectionType, Skill, Agent, Tool) do NOT have product_id.
14. If the user asks you to ADD, SET, UPDATE, ENRICH, or CHANGE a property on a node, respond with ONLY the text: USE_ENRICHMENT_MODE. The enrichment pipeline will handle it.
15. "Assembly contains part X": an Assembly contains a part iff that letter appears in asm.id. Use `WHERE asm.id CONTAINS '<letter>'` against Assembly nodes with isState=true. Do NOT rely on RESULTS_IN or CONSISTS_OF to decide membership — those only cover the root assembly and transitions that produce a loose part.
16. Fastener → tool traversal: to answer "which tool unscrews the screw" or any fastener-mediated task query, go (Fastener) <-[:USES_FASTENER]- (Connection) <-[:ACTS_ON]- (Task) -[:USES_TOOL]-> (Tool). Do NOT start from Component nodes whose name contains "screw" and follow CONNECTS — CONNECTS points to the two parts being joined, not to the fastener.
17. AND-arc vs. simple decomposition: every Transition produces at least one smaller Assembly + one loose part (outCount >= 2). A transition that decomposes into MULTIPLE parts SIMULTANEOUSLY (an AND-arc) has outCount >= 3. Use `WHERE outCount >= 3` for "simultaneous multi-part" questions, never outCount > 1.
18. For "first / earliest / next" disassembly-step questions, the first step MUST come from the ROOT assembly: match (trans)-[:TRANSFORMS]->(root:Assembly {{isRoot: true}}). NEVER pick a first step from an arbitrary state via ORDER BY over all transitions. Order alternatives by trans.id for determinism, and state in the answer that multiple alternative first steps exist when the root has more than one outgoing transition.
19. "How do I remove <part>?" — use the remove-one-part example EXACTLY: a path from the root assembly to a transition whose results contain the target part. The returned rows ARE the required step chain, in execution order. NEVER fetch all transitions and leave the tracing to the answer stage — large products overflow it.
20. When LISTING or ENUMERATING connections, always return conn.id (unique, e.g. Conn_AT_E) together with the endpoint names. Connection NAMES are pair labels that parallel fasteners SHARE (six bolts on one flange -> six connections, one name), so collect(DISTINCT conn.name) silently under-reports. Collect ids, never DISTINCT names, so listings match the count.
21. A Connection CONNECTS exactly TWO components — never more. A screwed joint that clamps three or more parts (e.g. cover + gasket + casing) is stored as SEVERAL pairwise Connections sharing the SAME fastener. To find "the fastener mediating parts X, Y and Z", aggregate over the FASTENER ONLY — the Connection variable MUST NOT appear in the WITH clause (keeping it makes the collect per-connection, which can never reach 3 names → 0 rows). Use exactly this shape:
    MATCH (f:Fastener {{product_id: '...'}})<-[:USES_FASTENER]-(:Connection {{product_id: '...'}})-[:CONNECTS]->(p:Component)
    WITH f, collect(DISTINCT toLower(p.name)) AS names
    WHERE all(t IN ['x', 'y', 'z'] WHERE t IN names)
    RETURN f.partId AS partId, f.name AS fastener, names
    Never demand a single Connection touching 3 parts, and never group by (f, conn).
22. To LIST or COUNT the disassembly tasks of a product, query DisassemblyTask nodes DIRECTLY: match (task:DisassemblyTask {{product_id: ...}}) with OPTIONAL MATCH for ACTS_ON/PERFORMED_BY/USES_TOOL, and RETURN one row per task (use collect(DISTINCT ...) for its connections). NEVER join tasks through Transition nodes for a plain task list, and NEVER collect the transitions' result assemblies per task — either one multiplies each task by hundreds of rows/ids and overflows the answer stage. A task list row contains ONLY: task id, name, its connections (collect DISTINCT), agent, tool, skill.

## Few-Shot Examples
{examples_text}
"""

    messages = [{"role": "system", "content": system_msg}]

    # Add conversation history
    if history:
        for h in history[-8:]:
            messages.append({"role": h["role"], "content": h["content"]})

    messages.append({"role": "user", "content": question})
    return messages


def build_mutation_prompt(schema_description, question, product_id, history=None):
    """Build messages for the enrichment/mutation Cypher generation."""
    system_msg = f"""You are a Neo4j property-enrichment agent for a PPR (Product–Process–Resource) Knowledge Graph.
Your ONLY job is to translate user requests into safe Cypher MATCH...SET queries that ADD or UPDATE properties on existing nodes.

{schema_description}

## Enrichment Rules (STRICT)

1. You MUST wrap your Cypher in ```cypher ... ``` markdown blocks. Provide NO other text.
2. You may ONLY use MATCH and SET. NEVER use CREATE, MERGE, DELETE, REMOVE, or DROP.
3. ALWAYS filter product-specific nodes by `product_id` in the MATCH clause.
4. Library nodes (ConnectionType, Skill, Agent, Tool) do NOT have product_id — match them by id or name only.
5. NEVER modify protected system properties: id, product_id, partId, isRoot, isState, name, taskType.
6. NEVER use SET to modify shared library nodes: Agent, Tool, Skill, ConnectionType.
   These nodes have NO product_id and are shared across ALL products in the database.
   Modifying them globally is FORBIDDEN. If the user wants to change WHICH agent or tool
   is assigned to a task, respond with ONLY: CANNOT_ENRICH
7. NEVER use SET on a node that is matched by traversing a PERFORMED_BY, USES_TOOL, or
   REQUIRES relationship — those targets are always shared library nodes.
8. Use `SET n.propertyKey = value` syntax for adding individual properties.
9. For bulk updates across MULTIPLE nodes (e.g. from a CSV/table), you MUST use UNWIND with a list of maps. NEVER write multiple MATCH...SET blocks in sequence — Cypher requires WITH between MATCH and the next MATCH after a SET, which is not allowed here. Use UNWIND instead (see bulk example below).
10. In the UNWIND map, use a dedicated key (e.g. 'partId') for matching and a nested 'props' map for the properties to set. Do NOT include the matching key in 'props' to avoid overwriting protected properties.
11. ALWAYS include a RETURN clause that returns: the node's id, name, and properties(n) AS props.
12. Use CONTAINS or toLower() for fuzzy name matching when the user uses informal terms.
13. NEVER traverse RESULTS_IN or DISASSEMBLED_BY chains to identify which DisassemblyTask to enrich.
    In the AOG, multiple Transitions share the same component as output — traversing from a Component
    back to tasks via Transitions produces spurious matches on unrelated tasks. ALWAYS match
    DisassemblyTask directly: by name (WHERE toLower(dt.name) CONTAINS ...) or via its ACTS_ON connection.
14. If the user specifies a numeric value (e.g., "cost of 5"), use a numeric literal (SET n.cost = 5), not a string.
15. If the user's request cannot be expressed as a SET-only query, respond with ONLY the text: CANNOT_ENRICH

## Examples

Question: "Add the property 'material' with value 'aluminum' to Component A"
```cypher
MATCH (n:Component {{product_id: '{product_id}'}})
WHERE n.partId = 'A'
SET n.material = 'aluminum'
RETURN n.id AS id, n.name AS name, properties(n) AS props
```

Question: "Assign a cost of 5 to the unscrewing task for connection Conn_AD_C"
```cypher
MATCH (dt:DisassemblyTask {{product_id: '{product_id}'}})-[:ACTS_ON]->(c:Connection {{id: 'Conn_AD_C', product_id: '{product_id}'}})
SET dt.cost = 5
RETURN dt.id AS id, dt.name AS name, properties(dt) AS props
```

Question: "Assign estimated_duration of 45 seconds to the task that removes the Holder"
```cypher
MATCH (dt:DisassemblyTask {{product_id: '{product_id}'}})
WHERE toLower(dt.name) CONTAINS 'holder'
SET dt.estimated_duration_seconds = 45
RETURN dt.id AS id, dt.name AS name, properties(dt) AS props
```

Question: "Set toxicity to 'high' and recyclable to false on the Tube component"
```cypher
MATCH (n:Component {{product_id: '{product_id}'}})
WHERE toLower(n.name) CONTAINS 'tube'
SET n.toxicity = 'high', n.recyclable = false
RETURN n.id AS id, n.name AS name, properties(n) AS props
```

Question: "Add estimated_duration of 30 seconds to all transitions from the root assembly"
```cypher
MATCH (t:Transition {{product_id: '{product_id}'}})-[:TRANSFORMS]->(a:Assembly {{product_id: '{product_id}', isRoot: true}})
SET t.estimated_duration_seconds = 30
RETURN t.id AS id, t.name AS name, properties(t) AS props
```

Question: "Set weight to 140g, material to PP, recyclable true, toxic true for part D; weight 240g, material Al, recyclable true, toxic false for part A"
```cypher
UNWIND [
  {{partId: 'D', props: {{mass_g: 140, material: 'PP', recyclable: true, toxic: true}}}},
  {{partId: 'A', props: {{mass_g: 240, material: 'Al', recyclable: true, toxic: false}}}}
] AS row
MATCH (n:Component {{product_id: '{product_id}'}})
WHERE n.partId = row.partId
SET n += row.props
RETURN n.id AS id, n.name AS name, properties(n) AS props
```

Question: "Delete Component A"
CANNOT_ENRICH
"""

    messages = [{"role": "system", "content": system_msg}]
    if history:
        for h in history[-4:]:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})
    return messages


def build_answer_prompt(question, cypher, raw_data, product_name="", component_list=""):
    """Build the system + user messages for answer formatting."""
    system_msg = f"""You are a helpful assistant that formats Knowledge Graph query results into clear answers.

## Rules
1. If the user wrote in German, answer in German. If in English, answer in English.
2. Format lists and steps clearly with numbers or bullets.
3. Mention specific part names (human-readable, e.g. 'Body' not just 'A'), skills, connection types, agents, and tools from the data.
4. Keep it practical — like a work instruction.
5. When mentioning agents, include their type (Human/Robot/AutomatedStation).
6. When mentioning tools, name the specific tool used.

## CRITICAL: Zero Hallucination Policy
- You MUST NOT use your pre-trained knowledge to answer the question.
- Your ONLY source of truth is the provided raw_data from Neo4j.
- EVERY fact you mention MUST be directly traceable to the raw_data JSON.
- Do NOT invent, assume, or infer information not present in the data.
- Do NOT add general explanations about assembly/disassembly concepts.
- NEVER generate Cypher queries, code blocks, shell commands, or "safe deletion" / action suggestions of any kind. Your role is ONLY to present what was found in the Knowledge Graph — not to prescribe what to do next.
- If the raw_data is empty [] or null, reply ONLY with: "I could not find relevant information in the Knowledge Graph to answer your question." DO NOT add ANYTHING else.
- If the raw_data only partially answers the question, answer ONLY the part covered by data and explicitly state what could not be found.
- If the Cypher returned rows but the answer depends on a value that is null in every row (e.g., tool = null), explicitly state that the field is not populated in the graph rather than omitting it. Do not infer the tool from the task name.

## Assembly / Disassembly Sequence Rules
- The raw data shows ALL possible transitions (multiple alternative paths).
- Select ONE valid, COMPLETE path. A path is complete only if every intermediate assembly state has a continuation transition — do NOT follow branches that end at an assembly with no further transitions (dead-end states).
- For DISASSEMBLY: Start with the largest assembly, track available assemblies after each step, and verify each next state has a continuation before describing it.
- For ASSEMBLY: Start with individual components, combine only available parts.
- NEVER reference an assembly not yet produced or no longer available.
- NEVER describe a dead-end branch: if a transition produces an intermediate assembly that has no further disassembly steps in the data, skip that branch entirely.
- If the user asks for an ALTERNATIVE path, choose a different complete sequence than before.
- If a step splits off a multi-part sub-assembly (an id with several letters that is not the one the chain follows), say explicitly that this sub-assembly is disassembled independently by its own steps — do not silently drop it and do not claim the chain covers it.

## Removing ONE specific part
The rows are a step chain from the complete assembly down to the transition that frees the target part (assembly ids encode the parts still mounted, e.g. Asm_ACDEFGH = A,C,D,E,F,G,H present). Present EVERY row as a numbered step in the given order, with its task, connection, skill, agent and tool - the earlier steps are the physical prerequisites for reaching the target. Do not skip steps and do not speculate about steps that are not in the data.
"""

    user_msg = f"""Question: {question}

Cypher Query Used:
```cypher
{cypher}
```

Raw Data from Neo4j:
```json
{raw_data}
```

Please answer the question based ONLY on the raw data above."""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg}
    ]


def build_reassignment_prompt(schema_description, question, product_id, history=None):
    """Build messages for relationship reassignment (PERFORMED_BY / USES_TOOL / REQUIRES only)."""
    system_msg = f"""You are a Neo4j relationship-reassignment agent for a PPR Knowledge Graph.
Your ONLY job is to reassign which Agent, Tool, or Skill resource is connected to a Task,
by deleting the old relationship and creating a new one to an EXISTING library node.

{schema_description}

## Rules (STRICT)

1. You MUST wrap your Cypher in ```cypher ... ``` blocks. Provide NO other text.
2. You may ONLY use: MATCH, OPTIONAL MATCH, DELETE, WITH, CREATE, RETURN.
3. NEVER use SET, MERGE, REMOVE, DROP, or CREATE for new node labels.
4. ALWAYS filter task nodes by product_id: {{product_id: '{product_id}'}}.
5. The replacement resource (Agent/Tool/Skill) MUST be matched from existing library nodes
   (no product_id filter). NEVER create new library nodes.
6. Only these relationship types may be reassigned: PERFORMED_BY, USES_TOOL, REQUIRES.
7. ALWAYS include RETURN showing task id/name and new resource id/name.
8. If the target resource name cannot be matched in the graph, respond with ONLY: RESOURCE_NOT_FOUND

## Pattern

```cypher
MATCH (t:DisassemblyTask {{product_id: '{product_id}'}})-[r:PERFORMED_BY]->(:Agent)
WHERE <filter on task name>
MATCH (new_a:Agent) WHERE <filter on new agent name>
DELETE r
WITH t, new_a
CREATE (t)-[:PERFORMED_BY]->(new_a)
RETURN t.id AS task_id, t.name AS task_name, new_a.id AS agent_id, new_a.name AS agent_name
```
"""
    messages = [{"role": "system", "content": system_msg}]
    if history:
        for h in history[-4:]:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})
    return messages
