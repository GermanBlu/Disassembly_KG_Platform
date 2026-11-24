#!/usr/bin/env python3
"""Repeated questions: ask the same question N times in fresh chats.

Records for every run which transition ids the answer names (in the order of
the answer) and the first 600 characters of the answer, so the variation
between runs can be counted. The summary fields at the top of the record are
derived from the per-run data.

Usage (the two questions of scripts/determinism_summary.md):
    python scripts/run_determinism.py "What is the first step to disassemble this product?" \
        --out scripts/determinism_first_step.json
    python scripts/run_determinism.py "Generate a complete disassembly sequence for this product." \
        --out scripts/determinism_sequence.json
    options: [--n 10] [--product Prod_CentrifugalPump] [--base-url URL]

The server address defaults to $RAG_EVAL_BASE_URL (alias $KG_EVAL_BASE_URL),
then to http://localhost:5050. The language model is the one the server was
started with (the shipped records: OPENAI_MODEL=gpt-6-luna).
"""
import argparse, collections, json, os, re, sys
PLATFORM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLATFORM_DIR)
from rag_eval.runner import default_base_url, stream_chat  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("question")
ap.add_argument("--n", type=int, default=10)
ap.add_argument("--base-url", default=default_base_url())
ap.add_argument("--product", default="Prod_CentrifugalPump")
ap.add_argument("--out", required=True)
a = ap.parse_args()

runs = []
for i in range(a.n):
    obs = stream_chat(a.base_url, a.product, a.question, timeout=240)
    tids = re.findall(r"\bT\d+\b", obs.get("answer") or "")
    seq = tuple(dict.fromkeys(tids))          # order-preserving unique
    runs.append({"run": i + 1, "transition_ids": list(seq),
                 "first": seq[0] if seq else None,
                 "error": obs.get("error"),
                 "answer_head": (obs.get("answer") or "")[:600]})
    print(f"run {i+1}: first={seq[0] if seq else '-'}  ids={len(seq)}", flush=True)

# Derived summary fields:
#   first_named_transition_distribution  the first transition id named in each
#       answer (None: no id named); the id named first need not be a transition
#       from the complete product
#   distinct_transition_sets  number of different sets of named ids among the
#       runs that name ids (the order of presentation is ignored)
#   runs_without_transition_ids  runs whose answer names no id
firsts = collections.Counter(r["first"] for r in runs)
sets = collections.Counter(frozenset(r["transition_ids"]) for r in runs if r["transition_ids"])
without = sum(1 for r in runs if not r["transition_ids"])
identical = len(sets) == 1 and without == 0
summary = {"question": a.question, "n": a.n,
           "first_named_transition_distribution": dict(firsts),
           "distinct_transition_sets": len(sets),
           "runs_without_transition_ids": without,
           "identical_across_runs": identical,
           "runs": runs}
json.dump(summary, open(a.out, "w"), indent=1)
print(f"\nfirst named transition id: {dict(firsts)}")
print(f"distinct sets of named ids: {len(sets)}  (runs without ids: {without}; "
      f"{'IDENTICAL every run' if identical else 'varies'})")
