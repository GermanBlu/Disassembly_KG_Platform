# Contributing to KG_Platform

Thanks for your interest. This is a research codebase, and the bar we aim for is **reproducibility**: anyone with the repo and a Neo4j instance should be able to re-run the reference validation cases and get the same numbers.

This document covers how to contribute code or docs. For how to *keep* docs current once they are merged, see [`docs/documentation-rules.md`](docs/documentation-rules.md).

## Before you open a pull request

1. **Read the docs first.**
   - [`README.md`](README.md) for setup and the public API.
   - [`ARCHITECTURE.md`](ARCHITECTURE.md) for the "how and why".
   - [`docs/schema.md`](docs/schema.md) if you are touching Neo4j.
   - [`docs/pipeline.md`](docs/pipeline.md) if you are touching anything under `pipeline/` or `models/`.
   - [`docs/rag.md`](docs/rag.md) if you are touching `rag/`.

2. **Check that the benchmark numbers still reproduce.** See [`docs/reproduce.md`](docs/reproduce.md). If your change legitimately alters the counts, that is fine, but it should be conscious, motivated, and called out in the PR description.

3. **Skim [`docs/documentation-rules.md`](docs/documentation-rules.md)**: it tells you which docs must change in the same PR as which code.

## Local setup

```bash
git clone https://github.com/GermanBlu/Disassembly_KG_Platform.git KG_Platform
cd KG_Platform
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in Neo4j + OpenAI credentials
python3 app.py
```

For the STEP pipeline (optional), install `pythonocc-core` via conda, see [`README.md`](README.md) "STEP CAD Pipeline".

## Pull-request expectations

A well-formed PR has:

- **One topic.** Mixing a bug fix with a refactor with a new feature is hard to review. Split it.
- **A short description** that answers: what changed, why, how to test it, and any user-visible impact.
- **Docs updated in the same PR**: see `docs/documentation-rules.md` §2.
- **A test plan.** At minimum, state which sample products you ran it against and what you looked for.
- **No unrelated cleanup.** White-space-only or unrelated style changes should be their own PR.

## Code style

Python follows [PEP 8](https://peps.python.org/pep-0008/) with a few project-specific conventions:

### Docstrings

Every module, public function, and public class has a docstring. Minimum shape:

```python
"""One-sentence imperative summary.

Optional second paragraph explaining the invariant or non-obvious rationale.

Args:
    name: description.
Returns:
    description.
"""
```

Don't paraphrase the function name: document the **why**, the **invariants**, and the **pitfalls**. See [`docs/documentation-rules.md`](docs/documentation-rules.md) §7.

### Neo4j access

Always use the composite key `(id, product_id)` for product-specific MERGE / MATCH. Dropping `product_id` silently cross-contaminates products. If you find yourself writing a query without a `product_id` constraint, stop and check whether the target is a shared library node (only those are allowed to skip it).

### Label interpolation (Cypher injection)

Any Cypher label that comes from user input, URL params, or request bodies **must** be validated against a whitelist before being interpolated into a query via f-string. Use `models/library.py:_validate_label` (or a sibling whitelist, see `_ALLOWED_SKILL_SUBTYPES`, `_ALLOWED_AGENT_SUBTYPES`, `_ALLOWED_TOOL_SUBTYPES`). Expose the same pattern when you add a new labelled endpoint: the route returns `400` when `_validate_label` raises `ValueError`, never `500`.

### File uploads

Any endpoint that writes uploaded bytes to disk **must** go through `werkzeug.utils.secure_filename` plus an `os.path.commonpath` check to confirm the final path still resolves inside the intended tmp directory. See the `/api/step/run` handler in `app.py` for the pattern. Do not trust `request.files[].filename` verbatim.

### Changes to the schema

Label / relationship / property changes must be documented **before** they land. The coupled files are listed in `docs/documentation-rules.md` §3. The schema description used for LLM Cypher generation lives in `rag/schema.py`; if you change the KG but not the prompt, the chat silently stops working for the new feature.

### Logging

Prefer `log("...")` inside `generate_semantic_tables` (the pipeline's own collector) over `print`. Logs surface in the UI and in diagnostic outputs. `print` is for one-off scripts (`seed_benchmark.py`, `diagnose_pipeline.py`).

### Dependencies

If you add a Python dependency, add it to `requirements.txt` with a minimum-version pin. Don't pin exact versions unless there is a known incompatibility above that version. Note in the PR why the dependency is needed.

## Testing

There is no CI service; run the checks locally before opening a PR.

**Automated tests.** The pytest suite in `tests/` runs without Neo4j and without an OpenAI key:

```bash
pip install pytest
python -m pytest -q -m "not slow"     # fast suite
python -m pytest -q                   # adds the slow tests (they run the geometry pipeline)
```

Tests that need OpenCASCADE (`pythonocc-core`) or a CAD file that is not in the repository are skipped when it is missing. See [`tests/README.md`](tests/README.md).

**Manual self-test** with a running database:

1. Start Neo4j.
2. Seed the library (`POST /api/library/ensure`).
3. Ingest `sample_data/ballpoint_pen.json`: verify the counts in `docs/reproduce.md` §Case 1.
4. Ingest `sample_data/hypothetical_product.json`: verify the counts in `docs/reproduce.md` §Case 2.
5. Open the chat for each product and run one query of each of the three kinds (read, enrichment, reassignment or destructive-verb refusal).

If your change only affects a narrow area (e.g. UI-only), the relevant subset is enough. State in the PR which subset you ran.

## Commit messages

One sentence in imperative tense for the subject line: "Fix broken-connection check for 3-contact fasteners", not "Fixed" or "Fixes". If the change has rationale beyond "obvious", add a paragraph under the subject. Reference issue numbers if applicable.

## What "done" looks like

A change is ready to merge when:

- The PR description is accurate.
- Docs updates are in the same PR.
- The pytest suite and the self-test have been run and the results are stated.
- At least one maintainer review has signed off.
- Nothing in the PR is only in the reviewer's head: everything worth knowing is in the code, the docs, or the PR description.

## Publishing

Release conventions:

- `main` is the release branch. Every merged PR must leave `main` working.
- Tag a release (`git tag vX.Y.Z && git push --tags`) whenever we cite a version in a paper or reproduction guide.
- Update `CITATION.cff` with the new version and release date when tagging.

## Conduct

Research code, public or not, gets more users than authors. Be kind, be precise, assume good intent, correct rather than punish. No one owes anyone else engagement; if a thread is no longer productive, step away.
