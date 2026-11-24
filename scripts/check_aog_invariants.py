#!/usr/bin/env python3
"""Check six structural properties of a generated AND/OR graph.

The equivalence check (verify_aog_equivalence.py) compares the knowledge graph
with the generator output. It shows that the transformation into the graph
database loses nothing; it does not show that the AND/OR graph itself is well
formed. This script checks the AND/OR graph against properties that follow
from the definition of a disassembly AND/OR graph, independently of how the
graph was produced.

Input is a product JSON file (components, connections, transitions). A state
is the source state of a transition or a result with more than one part. The
script needs no database and no CAD kernel.

The six properties, in the order and wording of the paper, and what the
script checks for each:

  1. partition      "every hyper-arc partitions its parent state exactly":
                    for every transition, the union of the results equals the
                    source state and no part occurs in two results.
  2. reduction      "every transition reduces the component count": every
                    result of a transition has fewer parts than the source
                    state, so the graph has no cycles.
  3. connectedness  "each assembly state is connected under the defined
                    connections": the parts of every state form one connected
                    piece. A connection with a fastener links its two parts
                    only while the fastener is present; the fastener itself is
                    linked to each of the two parts that is present.
  4. unique_root    "the root state is unique": exactly one state is not the
                    result of any transition, and this state consists of all
                    parts of the product. The record stores the second half as
                    "root_is_full_assembly". The violation count is 0 if both
                    hold, otherwise the number of states that are not the
                    result of any transition (at least 1).
  5. closure        "the graph is closed under the transition relation": every
                    state is the source state of at least one transition.
                    Since the states are the source states and the multi-part
                    results, every multi-part result is taken apart further,
                    down to single parts. The violations are the states
                    without a transition; the record stores their number as
                    "closure" under "violations" and again as
                    "states_without_transition".
  6. reachability   "every state is reachable from the root": a graph search
                    starts at the state that consists of all parts and follows
                    every transition from its source state to its multi-part
                    results. The violations are the states the search does
                    not visit.

One additional check is reported separately and is not one of the six:

     progress       Every transition has at least two results, and none of
                    them is the source state itself. It follows from
                    properties 1 and 2 and is kept as a direct test of the
                    transition records ("additional_checks" in the record).

Usage (from the repository root):

    python scripts/check_aog_invariants.py
        checks the three sample products and writes one record each to
        scripts/aog_invariants_<product id>.json

    python scripts/check_aog_invariants.py --data sample_data/ballpoint_pen.json
    python scripts/check_aog_invariants.py --data <file.json> --out <record.json>
    python scripts/check_aog_invariants.py --no-save

Exit code 0 if the six properties and the additional check hold for every
checked product, otherwise 1.
"""
import argparse
import json
import os
import sys

PLATFORM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE_FILES = [
    os.path.join("sample_data", "ballpoint_pen.json"),
    os.path.join("sample_data", "hypothetical_product.json"),
    os.path.join("sample_data", "Centrifugal Pump", "centrifugal_pump_product.json"),
]


def connected_under(parts, connections):
    """Do these parts hang together via the defined connections?

    A screw joint holds only while the fastener and both secured parts are
    present; that is the same rule the pipeline applies semantically.
    """
    parts = set(parts)
    if len(parts) <= 1:
        return True
    adj = {p: set() for p in parts}
    for c in connections:
        a, b, f = c["part1"], c["part2"], c.get("fastener_id")
        if a in parts and b in parts and (f is None or f in parts):
            adj[a].add(b)
            adj[b].add(a)
        if f and f in parts:
            for p in (a, b):
                if p in parts:
                    adj[f].add(p)
                    adj[p].add(f)
    seen, stack = set(), [next(iter(parts))]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj[cur] - seen)
    return seen == parts


