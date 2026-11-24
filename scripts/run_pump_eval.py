#!/usr/bin/env python3
"""Run one of the two question catalogues of the paper against the live server.

  rag_eval/cases_pump.json   centrifugal pump, 27 questions (paper Table A.2), default
  rag_eval/cases_hp.json     hypothetical product, 33 questions (paper Table A.1)

For every case in the catalogue: send the question to
/api/products/<pid>/chat, capture the generated Cypher, the row count and the
answer of the language model, evaluate the assertions, and write a JSON record,
a Markdown report (question, Cypher, answer, verdict) and a CSV with the same
content.

Usage:
    python scripts/run_pump_eval.py                                   # pump
    python scripts/run_pump_eval.py --catalog rag_eval/cases_hp.json \
        --json-out scripts/hp_eval_new_results.json \
        --md-out scripts/hp_eval_new_report.md                         # hypothetical product
Without --json-out / --md-out the script writes to
scripts/pump_eval_new_results.json and scripts/pump_eval_new_report.md (plus
the .csv next to the report); the shipped records are not overwritten.
    options: [--case P13 ...] [--base-url URL] [--timeout S] [--note TEXT]

Prerequisites: the app is running with a populated Neo4j and OPENAI_API_KEY,
and the product named in the catalogue is loaded. The language model is the
one the server was started with; the paper runs used
OPENAI_MODEL=gpt-6-luna. The server address defaults to $RAG_EVAL_BASE_URL
(alias $KG_EVAL_BASE_URL), then to http://localhost:5050.

A case may carry an optional "product" key that overrides the catalogue's
product for that case only. The four write and safety cases of the
hypothetical product use it: they run on a copy of
sample_data/hypothetical_product.json loaded under the id Prod_EvalScratchHP,
which has to be created before the run (POST /api/products with the id
rewritten) and can be deleted afterwards.

The shipped records scripts/{hp,pump}_eval_run{1,2}_* were produced with this
script (two runs per catalogue, each written with --json-out and --md-out to
the file names of that run and titled with --note).
"""
import argparse
import csv
import json
import os
import sys

PLATFORM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLATFORM_DIR)

from rag_eval.assertions import evaluate          # noqa: E402
from rag_eval.runner import default_base_url, stream_chat   # noqa: E402

DEFAULT_CATALOG = os.path.join("rag_eval", "cases_pump.json")


def write_reports(results, md_out, title, note=""):
    """Write the Markdown report and the CSV next to it; returns the CSV path."""
    n_pass = sum(1 for r in results if r["pass"])
    with open(md_out, "w") as fh:
        fh.write(f"# {title}: {n_pass}/{len(results)} pass\n\n")
        if note:
            fh.write(note.strip() + "\n\n")
        for r in results:
            fh.write(f"## {r['id']} ({r['category']}): "
                     f"{'PASS' if r['pass'] else 'FAIL'}\n\n"
                     f"**Q:** {r['question']}\n\n")
            if r.get("product"):
                fh.write(f"**Product:** {r['product']}\n\n")
            for cy in (r["cyphers"] or []):
                fh.write(f"```cypher\n{cy.strip()}\n```\n\n")
            answer_md = "\n".join("> " + ln for ln in (r['answer'] or '(none)').splitlines())
            fh.write(f"**Rows:** {r['rows']}\n\n**Answer:**\n\n"
                     f"{answer_md}\n\n")
            if not r["pass"]:
                fh.write("**Failures:** " + "; ".join(r["failures"]) + "\n\n")
            fh.write("---\n\n")
    csv_out = md_out.rsplit(".", 1)[0] + ".csv"
    with open(csv_out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "category", "question", "cypher", "rows",
                    "llm_answer", "pass", "failures"])
        for r in results:
            w.writerow([r["id"], r["category"], r["question"],
                        "\n---\n".join(r["cyphers"] or []), r["rows"],
                        r["answer"] or "", "PASS" if r["pass"] else "FAIL",
                        "; ".join(r["failures"])])
    return csv_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=default_base_url())
    ap.add_argument("--case", nargs="*", default=None)
    ap.add_argument("--json-out", default="scripts/pump_eval_new_results.json")
    ap.add_argument("--md-out", default="scripts/pump_eval_new_report.md")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--catalog", default=DEFAULT_CATALOG,
                    help="case catalog (relative paths resolve against the "
                         "repo root); default rag_eval/cases_pump.json")
    ap.add_argument("--note", default="",
                    help="one paragraph written under the report title "
                         "(date, model, product)")
    args = ap.parse_args()

    catalog_path = args.catalog if os.path.isabs(args.catalog) \
        else os.path.join(PLATFORM_DIR, args.catalog)
    catalog = json.load(open(catalog_path))
    pid = catalog["product"]
    cases = [c for c in catalog["cases"]
             if not args.case or c["id"] in args.case]

    results, n_pass = [], 0
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}  {case['question'][:64]}",
              flush=True)
        # optional per-case product override (e.g. write/safety cases on a copy)
        case_pid = case.get("product") or pid
        obs = stream_chat(args.base_url, case_pid, case["question"],
                          timeout=args.timeout)
        failures = evaluate(case["expect"], obs)
        ok = not failures
        n_pass += ok
        print(f"        {'PASS' if ok else 'FAIL: ' + '; '.join(failures)[:120]}",
              flush=True)
        record = {"id": case["id"], "category": case["category"],
                  "question": case["question"], "note": case.get("note", ""),
                  "cyphers": obs.get("cyphers"), "rows": obs.get("rows"),
                  "answer": obs.get("answer"), "error": obs.get("error"),
                  "duration_s": round(obs.get("duration_s", 0), 1),
                  "pass": ok, "failures": failures}
        if case.get("product"):
            record["product"] = case_pid
            record["mutation"] = obs.get("mutation")
        results.append(record)

    json.dump(results, open(args.json_out, "w"), indent=1)
    title = f"Catalogue run ({pid}, {os.path.basename(args.catalog)})"
    csv_out = write_reports(results, args.md_out, title, args.note)
    print(f"\n{n_pass}/{len(cases)} pass  ->  {args.md_out}  +  {csv_out}")
    return 0 if n_pass == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
