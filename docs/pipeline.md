# STEP → Knowledge Graph Pipeline

This document walks the pipeline one stage at a time, with file/line references and the exact reasoning behind each filter. It is the place to look when the code's output does not match your expectation and you need to understand *why*.

For the graph schema that the pipeline writes into, see [`schema.md`](schema.md). For the JSON contract produced by Phase 2 and consumed by the KG builder, see [`input-format.md`](input-format.md).

## Two entry points

Products can reach the KG through one of two paths:

1. **JSON upload**: `POST /api/products` with a fully assembled JSON body (see [`input-format.md`](input-format.md)). Skips Phases 1 and 2 entirely; the builder runs Stages 1–3.
2. **STEP upload**: `POST /api/step/run` for Phase 1, user confirmation in the UI, then `POST /api/step/generate-tables` for Phase 2 which produces the same JSON that a manual upload would, and finally `POST /api/products` to build the KG.

Below we walk the full STEP → KG path. The JSON path is the bottom half of it.

## Phase 1: Geometric extraction

*Subprocess entry point: `models/step_worker.py`. Called by `app.py:_run_step_phase1_subprocess()`.*

Phase 1 starts from the standard settings `pipeline.settings.STANDARD_SETTINGS`: `run_step_phase1` merges any explicit settings over them (`resolve_standard`; an invalid value keeps its standard value), and every entry point (Studio, `run_step_pipeline`, `seed_benchmark.py`, `diagnose_pipeline.py`) goes through it. Over HTTP a client may change only the leaves in `pipeline.settings.CLIENT_SETTINGS`, a developer feature for trying other settings; `app.py:_parse_pipeline_settings` drops every other leaf and the result lists it in `pipeline_settings_ignored`. The module-level defaults of the individual functions differ from the standard settings and only matter for direct function calls.

### 1.1 XCAF assembly parsing

*File: `pipeline/geometry.py`, `load_parts_from_assembly`.*

1. Open the STEP file with `STEPCAFControl_Reader`.
2. Enumerate **direct** children of the root assembly (`GetComponents(root, labels, subchilds=False)`). We intentionally do **not** recurse into nested sub-assemblies: the AOG operates on a flat part list and depth should come from the decomposition logic, not the containment hierarchy.
3. For each child label, resolve its *referred* (prototype) label. The part name is read from the prototype via `GetLabelName()`. The instance label carries only the placement transform and will return an empty name if queried directly: this is a recurrent XCAF pitfall.
4. Apply the instance's transform to the prototype's shape: `transformed_shape = shape.Located(location)`.
5. Duplicate names are de-duplicated with `_1`, `_2` suffixes, and each part receives a single-character canonical identifier (`A`–`Z`, then `a`–`z`, then `0`–`9`; at most 62 parts, `pipeline/part_ids.py`) used throughout the rest of the pipeline.

### 1.2 Contacts (liaison matrix)

*Files: `pipeline/liaison_matrix.py:compute_contacts`, `compute_gap_matrix`, driven from `pipeline/geometry.py:load_and_extract`.*

An *N* × *N* symmetric 0/1 matrix. `lm[i][j] = 1` iff the minimum distance between parts *i* and *j* is below the contact threshold. The distances form a **gap matrix**: a cheap analytic bounding-box distance is computed for every pair; for near pairs (bounding boxes within `near_bound_factor` × the characteristic part size, default 2) it is replaced by the exact `BRepExtrema_DistShapeShape` distance, and all other pairs keep the bounding-box distance, a lower bound far above any contact threshold. The gap matrix is therefore exact only for near pairs. This two-step distance computation is an implementation choice of the platform.

**Threshold: 0.5 mm.** Two parts are in contact when their minimum distance is below 0.5 mm. The value is a platform parameter. It is meant to separate touching pairs from clearly separated ones; whether it does so for a given model can be checked in the gap histogram of the Studio. The research group behind [31] determines contacts with the clash analysis of the CAD tool: a clash value of zero is contact, a negative value interference and a positive value clearance, and only surface contact counts (Bahubalendruni et al. 2019; Kumar et al. 2022). It uses no tolerance band. The pipeline counts every pair closer than 0.5 mm as a contact. Shared surfaces are computed only for pairs in contact and are needed only for the test directions (Section 1.4): a pair that touches only along an edge or at a point is a contact but contributes no direction. The data-driven `auto_contact_threshold` remains selectable through explicit settings for other product families; it is not used for the reference results.

### 1.3 Overlap check

