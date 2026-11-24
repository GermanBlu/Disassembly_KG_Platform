# KG_Platform: Product-Process-Resource Knowledge Graph Platform

Reference implementation of the knowledge graph schema and population pipeline described in the paper **"A knowledge graph schema for disassembly planning with integrated AND/OR disassembly logic"** (Bluvstein et al., *Journal of Manufacturing Systems*, under review). The platform was developed at the Institute for Machine Tools and Industrial Management (iwb), Technical University of Munich.

- **Architecture overview:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Detailed references:** [`docs/`](docs/README.md) (schema, pipeline, input format, GraphRAG, reproduction)
- **Reproducing the paper:** [section below](#reproducing-the-paper) and [`docs/reproduce.md`](docs/reproduce.md)
- **Citation:** [section below](#citing-this-work) and [`CITATION.cff`](CITATION.cff)
- **License:** [MIT](LICENSE); bundled third-party files are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)

## Purpose
Disassembly planning needs more than a list of components or a set of geometric sequences. Product structure, alternative decomposition steps, tasks, tools and agent capabilities need to be connected and accessible together. CAD-based AND/OR graphs describe decomposition possibilities but do not provide operational knowledge or an accessible interface for querying it by themselves.
KG_Platform addresses this gap by using a Product-Process-Resource (PPR) schema in a knowledge graph. It enables the connection of assembly states and disassembly transitions to connections, fasteners, tasks, skills, tools and agents. The platform supports CAD-based graph generation, operational enrichment and natural-language access through a browser interface.

## What the platform provides

- A PPR schema that represents AND/OR decomposition and operational knowledge
- A STEP file to KG pipeline with geometric analysis, fastener grouping and semantic transition filtering.
- Product and resource editors, interactive graph views and a GraphRAG interface that generates Cypher queries and answers from retrieved graph data.
- Three reference use cases: the ballpoint pen, the hypothetical product and the centrifugal pump (industrial scalability case).

The implementation separates graph consistency from physical feasibility. In particular, the current geometric generation method does not detect every enclosure or extraction constraint. The evaluation documents these limits alongside the measured results.

## Documentation guide

| Document | What to find there |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Components, data flow and operating details. |
| [`docs/schema.md`](docs/schema.md) | Entities, relationships, AND/OR encoding and task-to-connection bundles. |
| [`docs/pipeline.md`](docs/pipeline.md) | Geometric extraction, fastener grouping, transition filters and graph population. |
| [`docs/input-format.md`](docs/input-format.md) | JSON product file. |
| [`docs/rag.md`](docs/rag.md) | Query generation, enrichment and write guards of the GraphRAG interface. |
| [`docs/reproduce.md`](docs/reproduce.md) | Reproduction of the reference use cases. |


---

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | |
| Neo4j | 5.9+ | Complete-sequence retrieval uses quantified path patterns. Neo4j Desktop or AuraDB. |
| OpenAI API key | - | For the GraphRAG chat engine |

### 1. Clone & Install

The project runs on **macOS, Linux and Windows**. All entry points
(`run.py`, `run.sh`, `run.bat`) auto-detect the host OS and pick the right
interpreter / path conventions, no per-OS code edits needed.

**macOS / Linux:**

```bash
git clone https://github.com/GermanBlu/Disassembly_KG_Platform.git KG_Platform
cd KG_Platform

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/GermanBlu/Disassembly_KG_Platform.git KG_Platform
cd KG_Platform

py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Set Up Neo4j

**Option A, Neo4j Desktop (recommended for local dev):**

1. Download and install [Neo4j Desktop](https://neo4j.com/download/)
2. Create a new project and add a **Local DBMS** (Neo4j 5.9 or later)
3. Set a password (you'll need it for `.env`)
4. Start the database
5. The default bolt URI is `bolt://localhost:7687`

**Option B, Neo4j AuraDB (cloud, free tier available):**

1. Create an account at [console.neo4j.io](https://console.neo4j.io)
2. Create a free AuraDB instance
3. Note the connection URI (e.g. `neo4j+s://xxxxx.databases.neo4j.io`) and password

### 3. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
NEO4J_URI=bolt://localhost:7687       # or neo4j+s://... for AuraDB
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-5.4-mini              # any supported OpenAI chat model
PORT=5050
```

`gpt-5.4-mini` is the default in `config.py`. The GraphRAG evaluation of the paper was run with `OPENAI_MODEL=gpt-6-luna`; set this value to reproduce it.

### 4. Run the Application

Pick whichever entry point matches your shell, they all delegate to the
same cross-platform launcher (`run.py`):

```bash
# macOS / Linux
./run.sh
# or:  python3 run.py

# Windows (cmd)
run.bat
# Windows (PowerShell)
py -3 run.py
```

The application starts at [http://localhost:5050](http://localhost:5050).

### 5. Initialize the Library

Open the **Library** page to inspect the shared connection types, skills, agents and tools. In normal mode, the backend initializes the library when it is accessed and before product creation. There is no separate initialization button in the current dashboard. The API also exposes `POST /api/library/ensure` for explicit initialization.

### 6. Add a Product

Either:

- Use the **Pipeline Studio** (`/#/new`), drop a STEP assembly or import a prepared JSON, review, build
- Or upload one of the sample JSON files from `sample_data/`:
  - `ballpoint_pen.json`, simple 6-component product
  - `hypothetical_product.json`, 8-component benchmark with 114 transitions
  - `Centrifugal Pump/centrifugal_pump_product.json`, 25-component pump (ten bolts in two fastener groups; the cap nut is a part) with 40 connections, 20 tasks and 340 transitions. The STEP file is not included (GrabCAD terms of use): `Centrifugal Pump/MODEL_CHANGES.md` links the GrabCAD model and lists the changes, after which the same graph can be regenerated in the Studio by accepting the two suggested fastener groups, unticking the cap nut as a fastener and adding the rule that shaft and impeller stay together while the cap nut is in place

---

## STEP CAD Pipeline (Optional)

The STEP pipeline processes CAD assembly files to automatically extract components, compute liaison matrices, detect interferences, and generate disassembly sequences. This is **completely optional**, all other features work without it.

### Installing OpenCASCADE (pythonocc-core)

pythonocc-core requires conda (it is not available via pip on most
platforms). The conda commands below are identical on macOS, Linux and
Windows, `conda activate occ` works the same in bash, zsh, cmd and
PowerShell once conda is on your PATH.

```bash
# Create a dedicated conda environment
conda create -n occ python=3.10 -y
conda activate occ

# Install OpenCASCADE bindings
conda install -c conda-forge pythonocc-core -y

# Install the platform's Python dependencies into this env too
pip install -r requirements.txt

# macOS only: required for subprocess GPU rendering
pip install pyobjc-framework-Cocoa
```

Then run the application from within the conda environment:

```bash
conda activate occ
python run.py        # cross-platform; same command on Mac/Linux/Windows
```

`app.py` automatically discovers the `occ` env in the standard conda
install locations on all three OSes (`/opt/miniconda3/envs/occ`,
`~/miniconda3/envs/occ`, `%USERPROFILE%\miniconda3\envs\occ`,
`C:\ProgramData\miniconda3\envs\occ`, …), so the STEP subprocess works
without configuration as long as conda is installed in a conventional spot.

### How It Works

The STEP workflow has three phases: geometric extraction, semantic generation and knowledge-graph population. The first two produce the product data before it is written to Neo4j:

**Phase 1, Geometric Analysis** (`POST /api/step/run`):

Phase 1 runs with the standard settings `pipeline.settings.STANDARD_SETTINGS` (Studio, `seed_benchmark.py`, `diagnose_pipeline.py`). As a developer feature, a client can change the values listed in `pipeline.settings.CLIENT_SETTINGS` to try other settings (Studio: "Developer settings"); the server ignores every other value and names it in the result.

- Loads STEP assembly files via XCAF (with assembly-position transforms)
- Extracts individual parts and their bounding boxes
- Computes the liaison matrix: two parts are in contact when their minimum distance is below 0.5 mm (exact BRep distance for near pairs, a bounding-box lower bound for all others); the gap histogram is an inspection display
- Reports contacting pairs with a common volume above 0.01 mm³ as overlap warnings; overlapping parts can block removals that would otherwise be free
- Derives the test directions from the surfaces that contacting parts share (plane normals, axes of revolution)
- Detects interference along every test direction: bounding-box prefilter plus forward and reverse visual tests, using overlap-region counting, one-pixel edge exclusion, 1% contact tolerance and zero non-contact tolerance; a view in which the moving part renders no pixel counts as blocked
- Recognises parts that leave in two straight moves (automatic two-step releases, a part-level heuristic)
- Auto-detects fasteners by part name (screw, bolt, nut, etc.)

The two-step release checks individual parts rather than full group motions, and its free-travel search is sampled. Phase 1 does not certify the physical feasibility of every transition.

**Phase 2, Semantic Enrichment** (`POST /api/step/generate-tables`):

- User confirms fastener tags via the UI
- Optionally groups identical fasteners with the same contact pattern for AOG generation. On the pump, six M20 and four M12 fasteners form two groups. Individual fastener entities remain in the product graph
- Optionally defines **separation precedence rules** (e.g. "EndPlate must be removed before Shaft and Holder can separate")
- Generates ScrewJoint / PressFit connections from the liaison matrix
- Builds AND/OR Graph (AOG) via bottom-up BFS with bitmask representation
- Extracts transitions using the phantom-state guard, broken-connection check, precedence and separation-precedence checks, disintegration handling (split-off parts must be able to leave the rest geometrically), duplicate elimination and forward reachability filtering. Counts for these checks are returned for review

**Phase 3, KG Population:**

- Stage 1 deletes the existing product-scoped graph (all nodes with this `product_id`, tasks included) and writes the structural nodes and relationships
- Stage 2 attaches operational tasks, connection bundles, skills, agents and tools with `MERGE`
- Stage 3, property enrichment, is carried out through the natural language interface: an enrichment request is translated into a query that `SET`s properties on existing nodes (see [`docs/rag.md`](docs/rag.md)). The builder function of this stage (`build_stage3_properties`, `POST /api/products/<id>/properties`) has no automatic step and writes nothing. Single properties can also be set with `PATCH /api/products/<id>/nodes/<node_id>/properties`

A structural rebuild replaces the product graph and can remove custom product properties. It is not an incremental merge.

> **Cross-platform note:** Phase 1 runs in a separate subprocess on all OSes for clean isolation of OpenCASCADE's renderer from Flask's process. On macOS this is mandatory (Cocoa/NSApplication init is required and would conflict with Flask's event loop). On Windows and Linux the separate subprocess also provides isolation. The Cocoa init is automatically skipped on non-macOS platforms, no user action needed.

### Checking OCC Availability

`GET /api/step/check` returns whether pythonocc-core is installed and usable.

### Benchmark Seeding

To seed the Hypothetical Product benchmark from the assembly STEP file:

```bash
conda activate occ
python3 seed_benchmark.py
```

The script reads `sample_data/Hypothetical Product STEP/Hypothetical_Product_Passungen.step`, runs Phase 1 with the standard settings and Phase 2 without precedence rules or fastener groups, and writes the product to the Neo4j database configured in `.env` (the product-scoped graph of `Prod_HypotheticalProduct` is replaced). It needs OpenCASCADE and a running Neo4j and should report 6 connections and 114 transitions. `python3 seed_benchmark.py --help` prints the description without running anything.

### Pipeline Diagnostics

To trace the full pipeline (liaison matrix, interference, AOG, transitions) with detailed output:

```bash
conda activate occ
python3 diagnose_pipeline.py
```

This runs Phase 1 with the standard settings, as the platform does, and outputs pairwise part distances, the liaison matrix, the test directions, the interference matrices per direction, the two-step removals, a separability analysis and the transition counts. Results are saved to `diagnostic_output.json`.

---

## Architecture

The same architecture supports the ballpoint pen, hypothetical product and centrifugal pump. Each product has its own structural graph and references the shared operational library. The pump extends the evaluation to an industrial scalability case with grouped fasteners and three-part joints. Schema and processing decisions are explained in [`docs/schema.md`](docs/schema.md) and [`docs/pipeline.md`](docs/pipeline.md).

```
KG_Platform/
├── app.py                  Flask REST API + SPA routes
├── config.py               Environment variable configuration (loads .env)
├── seed_benchmark.py       Seed benchmark product from assembly STEP (needs Neo4j)
├── seed_demo_product.py    Seed the product of the read-only demo
├── diagnose_pipeline.py    Full pipeline diagnostic (dev tool)
├── eval_rag.py             GraphRAG evaluation runner (cases in rag_eval/)
├── requirements.txt        Python dependencies
├── pytest.ini              Test configuration and markers
├── run.py                  Cross-platform startup launcher (OS-detecting)
├── run.sh                  POSIX shell wrapper around run.py (macOS/Linux)
├── run.bat                 Windows wrapper around run.py
├── .env.example            Environment variable template
├── Dockerfile.demo         Image of the read-only demo
├── docker-compose.demo.yml Read-only demo with Neo4j (see docs/demo-deployment.md)
├── ARCHITECTURE.md         Technical architecture and design decisions
├── CHANGELOG.md            Release notes
├── CITATION.cff            Citation metadata
├── CONTRIBUTING.md         Contribution guide
├── LICENSE                 MIT license
├── THIRD_PARTY_NOTICES.md  Licenses of the bundled third-party scripts
│
├── models/
│   ├── product.py          Product CRUD & subgraph queries
│   ├── kg_builder.py       JSON → Neo4j graph construction (3-stage)
│   ├── library.py          Shared taxonomy management
│   ├── economics.py        Economic property helpers
│   ├── step_pipeline.py    STEP CAD file processing orchestrator
│   └── step_worker.py      Subprocess entry point for Phase 1 (OCC isolation)
│
├── pipeline/
│   ├── geometry.py         STEP/XCAF loading, liaison matrix computation
│   ├── interference.py     Contact-derived directions, two-stage interference check (AABB + GPU visual)
│   ├── two_step.py         Automatic two-step releases
│   ├── aog_builder.py      Entry point of the AND/OR graph generation
│   ├── aog_generation.py   AND/OR graph generation via bottom-up BFS
│   ├── liaison_matrix.py   Contact detection: gap matrix and contact threshold
│   ├── bbox_projection.py  Bounding-box projection along a test direction
│   ├── part.py             Part: shape, bounding box, id and name
│   ├── semantic.py         Fastener semantics, connection/transition generation
│   ├── fastener_detection.py  Name-based fastener detection + group suggestion
│   ├── mesh_distance.py    Approximate mesh-distance helpers
│   ├── part_ids.py         Part identifier helpers
│   └── settings.py         Pipeline settings
│
├── rag/
│   ├── engine.py           GraphRAG streaming Q&A engine
│   ├── schema.py           Dynamic Neo4j schema description for LLM
│   ├── prompts.py          Cypher generation & answer formatting prompts
│   └── examples.py         Few-shot Cypher examples
│
├── static/
│   ├── app.html            Dashboard, chat and library interface
│   ├── css/app.css         Stylesheet of the interface
│   ├── js/
│   │   ├── graph.js        Shared Cytoscape rendering and details
│   │   └── studio.js       Interactive STEP-to-KG workflow
│   └── vendor/             Bundled third-party scripts (see THIRD_PARTY_NOTICES.md)
│
├── docs/                   Markdown references
├── scripts/                Reproduction and evaluation tools with their records
│   ├── count_state_space.py        Connected subsets of the pump contact graph (Table 8)
│   ├── check_aog_invariants.py     Six structural properties of the AND/OR graph (no database)
│   ├── verify_aog_equivalence.py   AND/OR graph in Neo4j against the generated one (read-only)
│   ├── run_pump_eval.py            Runs a question catalogue of the paper against the chat
│   ├── run_determinism.py          Asks one question repeatedly and records the answers
│   └── *.json, *.md, *.csv         Records of the runs (see "Where each result comes from")
├── tests/                  Automated checks
├── rag_eval/               GraphRAG evaluation cases and runner modules
└── sample_data/
    ├── ballpoint_pen.json
    ├── hypothetical_product.json
    ├── Hypothetical Product STEP/        Hypothetical_Product_Passungen.step is the assembly used for the 114 transitions
    └── Centrifugal Pump/
        ├── MODEL_CHANGES.md              GrabCAD source and the changes to it (the STEP file is not included)
        └── centrifugal_pump_product.json Prepared pump input (340 transitions, two fastener groups)
```

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, Flask 3.0+ |
| Database | Neo4j 5.9+ (Cypher quantified path patterns) |
| LLM | OpenAI API (`gpt-5.4-mini` by default; the paper's evaluation used `gpt-6-luna`) |
| Frontend | Vanilla JS, Tailwind CSS, Cytoscape.js |
| CAD (optional) | pythonocc-core 7.8+ (OpenCASCADE bindings via conda) |

---

## Using the Application

The web UI is a single-page app served at `/` (hash routing, so every view lives under one route). The page is `static/app.html` and provides the product dashboard, graph views with the condensed mode, the GraphRAG chat, the library editor, and the **Pipeline Studio** as its "New product" flow.

### Product Overview (`/#/products`)

Lists all products in the database with their component and transition counts. From here you can open a product dashboard or delete products.

### Product Dashboard (`/#/product/<id>`)

- **Graph view**, interactive Cytoscape visualization with multiple view modes:
  - *Full*, all nodes and relationships
  - *Reversibility*, decomposition viewed in the reverse direction
  - *Structure*, component hierarchy
  - *Precedence*, disassembly sequence (Assembly states + Transitions)
  - *Tasks*, task graph (DisassemblyTask nodes)
  - *Resources*, task → agent/tool/skill assignments
  - *Connections*, connection graph

- **Condensed rendering**, available for Precedence and Reversibility. Transition nodes are collapsed into display edges for a more compact state graph
- **Metrics**, component, connection, transition and sequence counts, with shortcuts to graph views. "Sequences" is the number of complete disassembly sequences; the tooltip of the tile also gives the number of orders of execution
- **Node and edge details**, select graph elements to inspect their properties and relationships
- **Chat**, ask natural language questions about the product in the adjacent streaming GraphRAG panel

The dashboard uses shared graph-rendering helpers in `static/js/graph.js`. Pipeline Studio is implemented in `static/js/studio.js`.

### Library (`/#/library`)

Manage the shared taxonomy used across all products:

- **ConnectionTypes**, Screw Joint, Weld Joint, Snap Joint, etc.
- **Skills**, the 14 disassembly skills and their `SUITABLE_FOR` mappings to connection types
- **Agents**, Human Worker, Assembly Robot, Automated Station
- **Tools**, Tweezers, Screwdriver, etc.

Edits here propagate immediately to all products that reference these shared nodes.

### Pipeline Studio (`/#/new`)

The interactive STEP→KG workflow for adding a new product:

1. Provide product metadata
2. Drop a STEP assembly (or import a prepared JSON), for STEP files:
   - Phase 1: Extract parts, compute liaison matrix and interferences
   - Inspect the fixed contact rule, gap histogram, test directions, overlap warnings and automatic two-step releases
   - Tag fasteners (auto-detected by name, user confirms) with inline consequences
   - Group identical fasteners (auto-group by contact pattern)
   - Define disassembly rules via the sentence-builder precedence constraints
   - Review the server-computed size estimate, which indicates combinatorial growth of the graph (shown in the Studio as "Explosion risk"), and the generated semantics
3. Review and edit the generated semantics and task names
4. Build the knowledge graph in Neo4j

---

## Input Data Format

Products are described in JSON. Example structure:

```json
{
  "product": {
    "id": "Prod_BallpointPen",
    "name": "Ballpoint Pen"
  },
  "components": [
    { "partId": "A", "name": "Body", "type": "Part" },
    { "partId": "B", "name": "Head", "type": "Part" },
    { "partId": "C", "name": "Clip Screw", "type": "Fastener" }
  ],
  "connections": [
    {
      "id": "Conn_AB",
      "part1": "A",
      "part2": "B",
      "connectionType_id": "CT_SnapJoint",
      "agent_id": "Agent_HumanWorker",
      "tool_id": "Tool_None"
    }
  ],
  "transitions": [
    {
      "id": "T01",
      "from_parts": "ABC",
      "results_in": ["AB", "C"],
      "broken_connection_id": "Conn_AC",
      "removed_part": "C"
    }
  ]
}
```

See [ballpoint pen](sample_data/ballpoint_pen.json), [hypothetical product](sample_data/hypothetical_product.json) and [centrifugal pump](sample_data/Centrifugal%20Pump/centrifugal_pump_product.json) for full product JSON examples.

### Available Connection Type IDs

`CT_ScrewJoint`, `CT_ClampJoint`, `CT_PressFit`, `CT_SnapJoint`, `CT_PinJoint`, `CT_KeyJoint`, `CT_AdhesiveBond`, `CT_WeldJoint`, `CT_SolderJoint`, `CT_FlangeJoint`, `CT_SeamJoint`, `CT_CrimpJoint`, `CT_StakedJoint`, `CT_Containment`, `CT_LooseFit`

---

## Neo4j Graph Schema

### Node Labels

| Label | Scope | Key Properties |
|-------|-------|----------------|
| `Product` | Per product | `id`, `name`, `product_id`, `input_data`, `liaison_matrix` |
| `Assembly` | Per product | `id`, `name`, `product_id`, `isState=true`, `isRoot=true` (only on full assembly) |
| `Component` | Per product | `id`, `name`, `partId`, `product_id` |
| `Fastener` | Per product | `id`, `name`, `partId`, `product_id` (also has Component label) |
| `Connection` | Per product | `id`, `name`, `product_id` |
| `ConnectionType` | Shared | `id`, `name`, `destructiveness` |
| `Transition` | Per product | `id`, `name`, `product_id` |
| `Task` | Per product | `id`, `name`, `taskType`, `product_id` (base label. In the current codebase, co-occurs only with `DisassemblyTask`) |
| `DisassemblyTask` | Per product | (inherits `Task`) |
| `Skill` | Shared | `id`, `name`, `type` (base label. In the current codebase, co-occurs only with `DisassemblySkill`) |
| `DisassemblySkill` | Shared | (inherits `Skill`) |
| `Agent` | Shared | `id`, `name`, `agentType`, `description` |
| `Tool` | Shared | `id`, `name`, `toolType`, `description` |

**"Shared" nodes** (ConnectionType, Skill, Agent, Tool) have no `product_id` and are referenced by all products. **"Per product" nodes** always carry `product_id` to prevent cross-product data contamination.

### Relationship Types

| Relationship | From → To | Meaning |
|---|---|---|
| `CONSISTS_OF` | `Product → Assembly`, `Assembly → Component` | Product links to the root assembly. Every assembly state (root and intermediate) links to its constituent components. No `Assembly → Assembly` nesting. |
| `CONNECTS` | Connection → Component | Parts joined by this connection |
| `OF_TYPE` | Connection → ConnectionType | Connection category |
| `TRANSFORMS` | Transition → Assembly | Input state (before disassembly) |
| `RESULTS_IN` | Transition → Assembly/Component | Output state(s) after disassembly |
| `DISASSEMBLED_BY` | Transition → DisassemblyTask | Links a transition to the work instruction that performs it |
| `ACTS_ON` | DisassemblyTask → Connection | The connection(s) one operation dissolves, ≥ 1 (a grouped-fastener task acts on the whole bundle) |
| `REQUIRES` | DisassemblyTask → Skill | Required capability (auto-resolved from connection type) |
| `PERFORMED_BY` | DisassemblyTask → Agent | Assigned agent |
| `USES_TOOL` | DisassemblyTask → Tool | Tool used |
| `USES_FASTENER` | Connection → Fastener | Optional, the fastener that mediates this connection |
| `SUITABLE_FOR` | Skill → ConnectionType | Compatible connection types (library) |

---

## REST API

### Products

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/products` | List all products |
| `POST` | `/api/products` | Create product (builds KG from JSON body) |
| `GET` | `/api/products/<id>` | Get product details & stats |
| `DELETE` | `/api/products/<id>` | Delete product and all its nodes |
| `GET` | `/api/products/<id>/graph?view=<type>` | Subgraph for visualization |
| `GET` | `/api/products/<id>/parts` | Part ID → name mapping |
| `GET` | `/api/products/<id>/sequence-count` | Number of complete disassembly sequences (`count`, `sequence_count`) and of their orders of execution (`ordering_count`) |
| `POST` | `/api/products/<id>/chat` | GraphRAG Q&A (Server-Sent Events stream) |
| `POST` | `/api/products/<id>/structural` | Stage 1, deletes the product's existing graph and builds the structural layer. |
| `POST` | `/api/products/<id>/operational` | Stage 2, Enrich with `DisassemblyTask` and its edges. Assumes Stage 1 already ran. |
| `POST` | `/api/products/<id>/properties` | Stage 3, property enrichment: no automatic step, writes nothing and returns `properties_set: 0`. Properties are set through the chat (enrichment) or the `PATCH` endpoint below. |
| `PATCH` | `/api/products/<id>/nodes/<node_id>/properties` | Add or update custom properties on a node. Non-destructive. |
| `DELETE` | `/api/products/<id>/nodes/<node_id>/properties/<key>` | Remove a single custom property from a node. |

### Library

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/library` | Library statistics |
| `GET` | `/api/library/graph` | Library subgraph |
| `GET` | `/api/library/items/<label>` | Items by label (`ConnectionType`, `Skill`, `Agent`, `Tool`) |
| `POST` | `/api/library/items/<label>` | Bulk save/update items |
| `DELETE` | `/api/library/items/<label>/<id>` | Delete item |
| `POST` | `/api/library/ensure` | Idempotently seed library taxonomy |
| `POST` | `/api/library/reset` | Wipe and re-seed library. Requires configured `ADMIN_TOKEN` and the matching request header. |

### STEP Pipeline

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/step/check` | Check if pythonocc-core is available |
| `POST` | `/api/step/run` | Phase 1: Geometric analysis from STEP files |
| `POST` | `/api/step/suggest-groups` | Suggest fastener groups by contact pattern |
| `POST` | `/api/step/generate-tables` | Phase 2: Semantic enrichment (accepts `fastener_groups`, `separation_precedence`) |
| `POST` | `/api/step/task-names` | Suggested task names for a build payload (same code as the build, no database access) |

### Utility

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/validate` | Validate JSON input before building |
| `GET` | `/api/config` | Runtime configuration for the client (`demo_mode`) |
| `GET` | `/api/chat/starters` | The six starter questions of the chat (the `ui_starter` cases of `rag_eval/cases.json`) |
| `GET` | `/api/pipeline/algorithms` | Selectable pipeline algorithms and the settings schema with the standard values |

### Chat Endpoint Details

`POST /api/products/<id>/chat`

Request body:
```json
{
  "message": "What is the disassembly sequence?",
  "history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

Response: `text/event-stream` (SSE). Events:

Every event is one line `data: {"type": "<type>", "data": <string>}`. The `data` value is always a string; for the structured types it holds JSON that the client parses again.

| `type` | `data` |
|---|---|
| `status` | Progress text (for example "Generating Cypher query...") |
| `cypher` | The generated Cypher query (sent again after an automatic correction) |
| `graph_data` | JSON list of the rows returned by Neo4j |
| `subgraph` | JSON object with `nodes` and `edges` for the graph view (read questions with a non-empty result) |
| `token` | A piece of the answer text; the client appends the tokens in order |
| `debug` | JSON list of the engine's log entries for this request |
| `done` | JSON object with `cypher` and `rows` (and `mutation` for write requests); last event of a successful stream |
| `error` | Error text |

---

## GraphRAG Engine

The `rag/` module implements graph-grounded natural-language querying, with separate read, enrichment and reassignment flows:

1. **Schema generation**, Describes the Neo4j graph schema and the specific product's components to the LLM
2. **Cypher generation**, LLM generates a Cypher query from the natural language question using few-shot examples
3. **Query execution**, Cypher runs against Neo4j. On failure, the LLM auto-corrects once
4. **Answer formatting**, LLM formats the raw Neo4j result into a readable answer

**Grounding and guards:** Empty read results trigger a refusal. Answer prompts require the model to use retrieved data, and query guards restrict writes. The generated write queries are checked in code before execution: an enrichment query may only `SET` non-protected properties on existing product nodes, and a reassignment query may only delete and create `PERFORMED_BY`, `USES_TOOL` and `REQUIRES` relationships between matched nodes (see [`docs/rag.md`](docs/rag.md)). These measures reduce unsupported answers but do not guarantee that every generated query or answer is correct.

**Complete teardown:** The generated query anchors on the root assembly and selects one transition per visited assembly using a seed literal. It follows all resulting subassemblies, including side branches, down to individual parts. Selection is repeatable against the same graph with the same query and seed. It does not imply optimality or uniform sampling of sequences.

**Task and connection retrieval:** Plain task lists query tasks directly to avoid multiplication through transitions. Connection listings retain connection IDs. Three-part fastener joints are retrieved by aggregating their pairwise connections over the shared fastener, and grouped tasks can act on multiple connections. See [`docs/rag.md`](docs/rag.md) for query flow and examples.

**Language support:** German questions are supported, the engine translates internally and answers in the user's language.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: flask` | Activate your venv: `source .venv/bin/activate` then `pip install -r requirements.txt` |
| Neo4j connection refused | Make sure Neo4j is running and `NEO4J_URI` in `.env` is correct |
| Chat returns no answer | Check that `OPENAI_API_KEY` in `.env` is valid |
| STEP pipeline unavailable | Install pythonocc-core via conda (see STEP Pipeline section) |
| `Aspect_WindowDefinitionError` (macOS) | Install `pyobjc-framework-Cocoa`: `pip install pyobjc-framework-Cocoa` |
| Library page empty | The library is seeded automatically when it is first accessed or a product is built (not in demo mode). Check the Neo4j connection, or call `POST /api/library/ensure`. |
| `413 Request Entity Too Large` on STEP upload | The cap is 50 MB when `.env` is copied from `.env.example` (300 MB in code without the variable). Raise it via `MAX_UPLOAD_MB=<MB>` in `.env`. |
| `401 unauthorized` calling `/api/library/reset` | The endpoint is gated on `ADMIN_TOKEN`. Set it in `.env` and send `X-Admin-Token: <value>`. |

---

## Environment Variable Reference

`config.py` reads these variables and loads the `.env` file in the repository root on import. The app, `seed_benchmark.py`, `seed_demo_product.py` and the scripts under `scripts/` that open a database connection therefore use the same settings. A variable that is already set in the environment takes precedence over the `.env` file.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_URI` | Yes | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | Yes | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | Yes | `password` | Neo4j password. The code default in `config.py` is a placeholder; set the password of your database. `docker-compose.demo.yml` passes its own value (`demo_change_me` unless `NEO4J_PASSWORD` is set) to the database, the seed and the app container. |
| `OPENAI_API_KEY` | Yes | - | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-5.4-mini` | OpenAI model name. The paper's evaluation used `gpt-6-luna`. |
| `PORT` | No | `5050` | Flask server port |
| `FLASK_HOST` | No | `127.0.0.1` | Bind address. Set to `0.0.0.0` only if you intentionally want network exposure. |
| `FLASK_DEBUG` | No | `0` | Werkzeug debug console. **OFF by default**, `1` enables an RCE vector. Only safe for local dev. |
| `MAX_UPLOAD_MB` | No | `300` in code | Upload size cap in MB. `.env.example` explicitly sets `50`, which overrides the code default when copied. Oversize requests return HTTP 413. |
| `ADMIN_TOKEN` | No | _(unset)_ | Gates destructive endpoints (currently `/api/library/reset`). **Unset ⇒ endpoint disabled**, the safer default. If set, clients must send `X-Admin-Token: <value>`. |
| `LOG_LEVEL` | No | `INFO` | Python logging level. `DEBUG` shows Cypher generation internals. |
| `DEMO_MODE` | No | `0` | `1`, `true`, `yes` or `on` makes the server read-only: every `POST`, `PUT`, `PATCH` and `DELETE` request except the chat returns HTTP 403, and the chat answers read questions only. |
| `DEMO_PORT` | No | `5050` | Host port of the demo, read by `docker-compose.demo.yml` only (see [`docs/demo-deployment.md`](docs/demo-deployment.md)). |

---

## Reproducing the paper

The repository includes the three use cases of the paper, with inputs and evaluation results:

- **Ballpoint pen**, 6 components, 5 connections, 9 assembly states, 13 transitions (the AND/OR graph of Iwase 2025, Fig. 10a), 6 complete disassembly sequences of 5 steps; the knowledge graph has 39 nodes and 120 relationships (product-scoped). Source: `sample_data/ballpoint_pen.json`.
- **Hypothetical product**, 8 components (2 M8 fasteners), 6 connections, 41 assembly states, 114 transitions, 284 complete disassembly sequences of 6 steps, 6 disassembly tasks; the knowledge graph has 176 nodes and 729 relationships (product-scoped). Source: `sample_data/hypothetical_product.json`, or regenerate it from `sample_data/Hypothetical Product STEP/Hypothetical_Product_Passungen.step` with `python3 seed_benchmark.py` or the Studio, without precedence rules or fastener groups; Phase 1 recognises the end plate's two-step removal. The 33-question catalogue (Table A.1, `rag_eval/cases_hp.json`) was run twice with gpt-6-luna: 33 of 33 questions pass in both runs. Question 18 is counted by inspection: its automated row check fails because the tools come back in one row, so the automatic count is 32 of 33 in both runs.
- **Centrifugal pump**, 25 components (ten bolts as fasteners; the M20 cap nut is a part), 48 contacts, 40 connections, 20 tasks (one per connection bundle), 102 assembly states (83 with alternative transitions, at most 9 from one state) and 340 transitions, generated from the reworked GrabCAD model (`sample_data/Centrifugal Pump/MODEL_CHANGES.md`; the STEP file is not included) with groups of six M20 bolts and four M12 bolts and one rule: shaft and impeller stay together while the cap nut is in place. Each transition links the tasks of all connection bundles it dissolves. The graph admits 124,693 complete disassembly sequences, all of 13 steps, and the knowledge graph has 528 nodes and 3,238 relationships (product-scoped). The prepared `sample_data/Centrifugal Pump/centrifugal_pump_product.json` holds this graph; in it the M20 hex bolts (ISO 4014/4017) and the cap nut are removed with a 30 mm combination wrench, the M12 bolts with an 18 mm wrench, and ten connections are typed Loose Fit. The 27-question pump catalogue (Table A.2, `rag_eval/cases_pump.json`) was run twice on this graph with gpt-6-luna: 26 and 25 of 27 questions pass. Question 10 fails in both runs: the generated query looks for the cap nut as a fastener, finds nothing, and the answer declines. "How do I remove the Shaft?" fails in the second run: the generated path query excluded the Shaft node and returned no rows.

Response times of the chat, measured in these runs on one machine, over both runs of each catalogue: median 4.2 s and 95th percentile 9.2 s for the hypothetical product (62 answers), 4.5 s and 14.2 s for the pump (54 answers). They depend on the response time of the OpenAI API. Executing the generated Cypher on the pump graph took 0.6 ms in the median in the same setting (95th percentile 1.6 ms, slowest 2.7 ms). Two pump questions were asked ten times each. First step: six answers named a single first step, four listed all first steps, and all ten started at the complete pump. Complete sequence: nine answers named all 13 steps with identifiers and one named none; the nine answers contained seven different sequences.


### Where each result comes from

The pump STEP file is not part of this repository. The last column states whether a result can be reproduced without it. The STEP folder of the hypothetical product holds three inputs: `Hypothetical_Product_Passungen.step` is the assembly with fits and gives the 114 transitions; `Hypothetical Product.step` is the same assembly without fits, in which the two screws overlap the holder and the base plate (four pairs in the overlap warning) and Phase 2 returns 0 transitions; the eight `Hypothetical Product - <part>.step` files are the single parts; loaded together they overlap one another and Phase 2 stops with an error, so they are not a pipeline input.

| Result in the paper | How to reproduce | Recorded in | Without the pump STEP file |
|---|---|---|---|
| Ballpoint pen: 9 assembly states, 13 transitions | load `sample_data/ballpoint_pen.json` (Quick Start); `pytest tests/test_ballpoint_semantic.py` checks the 13 transitions against the semantic checks | `sample_data/ballpoint_pen.json` | yes |
| Hypothetical product: 41 assembly states, 114 transitions, 6 tasks | `python3 seed_benchmark.py` (needs OpenCASCADE and the Neo4j database, into which it writes the product), or the Studio with `sample_data/Hypothetical Product STEP/Hypothetical_Product_Passungen.step` without accepting the suggested screw group | `sample_data/hypothetical_product.json` | yes |
| Centrifugal pump: 102 assembly states, 340 transitions, 20 tasks | load `sample_data/Centrifugal Pump/centrifugal_pump_product.json` (Quick Start). Regenerating the graph from CAD needs the reworked GrabCAD model (`sample_data/Centrifugal Pump/MODEL_CHANGES.md`): in the Studio accept the two fastener groups, untick the cap nut as a fastener, add the rule that shaft and impeller stay together while the cap nut is in place | `sample_data/Centrifugal Pump/centrifugal_pump_product.json` | loading: yes; regenerating: no |
| Complete disassembly sequences (trees of transitions from the complete product down to single components: one transition per reached state, all results expanded): 6 (pen), 284 (Hypothetical product), 124,693 (pump); orders of execution (linear orderings of these sequences): 12, 360, 8,883,888 | `pytest tests/test_sequence_count.py` (`models.product.count_sequences`); with a database: `GET /api/products/<id>/sequence-count` returns `sequence_count` and `ordering_count` | asserted in the test | yes |
| No transition of the pump separates the impeller from the closed casing | `pytest tests/test_pump_enclosure_json.py` (reads the product file); `pytest tests/test_pump_enclosure.py` derives the transitions from the pump STEP file | asserted in the tests | from the product file: yes; from CAD: no |
| Connected subsets with and without fastener groups (Table 8): 4,043,349 / 613,444 / 127,362 / 20,161, factor 200.6 | `python3 scripts/count_state_space.py` (reads the contact matrix and the two groups from the pump STEP file when it is present, otherwise from `sample_data/Centrifugal Pump/centrifugal_pump_product.json`) | `scripts/state_space_counts.json` | yes (from the product JSON) |
| Computation times of Phase 1, Phase 2 and the graph build (Table 9; measured on one machine, not benchmarks) | the Studio shows the time of each stage | Table 9 of the paper (no record in this repository) | hypothetical product: yes; pump: no |
| AND/OR graph reconstructed from the knowledge graph is identical to the generated one (states, transitions with source and result states) | `python scripts/verify_aog_equivalence.py` (needs the Neo4j database with the three products imported; read-only) | `scripts/aog_equivalence_<product id>.json` | yes |
| Six structural properties of the AND/OR graph hold for all three products | `python scripts/check_aog_invariants.py` (no database) | `scripts/aog_invariants_<product id>.json` | yes |
| Knowledge-graph size per product (Table 11) | load the product files (Quick Start), then `MATCH (n {product_id: $p}) RETURN count(n)` and `MATCH (n {product_id: $p})-[r]-() RETURN count(DISTINCT r)` | 39 nodes / 120 relationships (pen), 176 / 729 (Hypothetical product), 528 / 3,238 (pump) | yes |
| GraphRAG catalogue of the Hypothetical product (33 questions, Table A.1) | `python3 scripts/run_pump_eval.py --catalog rag_eval/cases_hp.json --json-out <file>.json --md-out <file>.md` (running app, seeded Neo4j, `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-6-luna`); the four write and safety questions run on a copy of the product loaded as `Prod_EvalScratchHP` | `scripts/hp_eval_run1_*` and `scripts/hp_eval_run2_*` (`_report.md`, `_report.csv`, `_results.json`); both runs summarised in `scripts/eval_runs_summary.json` | yes |
| GraphRAG catalogue of the pump (27 questions, Table A.2) | `python3 scripts/run_pump_eval.py --json-out <file>.json --md-out <file>.md` (same requirements; without the two options the script writes to `scripts/pump_eval_new_results.json`, `scripts/pump_eval_new_report.md` and the matching `.csv`, so the shipped records are not overwritten) | `scripts/pump_eval_run1_*` and `scripts/pump_eval_run2_*` (`_report.md`, `_report.csv`, `_results.json`); `scripts/eval_runs_summary.json`; Cypher execution times in `scripts/cypher_timing.json` | yes |
| Repeated questions (first step, complete sequence, 10 runs each) | `python3 scripts/run_determinism.py "<question>" --out <file>` | `scripts/determinism_first_step.json`, `scripts/determinism_sequence.json`, `scripts/determinism_summary.md` | yes |

Query-by-query walk-through with expected results: [`docs/reproduce.md`](docs/reproduce.md).

## Citing this work

If this software or the underlying paper is useful in your research, please cite the paper:

```bibtex
@article{bluvstein2026kg_disassembly,
  title   = {A knowledge graph schema for disassembly planning with integrated AND/OR disassembly logic},
  author  = {Bluvstein, German and van Crüchten, Richard and Streibel, Lasse and Brunnenkant, Finn-Augustin and Kurscheid, Sebastian and Trattnig, Stephan and Geng, Paul and Daub, Rüdiger},
  journal = {Journal of Manufacturing Systems},
  note    = {Under review}
}
```

Machine-readable metadata for citation tools is in [`CITATION.cff`](CITATION.cff).

## Contributing

Pull requests and issues welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), and if your change touches the schema, pipeline, or GraphRAG engine, also review [`docs/documentation-rules.md`](docs/documentation-rules.md), some files are deliberately coupled and must be updated together.

## Production considerations

This is a research prototype. For production use:

- Use a WSGI server. `gunicorn` is not in `requirements.txt` and has to be installed separately (`pip install gunicorn`). The chat streams Server-Sent Events, so use threaded workers without a request timeout, as `Dockerfile.demo` does: `gunicorn --worker-class gthread --workers 1 --threads 8 --timeout 0 --bind 127.0.0.1:5050 app:app`
- Put a reverse proxy (nginx) in front
- Do **not** commit `.env`, use environment variables or a secrets manager
- Add authentication (no general auth is implemented, the app assumes everyone who reaches the port is trusted)
- `ADMIN_TOKEN` only gates the single destructive `/api/library/reset` endpoint. All other write endpoints remain unauthenticated
- Enable Neo4j TLS for remote connections
- Keep `FLASK_DEBUG=0` and `FLASK_HOST=127.0.0.1` (both defaults). The Werkzeug debug console is an RCE vector, and the default bind is localhost-only for a reason
