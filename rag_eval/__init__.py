"""GraphRAG evaluation: question catalog + assertion-based eval harness.

- cases.json     the catalog (single source of truth — consumed by the runner,
                 the pytest guards, and the /api/chat/starters endpoint)
- cases.py       loader / schema validation / selection helpers
- markers.py     refusal-name -> stable answer fragments (drift-guarded)
- assertions.py  evaluate(expect, observed) -> failures
- runner.py      SSE client + orchestration + reports  (python eval_rag.py)
"""