*File: `pipeline/geometry.py:volume_overlaps`.*

The interference test assumes an assembly without volume overlaps: `BRepExtrema` returns 0 both for two solids that share a face and for two solids that occupy the same space, and the rendered silhouettes of overlapping parts cover each other. Overlapping parts (a thread modelled at nominal diameter inside its hole, a press fit modelled with oversize) can block each other in directions in which they would otherwise be free. This removes feasible transitions: on a variant of the Hypothetical Product whose M8 screws overlap the holder and the base plate, the pipeline generated no transition at all. Phase 1 therefore intersects every contacting pair (`BRepAlgoAPI_Common`) and reports pairs whose common volume exceeds 0.01 mm³: `volume_overlaps` in the result, a warning in the log and in the Studio. It is a warning only; the pipeline neither stops nor corrects the model, and an overlap does not imply that every direction is blocked. Correct the model before relying on the result. Bahubalendruni et al. (2019) likewise treat interpenetrating parts as an invalid model that has to be corrected in the design.

### 1.4 Test directions from the contact surfaces

*Files: `pipeline/interference.py:build_contact_directions`, `common_surfaces`, `_surface_axis`.*

The test directions come from the mating surfaces, as in Section 3 of Prasad et al. (2022) [31]. For every contacting pair, the common surfaces EC = S<sub>i</sub> ∩ S<sub>j</sub> (the envelope of contact of Bahubalendruni et al. 2019) are computed with the Open CASCADE General Fuse (`BRepAlgoAPI_BuilderAlgo`, fuzzy value = contact threshold): coinciding face regions come out as one face shared by both parts, faces that touch only along an edge share none. Each common surface contributes, in both senses:

| Common surface | Direction |
|---|---|
| plane | its normal |
| cylinder, cone, torus, surface of revolution | its axis |
| curved ruled surface that is not a surface of revolution | none; [31] takes the normal through the centroid (not implemented) |
| sphere, free-form surface | none (choice of this pipeline) |

Directions closer than 10⁻³ are merged; common surfaces under 1 mm² are dropped (`COMMON_SURFACE_MIN_AREA`, fuzzy slivers at chamfers). A pair that touches only along an edge or at a point shares no face and contributes no direction. One element of [31] §3 is not implemented: for an incomplete surface of revolution, [31] also takes the normal through the centre of the semicircle, perpendicular to the axis and pointing out of the open side (Fig. 10 of [31], instance 2). Where two half shells meet in a planar split face, that direction coincides with the normal of the split face, which is in the set as the normal of a common plane. The direction set can omit useful removal directions; rotations and longer paths are not searched.

The Hypothetical Product yields six directions (± shaft axis, ± Z, ± tube axis), the same three axes as Table 9 of [31]. In [31] the tubes are inclined at 45° to the shaft axis, in our STEP model at about 55°. The centrifugal pump yields four test directions, ± Y and ± Z. No component of the pump leaves along ± X only, and a run with 36 test directions, including ± X, yields the same transitions.

### 1.5 Interference matrices

*File: `pipeline/interference.py:check_interference`.*

One *N* × *N* matrix per test direction *d*: `ims[d][i][j] = 1` iff part *i*, translated along *d* to infinity, is blocked by part *j*. The check follows the computative strategic planning projections algorithm (CSPPA) of [31] in two stages.

**Stage 1: AABB prefilter** (`_stage1_bbox_overlap`): flag pair `(i, j)` whenever the 2D lateral projections of the two axis-aligned bounding boxes (AABB) overlap *and* `j.depth_max > i.depth_min`, i.e. part *j* is not entirely behind part *i* along *d* (it may lie ahead of, beside or partly behind *i*). This is the bounding-box test of Algorithm 1 of [31], written for the removal direction: [31] tests the assembly of part *P<sub>i</sub>* along *U* and discards *P<sub>j</sub>* only if `P_j.minU ≥ P_i.maxU`. With *d* = −*U*, the pairs it keeps are exactly those with `j.depth_max > i.depth_min`.

> The condition keeps the *mutual depth overlap* case, a holder around a longer shaft, where neither part is entirely behind the other, and leaves the decision to Stage 2.

**Liaison bypass** forces every contacting pair into Stage 2 regardless of Stage 1. Stage 2 still decides the final value.

**Stage 2, test case 1: occlusion seen from ahead** (`_visual_check_with_tolerance`). The camera sits on the +*d* side, ahead of the moving part, and looks back along −*d*, so an obstacle in the extraction path lies between the camera and the part. Part *i* is rendered alone in green, then together with part *j* in red; the share of green pixels lost is the occlusion ratio. Two details decide which pixels count:

