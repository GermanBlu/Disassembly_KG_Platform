#!/usr/bin/env python3
"""Seed the Hypothetical Product benchmark into Neo4j — the reference recipe.

Reproduces the reference benchmark counts from the raw assembly STEP, mirroring the
golden end-to-end test (tests/test_golden_e2e.py):

    geometry          → 8 parts, 9 contacts (0.5 mm), 6 test directions from
                        the contact surfaces (Phase 1 with the standard settings)
    two-step removal  → the end plate (B) slides off the shaft and leaves
                        upwards; Phase 1 recognises it, no precedence rule
    fastener semantics→ the two M8 cap screws (auto-detected by name)
    result            → 6 connections, 41 assembly states, 114 transitions
                        (the geometric AND/OR graph before the semantic
                        checks has 70 nodes: 8 single parts and 62
                        subassemblies)

The result is written to the Neo4j database configured in config.py (environment
variables NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD or the `.env` file); the
product-scoped graph of Prod_HypotheticalProduct is replaced.

Usage (inside the OCC conda env, with Neo4j running):
    python seed_benchmark.py
"""
import argparse
import os
import re
import sys

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from pipeline.part_ids import part_id  # noqa: E402

ASSEMBLY_FILE = os.path.join(
    PLATFORM_DIR, "sample_data", "Hypothetical Product STEP",
    "Hypothetical_Product_Passungen.step",
)
_FASTENER_PAT = re.compile(r"\b(screw|bolt|nut|washer|rivet|pin)\b", re.I)


def seed_hypothetical_benchmark():
    from models.step_pipeline import check_occ_available, _init_cocoa
    available, err = check_occ_available()
    if not available:
        print(f"OCC unavailable: {err}")
        return
    _init_cocoa()

    from models.step_pipeline import run_step_phase1
    from pipeline.semantic import generate_semantic_tables

    print("Phase 1 — geometry from the assembly STEP (standard settings)...")
    p1 = run_step_phase1([ASSEMBLY_FILE], ["Assembly"])
    if not p1["success"]:
        print(f"Phase 1 failed: {p1['error']}")
        return
    labels = p1["parts"]
    lm_list = p1["liaison_matrix"]
    int_list = p1["interference_matrices"]
    contacts = sum(sum(row) for row in lm_list) // 2
    fasteners = [i for i, l in enumerate(labels) if _FASTENER_PAT.search(l)]
    print(f"  parts={len(labels)} contacts={contacts} fasteners={len(fasteners)} "
          f"two-step releases={len(p1['two_step_releases'])}")

    print("Phase 2 — semantics (fasteners, no precedence rule)...")
    res = generate_semantic_tables(
        fastener_indices=fasteners, part_labels=labels,
        liaison_matrix=lm_list, interference_matrices=int_list,
    )
    if not res.get("success"):
        print(f"Pipeline failed: {res.get('error')}")
        return
    aog = next((int(m.group(1)) for m in
                (re.search(r"AOG: (\d+) reachable nodes", line)
                 for line in res.get("log", [])) if m), None)
    print(f"  connections={len(res['connections'])} "
          f"aog_nodes={aog} transitions={len(res['transitions'])}")

    print("Saving to Neo4j (build replaces the product)...")
    from neo4j import GraphDatabase
    import config
    from models.kg_builder import build_product_kg

    components = []
    for i, label in enumerate(labels):
        letter = part_id(i)
        clean = label.replace(f" ({letter})", "").strip()
        components.append({"partId": letter, "name": clean,
                           "type": "Fastener" if i in fasteners else "Part"})

    driver = GraphDatabase.driver(config.NEO4J_URI,
                                  auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    build_product_kg(driver, {
        "product": {"id": "Prod_HypotheticalProduct",
                    "name": "Hypothetical Product"},
        "components": components,
        "connections": res.get("connections", []),
        "transitions": res["transitions"],
        "connection_bundles": res.get("connection_bundles"),
    })
    driver.close()
    print(f"\nBenchmark seeded: {len(labels)} parts, "
          f"{len(res['transitions'])} transitions "
          f"({'MATCHES' if len(res['transitions']) == 114 else 'DOES NOT MATCH'} "
          f"the documented 114).")


if __name__ == "__main__":
    # No options: any argument other than -h/--help is an error, so a mistyped
    # call does not start the pipeline or write to the database.
    argparse.ArgumentParser(
        description="Run the STEP pipeline on the Hypothetical product and write "
                    "the result (41 states, 114 transitions) to the Neo4j database "
                    "configured in config.py / .env. Needs pythonocc-core and a "
                    "running Neo4j.").parse_args()
    seed_hypothetical_benchmark()
