#!/usr/bin/env python3
"""End-to-end evaluation harness for the GraphRAG chat endpoint.

Thin CLI shim. The implementation lives in the rag_eval/ package:
  rag_eval/cases.json    the general question catalogue (golden facts per case)
  rag_eval/runner.py     SSE client, mode auto-detection, scratch product,
                         assertion engine, reports, exit codes

Every case carries deterministic expectations (numbers, names, refusal
markers). The run exits with code 1 when a core case does not pass, so it can
be used in CI against the read-only demo and the normal read-write deployment.

Usage:
    python eval_rag.py [--base-url http://localhost:5050] [--list]
                       [--category economics ...] [--case eco_total_teardown ...]
                       [--skip-writes] [--fail-fast] [--keep-scratch]
Reports: rag_test_results.json + rag_test_report.md.
Prerequisites: running Flask server with the seeded demo product; write cases
additionally need normal (non-demo) mode and OPENAI_API_KEY. The server address
defaults to $RAG_EVAL_BASE_URL (alias $KG_EVAL_BASE_URL), then to
http://localhost:5050. The language model is the one the server was started
with (OPENAI_MODEL, for example OPENAI_MODEL=gpt-6-luna python app.py).

The two catalogues of the paper are run with a second script:
    python scripts/run_pump_eval.py --catalog rag_eval/cases_hp.json    # Table A.1
    python scripts/run_pump_eval.py --catalog rag_eval/cases_pump.json  # Table A.2
"""
import sys

from rag_eval.runner import main

if __name__ == "__main__":
    sys.exit(main())
