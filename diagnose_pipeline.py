#!/usr/bin/env python3
"""Diagnostic script: run the full pipeline from STEP files with zero hardcoding.

Outputs every intermediate result so we can trace exactly what happens:
  1. Part extraction (names, order)
  2. Computed liaison matrix (who contacts whom)
  3. Interference matrices (one per test direction from the contact surfaces,
     Phase 1 with the standard settings, as the platform runs it)
  4. AOG statistics
  5. All transitions (with and without precedence rules)

Usage (run inside the OCC conda environment):
    python diagnose_pipeline.py
"""
import os, sys, time, json
import numpy as np

from pipeline.part_ids import part_id

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)


# ── Configuration ────────────────────────────────────────────────────────────

STEP_DIR = os.path.join(PLATFORM_DIR, "sample_data", "Hypothetical Product STEP")

# Use the ASSEMBLY STEP file — XCAF extraction applies correct position transforms.
# Individual part files DON'T carry assembly positions → parts load at origin → wrong liaison.
ASSEMBLY_FILE = os.path.join(STEP_DIR, "Hypothetical_Product_Passungen.step")

# Filled from Phase 1: one label per test direction, e.g. "(0, -1, 0)".
DIR_NAMES = []
CONTACT_TOL = 0.5   # mm, replaced by the value of the standard settings in main()