- **Counting region:** only pixels inside the intersection of the bounding rectangles of the two rendered silhouettes, the interfering region of [31] §2.2 and the only place where *j* can cover *i*. [31] introduces it to save computation time; with exact pixel equality it does not change the result. With the 1 % threshold it is also the reference area of the ratio.
- **Silhouette edge:** independently of [31], pixels within 1 px of the part's silhouette are ignored. At flush fits (a tube end flush with the face around its bore) the shared outline lies at equal depth, and the renderer gives those pixels to the obstacle.

A contacting pair blocks when more than 1 % of the counted pixels are lost; a non-contacting pair blocks on any lost pixel. If the moving part renders no pixel in a view (ratio −1, not measurable), the pair counts as blocked, never as free, and a warning is logged.

**Stage 2, test case 2: the reverse view** (`_reverse_check`). [31] declares a pair free only if both counts stay unchanged: part *i* seen past part *j* (test case 1) and part *j* seen past part *i* in the opposite direction (test case 2). Test case 2 for `(i, j, d)` is test case 1 for `(j, i, −d)`, so the pipeline sets `ims[d][i][j] |= ims[−d][j][i]` for every pair. This detects enclosed parts: the impeller inside the volute casing is hidden in the casing's own view, but the casing covers the impeller in the reverse view.

> Why tolerances? [31] counts every lost pixel. At flush fits the shared outline lies at equal depth and the renderer gives the whole one-pixel ring to the obstacle: for a part that is small in the image, such as a tube end flush with the plate face around its bore, that ring is a large share of its pixels, along an axis the part slides freely out of. Ignoring the outermost pixel ring removes this; the 1 % threshold for contacting pairs covers the remaining single pixels at coincident surfaces. Together they replace the exact pixel comparison of [31].

The directions run **sequentially**. `check_interference` takes `parallel=False`, and the production caller (`models/step_pipeline.py`) does not override it. Each direction still gets its own deep-copied parts inside `_check_single_direction`, so the projection mutations of one direction never leak into another. An optional `parallel=True` `ThreadPoolExecutor` path exists, but nothing enables it: it is unsafe on macOS (`Viewer3d` creates Cocoa `NSWindow` objects that macOS requires on the main thread, and worker threads trigger `SIGABRT`) and only safe on Linux/headless builds.

### 1.6 Two-step removals

*Files: `pipeline/two_step.py:derive_two_step_releases`, applied with `pipeline/interference.py:apply_motion_releases`.*

The interference test asks whether a part can leave along *d* to infinity. A part that first has to slide a short way along *d* to clear its contact partners, and can then leave sideways, is reported as blocked along *d* by whatever lies further ahead. Phase 1 recognises such parts:

1. **Candidate:** part *i* is blocked along *d*<sub>1</sub>, and only by parts it does not touch.
2. **Minimum shift:** *i* has to leave the bounding boxes of its contact partners along *d*<sub>1</sub>.
3. **Free travel:** the shift at which *i* first overlaps one of the blockers with positive volume, searched on the exact B-rep with Open CASCADE (`free_travel`). The search is sampled: while the parts are apart it advances by their current minimum distance; on arrival (and at the start, if they already touch) it tests the overlap 0.05 mm further on; while they slide along each other it tests every 0.1 mm; the first overlap is refined by bisection to 0.05 mm. A feature that *i* passes completely within one step while sliding (combined thickness along *d* below 0.1 mm) can be missed.
4. **Second move:** if the minimum shift is below the free travel, *i* is placed at the midpoint of the interval (a choice of this pipeline). This intermediate position takes the role of the turning point of Yu & Wang (2013): the part reaches it along a first collision-free direction, and the interference test (test cases 1 and 2, same counting region and edge) is repeated from there against all other parts in every test direction except ±*d*<sub>1</sub>. Yu & Wang set the initial displacement to an integer multiple of the part's bounding length (their Section 3.6). The shifted part touches nothing, so every pair uses the threshold for non-contacting pairs (any lost pixel); a view in which the part renders no pixel counts as blocked. If one direction is free, the entries of *d*<sub>1</sub> against the distant blockers are cleared (`apply_motion_releases`).

