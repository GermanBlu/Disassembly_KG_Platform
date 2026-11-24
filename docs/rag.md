# GraphRAG Engine

*File: `rag/engine.py` (plus `rag/schema.py`, `rag/prompts.py`, `rag/examples.py`).*

The GraphRAG engine lets users query the knowledge graph (KG) in natural language. It instantiates the LLM-over-KG / text-to-Cypher pattern surveyed by Pan et al. (2023) [28], applied here to a disassembly KG that combines structural and operational logic, and built on the automated-KG-construction context of Weikum et al. (2021) [27]. The generated query executes against Neo4j, and the answer model receives the resulting rows as context. This encourages graph-grounded responses, but does not guarantee that every query or explanation is correct. This document describes the three query pipelines and the places where write access is gated; see also [`reproduce.md`](reproduce.md) for the validation cases.

For the graph schema the engine reads and writes, see [`schema.md`](schema.md).

## Three pipelines, one entry point

`GraphRAGEngine.ask(question, history)` routes to one of three pipelines based on pattern-matching the question:

```
ask(question)
    │
    ├── destructive PHRASE in question? ──► hard refusal, no LLM call
    │        (phrase-level, not keyword-level: "delete ...",
    │         "remove the node", "drop all ...", "lösche ...";
    │         bare "remove" is allowed, see Write protection in three layers)
    │
    ├── reassignment signal? ──► _handle_reassignment
    │        ("change the agent", "reassign the tool", ...)
    │        (DELETE + CREATE on PERFORMED_BY / USES_TOOL / REQUIRES only)
    │
    ├── mutation signal? ──► _handle_mutation
    │        ("add the property", "set property", "annotate", ...)
    │        (MATCH + SET only; CREATE/MERGE/DELETE/REMOVE/DROP blocked)
    │
    └── otherwise ──► read pipeline (most common)
             1. generate Cypher from question + schema + few-shot examples
             2. execute against Neo4j (any write keyword blocked)
             3. on error, one retry with error appended to prompt
             4. empty result? return a fixed refusal
             5. LLM formats raw rows into Markdown, streamed via SSE
```

Every response reaches the client as a sequence of Server-Sent Events:

- `status`: progress markers for the UI spinner.
- `cypher`: the generated query (displayed in the debug panel).
- `graph_data`: the raw JSON rows Neo4j returned.
- `subgraph`: a rendering-ready `{nodes, edges}` extract. The subgraph match filters by the current product's `product_id` so nodes from other products never leak into the visualisation.
- `token`: streamed answer text.
- `error`: emitted when the query cannot be executed even after one retry, or on an unhandled pipeline exception.
- `debug`: the full trace of the current query.
- `done`: final marker of a successful stream, a JSON object with `cypher` and `rows`; the two write paths and the read-only refusal add `mutation` (`true` when the graph was changed).

## Read pipeline

### Step 1: Cypher generation

`_generate_cypher(question, history)` assembles a system prompt with:

1. The **dynamic schema description** (`rag/schema.py:build_schema_description`): scoped to the current product, with the part list inlined.
2. **Numbered rules** (`rag/prompts.py:build_cypher_prompt`), the most important of which:
   - Always filter product-specific nodes by `product_id = '<current product>'`.
   - Library nodes (`Agent`, `Tool`, `Skill`, `ConnectionType`) have no `product_id`.
   - `Task -[:PERFORMED_BY]-> Agent`, `Task -[:USES_TOOL]-> Tool`, `Task -[:REQUIRES]-> Skill`. Do not confuse them.
   - For "complete disassembly sequence" questions, the selection happens **inside the query**, not in the model: a quantified path pattern anchored on the root assembly selects one of the outgoing transitions at each visited assembly using a seeded hash tie-break. The generated query includes its seed, so the selected graph path can be reproduced against the same graph version. The query follows the resulting assembly branches down to individual parts; on the pump graph a complete teardown has 13 steps, so the query returns a short path rather than all 340 transitions. This does not establish uniform sampling or exhaustively explore all alternatives. No optimality claim is made. The query does not return every transition for the answer model to choose from, because that overflows the answer context at this scale.
   - "How do I remove *part*?" returns the prerequisite chain: a path from the root assembly to a transition whose results contain the target part. The rows are the required steps in execution order.
   - Task lists come from `DisassemblyTask` nodes directly: never joined through transitions, which multiplies every task by its hundreds of transitions.
   - A `Connection` connects exactly two components; a screwed joint clamping three parts is several pairwise connections sharing one fastener. "Which fastener mediates X, Y and Z" aggregates endpoints per **fastener**. Connection listings return unique ids, since parallel fasteners share pair names.
   - Assembly membership is decided by the assembly's `id`: an Assembly contains part *X* iff that letter appears in `asm.id`. Do not infer membership from `RESULTS_IN` or `CONSISTS_OF`.
   - AND-arc decomposition: a transition that splits one assembly into multiple parts simultaneously has `outCount >= 3`; "simultaneous multi-part" questions filter on that, never `outCount > 1`.
   - Never generate write Cypher here. Enrichment requests must return exactly the token `USE_ENRICHMENT_MODE`.
