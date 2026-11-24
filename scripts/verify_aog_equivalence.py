#!/usr/bin/env python3
"""Compare the AND/OR graph stored in the knowledge graph with the generated one.

Equal entity counts do not imply equal graphs. This script therefore
reconstructs the AND/OR graph from the populated knowledge graph and compares
it element by element with the generator output, which is the transition list
of the product JSON file.

Both sides are reduced to the same two sets:

  states       On the generator side: the source state of every transition and
               every result with more than one part. On the knowledge graph
               side: all Assembly nodes of the product.
  transitions  Pairs (source state, set of result states). On the knowledge
               graph side they are read from the Transition nodes with their
               TRANSFORMS and RESULTS_IN relationships.

The six comparisons, exactly as checked:

  1. states_identical             the two state sets are equal
  2. arcs_identical               the two sets of (source state, result
                                  states) pairs are equal
  3. branching_identical          every state has the same number of
                                  alternative transitions on both sides
  4. root_identical               both sides have the same single state that
                                  is not the result of any transition
  5. terminals_identical          both sides have the same set of states
                                  without an outgoing transition
  6. multi_result_arcs_identical  the transitions with more than two results
                                  are the same on both sides

Any mismatch is printed with examples.

Requirements: a running Neo4j database that holds the knowledge graph of the
product (import the product in the application first). The connection is taken
from config.py, that is from the environment variables NEO4J_URI, NEO4J_USER
and NEO4J_PASSWORD or the .env file. The script only reads from the database; the session is
opened in read access mode.

Usage (from the repository root):

    python scripts/verify_aog_equivalence.py
        compares the three sample products and writes one record each to
        scripts/aog_equivalence_<product id>.json

    python scripts/verify_aog_equivalence.py --data sample_data/ballpoint_pen.json
    python scripts/verify_aog_equivalence.py --data <file.json> --out <record.json>

Exit code 0 if every compared product is equivalent, otherwise 1.
"""
import argparse
import collections
import json
import os
import re
import sys

PLATFORM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLATFORM_DIR)

SAMPLE_FILES = [
    os.path.join("sample_data", "ballpoint_pen.json"),
    os.path.join("sample_data", "hypothetical_product.json"),
    os.path.join("sample_data", "Centrifugal Pump", "centrifugal_pump_product.json"),
]


def strip(node_id):
    return re.sub(r"^(Asm_|Comp_)", "", node_id)


def source_aog(data):
    """The generator's output: the transition list the pipeline emitted."""
    arcs = set()
    states = set()
    for t in data["transitions"]:
        parent = t["from_parts"]
        children = tuple(sorted(t["results_in"]))
        arcs.add((parent, children))
        states.add(parent)
        states.update(c for c in t["results_in"] if len(c) > 1)
    return {"arcs": arcs, "states": states,
            "n_transitions": len(data["transitions"])}


def graph_aog(driver, pid):
    """The same graph, read back out of Neo4j through the schema (read-only)."""
    from neo4j import READ_ACCESS

    arcs = set()
    with driver.session(default_access_mode=READ_ACCESS) as s:
        states = {strip(r["id"]) for r in s.run(
            "MATCH (a:Assembly {product_id:$pid}) RETURN a.id AS id", pid=pid)}
        for r in s.run(
                "MATCH (t:Transition {product_id:$pid})-[:TRANSFORMS]->(f:Assembly) "
                "OPTIONAL MATCH (t)-[:RESULTS_IN]->(c) "
                "RETURN t.id AS tid, f.id AS parent, collect(c.id) AS children",
                pid=pid):
            children = tuple(sorted(strip(c) for c in r["children"] if c))
            arcs.add((strip(r["parent"]), children))
    return {"arcs": arcs, "states": states}


def branching(arcs):
    b = collections.Counter(parent for parent, _ in arcs)
    return b


