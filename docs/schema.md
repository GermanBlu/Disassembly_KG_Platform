# Neo4j Schema Reference

> **This document is the canonical schema source.** If the code changes, update this file in the same PR. If this file and the code disagree, the **code** is the ground truth and this file is a bug.
>
> Scholarly works that prior methods are attributed to are listed under [References](#references).

The Knowledge Graph follows the **Product–Process–Resource (PPR)** paradigm (ISO 15531; Cutting-Decelle et al., 2007 [29]), adopted here to organise the schema's three domains. Ten base entity types, three core specialisation labels, an optional FastenerGroup label and twelve relationship types are organised across three domains: the *product* domain (what the artefact is), the *process* domain (how it is decomposed and which tasks dissolve which connections), and the *resource* domain (what skills, tools, and agents are needed).

Several entity types additionally carry a **specialised label** on top of a base label; these are noted below.

## Entity types

### Product domain

| Label | Scope | Key properties | Purpose |
|---|---|---|---|
| `Product` | per-product | `id`, `name`, `product_id`, `input_data`, `liaison_matrix` | Root node for a single product instance. Exactly one per ingested product. |
| `Assembly` | per-product | `id`, `name`, `product_id`, `isState` (always `true`), `isRoot` (`true` only on the full assembly), optional `groupName` | A subassembly state in the AOG. The root assembly and every reachable intermediate state are individual `Assembly` nodes. |
| `Component` | per-product | `id`, `name`, `partId`, `product_id` | An atomic part that is not further decomposed in this product. |
| `Fastener` | per-product | `id`, `name`, `partId`, `product_id` | Specialisation of `Component`. Carries **both** labels (`:Component:Fastener`). |
| `Connection` | per-product | `id`, `name`, `product_id` | A physical joint between two or more components. The builder stores every `Connection` between two `Component` entities (`part1`, `part2`); a joint of more than two components is stored as several pairwise connections that share one fastener and one task. |
| `ConnectionType` | **shared** | `id`, `name`, `destructiveness` ∈ {`Non-destructive`, `Semi-destructive`, `Destructive`} | Taxonomic category of a join, following the joining-process classification of DIN 8593-1 [30]. See [library](#shared-library-populated-once) for the canonical 15. |

### Process domain

| Label | Scope | Key properties | Purpose |
|---|---|---|---|
| `Transition` | per-product | `id`, `name`, `product_id` | A direction-agnostic decomposition step. Encodes one AND-arc of the AOG and anchors the operational layer (see the operational table below). |
| `Task` | per-product | `id`, `name`, `taskType`, `product_id` | Base label for work instructions. Never appears alone in the current codebase: always co-labelled with `DisassemblyTask`. Reserved for future symmetric `AssemblyTask`. |
| `DisassemblyTask` | per-product | (same as `Task`) | A concrete disassembly operation. Carries **both** labels (`:Task:DisassemblyTask`). |

### Resource domain

| Label | Scope | Key properties | Purpose |
|---|---|---|---|
| `Skill` | **shared** | `id`, `name`, `type` | Base label for capabilities. Co-labelled with `DisassemblySkill`. |
| `DisassemblySkill` | **shared** | (same as `Skill`) | A specific disassembly capability. Carries **both** labels (`:Skill:DisassemblySkill`). |
| `Agent` | **shared** | `id`, `name`, `agentType` ∈ {`Human`, `Robot`, `AutomatedStation`}, `description` | An entity capable of performing tasks. Carries the value of `agentType` as a second label (for example `:Agent:Human`). |
| `Tool` | **shared** | `id`, `name`, `toolType` ∈ {`HandTool`, `PowerTool`}, `description` | A specific instrument used for task execution. Carries the value of `toolType` as a second label (for example `:Tool:HandTool`). |

### Specialisation labels (not counted separately)

| Base label | Specialisation label | Created by | Used for |
|---|---|---|---|
| `Assembly` | `FastenerGroup` | `kg_builder.py`, only on an assembly state whose parts are exactly the members of a fastener group (no such state exists in the three shipped products) | Marking an assembly state that consists of one group of identical fasteners |
| `Agent` | `Human`, `Robot`, `AutomatedStation` | `library.py`, from the `agentType` property | Filtering agents by kind |
| `Tool` | `HandTool`, `PowerTool` | `library.py`, from the `toolType` property | Filtering tools by kind |

**Label convention:** 10 base entity types + 3 core specialisation labels (`Fastener`, `DisassemblyTask`, `DisassemblySkill`) + the optional `FastenerGroup` label. The subtype labels of `Agent` and `Tool` mirror a property value and are not counted either. These labels are distinct from the 12 relationship types.

> **Counting labels:** specialisation labels are listed separately from their base labels. The implementation in `models/library.py` and `models/kg_builder.py` is the ground truth per `documentation-rules.md` §3.

### Scope conventions

- **per-product** nodes carry a `product_id` property equal to the `Product.id` they belong to. Every `MATCH` / `MERGE` on a per-product node **must** constrain on `product_id`. Two products can both declare a component with the same `partId` without colliding.
- **shared** nodes have no `product_id`. They are seeded once by `library.py` and referenced by every product. Do not constrain them by `product_id`.

## Relationship types

### Structural (Stage 1)

| Relationship | Direction | Cardinality | Meaning |
|---|---|---|---|
| `CONSISTS_OF` | `Product → Assembly`; `Assembly → Component` | Product has exactly one outgoing edge; each Assembly has one edge per constituent component | Flat membership. Every assembly state (root and intermediate) links to its constituent components. No `Assembly → Assembly` nesting. |
| `CONNECTS` | `Connection → Component` | exactly 2 per `Connection` | Which two parts a connection joins. |
| `OF_TYPE` | `Connection → ConnectionType` | exactly 1 per `Connection` | The taxonomic category. |
| `USES_FASTENER` | `Connection → Fastener` | 0 or 1 per `Connection` | Optional, which `Fastener` mediates this join (for `ScrewJoint` and similar). |
| `TRANSFORMS` | `Transition → Assembly` | exactly 1 per `Transition` | Points to the **larger** (input) assembly being decomposed. |
| `RESULTS_IN` | `Transition → Assembly` \| `Component` | ≥ 2 per `Transition` | Points to the **smaller** resulting entities produced by the decomposition. Multiple edges encode the AND relationship. |

### Operational (Stage 2)

In the AND/OR-graph (AOG) formalism a decomposition step carries no operational information, and PPR manufacturing ontologies such as MASON [20], PSL [21], and MaRCO [19] assume the process sequence is already known. The direction-agnostic `Transition` here both encodes the AOG state change (`TRANSFORMS` / `RESULTS_IN`) and anchors the operational layer through `DISASSEMBLED_BY → DisassemblyTask`, so a single traversal retrieves the structural decomposition together with its full operational context (connection dissolved, skill required, tool needed, agent performing). Decoupling `Transition` from `DisassemblyTask` additionally lets one task be reused across multiple assembly states. This role links structural and operational information in one graph.

| Relationship | Direction | Cardinality | Meaning |
|---|---|---|---|
| `DISASSEMBLED_BY` | `Transition → DisassemblyTask` | 1 or more per `Transition`: one to the task of every connection bundle the transition dissolves | Links a structural decomposition to the work instructions that perform it; all linked tasks belong to the transition, none is an alternative to another. |
| `ACTS_ON` | `DisassemblyTask → Connection` | ≥ 1 per task | Every physical `Connection` this one operation dissolves. A task keyed to a fastener group or a multi-part screwed joint acts on all of the bundle's connections (pump: "Unscrew 6x M20" acts on 18); simple joints keep exactly one. |
| `REQUIRES` | `DisassemblyTask → Skill` | 1 | The capability needed. Resolved automatically from the connection type. |
| `PERFORMED_BY` | `DisassemblyTask → Agent` | 1 | Who or what performs the task. Assigned per connection. |
| `USES_TOOL` | `DisassemblyTask → Tool` | 1 | Which specific instrument is used. Assigned per connection. |

### Library (shared)

| Relationship | Direction | Meaning |
|---|---|---|
| `SUITABLE_FOR` | `Skill → ConnectionType` | Which connection types a skill can handle. Used by GraphRAG queries; mirrored in `kg_builder.py`'s `_DIS_SKILLS` for write-path resolution. |

**Count:** 12 relationship types (6 structural + 5 operational + 1 library).

## Encoding the AND/OR graph

The AND/OR-graph (AOG) formalism was introduced for assembly planning by Homem de Mello & Sanderson (1990) [11] (a hyper-arc is one operation, AND denotes simultaneously produced child states, and OR denotes alternative decompositions) and later applied to disassembly as the reverse of assembly [12]. Classical AOG representations and the OWL-based disassembly information model of Zhu & Roy [23] mark AND/OR explicitly as hyper-arc constructs in a separate symbolic layer. Here the logic is carried by property-graph topology alone: multiple `Transition` nodes on one `Assembly` are the OR, and multiple `RESULTS_IN` edges from one `Transition` are the AND. No dedicated `AND` or `OR` label is stored, so the complete feasible-sequence space remains a directly traversable subgraph rather than a separate construct. Concretely, it falls out of the graph topology:

- **OR** (alternative decompositions at the same assembly state): multiple `Transition` nodes with `TRANSFORMS → sameAssembly`.
- **AND** (the results that together constitute one decomposition): multiple `RESULTS_IN` edges from the same `Transition`.
- **Precedence** (what must happen before what): implicit in the `RESULTS_IN → TRANSFORMS` chain. If `T_A` produces an Assembly that `T_B` decomposes, then `T_A` precedes `T_B`. No explicit precedence relation is stored.

A **feasible disassembly sequence** is a walk that:

1. Starts at the root `Product`, follows `CONSISTS_OF` to the root `Assembly`.
2. At every `Assembly` encountered, selects exactly one outgoing-via-`TRANSFORMS` `Transition` (OR selection).
3. For the selected transition, visits all `RESULTS_IN` targets (AND expansion).
4. Recursively applies steps 2–3 to any resulting `Assembly` node until only `Component` leaves remain.

These walks enumerate the disassembly sequences represented by the stored AOG. The ballpoint-pen reference case yields 6 complete disassembly sequences (12 orders of execution).

## Shared library (populated once)

Seeded by `models/library.py → build_library` on the first `POST /api/library/ensure` call. Stays constant across products.

### 15 `ConnectionType`

The 15 types and their `destructiveness` classification are derived from the joining-process taxonomy of DIN 8593-1 [30]. Together with the `SUITABLE_FOR` bridge from `DisassemblySkill` (below), `ConnectionType` is what makes resource-to-structure reasoning possible, for example, tracing an unavailable tool back through tasks and transitions to the connection types it affects. Such cross-domain queries are not representable within the AOG formalism, which is why the joining taxonomy is modelled as a first-class shared entity rather than a free-text property.

| `id` | `name` | `destructiveness` |
|---|---|---|
| `CT_ScrewJoint` | Screw Joint | Non-destructive |
| `CT_ClampJoint` | Clamp Joint | Non-destructive |
| `CT_PressFit` | Press Fit | Non-destructive |
| `CT_SnapJoint` | Snap Joint | Non-destructive |
| `CT_KeyJoint` | Key Joint | Non-destructive |
| `CT_Containment` | Containment | Non-destructive |
| `CT_LooseFit` | Loose Fit | Non-destructive |
| `CT_PinJoint` | Pin Joint | Semi-destructive |
| `CT_AdhesiveBond` | Adhesive Bond | Semi-destructive |
| `CT_FlangeJoint` | Flange Joint | Semi-destructive |
| `CT_WeldJoint` | Weld Joint | Destructive |
| `CT_SolderJoint` | Solder Joint | Destructive |
| `CT_SeamJoint` | Seam Joint | Destructive |
| `CT_CrimpJoint` | Crimp Joint | Destructive |
| `CT_StakedJoint` | Staked Joint | Destructive |

### 14 `DisassemblySkill` (one per connection-type category; `PressFit` and `KeyJoint` share `PullingOff`)

`Unscrewing`, `Unclamping`, `PullingOff`, `SnappingOut`, `DrivingOut`, `Separating`, `CuttingOff`, `Desoldering`, `Unbending`, `RippingSeam`, `CuttingOpen`, `GrindingOff`, `Draining`, `Picking`.

### 3 `Agent`

`Agent_HumanWorker`, `Agent_Robot`, `Agent_AutomatedStation`.

### 7 `Tool`

`Tool_Tweezers`, `Tool_FlatScrewdriver`, `Tool_AllenKey5mm`, `Tool_PullOffTool`, `Tool_CombinationWrench18mm`, `Tool_CombinationWrench30mm`, `Tool_None` (manual). All seven are seeded with `toolType` `HandTool`.

### `SUITABLE_FOR` mapping

Defined in `library.py → SKILL_SUITABILITY` and also baked into `kg_builder.py → _DIS_SKILLS` for the write path. **The two must stay consistent.** See [`documentation-rules.md`](documentation-rules.md) §"Coupled definitions".

## Example: the ballpoint pen after Stage 2

After ingesting `sample_data/ballpoint_pen.json` (6 components, 5 connections, 13 transitions), the graph contains:

```
 1 × Product  (Prod_BallpointPen)
 9 × Assembly (1 root + 8 intermediate states)
 6 × Component (A=Body, B=Head, C=Cartridge, D=Ink, E=Button, F=Cap)
 5 × Connection (each with 2× CONNECTS + 1× OF_TYPE)
13 × Transition (each with 1× TRANSFORMS + ≥2× RESULTS_IN + 1× DISASSEMBLED_BY)
 5 × DisassemblyTask (one per connection bundle; each with ACTS_ON ≥1, PERFORMED_BY, USES_TOOL, REQUIRES)
```

Plus the shared library (15 `ConnectionType`, 14 `DisassemblySkill`, 3 `Agent`, 7 `Tool`). The `MATCH (t:Transition {product_id: 'Prod_BallpointPen'})` query returns 13 nodes, one per hyper-arc of the AND/OR graph in Iwase (2025, Fig. 10a).

## Schema at a glance

```
           ┌─────────┐
           │ Product │
           └────┬────┘
                │ CONSISTS_OF  (1 edge)
                ▼
           ┌──────────┐
           │ Assembly │  (root, isRoot=true)
           └──┬──┬────┘◄──────────────── TRANSFORMS ───────┐
              │  │                                         │
              │  │ CONSISTS_OF                             │
              │  ▼                                         │
              │  ┌───────────┐                       ┌─────┴──────┐
              │  │ Component │◄── RESULTS_IN ────────│ Transition │
              │  └───────────┘                       └──────┬─────┘
              │                                             │
              │  (intermediate                              │ DISASSEMBLED_BY
              │   Assembly states                           │
              │   link the same way)                        ▼
              │                                      ┌──────────────────┐
              │                                      │ DisassemblyTask  │
              │                                      │ (:Task:Disas...) │
              │                                      └─┬──┬──┬──┬───────┘
              │                                        │  │  │  │
              │                          ACTS_ON ◄─────┘  │  │  │
              │                                           │  │  │
              │                          REQUIRES ◄───────┘  │  │
              │                                              │  │
              │                          PERFORMED_BY ◄──────┘  │
              │                                                 │
              │                          USES_TOOL ◄────────────┘
              │
              ▼
     ┌────────────┐ OF_TYPE ┌────────────────┐
     │ Connection │────────►│ ConnectionType │ (shared)
     └─────┬──────┘         └────────┬───────┘
           │ CONNECTS (×2)           │
           ▼                  SUITABLE_FOR
     ┌───────────┐                   │
     │ Component │                   ▼
     └───────────┘            ┌──────────┐
                              │  Skill   │ (shared)
                              └──────────┘
```

## Changing the schema

When you add, rename, or remove a label or relationship, update in lockstep:

1. This document: the authoritative reference.
2. `rag/schema.py`: the description injected into every Cypher-generation prompt.
3. `rag/prompts.py`: any rule that mentions the changed item.
4. `rag/examples.py`: the few-shot examples.
5. `models/kg_builder.py`: the writer.
6. `docs/input-format.md` if the JSON contract changes.
7. `docs/pipeline.md` if any pipeline stage is affected.
8. The Cypher snippets in `README.md`.

See [`documentation-rules.md`](documentation-rules.md) for the full checklist.

## References

Prior methods that this schema adopts or deviates from are attributed inline. The reference numbers are those of this documentation, not those of the paper.

- **[11]** L. S. Homem de Mello, A. C. Sanderson, *And/or graph representation of assembly plans*, IEEE Transactions on Robotics and Automation 6 (2) (1990) 188–199. doi:10.1109/70.54734
- **[12]** H. Wang, D. Xiang, Y. Rong, L. Zhang, *Intelligent disassembly planning: a review on its fundamental methodology*, Assembly Automation 33 (1) (2013) 78–85. doi:10.1108/01445151311294801
- **[19]** E. Järvenpää, N. Siltala, O. Hylli, M. Lanz, *The development of an ontology for describing the capabilities of manufacturing resources*, Journal of Intelligent Manufacturing 30 (2) (2019) 959–978. doi:10.1007/s10845-018-1427-6
- **[20]** S. Lemaignan, A. Siadat, J.-Y. Dantan, A. Semenenko, *Mason: A proposal for an ontology of manufacturing domain*, in: IEEE Workshop on Distributed Intelligent Systems (DIS'06), IEEE, 2006, pp. 195–200. doi:10.1109/dis.2006.48
- **[21]** M. Grüninger, *Using the PSL ontology*, in: S. Staab, R. Studer (Eds.), Handbook on Ontologies, Springer, Berlin and Heidelberg, 2009, pp. 423–443. doi:10.1007/978-3-540-92673-3_19
- **[23]** B. Zhu, U. Roy, *Modeling and validation of a web ontology language based disassembly planning information model*, Journal of Computing and Information Science in Engineering 18 (2) (2018). doi:10.1115/1.4039849
- **[29]** A. F. Cutting-Decelle, R. Young, J. J. Michel, R. Grangel, J. Le Cardinal, J. P. Bourey, *ISO 15531 MANDATE: A product-process-resource based approach for managing modularity in production management*, Concurrent Engineering 15 (2) (2007) 217–235. doi:10.1177/1063293x07079329
- **[30]** Deutsches Institut für Normung, *DIN 8593-1:2003-09, Fertigungsverfahren Fügen. Teil 1: Zusammensetzen. Einordnung, Unterteilung, Begriffe*. doi:10.31030/9500685
