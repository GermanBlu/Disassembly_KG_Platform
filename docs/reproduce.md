# Reproducing the Reference Results

This walkthrough reproduces the ballpoint-pen and hypothetical-product reference cases. Each `R`-claim below identifies a validation requirement for these cases.

All commands below assume a clean clone, an activated virtual environment, a running Neo4j instance, and an `.env` that points to it. See [`../README.md`](../README.md) for setup.

The **scalability case** (centrifugal pump) has its own reproduction path: the STEP file is not included (GrabCAD terms of use); `sample_data/Centrifugal Pump/MODEL_CHANGES.md` links the GrabCAD model and lists the changes that turn it into the model used here. Process that file in the Studio, accept the two suggested fastener groups (six M20 and four M12 bolts), untick the M20 cap nut as a fastener (it is a part) and add one rule: shaft and impeller stay together while the cap nut is in place. Generation yields 48 contacts, 40 connections, 102 assembly states (83 with alternative transitions, at most 9 from one state) and 340 transitions, and the build creates 20 tasks (one per connection bundle); each transition links the tasks of all bundles it dissolves. The knowledge graph has 528 nodes and 3,238 product-scoped relationships, and the graph admits 124,693 complete disassembly sequences (disassembly trees; 8,883,888 when every order of independent branches is counted), all of 13 steps. The prepared `sample_data/Centrifugal Pump/centrifugal_pump_product.json` contains the same graph and can be uploaded directly, without the STEP file; in it the M20 hex bolts (ISO 4014/4017) and the cap nut are removed with a 30 mm combination wrench, the M12 bolts with an 18 mm wrench, and ten connections are typed Loose Fit. The counts of the three knowledge graphs and the connected-subset counts of the pump are collected in [`../scripts/product_comparison_table.md`](../scripts/product_comparison_table.md). The question catalogues are described in [Question catalogues](#question-catalogues) below.

## TL;DR

```bash
# 1 — seed the shared library
curl -X POST http://localhost:5050/api/library/ensure

# 2 — ingest the two benchmarks
curl -X POST http://localhost:5050/api/products \
  -H 'Content-Type: application/json' \
  --data-binary @sample_data/ballpoint_pen.json

curl -X POST http://localhost:5050/api/products \
  -H 'Content-Type: application/json' \
  --data-binary @sample_data/hypothetical_product.json

# 3 — run the validation queries (below)
```

Or, if you prefer the STEP pipeline for the hypothetical product:

```bash
conda activate occ
python3 seed_benchmark.py
```

## Case 1: Ballpoint pen

Validates **R1.1–R1.4** on the 6-component ballpoint-pen example described by Lambert (2006), who attributes it to Bourjault (1984) [33]. The AND/OR graph in the prepared JSON (9 states, 13 transitions) is the one of Iwase (2025, Fig. 10a) [34] and was entered by hand.

### What you should see after ingestion

| Quantity | Expected |
|---|---|
| `Product` nodes (for this product) | 1 |
| `Assembly` nodes | 9 (1 root + 8 intermediate) |
| `Component` nodes | 6 (A–F) |
| `Connection` nodes | 5 |
| `ConnectionType` distinct categories referenced | 3 (`Press Fit`, `Snap Joint`, `Containment`) |
| `Transition` nodes | 13 |
| `DisassemblyTask` nodes | 5 (one per connection) |
| Product-scoped nodes / relationships | 39 / 120 (the shared library is counted separately) |
| `DisassemblySkill` referenced | 3 |
| Distinct `Agent` referenced | 1 (`HumanWorker`) |
| Distinct `Tool` referenced | 3 (`Flat Screwdriver`, `Tweezers`, `No Tool (Manual)`) |

### R1.1: Product structure

```cypher
MATCH (p:Product {id: 'Prod_BallpointPen'})-[:CONSISTS_OF]->(a:Assembly)
      -[:CONSISTS_OF]->(c:Component)
RETURN p, a, c
```

Returns one row per `(Product, root Assembly, Component)` triple (6 rows for the 6 parts of the root assembly). A variant that enumerates the full hierarchy (including intermediate assemblies' `CONSISTS_OF` edges) returns 33 `CONSISTS_OF` relationships in total (1 `Product`→root plus 32 `Assembly`→`Component`):

```cypher
MATCH ()-[r:CONSISTS_OF]->()
WHERE startNode(r).product_id = 'Prod_BallpointPen'
   OR endNode(r).product_id   = 'Prod_BallpointPen'
RETURN count(r) AS consistsOfCount
```

### R1.2: AND/OR encoding

**OR branches**: assembly states with more than one outgoing `TRANSFORMS`:

```cypher
MATCH (a:Assembly {product_id: 'Prod_BallpointPen'})<-[:TRANSFORMS]-(t:Transition)
WITH a, count(t) AS alternatives, collect(t.name) AS transitions
WHERE alternatives > 1
RETURN a.id AS assembly, alternatives, transitions
ORDER BY size(a.id) DESC
```

Expect four rows (ABCDEF, ABCDE, ABCDF, ABCD), each with 2 alternatives.

**AND branches**: transitions with more than one result:

```cypher
MATCH (t:Transition {product_id: 'Prod_BallpointPen'})-[:RESULTS_IN]->(r)
WITH t, collect(CASE WHEN r:Assembly THEN r.id ELSE 'Comp_' + r.partId END) AS results
WHERE size(results) > 1
RETURN t.name AS transition, results
```

All 13 transitions appear; each has exactly 2 results (AND arity 2 for the ballpoint pen).

**Sequence count**: the endpoint returns the number of complete disassembly sequences and the number of their orders of execution.

```
GET /api/products/Prod_BallpointPen/sequence-count
```

`sequence_count` (also returned as `count`) is the number of complete disassembly sequences in the sense of the paper: a complete sequence is a tree of transitions from the complete product down to single components, with one transition chosen in every reached state and all its results taken apart; the order of independent branches is not counted. Expect **6** for the pen (284 for the hypothetical product, 124,693 for the pump). `ordering_count` is the number of orders of execution: every linear order in which the transitions of such a sequence can be executed is counted separately. Expect **12** for the pen (360 for the hypothetical product, 8,883,888 for the pump). The dashboard shows `sequence_count` as "Sequences" and the orders of execution in the tooltip of that tile. Both counts are computed by `models.product.count_sequences` and asserted for the three sample files in `tests/test_sequence_count.py` (`pytest tests/test_sequence_count.py`). Both are counts on the AND/OR graph, the formalism introduced by Homem de Mello & Sanderson (1990) [11] for representing all feasible (dis)assembly sequences; the schema preserves that complete sequence space as a traversable subgraph.

### R1.3: Operational context in a single traversal

Prior AND/OR-graph representations encode the feasible-sequence space but carry no tooling, skill, or resource information, so operational context has to live in a separate model. Because the schema anchors each `Transition` to a `DisassemblyTask` (and through it to `Connection`, `Skill`, `Agent`, and `Tool`) a single traversal returns the structural step together with its full operational context, which is not achievable within the AOG formalism alone.

```cypher
MATCH (t:Transition {product_id: 'Prod_BallpointPen'})-[:DISASSEMBLED_BY]->(task:DisassemblyTask),
      (task)-[:ACTS_ON]->(conn:Connection),
      (task)-[:REQUIRES]->(skill:Skill),
      (task)-[:USES_TOOL]->(tool:Tool)
RETURN t.name AS transition, task.name AS task,
       conn.name AS connection, skill.name AS skill, tool.name AS tool
ORDER BY transition
```

You should see the **"Pull Off Cap"** task appear in three distinct transitions (`ABCDEF → ABCDE+F`, `ABCDF → ABCD+F`, `ABF → AB+F`): evidence of the task-reuse property of the schema. `DisassemblyTask` is modelled one-per-`Connection` rather than one-per-`Transition`; decoupling the two lets a single standardized work instruction be shared by every transition that dissolves the same connection. The three "Pull Off Cap" transitions therefore reuse one task node, avoiding the duplicated process descriptions that arise when operational steps are tied directly to AOG arcs.

### R1.4: ConnectionType as semantic bridge

Classifying every `Connection` against a shared `ConnectionType` taxonomy lets resource-availability questions propagate back to the joining type: starting from an unavailable tool, the graph traces the affected tasks, their transitions, and the connection type they operate on, so an operator can decide whether an alternative or a destructive operation is needed. This cross-domain reasoning is a direct consequence of embedding operational semantics in the structural representation and is not representable within the AOG formalism alone.

```cypher
MATCH (tool:Tool)<-[:USES_TOOL]-(task:DisassemblyTask)-[:ACTS_ON]->(conn:Connection)
      -[:OF_TYPE]->(ct:ConnectionType)
WHERE task.product_id = 'Prod_BallpointPen'
RETURN DISTINCT tool.name AS tool, task.name AS task,
       conn.name AS connection, ct.name AS connectionType
ORDER BY tool
```

The `Tweezers` row should show only one task (`Pull Off Head`) and connection type (`Press Fit`).

## Case 2: Hypothetical product

Validates **R2.1–R2.3** on the 8-component hypothetical product adapted from Kumar et al. (2021) [32]: six structural parts and two rivets, modelled here as two M8 screws. [32] publishes the liaison matrix, an omnidirectional feasibility matrix and a stability matrix of the product; it contains no AND/OR graph, so the 41 states and 114 transitions below are generated by this pipeline. If you used the STEP pipeline (`seed_benchmark.py`), you are also validating the full Phase 1 → Phase 2 geometric chain.

### What you should see after ingestion

| Quantity | Expected |
|---|---|
| `Component` nodes | 8 (2 `:Fastener`-labelled) |
| `Connection` nodes | 6 (2 `ScrewJoint` + 1 `LooseFit` + 3 `PressFit`) |
| `Assembly` nodes | 41 (reachable states in the AOG) |
| `Transition` nodes | 114 |
| `DisassemblyTask` nodes | 6 |
| Product-scoped nodes / relationships after Stage 2 | 176 / 729 (the shared library is counted separately) |

### R2.1: AOG compatibility

```cypher
MATCH (a:Assembly)     WHERE a.product_id    = 'Prod_HypotheticalProduct'
MATCH (c:Component)    WHERE c.product_id    = 'Prod_HypotheticalProduct'
MATCH (conn:Connection) WHERE conn.product_id = 'Prod_HypotheticalProduct'
MATCH (t:Transition)   WHERE t.product_id    = 'Prod_HypotheticalProduct'
RETURN count(DISTINCT a) AS assemblies,
       count(DISTINCT c) AS components,
       count(DISTINCT conn) AS connections,
       count(DISTINCT t) AS transitions
```

Expect `41 / 8 / 6 / 114`. These are the reference benchmark counts. Through the STEP pipeline (`seed_benchmark.py` or the Studio) the same 114 transitions come out without any precedence rule or fastener group: Phase 1 recognises that the end plate leaves in two moves (see [`pipeline.md`](pipeline.md) §1.6). The STEP route proposes `PressFit` for the holder–shaft connection; the prepared data set it to `LooseFit`. Note that the two fasteners are kept in the component hierarchy as multi-label `Component:Fastener` nodes associated with the connections they mediate, rather than being stripped from the CAD model as in conventional geometric AOG generation. This makes each fastener queryable as a functional category while still grounding every surviving transition in exactly one defined `Connection`.

### R2.2: Incremental enrichment without structural modification

Run before and after an enrichment to confirm the structural counts do not change.

Before:
```cypher
MATCH (n) WHERE n.product_id = 'Prod_HypotheticalProduct'
RETURN labels(n)[0] AS label, count(n) AS n
ORDER BY label
```

Add a property via the GraphRAG chat (or directly via `MATCH (c:Component {partId: 'A', product_id: 'Prod_HypotheticalProduct'}) SET c.material = 'aluminum'`).

After: the same count query returns the **same** numbers. Only properties changed.

### R2.3: Dual query mode

Unlike general text-to-Cypher interfaces that let the model answer from parametric knowledge when a query fails, this engine returns a hard refusal whenever no Cypher can be generated or the result set is empty, and rejects all destructive verbs at the code level. The answer prompt restricts answers to the rows returned from the database instead of falling back on LLM knowledge; this reduces unsupported answers but is not a zero-hallucination guarantee (see [`rag.md`](rag.md)).

Exercise each of the three chat-accessible paths:

| # | User message (example) | Expected pipeline | Expected outcome |
|---|---|---|---|
| 1 | "What tool is needed to remove the End Plate?" | read | correct tool name from Neo4j |
| 2 | "Assign an estimated duration of 45 seconds to the task that removes the End Plate" | enrichment | `SET` applied; structural counts unchanged |
| 3 | "Delete Component A from the database" | hard refusal | refusal message, no Cypher executed |

(1) exercises the read pipeline end-to-end including answer streaming. (2) exercises the enrichment pipeline, protected-property lock, and product-id scoping. (3) exercises the natural-language destructive-verb guard before any LLM call.

## Fastener-group reduction on the hypothetical product

Run `sample_data/Hypothetical Product STEP/Hypothetical_Product_Passungen.step` through the Studio. The Studio suggests grouping the two M8 screws. The reference result of 114 transitions and 41 states is obtained without accepting that suggestion; with the group accepted the pipeline generates 38 transitions and 17 states. With the group, the AOG is generated on the reduced matrices (7 units instead of 8) and the transitions are expanded back to both screws `C` and `F`; the removal orders of the two screws are not enumerated. Münker & Schmitt (2022) [14] compare top-down and bottom-up CAD-based AND/OR graph generation; this pipeline generates bottom-up (see [`pipeline.md`](pipeline.md) for the phase-by-phase walk-through).

To check which variant is in the database, count the transitions and states of the product:

```cypher
MATCH (t:Transition {product_id: 'Prod_HypotheticalProduct'})
WITH count(t) AS transitions
MATCH (a:Assembly {product_id: 'Prod_HypotheticalProduct'})
RETURN transitions, count(a) AS states
```

`114 / 41` is the reference result without the group, `38 / 17` the result with the group accepted. The label `FastenerGroup` is no indicator of the reduction: the builder sets it only on an assembly state whose parts are exactly the members of a group, and no such state exists in the three shipped products.

## Question catalogues

The two catalogues of the paper are run against the chat endpoint of a running app with `scripts/run_pump_eval.py`. Prerequisites: Neo4j with the shared library and the product loaded, `OPENAI_API_KEY`, and the app started with the model of the paper:

```bash
OPENAI_MODEL=gpt-6-luna python3 app.py

# load the products (ids as in the catalogues)
curl -X POST http://localhost:5050/api/products -H 'Content-Type: application/json' \
  --data-binary @sample_data/hypothetical_product.json
curl -X POST http://localhost:5050/api/products -H 'Content-Type: application/json' \
  --data-binary "@sample_data/Centrifugal Pump/centrifugal_pump_product.json"

# copy of the hypothetical product for the two enrichment and two safety questions (H30 to H33)
python3 -c "import json; d=json.load(open('sample_data/hypothetical_product.json')); d['product']['id']='Prod_EvalScratchHP'; json.dump(d, open('scratch_hp.json','w'))"
curl -X POST http://localhost:5050/api/products -H 'Content-Type: application/json' --data-binary @scratch_hp.json

# Table A.1: hypothetical product, 33 questions
python3 scripts/run_pump_eval.py --catalog rag_eval/cases_hp.json \
  --json-out hp_results.json --md-out hp_report.md
# Table A.2: centrifugal pump, 27 questions
python3 scripts/run_pump_eval.py --catalog rag_eval/cases_pump.json \
  --json-out pump_results.json --md-out pump_report.md

curl -X DELETE http://localhost:5050/api/products/Prod_EvalScratchHP
```

The scripts read the server address from `--base-url` or `RAG_EVAL_BASE_URL` (default `http://localhost:5050`). Each run writes a JSON record, a Markdown report with question, generated Cypher, answer and verdict, and a CSV.

Each catalogue was run twice on 2 November 2026 with gpt-6-luna. The records are in `scripts/`; `scripts/eval_runs_summary.json` lists them with the pass counts and response times. All pass counts are by the automatic check of the script; one case was decided by inspection and is named below. The verdict of each question is the result of the automatic check defined in the catalogue; for the pump question on a complete disassembly sequence this check tests the generated query, not the wording of the answer.

| Catalogue | Run 1 | Run 2 | Records |
|---|---|---|---|
| Hypothetical product, 33 questions (Table A.1, `rag_eval/cases_hp.json`) | 32 of 33 | 32 of 33 | `scripts/hp_eval_run1_*`, `scripts/hp_eval_run2_*` |
| Centrifugal pump, 27 questions (Table A.2, `rag_eval/cases_pump.json`) | 26 of 27 | 25 of 27 | `scripts/pump_eval_run1_*`, `scripts/pump_eval_run2_*` |

- Hypothetical product, H18 (question 18, tools for the entire disassembly): the automatic row check fails in both runs because the query returns the tools in one row. Both answers name all three tools, so by inspection the result is 33 of 33 in both runs.
- Pump, P10 (question 10) fails in both runs: the generated query looks for the cap nut as a fastener, but it is a part; the query returns no rows and the answer reports that no information was found.
- Pump, P15b (question 16, "How do I remove the Shaft?") passes in run 1 and fails in run 2: the generated path query required every node of the path to be an assembly state or a transition and thereby excluded the Shaft itself; it returned no rows, and the answer reported that no information was found.
- Response time per answer, measured in these runs on one machine and dependent on the response time of the OpenAI API: hypothetical product median 4.2 s, 95th percentile 9.2 s (n = 62, without the two refused delete requests); pump median 4.5 s, 95th percentile 14.2 s (n = 54). Execution of the generated Cypher queries of the pump on Neo4j alone (`scripts/cypher_timing.json`): median of the per-query medians 0.6 ms, 95th percentile 1.6 ms, slowest query 2.7 ms.
- The runs used copies of the two sample graphs loaded under other product ids (`Prod_HypotheticalProductTimingRun`, `Prod_CentrifugalPump_V15`), which appear in the recorded Cypher.

Repeated questions (pump, 10 runs each, `scripts/run_determinism.py`): see [`../scripts/determinism_summary.md`](../scripts/determinism_summary.md) with the records `scripts/determinism_first_step.json` and `scripts/determinism_sequence.json`.

A third, general catalogue for the chat endpoint (`rag_eval/cases.json`, run with `python3 eval_rag.py`) covers the software functions of the language interface, including write and refusal cases; it is not part of the paper tables. This catalogue expects the demo product seeded by `python3 seed_demo_product.py` (the hypothetical product with material, end-of-life and placeholder economics data and the stored sequence count); its write cases run on a copy of the ballpoint pen that the runner creates and deletes.

## Checks of the AND/OR graph

Two scripts check the AND/OR graphs of the three sample products. Both write one record per product to `scripts/`.

```bash
# six structural properties of the AND/OR graph in the product files (no database)
python scripts/check_aog_invariants.py

# AND/OR graph read back from Neo4j against the transition list of the product file
# (needs the three products imported; the script only reads)
python scripts/verify_aog_equivalence.py
```

- `scripts/check_aog_invariants.py` checks, for every product file, that the results of each transition partition its source state, that every result has fewer parts than its source, that the parts of every state are connected under the defined connections, that exactly one state is not a result and consists of all parts (unique root), that every state is the source of at least one transition (closure), and that a graph search from the root reaches every state. It reports one additional check separately: every transition has at least two results. Records: `scripts/aog_invariants_<product id>.json`.
- `scripts/verify_aog_equivalence.py` reconstructs states and transitions (source state and result states) from the `Assembly` and `Transition` nodes of a product and compares them with the product file. Records: `scripts/aog_equivalence_<product id>.json`.

The connected-subset counts of Table 8 are produced by `python scripts/count_state_space.py` (record: `scripts/state_space_counts.json`). The script reads the contact matrix and the two fastener groups from the pump STEP file when it is present, otherwise from `sample_data/Centrifugal Pump/centrifugal_pump_product.json`.

## If your numbers differ

- **Counts off by a few units**: check `precedence_rules` and `separation_precedence`. Supplying different rules will legitimately change the transition count.
- **Exact duplicates**: check that you did not ingest the same product twice. Building a product again replaces its product-scoped graph (Stage 1 deletes it before writing), so a repeated build does not duplicate nodes; ingestions with different `product_id` values are two separate products.
- **Zero transitions from a STEP file**: first check the overlap warning of Phase 1: overlapping parts (for example threads modelled at nominal diameter) can block each other in directions in which they would otherwise be free; on a variant of the hypothetical product this removed every transition. Correct the model.
- **Zero transitions**: check the phantom-state guard is firing correctly. If the semantic liaison matrix is never suppressed for fastener-mediated joints, every fastener-adjacent state is phantom and every transition is rejected. Look for "Suppressed direct contact" log lines from Phase 2.
- **Missing GraphRAG answers**: check that the shared library was seeded (`POST /api/library/ensure`). Without it, `REQUIRES` / `PERFORMED_BY` / `USES_TOOL` edges have no targets.

## Regenerating graph views

Graph visualisations (AOG topology, subgraphs and cross-domain traversals) are exports from the **Product Dashboard graph view** at various `view=` modes:

- AOG topology: `/#/product/Prod_BallpointPen` → Graph → view = *Precedence*, showing Assembly states and Transitions (the `RESULTS_IN` targets include terminal component leaves, so single `Component` nodes appear at the bottom of the topology too).
- Single-transition subgraph: chat query like "show me the full disassembly of the cap" → the returned subgraph is rendered directly.
- GraphRAG interactions: live chat panel.

The views are implemented in `models/product.py:get_product_graph`. Adding a new view means extending that function with a new `view` argument and a matching Cypher builder.

## References

The reference numbers are those of this documentation, not those of the paper.

- **[11]** L. S. Homem de Mello, A. C. Sanderson, *And/or graph representation of assembly plans*, IEEE Transactions on Robotics and Automation 6 (2) (1990) 188–199. doi:10.1109/70.54734
- **[14]** S. Münker, R. H. Schmitt, *CAD-based and/or graph generation algorithms in (dis)assembly sequence planning of complex products*, Procedia CIRP 106 (2022) 144–149. doi:10.1016/j.procir.2022.02.169
- **[32]** G. Anil Kumar, M. V. A. R. Bahubalendruni, V. S. S. Prasad, K. Sankaranarayanasamy, *A multi-layered disassembly sequence planning method to support decision making in de-manufacturing*, Sadhana 46 (2) (2021) 102. doi:10.1007/s12046-021-01622-3
- **[33]** A. J. D. Lambert, *Disassembly planning*, Eindhoven University of Technology (2006), Figure 19, p. 35 (PDF p. 36). This figure attributes the example to Bourjault (1984). [Source document](https://pure.tue.nl/ws/portalfiles/portal/4412407/607395.pdf).
- **[34]** S. Iwase, *AND/OR graph generation for disassembly analysis: Deeply-nested subassemblies represented by a hypergraph*, International Journal of Production Research 63 (8) (2025) 3035–3063. doi:10.1080/00207543.2024.2416560. Fig. 10a.