The check runs for the single part *i* against the complete assembly; fewer parts can only block less. The release acts on matrix entries, so a subassembly that contains *i* and moves along *d*<sub>1</sub> is released from the same blockers, although the pipeline verifies the second move for *i* alone. The motion of the whole moving side as one body is not checked. Paths with three or more moves, rotation and tilting are not represented.

On the Hypothetical Product exactly one part qualifies: the end plate along the shaft axis (minimum shift 15 mm off the shaft end, free travel 21.956 mm up to the base plate, intermediate position 18.478 mm, then free along +Z). No manual rule is needed.

### 1.7 Fastener auto-detection (Tier 1)

*File: `pipeline/fastener_detection.py:detect_fasteners`.*

Regex matching on part names against a curated list:

```
screw, bolt, nut, washer, rivet, clip, pin, fastener, fixing,
set screw, grub screw, wing nut, flange nut,
M<digits>, ISO <3–5 digits>, DIN <3–5 digits>,
Schraube, Mutter, Scheibe, Bolzen, Stift, Niet,
hex socket, cap screw
```

Sealing elements (gasket, seal, O-ring) are not in the list: the `Fastener` label is reserved for components with a connecting or fixing function, and a seal closes a gap without holding parts together.

Matches are *suggestions*. Final fastener status is confirmed by the user in the UI before Phase 2. The regex set errs on the side of recall: false positives are easily unchecked in the UI; false negatives would cost the user more effort.

### 1.8 What Phase 1 returns

A JSON payload with:

- The part list (labels such as `Holder (A)`; the letter is the part ID).
- The liaison matrix, the gap matrix (exact for near pairs, lower bounds otherwise) and the contact threshold.
- The overlapping pairs (`volume_overlaps`; empty for a valid model).
- The test directions and one interference matrix per direction (after test case 2 and the two-step releases), plus the raw occlusion ratios (−1 where not evaluated or not measurable).
- The two-step releases (`two_step_releases`: part, first direction, cleared blockers, minimum shift, free travel, second directions).
- The fastener-detection log, the resolved settings (`pipeline_settings_resolved`) and the timing of every step.

This JSON is consumed by Phase 2 together with user-level decisions (confirmed fastener set, optional fastener groups, optional precedence rules).

## Phase 2: Semantic enrichment

*File: `pipeline/semantic.py:generate_semantic_tables`.*

Phase 2 turns raw geometry into the **Connection** and **Transition** entities the KG needs.

### 2.1 Fastener-mediated connections

For each confirmed fastener *F*, count its non-fastener neighbours in the liaison matrix:

