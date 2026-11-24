"""GraphRAG eval runner — assertion-based, CI-able (exit 0/1/2).

Runs the catalog (rag_eval/cases.json) against a live server, auto-detecting
demo vs normal mode from /api/config. Write cases run against a throwaway
scratch product (the ballpoint pen with a rewritten id) in normal mode and as
read-only-refusal probes in demo mode — the demo product's golden data is
never mutated.

Usage (entry point: python eval_rag.py …):
  --base-url URL     server (default $RAG_EVAL_BASE_URL or http://localhost:5050)
  --category C …     only these categories     --case ID …   only these cases
  --list             print the catalog and exit
  --skip-writes      skip write_* categories   --fail-fast   stop on first core failure
  --timeout S        per-question timeout (default 180)
  --keep-scratch     do not delete the scratch product afterwards
  --json-out PATH    default rag_test_results.json
  --md-out PATH      default rag_test_report.md

Exit codes: 0 all core cases pass · 1 core failures · 2 infrastructure problem.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

from rag_eval.assertions import evaluate
from rag_eval.cases import load_cases, select

_WRITE_CATEGORIES = {"write_enrichment", "write_reassignment"}

DEFAULT_BASE_URL = "http://localhost:5050"       # config.PORT default


def default_base_url():
    """Server address for all evaluation scripts.

    Read from RAG_EVAL_BASE_URL; KG_EVAL_BASE_URL is accepted as an alias.
    Without either, the app's default port 5050 on localhost is used.
    """
    return (os.getenv("RAG_EVAL_BASE_URL") or os.getenv("KG_EVAL_BASE_URL")
            or DEFAULT_BASE_URL)


def _get_json(base_url, path, timeout=10):
    with urllib.request.urlopen(f"{base_url}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(base_url, path, payload, timeout=120, method="POST"):
    req = urllib.request.Request(
        f"{base_url}{path}", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")


def stream_chat(base_url, product_id, question, history=None, timeout=180):
    """POST a chat question, parse the SSE stream, return the observed dict."""
    payload = json.dumps({"message": question, "history": history or []}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/products/{product_id}/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")

    observed = {"answer": "", "cyphers": [], "rows": None, "mutation": False,
                "error": None, "duration_s": 0.0}
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace")
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:].strip())
                except json.JSONDecodeError:
                    continue
                etype, edata = event.get("type"), event.get("data")
                if etype == "token":
                    observed["answer"] += edata or ""
                elif etype == "cypher" and edata:
                    observed["cyphers"].append(edata)
                elif etype == "error":
                    observed["error"] = edata or "unknown error"
                elif etype == "done":
                    try:
                        info = json.loads(edata) if isinstance(edata, str) else (edata or {})
                        observed["rows"] = info.get("rows")
                        observed["mutation"] = bool(info.get("mutation"))
                    except Exception:
                        pass
    except Exception as e:  # noqa: BLE001 — network/timeout surfaces as case failure
        observed["error"] = f"transport: {e}"
    observed["duration_s"] = round(time.time() - t0, 1)
    return observed


def _case_turns(case, demo_mode):
    """Yield (message, expect) per turn, honouring the demo override.

    In demo mode a case with expect_demo (write cases) runs only its first
    turn — the refusal happens before anything else could be verified.
    """
    override = case.get("expect_demo") if demo_mode else None
    turns = case.get("turns") or [{"message": None, "expect": case.get("expect", {})}]
    for turn in turns:
        message = turn.get("message") or case["question"]
        expect = override if override is not None else turn.get("expect", {})
        yield message, expect
        if override is not None:
            return  # demo override short-circuits multi-turn write cases


def run_case(base_url, case, product_ids, demo_mode, timeout):
    """Run one case (all turns); returns the result record."""
    pid = product_ids.get(case.get("target", "demo"), product_ids["demo"])
    history = []
    turn_records = []
    failures = []
    for message, expect in _case_turns(case, demo_mode):
        observed = stream_chat(base_url, pid, message, history, timeout)
        turn_failures = evaluate(expect, observed)
        failures.extend(f"[{message[:40]}…] {f}" if len(turn_records) else f
                        for f in turn_failures)
        turn_records.append({"question": message, "answer": observed["answer"],
                             "cypher": observed["cyphers"][-1] if observed["cyphers"] else None,
                             "rows": observed["rows"], "duration_s": observed["duration_s"],
                             "error": observed["error"]})
        history += [{"role": "user", "content": message},
                    {"role": "assistant", "content": observed["answer"]}]
        if turn_failures:
            break  # later turns depend on earlier ones (e.g. write → read-back)
    return {
        "case_id": case["id"], "category": case["category"],
        "severity": case.get("severity", "core"), "product_id": pid,
        "passed": not failures, "failures": failures, "turns": turn_records,
        "duration_s": round(sum(t["duration_s"] for t in turn_records), 1),
    }


# ── Scratch product (normal-mode write target) ──────────────────────────────

def _seed_scratch(base_url, catalog):
    scratch = catalog["products"]["scratch"]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, scratch["source"]), encoding="utf-8") as f:
        data = json.load(f)
    data["product"]["id"] = scratch["id"]
    data["product"]["name"] = scratch.get("name", scratch["id"])
    status, _ = _post_json(base_url, "/api/products", data)
    if status not in (200, 201):
        raise RuntimeError(f"scratch product creation failed (HTTP {status})")


def _delete_scratch(base_url, catalog):
    scratch_id = catalog["products"]["scratch"]["id"]
    req = urllib.request.Request(f"{base_url}/api/products/{scratch_id}", method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=60)
    except Exception as e:  # noqa: BLE001
        print(f"  warning: could not delete scratch product: {e}")


# ── Reports ──────────────────────────────────────────────────────────────────

def _write_reports(results, mode, base_url, json_out, md_out):
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "base_url": base_url, "results": results},
                  f, indent=2, ensure_ascii=False)

    cats = {}
    for r in results:
        c = cats.setdefault(r["category"], {"pass": 0, "fail": 0, "warn_fail": 0})
        if r["passed"]:
            c["pass"] += 1
        elif r["severity"] == "warn":
            c["warn_fail"] += 1
        else:
            c["fail"] += 1

    lines = [f"# GraphRAG Eval Report", "",
             f"- Mode: **{mode}** · Server: `{base_url}` · Cases: {len(results)}",
             f"- Core failures: **{sum(c['fail'] for c in cats.values())}** · "
             f"Warn failures: {sum(c['warn_fail'] for c in cats.values())}", "",
             "| Category | Pass | Core fail | Warn fail |", "|---|---|---|---|"]
    for cat, c in sorted(cats.items()):
        lines.append(f"| {cat} | {c['pass']} | {c['fail']} | {c['warn_fail']} |")
    lines.append("")

    for r in results:
        badge = "PASS" if r["passed"] else ("WARN-FAIL" if r["severity"] == "warn" else "FAIL")
        lines += [f"## [{badge}] {r['case_id']} ({r['category']}, {r['duration_s']}s)", ""]
        for f in r["failures"]:
            lines.append(f"- ✗ {f}")
        for t in r["turns"]:
            lines += [f"", f"**Q:** {t['question']}", "",
                      f"```cypher", f"{t['cypher'] or '(no cypher)'}", "```", "",
                      f"**A** ({t['rows']} rows): {t['answer'][:600]}", ""]
    with open(md_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default=default_base_url())
    p.add_argument("--category", action="append")
    p.add_argument("--case", action="append")
    p.add_argument("--list", action="store_true")
    p.add_argument("--skip-writes", action="store_true")
    p.add_argument("--fail-fast", action="store_true")
    p.add_argument("--keep-scratch", action="store_true")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--json-out", default="rag_test_results.json")
    p.add_argument("--md-out", default="rag_test_report.md")
    args = p.parse_args(argv)

    catalog = load_cases()
    cases = catalog["cases"]

    if args.list:
        print(f"{len(cases)} cases:")
        for c in cases:
            chip = " [chip]" if c.get("ui_starter") else ""
            print(f"  {c['category']:20} {c['id']:26} {c.get('severity','core'):4}{chip}  {c['question'][:70]}")
        return 0

    # Preflight
    base = args.base_url.rstrip("/")
    try:
        demo_mode = bool(_get_json(base, "/api/config").get("demo_mode"))
        products = _get_json(base, "/api/products")
    except Exception as e:  # noqa: BLE001
        print(f"Cannot reach {base} ({e}). Is the app running? "
              f"(set --base-url or RAG_EVAL_BASE_URL)")
        return 2
    mode = "demo" if demo_mode else "normal"
    demo_id = catalog["products"]["demo"]["id"]
    known = {pr.get("id") for pr in (products if isinstance(products, list) else products.get("products", []))}
    if demo_id not in known:
        print(f"Demo product {demo_id} not found on {base} — seed it first.")
        return 2

    selected = select(cases, mode, args.category, args.case)
    if args.skip_writes:
        selected = [c for c in selected if c["category"] not in _WRITE_CATEGORIES]
    if not selected:
        print("No cases selected.")
        return 2

    # Scratch product only needed for real writes (normal mode)
    write_selected = [c for c in selected if c["category"] in _WRITE_CATEGORIES]
    product_ids = {"demo": demo_id, "scratch": demo_id if demo_mode
                   else catalog["products"]["scratch"]["id"]}
    scratch_seeded = False
    if mode == "normal" and write_selected:
        print(f"Seeding scratch product {product_ids['scratch']} …")
        try:
            _seed_scratch(base, catalog)
            scratch_seeded = True
        except Exception as e:  # noqa: BLE001
            print(f"Scratch seeding failed: {e}")
            return 2

    print(f"Running {len(selected)} cases against {base} (mode: {mode})\n")
    results = []
    core_failed = 0
    try:
        for i, case in enumerate(selected, 1):
            r = run_case(base, case, product_ids, demo_mode, args.timeout)
            results.append(r)
            badge = "PASS" if r["passed"] else ("warn" if r["severity"] == "warn" else "FAIL")
            print(f"  [{i:2}/{len(selected)}] {badge:4} {r['case_id']:28} {r['duration_s']:6.1f}s"
                  + (f"  — {r['failures'][0]}" if r["failures"] else ""))
            if not r["passed"] and r["severity"] == "core":
                core_failed += 1
                if args.fail_fast:
                    break
    finally:
        if scratch_seeded and not args.keep_scratch:
            print("Deleting scratch product …")
            _delete_scratch(base, catalog)

    _write_reports(results, mode, base, args.json_out, args.md_out)
    warn_failed = sum(1 for r in results if not r["passed"] and r["severity"] == "warn")
    print(f"\n{len(results)} run · {sum(r['passed'] for r in results)} passed · "
          f"{core_failed} core failed · {warn_failed} warn failed")
    print(f"Reports: {args.json_out} · {args.md_out}")
    return 1 if core_failed else 0


if __name__ == "__main__":
    sys.exit(main())
