# Architecture Guide

This document explains **how** KG_Platform works end-to-end: the data flow, the core algorithms, and the non-obvious design decisions. Pair it with [`docs/pipeline.md`](docs/pipeline.md) for line-level detail on the STEP → Knowledge Graph pipeline and [`docs/schema.md`](docs/schema.md) for the authoritative Neo4j schema.

New to the codebase? Read [README.md](README.md) first for setup, then come back here.

## System at a glance

```
┌─────────────────────┐     ┌────────────────────┐     ┌─────────────────────┐
│   STEP CAD file     │     │  JSON product      │     │  User question      │
│   (optional input)  │     │  description       │     │  (natural language) │
└──────────┬──────────┘     └─────────┬──────────┘     └──────────┬──────────┘
           │                          │                           │
           ▼                          │                           │
   ┌──────────────────┐               │                           │
   │ STEP pipeline    │               │                           │
   │ (pipeline/*)     │               │                           │
   │ • geometry       │               │                           │
   │ • interference   │               │                           │
   │ • fastener det.  │               │                           │
   │ • AOG builder    │               │                           │
   │ • semantic       │               │                           │
   └──────────┬───────┘               │                           │
              │ emits JSON            │                           │
              ▼                       ▼                           │
       ┌──────────────────────────────────────────┐               │
       │  KG builder (models/kg_builder.py)       │               │
       │  3 stages, product replaced, UNWIND      │               │
       └──────────────────┬───────────────────────┘               │
                          │                                       │
                          ▼                                       │
                  ┌─────────────────┐                             │
                  │  Neo4j 5.9+     │◄────────────────────────────┤
                  │  (property KG)  │                             │
                  └────────┬────────┘                             │
                           │                                      │
                           │         ┌────────────────────────────┴──────┐
                           │         │  GraphRAG engine (rag/)           │
                           │         │  • text-to-Cypher + few-shot      │
                           └────────►│  • three pipelines: read,         │
                                     │    enrichment, reassignment       │
                                     │  • refusal on empty results       │
                                     │  • SSE streaming answers          │
                                     └────────────────────────────────────┘
```

Three things the diagram does not show but matter:

1. The JSON input path and the STEP input path **converge on the same KG builder**. The schema is identical regardless of how the product got there.
2. The KG builder is **layered**: Stage 1 writes structural nodes (Product/Assembly/Component/Connection/Transition), Stage 2 adds the operational layer (DisassemblyTask and its edges), Stage 3 is property enrichment, which is carried out through the natural language interface (queries that `SET` properties on existing nodes); the builder function of this stage has no automatic step and writes nothing. Each stage is its own write transaction; Stage 1 first deletes the product's existing graph in a separate transaction, so a rebuild replaces the product instead of merging into it.
3. The GraphRAG engine runs **entirely against Neo4j** for content. The LLM is instructed not to produce answer-level facts from training data: it generates Cypher, Neo4j returns data, the LLM formats that data. Empty result set → hard refusal. These controls reduce unsupported answers but do not guarantee that every query or answer is correct (see [`docs/rag.md`](docs/rag.md)).

## The STEP → KG pipeline (phase-by-phase)

### Phase 1: Geometric extraction

*File: `models/step_worker.py` → `models/step_pipeline.py:run_step_phase1` → `pipeline/geometry.py`, `pipeline/liaison_matrix.py`, `pipeline/interference.py`, `pipeline/two_step.py`, `pipeline/fastener_detection.py`. Phase 1 starts from the standard settings `pipeline.settings.STANDARD_SETTINGS`; a client may change the leaves in `CLIENT_SETTINGS`.*

