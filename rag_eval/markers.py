"""Refusal markers: catalog refusal names -> stable answer fragments.

The fragments are lowercase substrings matched against the chat answer. They
are copies of the texts rag/engine.py emits; tests/test_rag_eval_cases.py
tripwires them against the engine source so silent drift fails the suite.
"""

# refusal name (used in cases.json "expect.refusal") -> answer fragment
REFUSAL_FRAGMENTS = {
    "no_data":            "could not find relevant information in the knowledge graph",
    "read_only":          "this is a read-only demo",
    "destructive":        "i cannot delete or remove nodes or relationships",
    "cannot_enrich":      "cannot be handled as a property enrichment",
    "resource_not_found": "could not find the specified resource in the library",
    "blocked_protected":  "cannot modify protected property",
    "blocked_library":    "cannot set properties on shared library nodes",
}

# Fragments that must literally appear in rag/engine.py (case-insensitive) —
# checked by the drift tripwire test. Keys are engine constants/handler texts.
ENGINE_SOURCE_FRAGMENTS = list(REFUSAL_FRAGMENTS.values())