3. **Few-shot examples** (`rag/examples.py`): one per main query pattern (structure, AND/OR branching + complete sequence, agent & tool, fastener lookup, state count, connection-type list, assembly-contains-part, fastener→tool traversal, AND-arc decomposition, root-anchored first step, remove-one-part chain).

The LLM is expected to wrap its answer in a ```` ```cypher ... ``` ```` fence. `_extract_cypher` parses either a fenced block or a bare query that starts with `MATCH` / `OPTIONAL` / `WITH` / `CALL` / `RETURN`.

### Step 2: Execute

`_execute_cypher` runs the query against Neo4j after a keyword guard:

```python
for kw in ["CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP", "DETACH"]:
    if re.search(rf"\b{kw}\b", upper):
        return None, f"Write operation blocked: {kw}"
```

The keywords are matched as whole words, so a property such as `removed_part` does not block a read query.

On a Neo4j error, `_retry_cypher` does **one** retry with the failed query and error message appended to the original prompt.

### Step 3: Refusal behaviour and limits

The read path returns a fixed refusal (`NO_DATA_MSG`) when Cypher cannot be generated or repaired, or when Neo4j returns no rows. This prevents the answer stage from filling an empty result with a response. When rows do exist, the language model still generates the query and phrases the answer; either can be mistaken, incomplete, or misleading. The refusal behaviour is therefore a safeguard, not a zero-hallucination guarantee.

Three places can trigger a hard refusal:

1. `_generate_cypher` returns nothing / unparseable text → refuse.
2. The query is syntactically invalid and the one retry also fails → refuse.
3. Neo4j returns zero rows → refuse.

The refusal message is hard-coded (`NO_DATA_MSG` in `rag/engine.py`). The LLM is never given a chance to fall back on training data.

### Step 4: Answer formatting (streaming)

`_format_answer_stream` passes the question, the generated Cypher, and the raw Neo4j rows to a second LLM call. The answer prompt (`rag/prompts.py:build_answer_prompt`) instructs the model to:

- Base every claim on the supplied rows.
- Keep to the user's language (German questions get German answers).
- Format lists and steps clearly with numbers or bullets, naming specific parts, skills, connection types, agents, and tools from the data.

Tokens are streamed back as SSE `token` events as they arrive.

## Enrichment pipeline

Triggered when the question contains one of the mutation signals (`_MUTATION_SIGNALS`):

```
"add the property", "add property", "set the property", "set property",
"assign", "update the", "change the", "enrich", "annotate",
"add a cost", "add a weight", "add material", "add toxicity",
"setze", "füge hinzu", "ändere", "eigenschaft"
```

The signals are substrings of the lower-cased question, with one exception: `assign` must be a whole word, so "Which agent is assigned to this task?" stays on the read path. The read prompt has a second route into this pipeline: when the model recognises an enrichment request it returns the token `USE_ENRICHMENT_MODE`, and the engine hands the question over.

The mutation prompt (`build_mutation_prompt`) allows **only `MATCH` and `SET`**. Fifteen numbered rules govern it; the fourteen safety-relevant ones (all but the output-formatting rule) are:

