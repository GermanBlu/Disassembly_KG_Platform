#!/usr/bin/env python3
"""Connected subsets of the pump's contact graph, with and without fastener groups.

Every assembly state of an AND/OR graph is a connected subset of the contact
(liaison) graph, so the number of connected induced subgraphs is an upper bound
on the number of states the generator has to visit. It can be counted exactly
without building the AND/OR graph. This script produces the four counts of
Table 8 of the paper (no group, only the M12 group, only the M20 group, both
groups) and writes them to scripts/state_space_counts.json.

The count uses the standard connected-subgraph enumeration (each subset is
reached exactly once, anchored on its lowest-indexed vertex);
tests/test_state_counting.py checks it against closed-form counts and a
brute-force reference.

Input: the liaison matrix and the two fastener groups. They are read from
Phase 1 on the pump STEP file when that file is present (needs the OCC conda
environment). The STEP file is not distributed, so without it the script reads
the same matrix and groups from
sample_data/Centrifugal Pump/centrifugal_pump_product.json.

Usage:
    python scripts/count_state_space.py               # STEP file if present, else product JSON
    python scripts/count_state_space.py --from-json   # always the product JSON
    python scripts/count_state_space.py --step <file.stp> [--label NAME]   # one STEP file, no groups
"""
import argparse
import json
import os
import sys
import time

PLATFORM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLATFORM_DIR)

# Not distributed (GrabCAD terms); see sample_data/Centrifugal Pump/MODEL_CHANGES.md
PUMP = os.path.join(PLATFORM_DIR, "sample_data", "Centrifugal Pump",
                    "centrifugal_pump.stp")
PUMP_JSON = os.path.join(PLATFORM_DIR, "sample_data", "Centrifugal Pump",
                         "centrifugal_pump_product.json")
HYPO = os.path.join(PLATFORM_DIR, "sample_data", "Hypothetical Product STEP",
                    "Hypothetical_Product_Passungen.step")
OUT = os.path.join(PLATFORM_DIR, "scripts", "state_space_counts.json")


def count_connected_subsets(adj, n, limit=None):
    """Number of connected induced subgraphs (non-empty). Exact.

    ESU enumeration (Wernicke): each subset is reached exactly once, anchored on
    its lowest-indexed vertex. A vertex may only enter the extension if it is not
    already adjacent to the current subgraph — tracking that neighbourhood is
    what makes the count exact; testing only against the current extension set
    lets the same subset be reached through several orders.

    Returns (count, complete) — complete is False if `limit` was hit.
    """
    total = 0
    for v in range(n):
        higher = ~((1 << (v + 1)) - 1)          # vertices with index > v
        # (subgraph, extension, neighbourhood of the subgraph)
        stack = [(1 << v, adj[v] & higher, adj[v] | (1 << v))]
        while stack:
            sub, ext, nbhd = stack.pop()
            total += 1
            if limit is not None and total >= limit:
                return total, False
            rest = ext
            while rest:
                w = rest & -rest
                rest ^= w
                wi = w.bit_length() - 1
                # w's neighbours that the subgraph has not touched yet
                new_ext = rest | (adj[wi] & higher & ~nbhd)
                stack.append((sub | w, new_ext, nbhd | adj[wi] | w))
    return total, True


def count_connected_bruteforce(adj, n):
    """Reference implementation for validation — enumerates all 2^n subsets."""
    total = 0
    for mask in range(1, 1 << n):
        start = (mask & -mask).bit_length() - 1
        seen, stack = 0, [start]
        while stack:
            u = stack.pop()
            if seen & (1 << u):
                continue
            seen |= 1 << u
            nxt = adj[u] & mask & ~seen
            while nxt:
                b = nxt & -nxt
                nxt ^= b
                stack.append(b.bit_length() - 1)
        if seen == mask:
            total += 1
    return total


def adjacency(liaison):
    n = len(liaison)
    adj = [0] * n
    for i in range(n):
        for j in range(n):
            if i != j and liaison[i][j]:
                adj[i] |= 1 << j
    return adj


def phase1_liaison(step_file, label):
    from models.step_pipeline import _init_cocoa
    _init_cocoa()
    from pipeline.geometry import load_and_extract
    geo = load_and_extract(step_files=[os.path.abspath(step_file)],
                           part_labels=[label], log_fn=lambda m: None)
    lm = geo["liaison_matrix"]
    return (lm.tolist() if hasattr(lm, "tolist") else lm), geo["part_labels"]


