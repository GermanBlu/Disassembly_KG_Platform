# Documentation Rules

> **One-liner:** when the code changes, the docs ship in the same pull request. Docs that drift are worse than no docs.

This file is the contract for everyone who edits the codebase: authors, reviewers, maintainers and external contributors. Following it keeps the code, the documentation and the recorded results consistent.

## 1. Where each kind of information belongs

| Kind of information | Canonical location | Rule |
|---|---|---|
| Install, run, quick-start, public API, license | `README.md` | The **only** place a newcomer has to read first. |
| System overview, technical implementation and operating details | `ARCHITECTURE.md` | Developer reference. |
| Modelling and processing rationale | `docs/schema.md`, `docs/pipeline.md`, `docs/rag.md` | Keep the rationale beside the mechanism it explains. |
| Neo4j schema (labels, relationships, properties, invariants) | `docs/schema.md` | The canonical source. Code and this file must agree. |
| STEP → KG pipeline, semantic checks, phase-by-phase walk-through | `docs/pipeline.md` | With file/line references. |
| JSON input contract for `POST /api/products` | `docs/input-format.md` | With examples. |
| GraphRAG engine internals, prompts, guardrails | `docs/rag.md` | Three pipelines documented. |
| How to reproduce the reference results | `docs/reproduce.md` | Updated whenever sample data or counts change. |
| Repository governance (this file) | `docs/documentation-rules.md` | The rules themselves. |
| Contribution workflow (code style, reviews, tests) | `CONTRIBUTING.md` | What contributors actually do. |
| Per-function or per-class API notes | Python docstrings | Short, focused. Link to `docs/*.md` instead of duplicating. |
| Per-file orientation | Top-of-file module docstring | 1–3 sentences of purpose. |
| Change log of user-visible changes | `CHANGELOG.md` | Keep-a-Changelog format. |

**Do not** create new documentation locations without adding them to this table.

## 2. When you touch the code, update these docs

Use the table below as a pre-commit checklist. If a row applies to your change, the matching docs must be edited in the **same** PR.

| If you change … | Update … |
|---|---|
| A Neo4j label, relationship, or property | `docs/schema.md`, `rag/schema.py`, `rag/prompts.py`, `rag/examples.py`, sections in `ARCHITECTURE.md`, the schema tables in `README.md`. |
| The JSON input contract | `docs/input-format.md`, `models/kg_builder.py:validate_input`, the sample JSON files, the JSON example in `README.md`. |
| Any filter in `pipeline/semantic.py` | `docs/pipeline.md` §2.5, the transition-extraction summary (Step 2.5) in `ARCHITECTURE.md`. |
| `pipeline/interference.py` tolerances or directions, `pipeline/two_step.py`, the contact threshold, `STANDARD_SETTINGS` or `CLIENT_SETTINGS` | `docs/pipeline.md` §1.2–1.8 and "Deterministic reproduction", `ARCHITECTURE.md` (Phase 1 list, the two "Why …" sections on the test directions and the occlusion test, "Guard-rails for future changes"), `README.md` STEP-pipeline section, the Studio texts in `static/js/studio.js`, `docs/reproduce.md`. |
| The GraphRAG rules, prompts, or signal lists | `docs/rag.md`, sections in `ARCHITECTURE.md`, `rag/prompts.py` comments. |
| `library.py` seed data | `docs/schema.md` shared-library section, sample data if it references the changed IDs. |
| The REST API surface | `README.md` "REST API" table. |
| Environment variables | `README.md` env-var reference, `.env.example`. |
| Any assumption listed under "Guard-rails for future changes" in `ARCHITECTURE.md` | That section. |
| Sample product data (counts, structure) | `docs/reproduce.md`. |

## 3. Coupled definitions

Some facts are deliberately expressed in more than one file for performance or for separation-of-concerns reasons. Those **must** be updated together or they will silently drift. These are the known couplings:

| Fact | Location 1 | Location 2 | Rule |
|---|---|---|---|
| `ConnectionType → DisassemblySkill` mapping | `models/library.py:SKILL_SUITABILITY` (creates `SUITABLE_FOR` edges) | `models/kg_builder.py:_DIS_SKILLS` (used by the write path) | Any addition/renaming of a skill or connection type must touch both. |
| Destructive-keyword list (natural-language guard) | `rag/engine.py:ask()` `destructive_signals` | `rag/engine.py:_execute_cypher`, `check_enrichment_query`, `check_reassignment_query` (checks of the generated Cypher) | Keep in step; both levels are intended. |
| Mutation signal words (English + German) | `rag/engine.py:_MUTATION_SIGNALS` | mutation prompt rules (`rag/prompts.py:build_mutation_prompt`) | If the LLM's trigger set changes, the prompt's allowed verbs should match. |
| Canonical `ConnectionType` IDs | `models/library.py:CONNECTION_TYPES` | `docs/schema.md`, `README.md` "Available Connection Type IDs" | Adding a type requires updating the public doc. |
| Entity-type count in the documentation | `models/library.py` + `models/kg_builder.py` labels | `docs/schema.md` and the HTML schema reference | Count must be verifiable from code. |
| Library-label whitelist | `models/library.py:_ALLOWED_LIBRARY_LABELS` (plus `_ALLOWED_SKILL_SUBTYPES`, `_ALLOWED_AGENT_SUBTYPES`, `_ALLOWED_TOOL_SUBTYPES`) | `docs/schema.md` "Entity types" tables; `rag/schema.py` schema description sent to the LLM | Adding or renaming a library label requires updating all three. The whitelist is the source of truth for Cypher-label interpolation: any label reaching `MATCH (n:{label})` must pass `_validate_label`. |

