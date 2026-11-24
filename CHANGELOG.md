# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-24

First public release, the reference implementation of the paper *"A knowledge
graph schema for disassembly planning with integrated AND/OR disassembly logic"*
(Bluvstein et al., *Journal of Manufacturing Systems*, under review).

### Contents

- **Schema** (`docs/schema.md`): a Product-Process-Resource knowledge graph in
  Neo4j with ten entity types and twelve relationship types. Assembly states and
  transitions encode the AND/OR graph; tasks, skills, agents and tools carry the
  operational knowledge. A shared library holds 15 connection types, 14 skills,
  3 agents and 7 tools.
- **Population pipeline** (`models/kg_builder.py`): builds the graph of a product
  from a JSON description in a structural and an operational stage. A transition
  links the tasks of all connection bundles it dissolves; one task serves all
  transitions that dissolve the same bundle.
- **Geometric analysis** (`pipeline/geometry.py`, `pipeline/interference.py`,
  `pipeline/two_step.py`): reads a STEP assembly, computes contacts (minimum
  distance below 0.5 mm), derives the test directions from the shared surfaces of
  contacting parts, tests directional interference with a bounding-box prefilter
  and an occlusion test from both sides, reports overlapping parts and recognises
  parts that leave in two straight moves.
- **AND/OR graph generation with semantic checks** (`pipeline/aog_builder.py`,
  `pipeline/semantic.py`): fastener-mediated connections, optional grouping of
  identical fasteners, bottom-up AND/OR graph generation and the extraction of
  transitions with four semantic checks plus optional precedence rules.
- **GraphRAG interface** (`rag/`): natural-language questions are translated to
  Cypher, executed on Neo4j and answered from the returned rows. Empty results
  lead to a refusal, and write requests are restricted to property enrichment
  and resource reassignment.
- **Web interface** (`static/`): product dashboard with graph views, chat,
  library editor and the Pipeline Studio, the interactive workflow from a STEP
  file to the knowledge graph. A read-only demo mode (`DEMO_MODE`) with Docker
  files is included.
- **Three use cases** (`sample_data/`): the ballpoint pen (9 assembly states,
  13 transitions), the hypothetical product (41 assembly states, 114 transitions,
  with the STEP assembly) and the centrifugal pump (25 components, 40
  connections, 102 assembly states, 340 transitions, 20 tasks). The pump is
  provided as a prepared product file. Its STEP file is not distributed
  (GrabCAD terms of use); `sample_data/Centrifugal Pump/MODEL_CHANGES.md` links
  the source model and lists the changes made to it.
- **Evaluation catalogues and records** (`rag_eval/`, `scripts/`): the question
  catalogues of the hypothetical product (33 questions) and the pump
  (27 questions) with the runner, the recorded runs, the repeated-question
  records and the state-space counts.
- **Documentation**: `README.md`, `ARCHITECTURE.md`, and the Markdown
  references in `docs/`.
- **Tests** (`tests/`): a pytest suite for the pipeline, the graph builder, the
  sequence counts, the GraphRAG guards and the read-only mode. Tests that need
  OpenCASCADE or the pump STEP file are skipped when these are not available.