def check_invariants(data, verbose=True):
    """Check the six properties on one product dict and return the record."""
    say = print if verbose else (lambda *a, **k: None)

    trans = data["transitions"]
    conns = data.get("connections", [])
    all_parts = {c["partId"] for c in data["components"]}

    states = {t["from_parts"] for t in trans}
    for t in trans:
        states.update(r for r in t["results_in"] if len(r) > 1)

    say(f"== AND/OR graph properties: {data['product']['name']} ==")
    say(f"   {len(all_parts)} parts, {len(states):,} states, {len(trans):,} transitions\n")

    fails = {}

    def line(no, text, bad, word="VIOLATIONS"):
        say(f"   [{no}] {text:<52}: "
            f"{'OK' if not bad else f'{len(bad)} {word} {sorted(bad)[:5]}'}")

    # 1 - partition: every hyper-arc partitions its parent state exactly
    bad = []
    for t in trans:
        parent, kids = set(t["from_parts"]), [set(r) for r in t["results_in"]]
        union = set().union(*kids) if kids else set()
        overlap = sum(len(k) for k in kids) != len(union)
        if union != parent or overlap:
            bad.append(t["id"])
    fails["partition"] = bad
    line(1, "partition (results partition the source state)", bad)

    # 2 - reduction: every transition reduces the component count
    bad = [t["id"] for t in trans
           if any(len(r) >= len(t["from_parts"]) for r in t["results_in"])]
    fails["reduction"] = bad
    line(2, "reduction (every result smaller than the source)", bad)

    # 3 - connectedness: each state is connected under the defined connections
    bad = [s for s in states if not connected_under(s, conns)]
    fails["connectedness"] = bad
    line(3, "connectedness (every state hangs together)", bad, "DISCONNECTED")

    # 4 - unique root: exactly one state is not the result of any transition,
    # and it consists of all parts
    produced = {r for t in trans for r in t["results_in"]}
    roots = sorted(s for s in states if s not in produced)
    root_is_full = len(roots) == 1 and set(roots[0]) == all_parts
    fails["unique_root"] = [] if root_is_full else (roots or ["<no root>"])
    line(4, "unique root, equal to the complete product", fails["unique_root"], "ROOTS")

    # 5 - closure: every state (source state or multi-part result) is the
    # source state of at least one transition
    sources = {t["from_parts"] for t in trans}
    undecomposed = sorted(s for s in states if s not in sources)
    fails["closure"] = undecomposed
    line(5, "closure (every state has a transition)", undecomposed, "WITHOUT TRANSITION")

    # 6 - reachability: graph search from the state of all parts along the
    # transitions (source state -> multi-part results)
    successors = {}
    for t in trans:
        successors.setdefault(t["from_parts"], set()).update(
            r for r in t["results_in"] if len(r) > 1)
    start = [s for s in states if set(s) == all_parts]
    reached, stack = set(), list(start)
    while stack:
        cur = stack.pop()
        if cur in reached:
            continue
        reached.add(cur)
        stack.extend(successors.get(cur, ()))
    unreachable = sorted(s for s in states if s not in reached)
    fails["reachability"] = unreachable
    line(6, "reachability (every state reached from the root)", unreachable, "UNREACHABLE")

    # additional check, not one of the six: progress
    progress = [t["id"] for t in trans
                if len(t["results_in"]) < 2 or t["from_parts"] in t["results_in"]]
    say(f"   [+] {'progress (>=2 results, source not returned)':<52}: "
        f"{'OK' if not progress else f'{len(progress)} VIOLATIONS {progress[:5]}'}")

    ok = not any(fails.values())
    extra_ok = not progress
    say(f"\n   RESULT: {'all six properties hold' if ok else 'PROPERTIES VIOLATED'}"
        f"{'' if extra_ok else '; additional check failed'}")

    return {"product": data["product"],
            "states": len(states), "arcs": len(trans),
            "violations": {k: len(v) for k, v in fails.items()},
            "root_is_full_assembly": root_is_full,
            "states_without_transition": len(undecomposed),
            "states_reached_from_root": len(reached),
            "additional_checks": {"progress": len(progress)},
            "all_hold": ok and extra_ok}


def main():
    ap = argparse.ArgumentParser(
        description="Check six structural properties of a generated AND/OR graph.")
    ap.add_argument("--data", default=None,
                    help="product JSON file (default: the three sample products)")
    ap.add_argument("--out", default=None,
                    help="record file (only with --data; default: "
                         "scripts/aog_invariants_<product id>.json)")
    ap.add_argument("--no-save", action="store_true", help="do not write a record")
    args = ap.parse_args()

    if args.out and not args.data:
        ap.error("--out needs --data")
    paths = [args.data] if args.data else [os.path.join(PLATFORM_DIR, p)
                                           for p in SAMPLE_FILES]

    all_ok = True
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        report = check_invariants(data)
        all_ok = all_ok and report["all_hold"]
        if not args.no_save:
            out = args.out or os.path.join(
                PLATFORM_DIR, "scripts", f"aog_invariants_{data['product']['id']}.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
                f.write("\n")
            print(f"   Saved: {os.path.relpath(out)}")
        print()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