| Neighbours of *F* | Action |
|---|---|
| 1 | emit a `PressFit` `Connection` between *F* and its single neighbour; `fastener_id` is **unset** because the neighbour is not clamping another part |
| 2 | emit one `ScrewJoint` `Connection` between the two clamped parts with `fastener_id = F`. Suppress the direct contact between the two clamped parts in the *semantic* liaison matrix (the original is kept for the KG's `Product.liaison_matrix` property). |
| 3 | emit three pairwise `ScrewJoint` connections (one for every pair of clamped parts), each with `fastener_id = F`. Suppress all three direct contacts in the semantic matrix. |
| 0 | log a warning; no connection is created for this fastener |
| 4 or more | Phase 2 stops with an error: the pipeline models fastener joints for up to three clamped parts |

**Why the suppression?** Without it, a bolt through two plates would produce one `ScrewJoint` *plus* a spurious `PressFit` between the plates because they touch at the clamping surface. That would double-count the joint and hand the AOG an extra degree of freedom it does not physically have.

### 2.2 Direct non-fastener contacts

Every remaining `semantic_lm[i][j] == 1` where neither *i* nor *j* is a fastener becomes one `PressFit` `Connection`. These are the default classification and are editable by the user in the UI.

### 2.3 Fastener-group reduction (optional)

*Function: `_merge_fastener_groups`.*

If the caller supplies `fastener_groups`, the AOG input is compressed:

1. For each group, take the lowest-indexed member as the *representative*.
2. OR-merge the representative's row and column with those of the other members in both the liaison matrix and every interference matrix.
3. Delete the non-representative rows and columns.
4. Record a `group_expansion` map: `rep_letter → [all member letters]`.

The AOG then runs on the reduced matrices. After extraction, every transition's letters are expanded back through `group_expansion` so downstream stages see the original parts, not the representatives.

For products with many identical fasteners the reduction keeps the AOG tractable: the pump result (340 transitions) uses two groups, six M20 and four M12 bolts. Members of a group can only be removed together; removal orders of individual members are not enumerated. For the Hypothetical Product (`sample_data/Hypothetical Product STEP/Hypothetical_Product_Passungen.step`) the Studio suggests grouping the two M8 screws. The reference result of 114 transitions and 41 states is obtained without accepting that suggestion; with the group accepted the pipeline generates 38 transitions and 17 states.

### 2.4 AOG generation

*Files: `pipeline/aog_builder.py:build_aog` → `pipeline/aog_generation.py:AOG`.*

Bottom-up BFS over the AND/OR-graph formalism (Homem de Mello & Sanderson, 1990) [11]. Subassemblies are represented as **integer bitmasks**: bit *i* set iff part *i* is present. This gives:

- O(1) disjointness: `(bm1 & bm2) == 0`.
- O(1) union: `bm1 | bm2`.
- O(popcount) cardinality.

Binary splits are the candidate set. For each candidate split `(A = moving, B = remaining)` the algorithm checks:

- **Separability**: there exists at least one direction *d* where no part in `B` blocks any part in `A`. Implemented as a bitmask AND against the packed interference vectors.
- **Connectivity**: `A` is one connected component under the liaison graph restricted to `A`, and likewise for `B`. Implemented as a BFS on a bitmask adjacency representation.

Above 50 000 candidate pairs the validation runs in parallel via `ProcessPoolExecutor` with the **`spawn` context** (not `fork`: fork is unsafe with OCC on macOS; the AOG module doesn't import OCC so spawn is clean).

The algorithm returns a tree with all reachable subassembly nodes and their AND-arc children.

> **No atomicity pruning.** Many AOG formulations restrict each transition to a single-part removal. We deliberately keep the full set of binary splits, so one transition may produce two multi-part subassemblies at once. This is required for a topologically complete AND/OR graph: a restriction to single-part removals drops valid multi-part transitions (see [Deterministic reproduction](#deterministic-reproduction)).

### 2.5 Transition extraction: four semantic checks and optional precedence rules

This semantic processing turns raw AOG output into an operational representation. For every AND-arc the AOG emits, the following steps run in order:

```
AND-arc ─► (1) phantom-state guard       (skip or keep)
        ─► (2) broken-connection check   (skip or attach Connection.id)
        ─► (3) part-precedence guard     (skip or keep)  [if rules supplied]
        ─► (4) separation-precedence     (skip or keep)  [if rules supplied]
        ─► (5) disintegration handling   (expand multi-component results)
 after the per-arc loop:
        ─► (6) forward-reachability      (drop orphan transitions)
```

Steps 1, 2, 5 and 6 are the four semantic checks of the paper (phantom-state guard, broken-connection check, disintegration handling, forward reachability); they always run. Steps 3 and 4 are the optional precedence rules; they run only when the caller provides the corresponding rules. The headings below number the steps as Filter 1 to Filter 6.

#### Filter 1: Phantom-state guard

*Marked by the `PHANTOM-STATE GUARD` comment in `semantic.py`; uses `get_connected_components`.*

For each AOG node, expand the contained-parts bitmask to letters and run `get_connected_components` over the **semantic connection graph**. The semantic graph's rule for `ScrewJoint` edges: an edge is active only when **the fastener and both clamped parts are simultaneously present**. A state where the fastener has been removed but the two clamped parts are still together produces no active screw-edge, so those parts are no longer connected via the screw.

If the state is not one connected component under that rule, the AOG node is discarded, no transitions are emitted out of it. This rejects "phantom states" that are geometrically coherent but semantically impossible, such as a screw removed while the clamped parts still appear joined. Encoding the `ScrewJoint` edge as active only when the fastener and both clamped parts are present makes the connectivity test itself reject these states, so the guard is the structural fix: geometrically feasible but semantically impossible nodes never emit a transition.

#### Filter 2: Broken-connection check

*Functions: `tears_fastener_joint`, `dissolved_connections`.*

A split that separates parts held by a fastener while the fastener stays with one of them is rejected first (`rule_stats.torn_fastener_joints`): a screwed joint is dissolved only by removing its fastener. For the remaining AND-arcs `(sub1, sub2)`, walk the list of defined `Connection` entities and collect every connection the split severs:

- For a direct joint (`PressFit`, `LooseFit`): the two parts end on opposite sides.
- For a `ScrewJoint`: the fastener ends on one side and every clamped part still present ends together on the other side. The bundle of one fastener counts once.

If no connection qualifies, the transition is discarded (`rule_stats.no_broken_connection`). Otherwise all ids are stored on the transition as `broken_connection_ids` (one per fastener bundle, bundles first), the first one also as `broken_connection_id`; the KG links the transition to the task of each dissolved bundle (`DISASSEMBLED_BY → ACTS_ON`). Candidates with the same input state and the same results are kept once (`rule_stats.duplicates`).

The AOG hyper-arc is itself connection-agnostic: it records a state change but not *which* physical join the change dissolves. Binding each surviving transition to every `Connection` it severs is what joins the structural layer to the operational one: `broken_connection_ids` are the keys for `DISASSEMBLED_BY → ACTS_ON`, so one graph traversal recovers both the state change and the work instructions that perform it. This integration is not expressible in the AOG formalism alone.

#### Filter 3: Part-precedence guard

*Function: `_violates_precedence`. Only active if `precedence_rules` is supplied.*

A rule `{X: [Y]}` means "X cannot leave the assembly while Y is still mounted", *unless* Y itself is the single part being removed on its side. This models:

- X is pulled away with Y still installed → rule applies → reject.
- Y is removed alone → X and Y simply end up on different sides because Y was the removed leaf → no violation → accept.

#### Filter 4: Separation-precedence guard

*Function: `_violates_separation_precedence`. Only active if `separation_precedence` is supplied.*

A rule `{part1: P1, part2: P2, requires_removed: [R1, R2, …]}` means "P1 and P2 cannot end on opposite sides while any of `R1, R2, …` is still present in the union `sub1 ∪ sub2`".

This is the expressive form used for cases where the blocker is not a direct neighbour of the separating pair, e.g. the EndPlate blocks the extraction path of the Shaft out of the Holder even though naïve part-precedence rules only chain adjacent neighbours.

#### Filter 5: Disintegration handling

*Marked by the `DISINTEGRATION HANDLING` comment block in `semantic.py`.*

After the split has passed filters 1–4, each resulting half is **re-segmented** through `get_connected_components`. If a half splits into multiple components (e.g. removing the last screw in a three-part cluster leaves the remaining parts mutually disconnected), every component becomes its own `RESULTS_IN` target rather than the half being kept as a single Assembly.

Without this step, the KG would contain transitions whose results are Assemblies that are internally disconnected: a contradiction in terms.

**Trapped components.** Semantically loose is not geometrically free: a part that no connection holds can still be enclosed by the rest of its side. Before a split-off component is emitted as its own result, `has_trapped_component` (`pipeline/semantic.py`) peels the components of the side off one at a time; each must be separable from the union of the remaining ones in at least one test direction, using the same separability test as the AOG. If one cannot leave, the transition is dropped and counted in `rule_stats.trapped_components`.

Disassembly precedence graphs represent a single linear path with strictly pairwise ordering. Re-segmenting each half so every connected component becomes its own `RESULTS_IN` target lets one transition represent a simultaneous three-way (or *n*-way) separation, and lets a fastener-mediated cluster disintegrate into several Assemblies at once, while every resulting branch remains a queryable subgraph.

#### Filter 6: Forward-reachability

*Marked by the `REACHABILITY FILTER` comment block in `semantic.py`, after the per-arc loop.*

A BFS from the full assembly through surviving `from_parts → results_in` chains builds the set of states reachable from the root. Transitions whose `from_parts` is **not** in that set are pruned.

Local filters are blind to global reachability: a transition can survive filters 1–5 but originate in a state that, post-filtering, nothing decomposes into. This pass removes those orphans so every surviving transition lies on at least one end-to-end disassembly path.

### 2.6 What Phase 2 returns

`generate_semantic_tables` returns a dict with:

- `success` and `error`: whether the run completed, and the error message otherwise.
- `connections`: one entry per Connection node to be created (with `id`, `part1`, `part2`, `connectionType_id` and, for a screwed joint, `fastener_id`).
- `connection_bundles`: a map from the canonical connection of a bundle to all connection ids that one operation dissolves (the pairwise connections of one fastener and, with fastener groups, those of every group member). One task is created per bundle.
- `semantic_liaison_matrix`: the liaison matrix after the direct contacts of clamped parts are suppressed.
- `transitions`: one per surviving AND-arc, with `id`, `from_parts`, `results_in`, `broken_connection_id`, `broken_connection_ids` (every connection the step dissolves), and for single-part removals a convenience `removed_part` field.
- `aog_estimate`: the size estimate computed before generation.
- `rule_stats`: the number of candidates each check removed.
- `log`: the processing log.

The components and the fastener groups are not part of this result. The Studio adds them from the Phase 1 result and the user's choices when it assembles the product JSON documented in [`input-format.md`](input-format.md).

## Phase 3: KG population

*File: `models/kg_builder.py`.*

Three stages, each a single `session.execute_write` transaction.

### Stage 1: Structural foundation

*Function: `build_stage1_structural`.*

Creates, via UNWIND-batched MERGE:

| Nodes | Relationships |
|---|---|
| `Product` | `Product -[CONSISTS_OF]-> Assembly` (root) |
| `Assembly` (root and intermediates; the label `:FastenerGroup` is added only to an assembly state whose parts are exactly the members of a fastener group) | `Assembly -[CONSISTS_OF]-> Component` (for root **and** every intermediate assembly, one edge per contained component) |
| `Component` / `:Component:Fastener` | `Connection -[CONNECTS]-> Component` (×2) |
| `Connection` | `Connection -[OF_TYPE]-> ConnectionType` |
| `Transition` | `Connection -[USES_FASTENER]-> Fastener` (optional) |
|  | `Transition -[TRANSFORMS]-> Assembly` (the larger one) |
|  | `Transition -[RESULTS_IN]-> Assembly \| Component` (multiple, AND encoding) |

Every product-specific MERGE uses the composite key `(id, product_id)`. Before writing, the stage deletes every node with this `product_id` (`DETACH DELETE`), tasks and custom properties included. Running it again on the same input therefore gives the same structural graph, and Stage 2 has to run again to restore the tasks.

### Stage 2: Operational enrichment

*Function: `build_stage2_operational`.*

Via UNWIND-batched MERGE:

- One `DisassemblyTask` per connection bundle: a single connection (keyed as `Task_Dis_<connection-id-suffix>`) or the members of a `connection_bundles` entry that one operation dissolves, such as a fastener group or a three-part screwed joint (keyed as `Task_Dis_Grp_<removed part>`). Multiple transitions that dissolve the same connection all link to this single task via `DISASSEMBLED_BY`: task reuse across assembly states falls out of the schema rather than needing explicit deduplication. Prior ontology-based disassembly approaches keep operational task data in a model populated independently of the structural representation; here the operational layer is anchored directly onto the immutable structural layer, so there is no parallel model that can drift out of sync.
- `DisassemblyTask -[ACTS_ON]-> Connection`, one edge per connection of the bundle.
- `DisassemblyTask -[REQUIRES]-> DisassemblySkill`, resolved via the `_DIS_SKILLS` dict that mirrors `library.py`'s `SKILL_SUITABILITY`.
- `DisassemblyTask -[PERFORMED_BY]-> Agent`.
- `DisassemblyTask -[USES_TOOL]-> Tool`.

The task name follows a deterministic priority convention (`models/kg_builder.py`):

| Priority | When | Example |
|---|---|---|
| 0 | The connection carries an explicit `task_name` (set in the Studio review) | the given name |
| A | The connection has a `fastener_id` (screw joint) | `Unscrew <fastener.name>` (for a fastener group `Unscrew 6x <name>`) |
| B | No fastener; the part that most often leaves across all transitions breaking this connection (majority vote) | `Pull Off <part.name>` |
| C | Fallback: the connection's `part2` | `Snap Out <part2.name>` |

This ordering prevents ambiguous or misleading names in edge cases such as "transitions where both parts of a PressFit could equally be 'the removed one'". The majority vote is a heuristic; the Studio shows the automatic name as a suggestion (`POST /api/step/task-names`, same code as the build) so that it can be corrected before the build.

### Stage 3: Property enrichment

*Function: `build_stage3_properties`.*

Property enrichment (material, duration, cost and similar properties on existing nodes) is carried out through the natural language interface: an enrichment request is translated into a query that `SET`s properties on existing nodes (see [`rag.md`](rag.md)). The builder function of this stage has no automatic step: it writes nothing and returns a summary with `properties_set: 0`.

## Validation after Stage 1

*Function: `validate_structural_layer` in `kg_builder.py`.*

A lightweight integrity check, run by the endpoint `POST /api/products/<id>/structural` after Stage 1:

- Counts every label under the product.
- Verifies every `Transition` has at least one `RESULTS_IN` edge.
- Verifies every `Connection` has `CONNECTS` edges.

Returns `{is_valid, counts, errors}`. Errors are non-blocking warnings (the KG is still built) but they surface malformed input early.

## Deterministic reproduction

For the two reference validation cases the expected outputs are:

| Case | Components | Connections | Transitions | Assemblies | Disassembly tasks |
|---|---|---|---|---|---|
| Ballpoint pen | 6 | 5 | 13 | 9 | 5 |
| Hypothetical product | 8 (incl. 2 fasteners) | 6 (2 `ScrewJoint` + 1 `LooseFit` + 3 `PressFit`; the STEP route proposes `PressFit` for holder–shaft, set to `LooseFit` in the prepared data) | 114 | 41 | 6 |

The ballpoint pen is the assembly-sequencing example described by Lambert (2006), who attributes it to Bourjault (1984) [33]; its AND/OR graph in the prepared JSON (9 states, 13 transitions) is the one of Iwase (2025, Fig. 10a) [34]. The hypothetical product is the eight-component case of Kumar et al. (2021) [32]: six structural parts and two rivets, modelled here as two M8 screws. [32] publishes the liaison matrix, an omnidirectional feasibility matrix and a stability matrix of the product (Figs. 3, 4 and 6); it contains no AND/OR graph. The AND/OR graph with 41 states and 114 transitions is generated by this pipeline.

The STEP-based count of the hypothetical product comes out without any precedence rule (the ballpoint pen has no STEP file): its end plate leaves in two moves (Section 1.6). If your run produces different numbers, check the overlap warning of Phase 1 first (Section 1.3), then the fastener-group and precedence-rule inputs: the knobs that change the AOG size. See [`reproduce.md`](reproduce.md) for the full replay.

## References

Prior methods that this pipeline adopts or deviates from are attributed inline. The reference numbers are those of this documentation, not those of the paper; author–year entries are additional sources of Phase 1.

- **[11]** L. S. Homem de Mello, A. C. Sanderson, *And/or graph representation of assembly plans*, IEEE Transactions on Robotics and Automation 6 (2) (1990) 188–199. doi:10.1109/70.54734
- **[14]** S. Münker, R. H. Schmitt, *CAD-based AND/OR graph generation algorithms in (dis)assembly sequence planning of complex products*, Procedia CIRP 106 (2022) 144–149. doi:10.1016/j.procir.2022.02.169
- **[31]** V. S. S. Vara Prasad, M. Hymavathi, C. S. P. Rao, M. V. A. Raju Bahubalendruni, *A novel computative strategic planning projections algorithm (CSPPA) to generate oblique directional interference matrix for different applications in computer-aided design*, Computers in Industry 141 (2022) 103703. doi:10.1016/j.compind.2022.103703
- **[32]** G. Anil Kumar, M. V. A. R. Bahubalendruni, V. S. S. Prasad, K. Sankaranarayanasamy, *A multi-layered disassembly sequence planning method to support decision making in de-manufacturing*, Sādhanā 46 (2) (2021) 102. doi:10.1007/s12046-021-01622-3
- **[33]** A. J. D. Lambert, *Disassembly planning*, Eindhoven University of Technology (2006), Figure 19, p. 35 (PDF p. 36). This figure attributes the example to Bourjault (1984). [Source document](https://pure.tue.nl/ws/portalfiles/portal/4412407/607395.pdf).
- **[34]** S. Iwase, *AND/OR graph generation for disassembly analysis: Deeply-nested subassemblies represented by a hypergraph*, International Journal of Production Research 63 (8) (2025) 3035–3063. doi:10.1080/00207543.2024.2416560. Fig. 10a.
- **Bahubalendruni et al. (2019)** M. V. A. R. Bahubalendruni, A. Gulivindala, M. Kumar, B. B. Biswal, L. N. Annepu, *A hybrid conjugated method for assembly sequence generation and explode view generation*, Assembly Automation 39 (1) (2019) 211–225. doi:10.1108/AA-01-2018-014
- **Kumar et al. (2022)** G. A. Kumar, M. V. A. R. Bahubalendruni, V. S. S. V. Prasad, D. Ashok, K. Sankaranarayanasamy, *A novel geometric feasibility method to perform assembly sequence planning through oblique orientations*, Engineering Science and Technology, an International Journal 26 (2022) 100994 (online 2021; cited in [31] as Kumar et al. 2021). doi:10.1016/j.jestch.2021.04.013
- **Yu & Wang (2013)** J. Yu, C. Wang, *Method for discriminating geometric feasibility in assembly planning based on extended and turning interference matrix*, International Journal of Advanced Manufacturing Technology 67 (2013) 1867–1882. doi:10.1007/s00170-012-4615-0
