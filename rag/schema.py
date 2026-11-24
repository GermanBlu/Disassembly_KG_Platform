"""Dynamic PPR schema description — injected into every Cypher generation prompt.

Generates a product-scoped schema string that tells the LLM about:
- All node labels and their properties
- All relationship types
- Critical semantic rules
- Product-specific filtering via product_id
"""

SCHEMA_TEMPLATE = """
## PPR Knowledge Graph Schema (Product–Process–Resource)

### Node Labels & Properties

| Label | Description | Key Properties |
|-------|-------------|----------------|
| Product | Root product entity | id, name, product_id, total_mass_g, recyclable_mass_pct, full_teardown_time_s, full_teardown_cost_eur, disassembly_task_count, sequence_count (number of complete disassembly sequences) |
| Assembly | Composite state / sub-assembly | id, name, product_id, isState, isRoot (only true for full assembly) |
| Component | Atomic part (not decomposable) | id, name, partId, product_id, material, mass_g, recyclable, eol_route |
| Fastener | Special Component (extra label) | id, name, partId, product_id |
| Connection | Physical join between two parts | id, name, product_id |
| ConnectionType | Category of connection (SHARED) | id, name, destructiveness |
| Transition | Direction-agnostic state change | id, name, product_id |
| Task | Work instruction (base label) | id, name, taskType, product_id |
| DisassemblyTask | Task sub-label for disassembly ops | Task props + duration_s (seconds), cost_eur (total = labor + tool), labor_cost_eur, tool_cost_eur, difficulty (low/medium/high), force_n (some tasks) |
| FastenerGroup | Assembly sub-label for grouped fasteners | groupName (+ Assembly props) |
| Skill | Required capability (SHARED) | id, name |
| DisassemblySkill | Skill sub-label (SHARED) | (same as Skill) |
| Agent | Who performs a task (SHARED) | id, name, agentType, description, labor_rate_eur_h |
| Tool | Specific tool used (SHARED) | id, name, toolType, description, cost_eur (acquisition), usage_cost_eur (per use) |

### Relationship Types

| Relationship | Direction | Meaning |
|-------------|-----------|---------|
| CONSISTS_OF | Product → Assembly (root only); Assembly → Component (root and every intermediate state) | Structural hierarchy. No Assembly→Assembly edges. |
| CONNECTS | Connection → Component | Which parts a connection joins (1→2) |
| OF_TYPE | Connection → ConnectionType | Category of connection |
| TRANSFORMS | Transition → Assembly | Points to LARGER assembly (always!) |
| RESULTS_IN | Transition → Assembly/Component | Points to SMALLER parts (always!) |
| DISASSEMBLED_BY | Transition → DisassemblyTask | Disassembly work instruction |
| ACTS_ON | Task → Connection | Which connection a task operates on |
| REQUIRES | Task → Skill | Capability needed |
| PERFORMED_BY | Task → Agent | Who performs the task |
| USES_TOOL | Task → Tool | Which specific tool is used |
| USES_FASTENER | Connection → Fastener | Optional fastener usage |
| SUITABLE_FOR | Skill → ConnectionType | Which connection types a skill handles |

### Critical Rules

1. EVERY product-specific node has a `product_id` property. The SAME `id` can exist for different products (e.g. both products have `Comp_A`), so you MUST ALWAYS include `product_id = '{product_id}'` in MATCH/WHERE clauses for: Assembly, Component, Fastener, Connection, Transition, Task, DisassemblyTask. NEVER match a product-specific node by `id` alone.
2. Library nodes (ConnectionType, Skill, Agent, Tool) are SHARED across all products — do NOT filter them by product_id.
3. CONSISTS_OF edges: Product → root Assembly (exactly one edge), and every Assembly → its constituent Components (root AND every intermediate state). There are NO Assembly → Assembly edges. The decomposition relationship between assembly states is encoded by Transitions (TRANSFORMS/RESULTS_IN), not by nesting.
4. Transitions are direction-agnostic: TRANSFORMS always → LARGER assembly, RESULTS_IN always → SMALLER parts.
5. AND/OR encoding: Multiple outgoing Transitions from same Assembly = OR alternatives. Multiple RESULTS_IN from one Transition = AND arcs.
6. Agent property is 'agentType' (values: 'Human', 'Robot', 'AutomatedStation') — NOT 'type'.
7. To query agents/tools: (Task)-[:PERFORMED_BY]->(Agent) and (Task)-[:USES_TOOL]->(Tool). REQUIRES is only for Skills.
8. Time/cost/difficulty: a DisassemblyTask has `duration_s` (seconds), `cost_eur` (TOTAL), `labor_cost_eur` (= duration × the performing Agent's `labor_rate_eur_h`) and `tool_cost_eur` (= the USES_TOOL Tool's `usage_cost_eur`), so `cost_eur = labor_cost_eur + tool_cost_eur`; plus `difficulty` ('low'/'medium'/'high') and sometimes `force_n`. Agents carry `labor_rate_eur_h`; Tools carry `cost_eur` (one-off acquisition) and `usage_cost_eur` (per-use, folded into task cost). For "how long / how much to fully disassemble this product", SUM `duration_s` / `cost_eur` over its DisassemblyTasks, or read the precomputed `Product.full_teardown_time_s` / `full_teardown_cost_eur`. These are illustrative placeholder values, not measured.

9. Connection types: match a ConnectionType by its `id`, never by a guessed spelling of its name (e.g. "press-fit" or "screwed" find nothing). Library ids and names: {connection_types}.

### Current Product
- Product ID: {product_id}
- Product Name: {product_name}
- Components: {component_list}
"""


def build_schema_description(product_id, product_name, part_names):
    """Build the schema string with product-specific info."""
    from models.library import CONNECTION_TYPES
    comp_list = ", ".join(f"{pid}={name}" for pid, name in sorted(part_names.items()))
    ct_list = ", ".join(f"{ct['id']}={ct['name']}" for ct in CONNECTION_TYPES)
    return SCHEMA_TEMPLATE.format(
        connection_types=ct_list,
        product_id=product_id,
        product_name=product_name,
        component_list=comp_list
    )