1. `MATCH` + `SET` only: `CREATE` / `MERGE` / `DELETE` / `REMOVE` / `DROP` are forbidden.
2. Always filter product-specific nodes by `product_id`.
3. Library nodes have no `product_id`.
4. Protected properties cannot be modified: `id`, `product_id`, `partId`, `isRoot`, `isState`, `name`, `taskType`.
5. Never `SET` on `Agent`, `Tool`, `Skill`, `ConnectionType` (shared nodes).
6. Never `SET` on a node reached by traversing `PERFORMED_BY` / `USES_TOOL` / `REQUIRES` (those all land on shared library nodes).
7. Use `SET n.key = value` for individual properties.
8. For bulk updates, use `UNWIND` with a list of maps (Cypher forbids multiple `MATCH…SET` in sequence without `WITH`).
9. In the `UNWIND` map, use a dedicated matching key (e.g. `partId`) and a nested `props` map for the values to set; do not put the matching key inside `props`.
10. Always `RETURN` the node's `id`, `name`, and `properties(n)`.
11. `CONTAINS` / `toLower()` for fuzzy name matching.
12. Do **not** traverse `RESULTS_IN` / `DISASSEMBLED_BY` chains to find a task, that produces spurious matches because multiple transitions share components. Match tasks directly by name or `ACTS_ON`.
13. Numeric values use a numeric literal (`SET n.cost = 5`), not a string.
14. If the request cannot be expressed as a pure SET, emit `CANNOT_ENRICH`.

These rules are instructions to the model. The code check `check_enrichment_query` (called by `_execute_mutation` before anything is sent to Neo4j) does not rely on them. It removes comments and string literals from the generated query and then rejects the query if

- it contains `CREATE`, `MERGE`, `DELETE`, `DETACH`, `REMOVE`, `DROP`, `FOREACH`, `CALL` or `LOAD` as a keyword,
- it contains no `SET` clause,
- a `SET` item is not of the form `n.key = value` or `n += map` (this excludes `SET n = {...}`, `SET n:Label` and `SET n[key] = ...`),
- a `SET` item names one of the seven protected properties (`PROTECTED_PROPERTIES`; compared without regard to case). This covers `n.key = value` with any spacing or backticks, every item of a comma-separated list, the keys of a literal map in `n += {...}`, and the keys of the `props` maps of an `UNWIND` list in `n += row.props`,
- the keys set by `n += ...` cannot be read from the query text (a parameter, or a whole `UNWIND` row),
- the `SET` target is a relationship variable,
- the `SET` target is a shared library node: a variable with the label `Agent`, `Tool`, `Skill` or `ConnectionType`, or a node reached over `PERFORMED_BY`, `USES_TOOL` or `REQUIRES`.

An accepted query that consists of several `MATCH ... SET` blocks is split into individual statements, each with its own `RETURN` (Cypher requires `WITH` between `SET` and the next `MATCH`).

One case is not covered by the code check: a node matched without a label (for example by its `id` alone) is not recognised as a library node. For such a query only the prompt rules apply.

## Reassignment pipeline

Triggered by one of the reassignment signals (`_REASSIGNMENT_SIGNALS`), such as `"change the agent"`, `"replace the tool"` or `"reassign the agent"`. This check runs before the mutation signals. These requests do not fit a pure `SET`: an existing relationship is deleted and a new one is created.

The reassignment prompt (`build_reassignment_prompt`) limits the model to `MATCH`, `OPTIONAL MATCH`, `DELETE`, `WITH`, `CREATE` and `RETURN` on the three resource relationships. The code check `check_reassignment_query` (called by `_execute_reassignment`) enforces the scope on the generated query:

- `SET`, `MERGE`, `REMOVE`, `DROP`, `DETACH`, `FOREACH`, `CALL` and `LOAD` are rejected.
- The query must contain a `DELETE`.
- Every deleted item must be a relationship variable that is matched with a type, and every such type must be `PERFORMED_BY`, `USES_TOOL` or `REQUIRES`. Deleting a node variable is rejected.
- Every `CREATE` must be a relationship of exactly one of these three types, without properties, between node variables that are bound earlier in the query. A node pattern with a label, with properties or with a new variable is rejected, so no node is created.

Example: the question "Replace the tool of the Pull Off Head task with the Tweezers" contains the signal `replace the tool` and takes this path. A query the model may produce, and that the check accepts:

```cypher
MATCH (t:DisassemblyTask {product_id: 'Prod_BallpointPen'})
  WHERE toLower(t.name) CONTAINS 'pull off head'
MATCH (t)-[r:USES_TOOL]->(:Tool)
DELETE r
WITH t
MATCH (tool:Tool {id: 'Tool_Tweezers'})
CREATE (t)-[:USES_TOOL]->(tool)
RETURN t.id AS id, t.name AS name
```

