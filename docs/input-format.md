# JSON Input Format

The KG builder (`models/kg_builder.py`) consumes a single JSON object describing a product. This is the same object that `POST /api/products` expects as its body and that `pipeline/semantic.py` emits at the end of Phase 2. You can author it by hand for small products, or let the STEP pipeline build it for you.

The examples in `sample_data/` are the reference:

- [`sample_data/ballpoint_pen.json`](../sample_data/ballpoint_pen.json): the 6-component benchmark.
- [`sample_data/hypothetical_product.json`](../sample_data/hypothetical_product.json): the 8-component case with 2 screws and 114 transitions.

## Top-level shape

```json
{
  "product":      { "id": "...", "name": "..." },
  "components":   [ ... ],
  "connections":  [ ... ],
  "transitions":  [ ... ],

  "fastener_groups":        [ ... ],   // optional
  "connection_bundles":     { ... },   // optional; one task per bundle
  "liaison_matrix":         [[...]],   // optional, stored as provenance
  "separation_precedence":  [ ... ]    // optional; interpreted by Phase 2 only
}
```

Only the first four keys are required for building the KG. The remaining four are optional and are either used for provenance (`liaison_matrix`), by the KG builder (`connection_bundles`) or consumed by the semantic stage (`fastener_groups`, `separation_precedence`).

## `product`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Globally unique, short, URL-safe. Convention: `Prod_<CamelCaseName>`. Used as both `Product.id` and `product_id` everywhere. |
| `name` | string | yes | Human-readable. Displayed throughout the UI. |

## `components`

An array of component records. One entry per physical part after the flat XCAF extraction.

| Field | Type | Required | Notes |
|---|---|---|---|
| `partId` | string | yes | **One character** from the part alphabet of `pipeline/part_ids.py`: `A`–`Z`, then `a`–`z`, then `0`–`9` (62 symbols, so at most 62 parts). The builder validates this. The character is used throughout the pipeline for bitmask packing and assembly-state naming; this document calls it the letter. |
| `name` | string | yes | Human-readable. Used in UI and in `Connection.name` ("Body ↔ Cap"). |
| `type` | `"Part"` \| `"Fastener"` | no (default `Part`) | `Fastener` nodes receive the additional `:Fastener` label on top of `:Component`. |

> **Why letters?** Every representation in the AND/OR-graph (AOG) tradition (the assembly-plan formalism introduced by Homem de Mello & Sanderson (1990)) encodes subassemblies as bitmasks. Letters are the human-readable projection of the bit indices. `partId: "A"` corresponds to bit 0, `"B"` to bit 1, and so on. Assembly IDs are derived deterministically: the assembly containing parts A, C, and D is `Asm_ACD` (letters sorted).

## `connections`