def compare(product, src, kg):
    """Compare the two graphs, print the result and return the record."""
    print(f"== AOG equivalence: {product['name']} ==")
    print(f"   generator      : {len(src['states']):>6,} states  "
          f"{len(src['arcs']):>6,} distinct transitions  "
          f"({src['n_transitions']:,} in the file)")
    print(f"   knowledge graph: {len(kg['states']):>6,} states  "
          f"{len(kg['arcs']):>6,} distinct transitions")

    checks = {}

    # 1 - states
    missing = src["states"] - kg["states"]
    extra = kg["states"] - src["states"]
    checks["states_identical"] = not missing and not extra
    print(f"\n   [1] state sets identical        : "
          f"{'yes' if checks['states_identical'] else 'NO'}")
    if missing:
        print(f"       missing from graph ({len(missing)}): {sorted(missing)[:5]}")
    if extra:
        print(f"       only in graph ({len(extra)}): {sorted(extra)[:5]}")

    # 2 - transitions with source state and result states
    arc_missing = src["arcs"] - kg["arcs"]
    arc_extra = kg["arcs"] - src["arcs"]
    checks["arcs_identical"] = not arc_missing and not arc_extra
    print(f"   [2] transition sets identical   : "
          f"{'yes' if checks['arcs_identical'] else 'NO'}")
    for label, s in (("missing from graph", arc_missing), ("only in graph", arc_extra)):
        if s:
            print(f"       {label} ({len(s)}):")
            for parent, kids in sorted(s)[:5]:
                print(f"         {parent} -> {' + '.join(kids)}")

    # 3 - OR structure
    bs, bk = branching(src["arcs"]), branching(kg["arcs"])
    checks["branching_identical"] = bs == bk
    or_src = sum(1 for v in bs.values() if v > 1)
    print(f"   [3] OR branching identical      : "
          f"{'yes' if checks['branching_identical'] else 'NO'}"
          f"   ({or_src:,} states with alternatives, "
          f"max {max(bs.values()) if bs else 0})")
    if bs != bk:
        diff = [(k, bs.get(k), bk.get(k)) for k in set(bs) | set(bk)
                if bs.get(k) != bk.get(k)]
        print(f"       differing states ({len(diff)}): {diff[:5]}")

    # 4 - root state
    def root_of(arcs, states):
        produced = {c for _, kids in arcs for c in kids}
        return {s for s in states if s not in produced}
    r_src, r_kg = root_of(src["arcs"], src["states"]), root_of(kg["arcs"], kg["states"])
    checks["root_identical"] = r_src == r_kg and len(r_src) == 1
    print(f"   [4] unique root state           : "
          f"{'yes' if checks['root_identical'] else 'NO'}   {sorted(r_src)}")

    # 5 - terminal states
    decomposed = {p for p, _ in src["arcs"]}
    terminals_src = {s for s in src["states"] if s not in decomposed}
    terminals_kg = {s for s in kg["states"] if s not in {p for p, _ in kg["arcs"]}}
    checks["terminals_identical"] = terminals_src == terminals_kg
    print(f"   [5] terminal states identical   : "
          f"{'yes' if checks['terminals_identical'] else 'NO'}"
          f"   ({len(terminals_src)} states without an outgoing transition)")

    # 6 - AND semantics: transitions with more than two results
    multi_src = {a for a in src["arcs"] if len(a[1]) > 2}
    multi_kg = {a for a in kg["arcs"] if len(a[1]) > 2}
    checks["multi_result_arcs_identical"] = multi_src == multi_kg
    print(f"   [6] transitions with >2 results : "
          f"{'yes' if checks['multi_result_arcs_identical'] else 'NO'}"
          f"   ({len(multi_src)} transitions)")
    for parent, kids in sorted(multi_src)[:3]:
        print(f"         {parent} -> {' + '.join(kids)}")

    ok = all(checks.values())
    print(f"\n   RESULT: the knowledge graph is {'an exact' if ok else 'NOT an exact'} "
          f"encoding of the generated AND/OR graph")

    return {
        "product": product,
        "generator": {"states": len(src["states"]), "hyper_arcs": len(src["arcs"]),
                      "transitions": src["n_transitions"]},
        "knowledge_graph": {"states": len(kg["states"]), "hyper_arcs": len(kg["arcs"])},
        "or_states": or_src,
        "max_branching": max(bs.values()) if bs else 0,
        "multi_result_arcs": len(multi_src),
        "terminal_states": len(terminals_src),
        "root": sorted(r_src),
        "checks": checks,
        "equivalent": ok,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Compare the AND/OR graph in the knowledge graph with the "
                    "generated one (read-only database access).")
    ap.add_argument("--data", default=None,
                    help="product JSON file, the generator output "
                         "(default: the three sample products)")
    ap.add_argument("--out", default=None,
                    help="record file (only with --data; default: "
                         "scripts/aog_equivalence_<product id>.json)")
    args = ap.parse_args()

    if args.out and not args.data:
        ap.error("--out needs --data")
    paths = [args.data] if args.data else [os.path.join(PLATFORM_DIR, p)
                                           for p in SAMPLE_FILES]

    import config
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(config.NEO4J_URI,
                                  auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    all_ok = True
    try:
        for path in paths:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            pid = data["product"]["id"]

            src = source_aog(data)
            kg = graph_aog(driver, pid)
            if not kg["states"] and not kg["arcs"]:
                print(f"   NOTE: the database holds no AND/OR graph for {pid}; "
                      f"import the product first.")
            report = compare(data["product"], src, kg)
            all_ok = all_ok and report["equivalent"]

            out = args.out or os.path.join(PLATFORM_DIR, "scripts",
                                           f"aog_equivalence_{pid}.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
                f.write("\n")
            print(f"   Saved: {os.path.relpath(out)}\n")
    finally:
        driver.close()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
