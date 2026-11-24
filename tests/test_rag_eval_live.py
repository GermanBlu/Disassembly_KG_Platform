"""Live GraphRAG eval wrapper, opt-in via RAG_EVAL_BASE_URL.

Skipped in the default suite (no network, no LLM). To run the catalogue
rag_eval/cases.json against a live server:

    RAG_EVAL_BASE_URL=http://localhost:5050 pytest tests/test_rag_eval_live.py

or run the harness directly: python eval_rag.py --base-url …
KG_EVAL_BASE_URL is accepted as an alias of RAG_EVAL_BASE_URL.
"""
import os

import pytest

_BASE = os.getenv("RAG_EVAL_BASE_URL") or os.getenv("KG_EVAL_BASE_URL")

pytestmark = [
    pytest.mark.rag_eval,
    pytest.mark.skipif(not _BASE, reason="RAG_EVAL_BASE_URL not set (live eval is opt-in)"),
]


def test_full_catalog_passes():
    from rag_eval.runner import main
    assert main(["--base-url", _BASE]) == 0
