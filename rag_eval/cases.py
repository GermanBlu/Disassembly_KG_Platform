"""Catalog loader + schema validation + selection helpers (stdlib only).

The catalog (cases.json) is the single source of truth for the eval runner,
the pytest guards, and the /api/chat/starters endpoint.
"""
import json
import os
import re

from rag_eval.markers import REFUSAL_FRAGMENTS

_CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.json")

_VALID_MODES = {"demo", "normal"}
_VALID_TARGETS = {"demo", "scratch"}
_VALID_SEVERITIES = {"core", "warn"}
_WRITE_CATEGORIES = {"write_enrichment", "write_reassignment"}


class CatalogError(ValueError):
    """The catalog violates its schema."""


def _validate_expect(expect, where):
    if not isinstance(expect, dict):
        raise CatalogError(f"{where}: expect must be an object")
    for group in expect.get("answer_all", []):
        if not isinstance(group, list) or not group:
            raise CatalogError(f"{where}: answer_all groups must be non-empty lists")
        for alt in group:
            if not isinstance(alt, str) or not alt:
                raise CatalogError(f"{where}: answer_all alternatives must be non-empty strings")
            if alt.startswith("re:"):
                re.compile(alt[3:])  # raises on bad pattern
    for frag in expect.get("answer_none", []):
        if not isinstance(frag, str) or not frag:
            raise CatalogError(f"{where}: answer_none entries must be non-empty strings")
    rows = expect.get("rows")
    if rows is not None and not (isinstance(rows, dict) and set(rows) <= {"min", "max"}):
        raise CatalogError(f"{where}: rows must be {{min?, max?}}")
    for key in ("cypher_any", "cypher_all"):
        for pat in expect.get(key, []):
            re.compile(pat, re.IGNORECASE)
    refusal = expect.get("refusal")
    if refusal is not None and refusal not in REFUSAL_FRAGMENTS:
        raise CatalogError(f"{where}: unknown refusal {refusal!r}")


def _validate_case(case):
    cid = case.get("id")
    if not cid:
        raise CatalogError("case without id")
    where = f"case {cid}"
    if case.get("category") is None:
        raise CatalogError(f"{where}: missing category")
    modes = case.get("modes")
    if not modes or not set(modes) <= _VALID_MODES:
        raise CatalogError(f"{where}: modes must be a non-empty subset of {_VALID_MODES}")
    if case.get("target", "demo") not in _VALID_TARGETS:
        raise CatalogError(f"{where}: bad target {case.get('target')!r}")
    if case.get("severity", "core") not in _VALID_SEVERITIES:
        raise CatalogError(f"{where}: bad severity {case.get('severity')!r}")
    if not case.get("question"):
        raise CatalogError(f"{where}: missing question")

    turns = case.get("turns")
    if turns:
        for i, turn in enumerate(turns):
            _validate_expect(turn.get("expect", {}), f"{where} turn {i}")
        if turns[0].get("message") not in (None, case["question"]):
            raise CatalogError(f"{where}: first turn message must be null (uses 'question')")
    else:
        _validate_expect(case.get("expect", {}), where)

    is_write = case["category"] in _WRITE_CATEGORIES
    if is_write:
        demo_over = case.get("expect_demo") or {}
        if demo_over.get("refusal") != "read_only":
            raise CatalogError(f"{where}: write case must set expect_demo.refusal='read_only'")
        if case.get("target") != "scratch":
            raise CatalogError(f"{where}: write case must target the scratch product")
        if case.get("ui_starter"):
            raise CatalogError(f"{where}: write cases cannot be UI starters")
    if case.get("ui_starter") and "demo" not in modes:
        raise CatalogError(f"{where}: UI starter cases must run in demo mode")
    if case.get("expect_demo") is not None:
        _validate_expect(case["expect_demo"], f"{where} expect_demo")


def load_cases(path=_CASES_PATH):
    """Load + validate the catalog. Returns the full catalog dict."""
    with open(path, encoding="utf-8") as f:
        catalog = json.load(f)
    cases = catalog.get("cases", [])
    ids = [c.get("id") for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise CatalogError(f"duplicate case ids: {dupes}")
    for case in cases:
        _validate_case(case)
    if not catalog.get("products", {}).get("demo", {}).get("id"):
        raise CatalogError("catalog must define products.demo.id")
    return catalog


def select(cases, mode, categories=None, ids=None):
    """Filter cases by runtime mode and optional --category/--case filters."""
    out = [c for c in cases if mode in c["modes"]]
    if categories:
        out = [c for c in out if c["category"] in set(categories)]
    if ids:
        out = [c for c in out if c["id"] in set(ids)]
    return out


def starters(cases, limit=6):
    """UI starter chips: the ui_starter cases in ui_order (read-only by schema)."""
    chips = [c for c in cases if c.get("ui_starter")]
    chips.sort(key=lambda c: c.get("ui_order", 99))
    return [{"id": c["id"], "q": c["question"]} for c in chips[:limit]]