**When adding a new coupling**, add a row here. The goal is that a maintainer can answer "if I change X, what else do I have to touch?" in under 60 seconds.

## 4. Style

### Prose

- Reader first. Lead with what the reader needs, not the history of how you got there.
- Short declarative sentences. Avoid hedging ("generally", "usually") when you can state precisely.
- Plain English names over jargon when possible. Define every acronym on first use (yes, even AOG and KG in a new doc).
- Use "we" only in research-voice sections. Reference material should be impersonal.

### Code blocks

- Every Cypher block must be runnable as-is against a ballpoint-pen-loaded graph unless explicitly marked `// schematic`.
- Every bash block must assume the documented prerequisites from `README.md` §Quick Start.
- Do not put credentials in code blocks, even placeholder ones. Use `<...>` or `${VAR}`.

### Headings and structure

- Title case for top-level (`# Title`), sentence case below.
- Keep the TOC implicit via the heading structure; do not maintain a handwritten table of contents unless the document is > 2000 words.
- One `#` per file. Always.

### Tables

- Tables beat bullet lists for anything that has columns.
- Align on a stable key in the first column (label, function name, step number).
- Keep to three columns when possible; wider tables do not render on GitHub mobile.

### Code references

- Cite files with backticks and slashes: ``pipeline/semantic.py``.
- Cite functions with backticks: ``_handle_mutation``.
- Cite line numbers only for explicit anchors that are unlikely to move; prefer function names. Line numbers rot.

## 5. Diagrams

Prefer ASCII for anything that fits. ASCII diagrams survive renames and format changes.

If a diagram genuinely needs graphics:

1. Author the source (Mermaid, Excalidraw, draw.io) and commit it alongside the rendered image.
2. Put the rendered PNG/SVG under `docs/img/` and keep the source file next to it.
3. Reference the rendered image from docs; never the hosted-elsewhere URL.

## 6. Review checklist for doc PRs

Reviewers: at minimum, verify

- [ ] Every new claim has either a code citation or a runnable command backing it.
- [ ] Every cross-reference to another doc uses a relative link that actually resolves.
- [ ] Any added coupling is recorded in §3 of this file.
- [ ] The PR does not introduce a second source of truth for a fact that already has a canonical location (see §1).
- [ ] Line numbers, if cited, point to code that exists on the PR branch.
- [ ] `README.md` remains the entry point: detail that only some readers need goes to `docs/`.

## 7. Writing docstrings

Every module (`__init__.py` excluded unless it has non-trivial logic), every public function, and every public class has a docstring. The minimum:

```python
"""One sentence imperative summary.

Optional second paragraph explaining why this exists or what invariant it maintains.

Args:
    name: description
Returns:
    description (or a reference to the shape defined in docs/input-format.md)
Raises:
    ExceptionType: when
"""
```

Don't document the obvious. Do document:

- Invariants the function relies on (e.g. "assumes `product_id` is in every MERGE").
- Why a non-obvious design decision was made, with a link to `ARCHITECTURE.md` if the decision is documented there.
- Known pitfalls, with the exact failure mode (e.g. "fork-based multiprocessing with OCC on macOS SIGSEGVs: do not switch").

Docstrings that repeat the function name in prose add noise. Delete them.

## 8. When docs go stale

Assume they will. Mitigations:

- The reproducibility tests in `docs/reproduce.md` are the canary. If they stop matching on main, it is a release-blocker.
- Every quarter, a maintainer runs:
  - `grep -rn 'line [0-9]\+' docs/` and verifies each line cite is still valid.
  - `grep -rn 'TODO\|FIXME' docs/`: unaddressed TODOs in docs should not exist for long.
  - A documentation "linkrot" pass using a link checker on all `.md` files.
- When you discover a drift, the norm is **fix it or file an issue with the exact line**, never silently leave bad docs in place.

## 9. For external contributors

If you are submitting a PR to this repository:

1. Read [`../README.md`](../README.md) and [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
2. If your change has any of the effects listed in §2, update the matching docs in the same PR.
3. If you are not sure whether a coupling applies, ask in the PR: maintainers will point you at §3.
4. Keep your change focused; large mixed code+doc refactors are hard to review. One topic per PR.

## 10. When to create a new doc file

Default is **no**. Add to an existing file first. Create a new file only when:

- The topic is cross-cutting (affects multiple files in `/`) and does not fit in any existing doc.
- The topic has its own audience (e.g. ops runbooks if we ever ship a production deployment guide).
- The topic would bloat an existing file beyond ~1500 lines.

If you add a new doc, add it to the table in §1 in the same PR.

## 11. Evidence discipline

- `STANDARD_SETTINGS` are the standard settings of every Phase 1 run (`run_step_phase1` merges explicit settings over them). A client may change only the leaves in `CLIENT_SETTINGS`; the Studio rows `_ST_SETTINGS` and notes `_ST_SETTING_NOTES` in `static/js/studio.js` must list the same leaves. The module-level defaults of the individual functions apply only to direct function calls.
- Keep the statements on direction counts, reverse visual tests, overlap-region counting and the limits of two-step releases identical across the Geometry, Pipeline, Platform interface, Overview and Evaluation pages.
- Do not call sampled trajectory checks a proof of continuous collision freedom, and do not transfer single-part path checks to moving subassemblies.
- A result quoted in the documentation names the record it comes from (a file under `scripts/` or `sample_data/`, or a test). When a graph changes, update the records and every quoted number in the same PR.
- Describe Stage 1 of the interference check as the depth condition of Algorithm 1 of Prasad et al. (2022), written for the removal direction.
- Attribute a statement to a publication only after checking it against the full text, with the page or section where possible. Otherwise state it as a choice of the platform or leave it out.
- The reference numbers in the documentation are the numbering of this documentation, not that of the paper.