def report(name, liaison, labels, limit):
    n = len(labels)
    contacts = sum(sum(r) for r in liaison) // 2
    adj = adjacency(liaison)
    t0 = time.time()
    count, complete = count_connected_subsets(adj, n, limit=limit)
    dt = time.time() - t0
    singles = n                       # the n one-part states
    multi = count - singles
    print(f"\n== {name} ==")
    print(f"   parts            : {n}")
    print(f"   contacts         : {contacts}")
    print(f"   connected subsets: {count:,}{'' if complete else f' (stopped at limit {limit:,})'}")
    print(f"     of which single parts : {singles:,}")
    print(f"     of which subassemblies: {multi:,}")
    print(f"   counted in       : {dt:.1f}s")
    return {"parts": n, "contacts": contacts, "connected_subsets": count,
            "subassemblies": multi, "complete": complete, "seconds": round(dt, 1)}


def merge_groups(liaison, groups):
    """Contract every group (a list of vertex indices) to one vertex.

    The merged vertex is adjacent to everything any member was adjacent to.
    Returns the liaison matrix of the reduced graph.
    """
    n = len(liaison)
    owner = list(range(n))
    for members in groups:
        for m in members:
            owner[m] = members[0]
    units = sorted(set(owner))
    index = {u: k for k, u in enumerate(units)}
    out = [[0] * len(units) for _ in units]
    for i in range(n):
        for j in range(n):
            a, b = index[owner[i]], index[owner[j]]
            if a != b and liaison[i][j]:
                out[a][b] = out[b][a] = 1
    return out


def _group_label(names, members):
    """'M12 Flange Bolt' for the group of 'M12 Flange Bolt_1' … '_4'."""
    import re
    name = re.sub(r"\s*\([A-Za-z0-9]+\)$", "", names[members[0]])   # "… (L)" from Phase 1
    return re.sub(r"[_ ]\d+$", "", name)


def pump_from_json(path=PUMP_JSON):
    data = json.load(open(path))
    names = [c["name"] for c in data["components"]]
    groups = [list(g["members"]) for g in data.get("fastener_groups", [])]
    return data["liaison_matrix"], names, groups


def pump_from_step(path=PUMP):
    lm, labels = phase1_liaison(path, "Centrifugal Pump")
    from pipeline.fastener_detection import detect_fasteners, suggest_fastener_groups
    fast = detect_fasteners(None, labels)["fastener_indices"]
    groups = suggest_fastener_groups(sorted(fast), labels, lm)
    return lm, labels, [list(g["members"]) for g in groups]


def table8(liaison, names, groups, limit=None):
    """The four configurations of Table 8 as rows, plus the reduction factor."""
    groups = sorted(groups, key=len)
    configs = [("ungrouped", [])]
    configs += [(f"only the {len(g)} {_group_label(names, g)}s grouped", [g])
                for g in groups]
    if len(groups) > 1:
        configs.append(("all groups", groups))
    rows = []
    for label, gs in configs:
        lm = merge_groups(liaison, gs)
        count, complete = count_connected_subsets(adjacency(lm), len(lm), limit=limit)
        row = {"config": label, "units": len(lm), "connected_subsets": count}
        if not complete:
            row["complete"] = False
        rows.append(row)
        print(f"   {label:45s} units {len(lm):3d}   connected subsets {count:>12,}")
    factor = round(rows[0]["connected_subsets"] / rows[-1]["connected_subsets"], 1)
    return rows, factor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", default=None, help="single STEP file to analyse")
    ap.add_argument("--label", default=None)
    ap.add_argument("--limit", type=int, default=200_000_000)
    ap.add_argument("--from-json", action="store_true",
                    help="read the pump liaison matrix and groups from the "
                         "product JSON even if the STEP file is present")
    args = ap.parse_args()

    if args.step:
        lm, labels = phase1_liaison(args.step, args.label or "Assembly")
        report(args.label or "Assembly", lm, labels, args.limit)
        return

    if args.from_json or not os.path.exists(PUMP):
        if not args.from_json:
            print(f"Pump STEP file not found ({os.path.relpath(PUMP, PLATFORM_DIR)}); "
                  f"using the liaison matrix of {os.path.relpath(PUMP_JSON, PLATFORM_DIR)}.")
        source = PUMP_JSON
        lm, names, groups = pump_from_json()
    else:
        # Check of the method on a small product: the hypothetical product has
        # 83 connected subsets (8 single parts and 75 subassemblies). Its
        # AND/OR graph keeps 41 of them as assembly states.
        h_lm, h_labels = phase1_liaison(HYPO, "Hypothetical Product")
        report("Hypothetical Product", h_lm, h_labels, args.limit)
        source = PUMP
        lm, names, groups = pump_from_step()

    print("\n== Centrifugal Pump ==")
    rows, factor = table8(lm, names, groups, args.limit)
    print(f"   reduction factor ungrouped / all groups: {factor}")
    result = {
        "source": os.path.relpath(source, PLATFORM_DIR),
        "note": "exact enumeration of connected induced subgraphs of the contact graph",
        "rows": rows,
        "reduction_factor": factor,
    }
    with open(OUT, "w") as f:
        json.dump(result, f, indent=1)
    print(f"\nSaved: {os.path.relpath(OUT, PLATFORM_DIR)}")


if __name__ == "__main__":
    main()
