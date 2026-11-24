# Test suite

Run everything that works without OpenCASCADE:

```bash
python3 -m pytest --ignore=tests/test_golden_e2e.py
```

The full suite including the geometry golden test needs the `occ` conda
environment (see README → "STEP CAD pipeline"):

```bash
conda activate occ
python -m pytest
```

Note for macOS: run the golden test with the `occ` env even if your default
Python can import OCC: `_init_cocoa()` needs pyobjc (AppKit), and the raw
ctypes fallback can crash in sandboxed shells.

## Markers (pytest.ini)

| Marker | Meaning | When it runs |
| --- | --- | --- |
| `integration` | needs OpenCASCADE + sample STEP files | skipped automatically when `import OCC` fails (`conftest.requires_occ`) |
| `slow` | long-running geometry (detailed-solid distances) | excluded from quick runs with `-m "not slow"` |
| `rag_eval` | live GraphRAG eval: running app + seeded Neo4j + `OPENAI_API_KEY` | skipped unless `RAG_EVAL_BASE_URL` is set (e.g. `http://localhost:5050`) |

## Golden invariants

These counts are pinned by tests and must never change silently: they are the
regression net for the AND/OR-graph pipeline (any diff means the enumeration or
a pruning rule changed behaviour):

| Product | Parts | Contacts | Transitions | Guarded by |
| --- | --- | --- | --- | --- |
| Hypothetical Product (STEP) | 8 | 9 | **114** without any precedence rule (Phase 1 with `STANDARD_SETTINGS`: 6 test directions, automatic two-step release of the end plate; 6 connections, 41 assembly states; the geometric AND/OR graph before the semantic checks has 70 nodes, 8 single parts and 62 subassemblies). Adding the separation rule End plate before Shaft/Holder prunes nothing | `test_golden_e2e.py`, `test_prasad_config_e2e.py` |
| Centrifugal pump (STEP, reworked model) | 25 | 48 | **340** with two fastener groups (six M20, four M12 bolts), the cap nut as a part and the rule that shaft and impeller stay together while it is in place; test directions ±Y, ±Z; no transition separates the impeller from the closed volute casing | `test_pump_enclosure.py` (from the STEP file), `test_pump_enclosure_json.py` (from the product file) |
| Ballpoint pen (JSON) | 6 | 5 connections | **13** | `test_ballpoint_semantic.py` |

The pump test `tests/test_pump_enclosure.py` reads
`sample_data/Centrifugal Pump/centrifugal_pump.stp`. This STEP file is not
distributed with the repository (see
`sample_data/Centrifugal Pump/MODEL_CHANGES.md` for the source model and the
changes to apply). Without the file the test is skipped.
`tests/test_pump_enclosure_json.py` checks the same enclosure condition on the
shipped product file `sample_data/Centrifugal Pump/centrifugal_pump_product.json`
and always runs.

## Layout

- `test_golden_e2e.py`: full Phase 1→2 chain on the real STEP assembly (`requires_occ`, `slow`).
- `test_prasad_config_e2e.py`: Phase 1 with the standard settings on the Hypothetical Product: the six contact-derived directions, threshold independence, the automatic end-plate release and the 114 reference transitions (`requires_occ`, `slow`).
- `test_pump_enclosure.py`: centrifugal pump: the impeller stays enclosed by casing and cover; 340 transitions with the two fastener groups and the cap-nut rule (`requires_occ`, `slow`). Needs the pump STEP file, see the note above; skipped without it.
- `test_phase2_step_semantics.py`, `test_kg_task_links.py`: step semantics of Phase 2 and task links: the duplicate filter keeps different removals, no screwed joint is torn apart, every dissolved connection is recorded, the cap-nut rule; a step links to the task of every bundle it dissolves, and a task is named after a part of its own connection.
- `test_two_step.py`: the sampled collision search of `pipeline/two_step.free_travel`, incl. the thin head-on case (`requires_occ`).
- `test_interference_unmeasurable.py`, `test_interference_symmetry.py`, `test_common_surfaces.py`: a view without pixels counts as blocked; enclosure handling in the matrices and in disintegration; shared contact faces for the test directions.
- `test_fastener_bundle.py`, `test_fastener_suggestions.py`, `test_state_counting.py`, `test_rag_guard.py`: bundle semantics of fasteners clamping two or three parts, group suggestions, the connected-subset enumerator, and the destructive-request guard on disassembly vocabulary.
- `test_integration_pipeline.py`: geometry/interference integration (`requires_occ`).
- `test_semantic_pruning.py`, `test_aog_guards.py`, `test_semantic_rule_stats.py`: DB-free Phase-2 combinatorics: the four guard layers, precedence/separation rules, `rule_stats` counters, `estimate_only` contract.
- `test_ballpoint_semantic.py`, `test_task_naming.py`: operational layer: task derivation and naming priority (override > fastener > majority vote > part2).
- `test_graph_views.py`, `test_economics.py`: view condensation (REMOVES synthesis), placeholder economics enrichment.
- `test_sequence_count.py`: complete disassembly sequences (6 / 284 / 124,693 for pen, Hypothetical product and pump) and their orders of execution (12 / 360 / 8,883,888), computed by `models.product.count_sequences`, including sequences of different length.
- `test_pump_enclosure_json.py`: no transition in the shipped pump product file separates the impeller from the volute casing while the cover is mounted (108 transitions start from a state with impeller, casing and cover). Needs neither the STEP file nor OpenCASCADE.
- `test_aog_invariants.py`: the six structural properties of the AND/OR graph (`scripts/check_aog_invariants.py`: partition, reduction, connectedness, unique root, closure, reachability from the root) on the three sample products, the stored records, one failing case per property, and the additional progress check.
- `test_chat_starters.py`: the chat starter endpoint of the app.
- `test_demo_mode.py`, `test_demo_readonly.py`: the read-only demo tripwire: every write route must 403 under `DEMO_MODE=1`.
- `test_rag_eval_cases.py`: static guards over the 54-case question catalog (`rag_eval/cases.json`); `test_rag_eval_live.py` is the env-gated live run.
- `test_auto_threshold.py`, `test_mesh_distance.py`, `test_part_ids.py`, `test_pipeline_settings.py`, `test_settings_wiring.py`: unit tests for contact-threshold selection, mesh distance, the 62-symbol part-ID alphabet, and settings plumbing.

The tests are DB-free by design (pure functions over dict payloads, a recorder
in place of the Neo4j driver). Only the opt-in live run `test_rag_eval_live.py`
needs a running app with a seeded Neo4j; point it at a local instance, never a
shared or cloud instance.