A request phrased as "Assign the Tweezers tool to the Pull Off Head task" contains no reassignment signal. It matches the mutation signal `assign` and is routed to the enrichment pipeline, where the prompt answers a change of the assigned tool with `CANNOT_ENRICH`.

## Write protection in three layers

Requests that would change the structure of the graph pass three layers, in this order. Layers 1 and 3 are code; layer 2 is prompt text.

1. **Phrase filter on the question (code).** Before any model call, `ask()` scans the question for destructive phrases (`delete`, `destroy`, `detach delete`, `drop the`, `remove the node`, German equivalents and others) and answers with a fixed refusal. The filter works on phrases: the bare word "remove" is allowed, because disassembly questions use it ("which transitions remove the End plate?" is a read query).
2. **Prompt rules (prompt).** The read prompt forbids write Cypher, and the enrichment and reassignment prompts list the allowed subset.
3. **Check of the generated Cypher (code).** Each path checks its query before execution: `_execute_cypher` rejects every write keyword on the read path, `check_enrichment_query` allows only `SET` of non-protected properties on product-specific nodes, and `check_reassignment_query` allows only the deletion and creation of `PERFORMED_BY`, `USES_TOOL` and `REQUIRES` relationships between matched nodes.

In read-only mode (`DEMO_MODE`) both write paths refuse before a query is generated.

These controls constrain the supported write paths. They do not establish that every request is interpreted correctly, and they are not a database authorization boundary: the application should run with database credentials appropriate to its environment.

The destructive-phrase list lives in `GraphRAGEngine.ask()` (`rag/engine.py`). A new natural-language phrasing that should be blocked is added to that list; the check is not moved to the model.

## Why two skill sources?

The `SUITABLE_FOR` edge in the library is how the GraphRAG engine reasons about skills at query time ("which skills handle a Snap Joint?"). The `_DIS_SKILLS` dict in `kg_builder.py` is the same mapping baked into the write path so the builder can resolve a task's required skill without a round-trip to Neo4j. They must not drift apart, see [`documentation-rules.md`](documentation-rules.md) §"Coupled definitions".

## Extending the engine

When adding a new query pattern:

1. Add a few-shot example to `rag/examples.py`. Keep the list focused; every example spends tokens.
2. If the pattern reveals a constraint the current rules miss, add it as a numbered rule in `rag/prompts.py`. Put the rule before the examples so it is loaded in context.
3. Update `schema.py` if the pattern exposes a shortcut or a pitfall in the schema (e.g. "agents never have `product_id`").
4. Add a case covering the new pattern to the appropriate category in `rag_eval/cases.json` and run `python eval_rag.py` to see how the LLM handles it end-to-end.

When adding a new allowed edge to the reassignment pipeline:

1. Extend `REASSIGNABLE_RELATIONSHIPS` in `rag/engine.py`.
2. Add a rule to `build_reassignment_prompt`.
3. Add an accepted and a rejected query to `tests/test_rag_guard.py`.

When adding a new protected property to the enrichment pipeline:

1. Add it to `PROTECTED_PROPERTIES` in `rag/engine.py`.
2. Mention it in the rule `NEVER modify protected system properties` of the mutation prompt.

## References

The references below are the published works cited in this developer document.

- **[11]** L. S. Homem de Mello, A. C. Sanderson, *And/or graph representation of assembly plans*, IEEE Transactions on Robotics and Automation 6 (2) (1990) 188–199. doi:10.1109/70.54734
- **[27]** G. Weikum, X. L. Dong, S. Razniewski, F. Suchanek, *Machine knowledge: Creation and curation of comprehensive knowledge bases*, Foundations and Trends in Databases 10 (2–4) (2021) 108–490. doi:10.1561/1900000064
- **[28]** J. Z. Pan, S. Razniewski, J.-C. Kalo, S. Singhania, J. Chen, S. Dietze, H. Jabeen, J. Omeliyanenko, W. Zhang, M. Lissandrini, R. Biswas, G. de Melo, A. Bonifati, E. Vakaj, M. Dragoni, D. Graux, *Large Language Models and Knowledge Graphs: Opportunities and Challenges* (2023).