def hr(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_matrix(matrix, labels, title):
    """Pretty-print an NxN matrix with row/col labels."""
    n = len(labels)
    letters = [part_id(i) for i in range(n)]

    print(f"\n  {title}")
    header = "      " + "  ".join(f"{l:>3}" for l in letters)
    print(header)
    for i in range(n):
        row_vals = "  ".join(f"{int(matrix[i][j]):>3}" for j in range(n))
        print(f"  {letters[i]}   {row_vals}   {labels[i]}")


def print_contacts(liaison, labels):
    """Print which parts contact which."""
    n = len(labels)
    letters = [part_id(i) for i in range(n)]
    print("\n  Contact pairs (liaison = 1):")
    for i in range(n):
        contacts = [f"{letters[j]}({labels[j]})" for j in range(n) if liaison[i][j] == 1]
        if contacts:
            print(f"    {letters[i]}({labels[i]}) contacts: {', '.join(contacts)}")
        else:
            print(f"    {letters[i]}({labels[i]}) contacts: NONE")


def print_interference_detail(interference_matrices, labels):
    """For each direction, show which pairs interfere."""
    n = len(labels)
    letters = [part_id(i) for i in range(n)]

    for d, (matrix, dname) in enumerate(zip(interference_matrices, DIR_NAMES)):
        m = np.array(matrix)
        pairs = []
        for i in range(n):
            for j in range(n):
                if i != j and m[i][j] == 1:
                    pairs.append(f"{letters[i]}->{letters[j]}")
        count = int(m.sum())
        print(f"\n  Direction {dname}: {count} interferences")
        if pairs:
            # Group by blocker
            for i in range(n):
                blocked_by = [letters[j] for j in range(n) if j != i and m[i][j] == 1]
                if blocked_by:
                    print(f"    {letters[i]}({labels[i]}) blocked by: {', '.join(blocked_by)}")


def print_separability_analysis(liaison, interference_matrices, labels):
    """For each contacting pair, show in which directions they can separate."""
    n = len(labels)
    letters = [part_id(i) for i in range(n)]

    print("\n  Separability analysis (contacting pairs only):")
    for i in range(n):
        for j in range(i + 1, n):
            if liaison[i][j] != 1:
                continue
            free_dirs_ij = []  # directions where i can move away from j
            free_dirs_ji = []  # directions where j can move away from i
            for d, dname in enumerate(zip(interference_matrices, DIR_NAMES)):
                matrix, name = dname
                m = np.array(matrix)
                if m[i][j] == 0:
                    free_dirs_ij.append(name)
                if m[j][i] == 0:
                    free_dirs_ji.append(name)

            print(f"\n    {letters[i]}({labels[i]}) <-> {letters[j]}({labels[j]}):")
            print(f"      {letters[i]} free from {letters[j]} in: {free_dirs_ij or 'NONE (fully blocked)'}")
            print(f"      {letters[j]} free from {letters[i]} in: {free_dirs_ji or 'NONE (fully blocked)'}")


def analyze_transitions(transitions, labels):
    """Categorize and display transitions."""
    n = len(labels)
    letters = [part_id(i) for i in range(n)]

    print(f"\n  Total transitions: {len(transitions)}")

    # Group by from_parts length
    by_size = {}
    for t in transitions:
        size = len(t["from_parts"])
        by_size.setdefault(size, []).append(t)

    for size in sorted(by_size.keys(), reverse=True):
        group = by_size[size]
        print(f"\n  From {size}-part states ({len(group)} transitions):")
        for t in sorted(group, key=lambda x: x["from_parts"]):
            removed = t.get("removed_part", "?")
            results = " + ".join(t["results_in"])
            conn = t.get("broken_connection_id", "?")
            print(f"    {t['from_parts']} -> [{results}]  broken={conn}")

    # Transitions that remove the shaft or the end plate as a single part. The
    # part letters are read from the labels ("Shaft (H)").
    for name in ("Shaft", "End plate"):
        letter = next((letters[i] for i, label in enumerate(labels)
                       if label.rsplit(" (", 1)[0] == name), None)
        if letter is None:
            continue
        print(f"\n  --- {name} ({letter}) related transitions ---")
        related = [t for t in transitions
                   if letter in t.get("removed_part", "")
                   or any(r == letter for r in t["results_in"])]
        if related:
            for t in related:
                print(f"    {t['from_parts']} -> {t['results_in']}  broken={t.get('broken_connection_id')}")
        else:
            print(f"    (none where {letter} is removed as single part)")


def main():
    from models.step_pipeline import check_occ_available, _init_cocoa

    hr("DIAGNOSTIC: Hypothetical Product Pipeline Trace")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Check prerequisites ──────────────────────────────────────────────────
    available, err = check_occ_available()
    if not available:
        print(f"\n  ERROR: OpenCASCADE not available: {err}")
        print("  Run this script inside the OCC conda environment.")
        sys.exit(1)

    _init_cocoa()

    if not os.path.exists(ASSEMBLY_FILE):
        print(f"  ERROR: Missing assembly STEP file: {ASSEMBLY_FILE}")
        sys.exit(1)

    # ── Phase 1: Geometry + Liaison + Interference ───────────────────────────
    hr("PHASE 1: Geometry Extraction & Interference Check")

    from models.step_pipeline import run_step_phase1
    from pipeline.geometry import load_and_extract
    from pipeline.settings import STANDARD_SETTINGS

    global CONTACT_TOL
    CONTACT_TOL = STANDARD_SETTINGS["contact"]["fixed_value"]
    print(f"\n  Phase 1 on: {os.path.basename(ASSEMBLY_FILE)} (standard settings)")
    t0 = time.time()
    p1 = run_step_phase1([ASSEMBLY_FILE], ["Assembly"])
    if not p1["success"]:
        print(f"  ERROR: {p1['error']}")
        sys.exit(1)
    for line in p1["log"]:
        print(f"    {line}")
    # shapes for the pairwise distance table below
    parts = load_and_extract(step_files=[ASSEMBLY_FILE], part_labels=["Assembly"],
                             manual_liaison=None, settings=STANDARD_SETTINGS)["parts"]
    active_labels = p1["parts"]
    liaison = p1["liaison_matrix"]
    DIR_NAMES[:] = ["(" + ", ".join(f"{c:.3g}" for c in v) + ")" for v in p1["interference_directions"]]
    t_geo = time.time() - t0
    print(f"\n  Phase 1 done in {t_geo:.2f}s")

    # ── Print part assignment ────────────────────────────────────────────────
    hr("PART ASSIGNMENT")
    for i, label in enumerate(active_labels):
        print(f"  {part_id(i)}: {label}")

    # ── Print pairwise distances ────────────────────────────────────────────
    hr("PAIRWISE DISTANCES (mm) — for tolerance tuning")
    from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
    n = len(parts)
    letters = [part_id(i) for i in range(n)]
    print(f"\n  {'':6s}" + "".join(f"{letters[j]:>10s}" for j in range(n)))
    for i in range(n):
        row = f"  {letters[i]:4s}  "
        for j in range(n):
            if j <= i:
                row += f"{'':>10s}"
            else:
                dc = BRepExtrema_DistShapeShape(parts[i].Shape, parts[j].Shape)
                dist = dc.Value() if dc.IsDone() else -1
                marker = " *" if dist < CONTACT_TOL else ""
                row += f"{dist:>8.4f}{marker}"
        print(row)
    print(f"\n  * = below {CONTACT_TOL} mm threshold (contact)")

    # ── Print computed liaison matrix ────────────────────────────────────────
    hr(f"COMPUTED LIAISON MATRIX (from geometry, contact below {CONTACT_TOL} mm)")
    lm = np.array(liaison)
    print_matrix(lm, active_labels, "Liaison Matrix (1 = physical contact)")
    print_contacts(lm, active_labels)

    # ── Interference check ───────────────────────────────────────────────────
    hr(f"INTERFERENCE ({len(DIR_NAMES)} test directions from the contact surfaces)")
    int_matrices = [np.array(m) for m in p1["interference_matrices"]]
    t_int = p1["timing"].get("interference", 0.0)
    print(f"  Interference {t_int:.2f}s, two-step releases: {p1['two_step_releases'] or 'none'}")

    # Print each direction's matrix
    for d, (matrix, dname) in enumerate(zip(int_matrices, DIR_NAMES)):
        print_matrix(np.array(matrix), active_labels,
                     f"Interference Matrix — {dname}")

    # Print which parts block which in each direction
    hr("INTERFERENCE DETAIL (who blocks whom per direction)")
    print_interference_detail(int_matrices, active_labels)

    # ── Separability analysis ────────────────────────────────────────────────
    hr("SEPARABILITY ANALYSIS (contacting pairs)")
    print_separability_analysis(lm, int_matrices, active_labels)

    # ── Detect fasteners by name ────────────────────────────────────────────
    hr("FASTENER DETECTION")
    import re
    _FASTENER_PAT = re.compile(r'\b(screw|bolt|nut|washer|rivet|pin)\b', re.I)
    fastener_indices = [
        i for i, label in enumerate(active_labels) if _FASTENER_PAT.search(label)
    ]
    print(f"  Auto-detected fasteners (by name):")
    for fi in fastener_indices:
        print(f"    [{fi}] {letters[fi]}: {active_labels[fi]}")
    if not fastener_indices:
        print(f"    (none detected)")

    from pipeline.semantic import generate_semantic_tables

    int_matrices_list = [
        m.tolist() if hasattr(m, 'tolist') else [list(row) for row in m]
        for m in int_matrices
    ]

    # ── Phase 2a: WITH fasteners, NO precedence rules ────────────────────────
    hr("PHASE 2a: Semantic Tables — fasteners detected, NO precedence rules")

    result_a = generate_semantic_tables(
        fastener_indices=fastener_indices,
        part_labels=active_labels,
        liaison_matrix=lm.tolist(),
        interference_matrices=int_matrices_list,
        precedence_rules={},
    )

    if result_a["success"]:
        print(f"\n  Connections generated:")
        for c in result_a["connections"]:
            print(f"    {c['id']}: {c['part1']}<->{c['part2']} type={c['connectionType_id']}"
                  f" fastener={c.get('fastener_id')}")

        print(f"\n  Semantic liaison matrix (after fastener suppression):")
        if result_a.get("semantic_liaison_matrix"):
            slm = np.array(result_a["semantic_liaison_matrix"])
            print_matrix(slm, active_labels, "Semantic LM (fastener contacts suppressed)")

        analyze_transitions(result_a["transitions"], active_labels)
    else:
        print(f"  ERROR: {result_a.get('error')}")

    # ── Phase 2b: with one separation rule (redundant, because Phase 1
    #    recognises the end plate's two-step removal) ─────────────────────────
    # XCAF ordering: A=Holder, B=EndPlate, H=Shaft
    hr("PHASE 2b: Semantic Tables, fasteners + separation rule B→(H,A)")
    print("  Rule: B(EndPlate) must be removed before H(Shaft) and A(Holder) can separate"
          " — expected to prune nothing")

    result_b = generate_semantic_tables(
        fastener_indices=fastener_indices,
        part_labels=active_labels,
        liaison_matrix=lm.tolist(),
        interference_matrices=int_matrices_list,
        separation_precedence=[
            {"part1": "H", "part2": "A", "requires_removed": ["B"]},
        ],
    )

    if result_b["success"]:
        analyze_transitions(result_b["transitions"], active_labels)
    else:
        print(f"  ERROR: {result_b.get('error')}")

    # ── Comparison ───────────────────────────────────────────────────────────
    hr("COMPARISON")
    counts = {
        "Fasteners + no rules": len(result_a.get("transitions", [])),
        "Fasteners + separation rule": len(result_b.get("transitions", [])),
    }
    for label, count in counts.items():
        print(f"  {label:30s} → {count} transitions")

    # ── Save full results to JSON ────────────────────────────────────────────
    output_file = os.path.join(PLATFORM_DIR, "diagnostic_output.json")
    output = {
        "parts": active_labels,
        "computed_liaison_matrix": lm.tolist(),
        "interference_matrices": int_matrices_list,
        "interference_summary": [
            {"direction": dname, "count": int(np.array(m).sum())}
            for m, dname in zip(int_matrices, DIR_NAMES)
        ],
        "transitions_fasteners_no_rules": result_a.get("transitions", []),
        "transitions_fasteners_with_rules": result_b.get("transitions", []),
        "connections": result_a.get("connections", []),
    }
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Full results saved to: {output_file}")

    hr("DONE")


if __name__ == "__main__":
    main()