1. **XCAF assembly parsing**: the STEP file is opened through OpenCASCADE's XCAF reader. Direct children of the root assembly are enumerated flat (no nested sub-assembly traversal) so that every part receives a single letter A, B, C, … Part names are read from the *prototype* label via `GetLabelName()`, not the instance label, which carries only placement data.
2. **Liaison matrix**: an *N*×*N* symmetric 0/1 matrix. `lm[i][j] = 1` iff the minimum distance between parts *i* and *j* is below 0.5 mm, a platform parameter that does not identify joint types. The distance is the exact BRepExtrema distance for near pairs (bounding boxes within `near_bound_factor` × the characteristic part size); all other pairs keep the bounding-box distance, a lower bound far above any contact threshold.
3. **Overlap check**: every contacting pair is intersected; pairs with a common volume above 0.01 mm³ (a thread modelled at nominal diameter, a press fit with oversize) are reported as a warning, not corrected. Overlapping parts can block each other in directions in which they would otherwise be free, which removes feasible transitions.
4. **Test directions**: derived from the common surfaces of every contacting pair (plane normals, axes of revolution), as in Section 3 of the CSPPA method of Prasad et al. (2022); the common surfaces themselves are computed with the Open CASCADE General Fuse. Faces under 1 mm², spheres and free-form faces contribute no direction, and a pair that touches only along an edge or at a point contributes none either. The additional normal for incomplete surfaces of revolution (half shells, Prasad et al. Section 3) is not implemented.
5. **Interference matrices**: one per test direction. `ims[d][i][j] = 1` iff moving part *i* along direction *d* is blocked by part *j*. The check is two-stage: an AABB prefilter (Algorithm 1 of Prasad et al. 2022, written for the removal direction) followed by a GPU occlusion test seen from both sides (Prasad's test cases 1 and 2). A 1 px silhouette edge, a 1 % threshold for contacting pairs and zero for non-contacting pairs replace the exact pixel comparison of the paper. A view in which the moving part renders no pixel counts as blocked. The directions run sequentially.
6. **Two-step removals**: a part blocked only by parts it does not touch is moved past its contact partners and tested again from there; if it can leave sideways, its far blockers are released. The free travel is a sampled search on the exact B-rep (0.1 mm steps while the parts slide along each other). Only the motion of the single part is checked; the released matrix entries also apply to subassemblies that contain the part. These releases are part-level heuristics, not certification of group motion.
7. **Fastener detection (Tier 1)**: regex matching on part names against a curated list of fastener keywords (`screw`, `bolt`, `M<number>`, `ISO <id>`, `Schraube`, …). Matches are surfaced as *suggestions*: the final decision is made by the user in the UI.

**macOS isolation:** Phase 1 runs in a dedicated subprocess because OCC's offscreen renderer needs `NSApplication.sharedApplication()` to be initialised first, which conflicts with Flask. The subprocess redirects fd 1 → fd 2 before importing OCC so that OCC's native `printf` does not pollute the JSON written back over stdout.

### Phase 2: Semantic enrichment

*File: `pipeline/semantic.py` (`generate_semantic_tables`).*

Phase 2 converts raw geometric contacts into **semantic Connections** and **semantic Transitions**. This is where the AOG literature's pure-geometric view is turned into the KG's PPR-compatible representation.

#### Step 2.1 Fastener-mediated connections

For each user-confirmed fastener *F*:

| Non-fastener neighbours of *F* | Emitted connections |
|---|---|
| 1 | `PressFit` between *F* and its neighbour |
| 2 | one `ScrewJoint` between the two clamped parts; direct contact between them is suppressed in the semantic liaison matrix |
| 3 | three pairwise `ScrewJoint` connections between all three clamped parts; all three direct contacts are suppressed |

The semantic liaison matrix (not the original) is what downstream steps reason over. This suppression is what makes "bolt through two parts" appear in the KG as a single `ScrewJoint`, rather than as one `ScrewJoint` plus a spurious `PressFit` between the clamped parts.

#### Step 2.2 Direct non-fastener contacts

Remaining `semantic_lm[i][j] == 1` entries where neither *i* nor *j* is a fastener produce one `PressFit` `Connection` each. These are editable in the UI.

#### Step 2.3 Fastener-group reduction (optional)

If the caller passes `fastener_groups`, the AOG input matrices are compressed: for each group, rows/cols of members are OR-merged onto the first member (the *representative*), and the other rows/cols are deleted. The AOG then runs on the reduced matrices. After extraction, representative letters are expanded back to the full member set, so the members can still be referred to individually downstream. The pump result (340 transitions) uses two groups (six M20 and four M12 bolts). For the hypothetical product (`sample_data/Hypothetical Product STEP/Hypothetical_Product_Passungen.step`) the Studio suggests grouping the two M8 screws. The reference result of 114 transitions and 41 states is obtained without accepting that suggestion; with the group accepted the pipeline generates 38 transitions and 17 states.

#### Step 2.4 AOG generation

*File: `pipeline/aog_builder.py` → `pipeline/aog_generation.py`.*

Bottom-up BFS over the AND/OR-graph formalism (Homem de Mello & Sanderson, 1990) on the (possibly reduced) liaison and interference matrices. Subassemblies are represented as **integer bitmasks**, giving O(1) disjointness (`bm1 & bm2 == 0`) and O(1) union. For candidate-pair counts above 50 000, validation is parallelised via `ProcessPoolExecutor` with the `spawn` context (fork is unsafe with OCC on macOS).

#### Step 2.5 Transition extraction: four semantic checks and optional precedence rules

These checks constrain the generated structural model. The paper describes them as four semantic checks plus optional precedence rules: filters 1, 2, 5 and 6 below are the four semantic checks, filters 3 and 4 are the two kinds of precedence rule. For every AND-arc produced by the AOG, the steps run in this order:

```
AND-arc  ─►  (1) phantom-state guard
          ─►  (2) broken-connection check
          ─►  (3) part-precedence guard       ← only if rules supplied
          ─►  (4) separation-precedence guard ← only if rules supplied
          ─►  (5) disintegration handling
    after the per-arc loop:
          ─►  (6) forward-reachability filter
```

| # | Filter | What it checks | Why it exists |
|---|---|---|---|
| 1 | **Phantom-state guard** | The *input* assembly state is connected under the **semantic** connection graph (fastener edges active only when the fastener and both clamped parts are present). | A state can be geometrically coherent yet semantically impossible, e.g. a loose screw still "joining" two already-separated parts. Vanilla AOG cannot see this because it only uses geometry. |
| 2 | **Broken-connection check** | The split dissolves at least one defined `Connection`, and every connection it dissolves is recorded (`broken_connection_ids`, the first one also as `broken_connection_id`). A direct joint (`PressFit` and the like) is dissolved when its two parts land on opposite sides. A fastener joint is dissolved only by removing the fastener: the fastener ends on one side and all parts it clamps that are still present end together on the other (`dissolved_connections`). A split that pulls a clamped part away while the fastener stays with another clamped part is rejected (`tears_fastener_joint`). The fastener may leave together with other parts. | Anchors every surviving Transition to the connections it dissolves, which is what makes the `DISASSEMBLED_BY → ACTS_ON` traversal well defined. One transition can dissolve several connections: in the pump graph 214 of the 340 transitions link two to six tasks. |
| 3 | **Part-precedence guard** | `{X: [Y]}` rules: "X cannot leave while Y is still mounted", unless *Y itself* is what is being removed in this step. | Encodes topological constraints that geometry alone cannot infer. |
| 4 | **Separation-precedence guard** | `{part1, part2, requires_removed}` rules: "parts *p1* and *p2* cannot be separated while any of `requires_removed` is still present". | Pairwise variant for cases like "Shaft and Holder cannot separate while the EndPlate is still installed". |
| 5 | **Disintegration handling** | After the split, each resulting half is re-segmented through the semantic connection graph. If a half splits into multiple components, they are emitted as separate `RESULTS_IN` targets, but only if every split-off component can leave the rest of its side geometrically (`has_trapped_component`, counted in `rule_stats.trapped_components`); otherwise the transition is dropped. | Makes "remove the last fastener in a three-part cluster" correctly produce three results, not one disconnected blob, without releasing a loose part that is still enclosed (the impeller after its cap nut). |
| 6 | **Forward-reachability filter** | A BFS from the full assembly through surviving `from_parts → results_in` chains builds the set of states actually reachable from the root. Transitions from non-reachable states are pruned. | Local filters are blind to global reachability. Without this, orphan transitions from states that nothing decomposes into would survive. |

The pair of **precedence guards** (3) and (4) are user-driven and rule-based; the other four are automatic and structural. Guards 1/2/5/6 enforce automatic semantic validity; guards 3/4 enforce optional user constraints. In the code, the fastener rule of filter 2 is a separate test with its own counter (`torn_fastener_joints`), both rule kinds are checked a second time against the groups that disintegration produces, and steps with the same from-state and the same results are recorded once (`duplicates`). `rule_stats` returns one count per test.

### Phase 3: KG population

*File: `models/kg_builder.py`.*

Three stages, each a single `session.execute_write` transaction; Stage 1 is preceded by a separate deletion of the product's existing nodes (`DETACH DELETE` on `product_id`):

| Stage | Writes | Reads from | Effect of a repeated run |
|---|---|---|---|
| 1 (structural) | `Product`, `Assembly`, `Component`/`Fastener`, `Connection`, `Transition` + `CONSISTS_OF`, `CONNECTS`, `OF_TYPE`, `USES_FASTENER`, `TRANSFORMS`, `RESULTS_IN` | structural JSON | same result on every run (deletes the product graph, tasks included, then MERGE) |
| 2 (operational) | `DisassemblyTask` + `ACTS_ON`, `PERFORMED_BY`, `USES_TOOL`, `REQUIRES`, `DISASSEMBLED_BY` | structural JSON + library | same result for the same input (MERGE) |
| 3 (properties) | nothing in the builder (`build_stage3_properties` has no automatic step); properties are `SET` on existing nodes through the natural language interface | - | - |

**Composite keys.** Every product-specific MERGE uses `{id, product_id}` together, never `id` alone. Two products can both declare a component with `partId: "A"` and end up with different Neo4j nodes that don't collide. Shared library nodes (`ConnectionType`, `Skill`, `Agent`, `Tool`) are matched by `id` alone and are referenced by every product.

**UNWIND batching.** All writes group their inputs into a list and use a single `UNWIND ... MATCH ... MERGE` call rather than a per-row loop. For the hypothetical product (114 transitions, 729 product-scoped relationships) this issues far fewer Neo4j round-trips than a per-row `tx.run()` loop.

**Multi-label pattern.** Four types carry a base label plus a specialised one, so they can be queried via either:

| Base label | Specialised label | Produced by |
|---|---|---|
| `Component` | `Fastener` | `kg_builder.py` (if `type == "Fastener"`) |
| `Task` | `DisassemblyTask` | `kg_builder.py` |
| `Skill` | `DisassemblySkill` | `library.py` |
| `Assembly` | `FastenerGroup` | `kg_builder.py` (only on an assembly state whose parts are exactly the members of a fastener group; no such state exists in the three shipped products) |

## The GraphRAG engine

*File: `rag/engine.py`.*

Three pipelines, routed by pattern-matching the user's question:

```
user question
    │
    ├── contains destructive verb (delete/remove/drop/...) ──► hard refusal, no LLM call
    │
    ├── looks like a reassignment  ──► _handle_reassignment
    │   (PERFORMED_BY / USES_TOOL / REQUIRES edge swap; DELETE + CREATE of these three relationship types only,
    │    no node created or deleted)
    │
    ├── looks like an enrichment   ──► _handle_mutation
    │   (MATCH + SET only; CREATE/MERGE/DELETE/REMOVE/DROP rejected; the seven protected properties
    │    and the shared library nodes cannot be SET)
    │
    └── otherwise                  ──► read pipeline
        (MATCH only; any write keyword rejected; Cypher executed; empty result → hard refusal;
         LLM formats the raw Neo4j result into prose/Markdown, streamed via SSE)
```

All three pipelines receive the same product-scoped schema description; each has its own prompt. Only the read pipeline uses the few-shot examples of `rag/examples.py` and a correction step: on a Neo4j error, the engine retries **once** with the failed query and the error appended to the prompt. The two write pipelines run their query once, after a code check of the generated Cypher (`check_enrichment_query`, `check_reassignment_query`). An empty read result is answered with a fixed refusal, not with model knowledge.

See [`docs/rag.md`](docs/rag.md) for the prompt layout, the keyword lists and the checks.

## Key design decisions: the "why" log

### Why flat `CONSISTS_OF` instead of nested assemblies

Every `Assembly` state (root and intermediate) links directly to its constituent `Component` entities via `CONSISTS_OF`. No `Assembly → Assembly` edges. Decomposition depth is carried entirely by the `Transition` chain (`TRANSFORMS`/`RESULTS_IN`).

This keeps the structural layer queryable in isolation: you can answer "which parts belong to state *Asm\_ABCD*?" with a single-hop query regardless of where that state sits in the AOG. Ontology-based work that nests `Assembly → Assembly` trees duplicates the decomposition logic both in the containment tree and the transition graph, creating two sources of truth that need to stay consistent.

### Why one `DisassemblyTask` per connection bundle, not per `Transition`

The same physical operation ("Pull Off Cap") can appear in multiple transitions when it is feasible from several intermediate states. Keying tasks by the connection they dissolve means one canonical task per physical operation, referenced by multiple transitions through `DISASSEMBLED_BY`. Duplicating tasks per transition would create redundant nodes whose properties (agent, tool, duration) would need to be kept in sync. When one operation dissolves several connections (the bolts of a fastener group, the pairwise connections of a three-part screwed joint), Phase 2 returns them as a `connection_bundles` entry and the builder creates one task with an `ACTS_ON` edge to every member (`models/kg_builder.py`); products without bundles fall back to one task per connection.

### Why the `Transition` is direction-agnostic

`TRANSFORMS` always points to the **larger** assembly; `RESULTS_IN` always points to the **smaller** parts. The `DisassemblyTask` attached via `DISASSEMBLED_BY` supplies the direction. This leaves the door open for a symmetric `AssemblyTask` to later attach to the same `Transition` node: the current codebase is disassembly-only but the schema does not foreclose reassembly workflows.

### Why UNWIND + composite keys + MERGE

- **UNWIND**: batch writes are faster and easier to reason about than per-row `tx.run()`.
- **Composite key `(id, product_id)`**: prevents two products from silently merging nodes when they happen to share a component letter.
- **MERGE everywhere**: no write creates a duplicate. Stage 1 first deletes the product's nodes (tasks included) and writes the structural layer; running it again gives the same structural graph, and Stage 2 has to follow to restore the tasks. Running Stage 2 again on the same input changes nothing.

### Why the skill map is both an in-graph `SUITABLE_FOR` edge **and** a Python dict

`library.py`'s `SUITABLE_FOR` edges are what the GraphRAG engine reasons over at query time ("which skills can handle a Screw Joint?"). `kg_builder.py`'s `_DIS_SKILLS` dict is the same mapping baked in for the write path: the builder resolves a task's required skill locally, without a round-trip to Neo4j. The two must stay consistent; if you change one, update the other. See [`docs/documentation-rules.md`](docs/documentation-rules.md) §"Coupled definitions".

### Why the test directions come from the contact surfaces

A part can start to move along a direction its mating surfaces allow: along the axis of a bore, away from a planar face. Deriving the test directions from the common surfaces (Prasad et al. 2022, Section 3) therefore tests the directions in which removals typically begin, including oblique ones such as the inclined tubes of the hypothetical product. The set is the union over all contacting pairs, and every direction is tested for every part. A fixed set of axes misses oblique removals. Faces under 1 mm², spheres and free-form faces contribute no direction, and the additional normal for incomplete surfaces of revolution is not implemented, so the direction set can be incomplete. Rotations and longer removal paths remain outside the model.

### Why the occlusion test looks from both sides

A part enclosed by another (the impeller inside the volute casing) never covers a pixel of the enclosing part, so test case 1 alone would let the casing slide sideways off the impeller. Prasad's second test case swaps the roles: the impeller moves in the opposite direction, and the casing wall between the camera and the impeller covers it. A pair is free only if neither view loses more than the tolerance. With both views the pump graph has 340 transitions, and none of them separates the impeller from the closed casing. The test is a pixel comparison along straight directions, not a proof of continuous collision freedom.

### Why phantom-state elimination is not optional

Without the phantom-state guard, the AOG would happily emit AND-arcs out of states like "screw still clamping two parts that are geometrically separable". Every downstream query (sequence enumeration, task reuse, tool-availability reasoning) then returns plausible but physically impossible results. The guard is a structural fix, not a post-hoc cleanup.

### Why write operations are gated in code and in the prompt

The GraphRAG engine rejects destructive phrases in the **natural-language question** first (`ask()` in `rag/engine.py`). The prompts then restrict what the model may generate. Finally the **generated Cypher** is checked in code before execution: the read path rejects every write keyword (`_execute_cypher`), the enrichment path accepts only `SET` of non-protected properties on product-specific nodes (`check_enrichment_query`), and the reassignment path accepts only the deletion and creation of `PERFORMED_BY`, `USES_TOOL` and `REQUIRES` relationships (`check_reassignment_query`). A question that passes the phrase filter and a model that ignores its prompt still meet the code check.

## File map

| File | Purpose |
|---|---|
| `app.py` | Flask REST API, SPA routing, subprocess orchestration for the STEP pipeline |
| `config.py` | Environment-variable loader with defaults |
| `models/kg_builder.py` | JSON → Neo4j, three-stage population with UNWIND; a rebuild replaces the product-scoped graph |
| `models/library.py` | Shared taxonomy: 15 `ConnectionType`, 14 `DisassemblySkill`, agents, tools, `SUITABLE_FOR` edges |
| `models/product.py` | Product CRUD, subgraph queries per view mode, sequence counting |
| `models/step_pipeline.py` | Pipeline orchestrator, Cocoa init, Phase-1 orchestration |
| `models/step_worker.py` | Subprocess entry point for Phase 1 (OCC isolation) |
| `pipeline/geometry.py` | STEP/XCAF loading, liaison matrix computation, overlap check |
| `pipeline/interference.py` | Test directions from the common surfaces; two-stage interference check (AABB prefilter after Algorithm 1 of Prasad et al. + GPU occlusion test from both sides) |
| `pipeline/two_step.py` | Two-step removals: parts that slide past their contact partners and then leave sideways |
| `pipeline/fastener_detection.py` | Regex-based fastener detection and group suggestion |
| `pipeline/aog_builder.py` | Thin wrapper around the bitmask AOG |
| `pipeline/aog_generation.py` | Bottom-up BFS AOG over integer bitmasks (AND/OR graph after Homem de Mello & Sanderson, 1990) |
| `pipeline/liaison_matrix.py` | Contact detection: gap matrix and contact threshold (`compute_contacts`) |
| `pipeline/bbox_projection.py` | Bounding-box projection along a test direction (footprint and depth interval for the prefilter) |
| `pipeline/part.py` | `Part`: shape, bounding box, id and name of one solid |
| `pipeline/settings.py` | Settings schema, the standard settings `STANDARD_SETTINGS` and the client-adjustable leaves `CLIENT_SETTINGS` |
| `pipeline/semantic.py` | Fastener semantics, group reduction, transition extraction with four semantic checks and optional precedence rules |
| `rag/engine.py` | GraphRAG: read / enrichment / reassignment pipelines with SSE streaming |
| `rag/schema.py` | Dynamic PPR schema description injected into every Cypher-generation prompt |
| `rag/prompts.py` | Prompt builders (Cypher generation, answer formatting, mutation, reassignment) |
| `rag/examples.py` | Product-scoped few-shot Cypher examples |
| `sample_data/ballpoint_pen.json` | 6-component benchmark |
| `sample_data/hypothetical_product.json` | 8-component hypothetical product with 114 transitions |

## OS-specific handling (macOS)

### The Cocoa problem

OCC's `Viewer3d` offscreen renderer requires `NSApplication.sharedApplication()` to be called before any OpenGL context is created. Without it, macOS raises `Aspect_WindowDefinitionError` and the process crashes with SIGSEGV.

### Why Flask cannot host OCC in-process

Flask has no Cocoa event loop. Running the GPU renderer in-process kills the server. The `fork` multiprocessing strategy inherits Flask's broken Cocoa state; `spawn` has to import OCC again in every worker.

### The fix

Phase 1 runs in an isolated subprocess (`models/step_worker.py`):

- `app.py` → `_run_step_phase1_subprocess()` launches the worker via `subprocess.run()`.
- The worker redirects fd 1 → fd 2 at the OS level **before** importing OCC so that C-level `printf` from OpenCASCADE goes to stderr.
- `_init_cocoa()` in `step_pipeline.py` calls `NSApplication.sharedApplication()` via pyobjc.
- The JSON result is written back to the original fd 1 after pipeline completion.
- `pyobjc-framework-Cocoa` must be installed in the OCC conda environment.

### Tkinter is forbidden

Do **not** use `tkinter.Tk()` anywhere in the pipeline. On macOS 15+, initialising tkinter after `NSApplication.sharedApplication()` causes `NSInvalidArgumentException` and crashes the process.

## Guard-rails for future changes

**Do not:**

- Treat a larger direction set or a part-level two-step release as proof of complete physical feasibility.
- Bypass `run_step_phase1` with direct calls to `check_interference` on its function defaults: `run_step_phase1` passes the standard settings, the bare function does not.
- Raise the pixel threshold for non-contacting pairs above zero: a small part in front of a large one covers only a few percent of it.
- Change `STANDARD_SETTINGS` without re-running the reference products (`pytest -m slow` covers the hypothetical product: 114 transitions).
- Add internal limits or switches (graph caps, `parallel`, distance prefilters) to `CLIENT_SETTINGS`: a request could exhaust or crash the server.
- Remove the phantom-state or broken-connection guard: both are load-bearing for correctness.
- Add atomicity pruning (single-part removals only): it blocks valid multi-part transitions.
- Replace the bitmask AOG with a set-based implementation: functionally equivalent, but slower.
- Use `fork` or import OCC outside the subprocess: SIGSEGV on macOS.
- Drop `product_id` from any product-scoped MERGE: silent cross-product collisions follow immediately.
- Let `_DIS_SKILLS` in `kg_builder.py` and `SKILL_SUITABILITY` in `library.py` drift apart.

**Do:**

- Run the hypothetical product through the full pipeline after any change to `pipeline/*` or `kg_builder.py`. Expected: 41 assemblies, 114 transitions, 6 disassembly tasks.
- Use `validate_structural_layer(driver, product_id)` to assert KG completeness after Stage 1.
- Add new multi-label types only where they give genuinely new query paths; every label has a maintenance cost.
- Update [`docs/schema.md`](docs/schema.md) whenever you add or remove a label or relationship type. Same for [`docs/input-format.md`](docs/input-format.md) when the JSON contract changes.

## Further reading

- [`docs/pipeline.md`](docs/pipeline.md): STEP → KG pipeline at line-level detail, with the four semantic checks and the optional precedence rules worked out
- [`docs/schema.md`](docs/schema.md): canonical schema reference
- [`docs/input-format.md`](docs/input-format.md): JSON input contract
- [`docs/rag.md`](docs/rag.md): GraphRAG engine internals
- [`docs/reproduce.md`](docs/reproduce.md): step-by-step reproduction of the reference use cases
- [`docs/documentation-rules.md`](docs/documentation-rules.md): how to keep these docs current when the code changes
- [`CONTRIBUTING.md`](CONTRIBUTING.md): code style, review process, testing expectations
