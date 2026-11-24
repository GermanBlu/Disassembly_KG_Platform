#!/usr/bin/env python3
"""Seed the read-only demo.

Builds the knowledge graph of the hypothetical product from the bundled JSON
and then enriches every component with material, mass, recyclability and
end-of-life routing, adds product-level facts, placeholder disassembly
economics (time, cost and difficulty per task, labor rate per agent, tool cost,
product-level full-teardown totals) and the number of complete disassembly
sequences, so that the chat of the read-only demo can answer questions on
materials, recyclable mass, end-of-life streams, time and cost.

Safe to re-run: the build deletes the product-scoped graph of this product and
creates it again, then the enrichment is SET. The connection settings come from
config.py (environment variables NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD or the
`.env` file); the script waits for the database to come up.

Usage:
    python seed_demo_product.py
"""
import argparse
import json
import os
import time

from neo4j import GraphDatabase

import config

from models.economics import enrich_economics
from models.kg_builder import build_product_kg
from models.library import ensure_library
from models.product import count_disassembly_sequences

# Enrichment keyed by a case-insensitive substring of the component name.
ENRICHMENT = {
    "holder":     {"material": "Aluminium EN AW-6061", "mass_g": 120,
                   "recyclable": True, "eol_route": "recycle:aluminium"},
    "end plate":  {"material": "Steel S235JR", "mass_g": 85,
                   "recyclable": True, "eol_route": "recycle:steel"},
    "base plate": {"material": "Steel S235JR", "mass_g": 210,
                   "recyclable": True, "eol_route": "recycle:steel"},
    "tube":       {"material": "Brass CuZn37", "mass_g": 45,
                   "recyclable": True, "eol_route": "recycle:copper-alloy"},
    "shaft":      {"material": "Steel 42CrMo4 (hardened)", "mass_g": 160,
                   "recyclable": True, "eol_route": "recycle:steel"},
    "screw":      {"material": "Stainless steel A2-70", "mass_g": 12,
                   "recyclable": True, "eol_route": "recycle:steel"},
}

PRODUCT_PROPS = {
    "description": "Reference hypothetical product (8 parts, 2 M8 screw joints) "
                   "enriched with materials and end-of-life data for the demo.",
    "total_mass_g": 689,            # sum of component masses (120+85+12+210+45+12+45+160)
    "recyclable_mass_pct": 100,
}


def _connect():
    uri, user, pwd = config.NEO4J_URI, config.NEO4J_USER, config.NEO4J_PASSWORD
    last = None
    for attempt in range(60):
        try:
            driver = GraphDatabase.driver(uri, auth=(user, pwd))
            driver.verify_connectivity()
            print(f"Connected to Neo4j at {uri}")
            return driver
        except Exception as e:  # noqa: BLE001 — wait for the DB to come up
            last = e
            time.sleep(2)
    raise SystemExit(f"Could not connect to Neo4j at {uri} after retries: {last}")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    data = json.load(open(os.path.join(here, "sample_data", "hypothetical_product.json")))
    pid = data["product"]["id"]

    driver = _connect()
    ensure_library(driver)
    build_product_kg(driver, data)

    with driver.session() as s:
        for key, props in ENRICHMENT.items():
            s.run(
                "MATCH (c:Component {product_id: $pid}) "
                "WHERE toLower(c.name) CONTAINS $key "
                "SET c += $props",
                pid=pid, key=key, props=props,
            )
        s.run("MATCH (p:Product {id: $pid}) SET p += $props", pid=pid, props=PRODUCT_PROPS)

    # Placeholder disassembly economics (time / cost / difficulty / force) for
    # the chat and the node-detail panel.
    econ = enrich_economics(driver, pid)
    if econ:
        print(f"Economics enriched: {econ['task_count']} tasks, "
              f"~{econ['total_time_s']}s / ~€{econ['total_cost_eur']} full teardown")

    # Store both counts on the Product node (like full_teardown_*), so the
    # chat can answer "how many complete disassembly sequences exist?" (284).
    seq = count_disassembly_sequences(driver, pid)
    if seq and seq.get("sequence_count"):
        with driver.session() as s:
            s.run("MATCH (p:Product {id: $pid}) "
                  "SET p.sequence_count = $c, p.ordering_count = $o",
                  pid=pid, c=seq["sequence_count"], o=seq["ordering_count"])
        print(f"Sequence count seeded: {seq['sequence_count']} complete sequences, "
              f"{seq['ordering_count']} orders of execution")

    print(f"Demo product seeded and enriched: {pid}")
    driver.close()


if __name__ == "__main__":
    # No options: any argument other than -h/--help is an error, so a mistyped
    # call does not write to the database.
    argparse.ArgumentParser(
        description="Seed the demo product (Hypothetical product with material, "
                    "end-of-life and placeholder economics data) into the Neo4j "
                    "database configured in config.py / .env. The product-scoped "
                    "graph of Prod_HypotheticalProduct is replaced.").parse_args()
    main()