An array of physical joints. Each entry becomes one `Connection` node plus its edges.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Convention: `Conn_<partLetters>` (`Conn_AB`, `Conn_AD_C` if fastener-mediated by C). |
| `part1` | string | yes | `partId` of one side. Must exist in `components`. |
| `part2` | string | yes | `partId` of the other side. |
| `connectionType_id` | string | yes | One of the 15 canonical IDs from [`schema.md`](schema.md#15-connectiontype) (`CT_ScrewJoint`, `CT_PressFit`, …). The closed set of 15 and the destructiveness property derive from the DIN 8593-1 (2003) joining-process taxonomy; `schema.md` is the canonical definition. |
| `agent_id` | string | yes | A library `Agent.id`, e.g. `Agent_HumanWorker`. |
| `tool_id` | string | yes | A library `Tool.id`, e.g. `Tool_None`, `Tool_AllenKey5mm`. |
| `fastener_id` | string \| `null` | no | Letter of the mediating fastener. Required for `ScrewJoint`-style joints where a fastener clamps `part1` and `part2` together. |
| `task_name` | string | no | Name of the disassembly task of this connection (of its bundle, if it is the canonical connection). Overrides the automatic name; the Studio writes it when the user edits a task name. |

Example of a screw joint:

```json
{
  "id": "Conn_AD_C",
  "part1": "A",
  "part2": "D",
  "connectionType_id": "CT_ScrewJoint",
  "agent_id": "Agent_HumanWorker",
  "tool_id": "Tool_AllenKey5mm",
  "fastener_id": "C"
}
```

Recording the mediating fastener on the joint (`fastener_id`) means that fasteners are not treated as undifferentiated removable entities. The platform carries the fastener explicitly because a `ScrewJoint`-style connection is dissolved by removing the fastener that clamps `part1` and `part2`, and binding the transition to that one Connection is the prerequisite for attaching a `DISASSEMBLED_BY` work instruction. The pipeline resolves these fastener constraints during semantic processing.

The required skill is resolved from `connectionType_id` during Stage 2; you do **not** supply a skill here. The builder reads it from the fixed dict `_DIS_SKILLS` in `models/kg_builder.py`, which mirrors the `SUITABLE_FOR` mapping of the library (`models/library.py:SKILL_SUITABILITY`). During operational enrichment, the contract carries only the structural classification, and the operational requirement is derived from it rather than hand-entered.

## `transitions`

An array of AND-arcs (the hyper-arcs of an AOG) that passed the four semantic checks and the optional precedence rules (see [`pipeline.md` §2.5](pipeline.md)). Each entry becomes one `Transition` node. The AND/OR-graph formalism these arcs come from is due to Homem de Mello & Sanderson (1990); the semantic processing that turns raw AOG output into the transitions documented here is implemented in `pipeline/semantic.py`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes (assigned by Phase 2 if produced by STEP) | Convention: `T01`, `T02`, … |
| `from_parts` | string | yes | Sorted letters of the **input** assembly. `"ABCDEF"` means `Asm_ABCDEF`. |
| `results_in` | array of strings | preferred | Sorted letters per resulting entity. One-letter entries denote a `Component`; multi-letter entries denote an `Assembly`. Example: `["ABCDE", "F"]`. |
| `removed_part` | string | optional | A convenience: the single letter removed by this transition. It is read only when `results_in` is absent. If both are present, `results_in` wins. |
| `broken_connection_id` | string | recommended | The `Connection.id` that this transition dissolves. If omitted, the KG builder tries to infer it by examining which connection's endpoints are split across the result halves. Explicit is better. |
| `broken_connection_ids` | array of strings | optional | Every `Connection.id` the transition dissolves (one per bundle), written by Phase 2. The builder links the transition to the task of each listed connection; without the field it uses `broken_connection_id` alone. |

Two valid equivalents for the same transition:

```json
{
  "id": "T01",
  "from_parts": "ABCDEF",
  "results_in": ["ABCDE", "F"],
  "broken_connection_id": "Conn_FA"
}
```

```json
{
  "id": "T01",
  "from_parts": "ABCDEF",
  "removed_part": "F",
  "broken_connection_id": "Conn_FA"
}
```

The second form produces `results_in = ["F", "ABCDE"]` after normalisation. Prefer the first for new data: it is explicit about multi-result transitions (where disintegration handling, Filter 5 of the semantic stage, emitted more than two children).

The `results_in` array, rather than a single `removed_part`, is what lets one `Transition` represent an AND-arc with three or more simultaneous results, for example a fastener removal that disintegrates a subset into several disconnected components. Standard disassembly precedence models capture only a single pairwise split; representing each connected component produced by a removal as its own `RESULTS_IN` target is what preserves multi-part separations as a queryable subgraph.

## `fastener_groups` (optional)

Used to compress identical fasteners before AOG generation. The KG builder reads the list for the `:FastenerGroup` label: the builder sets the label (with the property `groupName`) only on an assembly state whose parts are exactly the members of a fastener group. No such state exists in the three shipped products, so none of their nodes carries the label.

| Field | Type | Required | Notes |
|---|---|---|---|
| `group_id` | integer | yes | Arbitrary unique identifier. |
| `name` | string | yes | Display name, e.g. `"6x M20 bolt"`. |
| `members` | array of integers | yes | 0-based part indices (not letters). Member 0 is the group representative. |
| `contact_pattern` | array of integers | no | Indices of the non-fastener parts that every member contacts. Used by the group-suggestion step; not required by the KG builder. |

## `connection_bundles` (optional)

Emitted by Phase 2 (`pipeline/semantic.py`) and passed on unchanged by the Studio. Maps a canonical connection id to the ids of all connections that one operation dissolves: the members of a fastener group (six identical bolts are unscrewed as one operation) or the pairwise connections of one screwed joint that clamps three parts. The KG builder creates **one** `DisassemblyTask` per bundle; without the field every connection gets its own task, and the tasks of the non-canonical members are reachable from no transition.

```json
"connection_bundles": { "Conn_AT_E": ["Conn_AT_E", "Conn_AT_J", "Conn_AT_Q"] }
```

## `liaison_matrix` (optional)

A 2D integer array (0/1) of shape *N* × *N*. Stored as a JSON-serialised string on the `Product` node under the `liaison_matrix` property, purely as provenance. Not used for queries.

## `pipeline_settings` (optional)

A settings object as described in `pipeline/settings.py` (the settings of the Phase 1 run that produced the product). The builder stores it as a JSON-serialised string on the `Product` node under the `pipeline_settings` property, as provenance. Not used for queries.

## `separation_precedence` (optional, Phase 2 only)

A parameter of Phase 2 (`POST /api/step/generate-tables`, `pipeline/semantic.py`), where it is applied during transition extraction. It is **not** read by the KG builder: in a product JSON sent to `POST /api/products` the field has no effect, because the transitions in that file are already final.

`separation_precedence` adds extraction-path constraints that the interference analysis does not find, for instance a part that blocks another's removal although the two are not in direct contact. Phase 2 uses these rules to prune transitions that separate two parts while a required blocking part is still installed.

| Field | Type | Notes |
|---|---|---|
| `part1` | string | Letter. |
| `part2` | string | Letter. |
| `requires_removed` | array of strings | Letters of parts whose absence is required before `part1` and `part2` may be separated. |

Example: `{"part1": "H", "part2": "A", "requires_removed": ["B"]}` means "H cannot separate from A while B is still installed".

## Validation

Before building the KG, input is run through `models/kg_builder.py:validate_input`. The checks:

| Check | Severity |
|---|---|
| `product.id` and `product.name` present | error |
| Non-empty `components`, `connections`, `transitions` | error |
| Every `component.partId` is present | error |
| Every `connection.part1` / `part2` refers to a known `partId` | error |
| Every letter in `transition.from_parts` is a known `partId` | error |
| Every letter in `transition.results_in` is a known `partId` | error |
| Every `transition.removed_part` is a known `partId` (if set) | error |
| No "dead-end" assemblies (states produced by some transition but with no outgoing transitions of their own) | warning |

`POST /api/validate` runs only this validation without writing anything. Use it as a dry run.

## Minimal hand-authored example

```json
{
  "product": {
    "id": "Prod_Example",
    "name": "Two-part press fit"
  },
  "components": [
    { "partId": "A", "name": "Shell",  "type": "Part" },
    { "partId": "B", "name": "Insert", "type": "Part" }
  ],
  "connections": [
    {
      "id": "Conn_AB",
      "part1": "A",
      "part2": "B",
      "connectionType_id": "CT_PressFit",
      "agent_id": "Agent_HumanWorker",
      "tool_id": "Tool_None"
    }
  ],
  "transitions": [
    {
      "id": "T01",
      "from_parts": "AB",
      "results_in": ["A", "B"],
      "broken_connection_id": "Conn_AB"
    }
  ]
}
```

After `POST /api/products`:

- 1 `Product`, 1 `Assembly` (root, `Asm_AB`), 2 `Component`, 1 `Connection`, 1 `Transition`.
- 1 `DisassemblyTask` linked to the connection.
- Standard library references (`Agent_HumanWorker`, `Tool_None`, the auto-resolved `Skill_PullingOff` for PressFit).

That is enough to exercise every pipeline stage and see the KG render in the UI.

## References

The methods this input contract serves (the four semantic checks and optional precedence rules, disintegration handling, fastener-mediated connections, separation precedence, automated skill resolution) are described in the paper; see `README.md` for the citation. The prior work it builds on:

- **[11]** L. S. Homem de Mello, A. C. Sanderson, *And/or graph representation of assembly plans*, IEEE Transactions on Robotics and Automation 6 (2) (1990) 188–199. doi:10.1109/70.54734
- **[14]** S. Münker, R. H. Schmitt, *CAD-based AND/OR graph generation algorithms in (dis)assembly sequence planning of complex products*, Procedia CIRP 106 (2022) 144–149. doi:10.1016/j.procir.2022.02.169
- **[30]** Deutsches Institut für Normung, *DIN 8593-1:2003-09, Fertigungsverfahren Fügen – Teil 1: Zusammensetzen; Einordnung, Unterteilung, Begriffe*. doi:10.31030/9500685
