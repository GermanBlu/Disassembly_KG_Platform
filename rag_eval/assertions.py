"""Deterministic assertion engine: evaluate(expect, observed) -> failures.

observed = {
  "answer":   full streamed answer text,
  "cyphers":  every cypher event captured (a retry emits a second one),
  "rows":     row count from the done event (None -> treated as 0),
  "mutation": mutation flag from the done event,
  "error":    error event payload or None,
}

Assertions target stable facts (numbers, names, refusal markers) — never
phrasing, because the LLM rewords answers between runs.
"""
import re

from rag_eval.markers import REFUSAL_FRAGMENTS


def _matches(alternative, text):
    if alternative.startswith("re:"):
        return re.search(alternative[3:], text, re.IGNORECASE) is not None
    return alternative.lower() in text.lower()


def evaluate(expect, observed):
    """Return a list of human-readable failure strings (empty = pass)."""
    failures = []
    answer = observed.get("answer") or ""
    cypher_text = "\n".join(c for c in observed.get("cyphers", []) if c)
    rows = observed.get("rows")
    rows = 0 if rows is None else rows
    mutation = bool(observed.get("mutation"))

    if observed.get("error"):
        failures.append(f"engine error: {observed['error']}")

    for group in expect.get("answer_all", []):
        if not any(_matches(alt, answer) for alt in group):
            failures.append(f"answer missing all of {group}")

    for frag in expect.get("answer_none", []):
        if frag.lower() in answer.lower():
            failures.append(f"answer contains forbidden fragment {frag!r}")

    rows_spec = expect.get("rows") or {}
    if "min" in rows_spec and rows < rows_spec["min"]:
        failures.append(f"rows {rows} < min {rows_spec['min']}")
    if "max" in rows_spec and rows > rows_spec["max"]:
        failures.append(f"rows {rows} > max {rows_spec['max']}")

    for pat in expect.get("cypher_any", []):
        if re.search(pat, cypher_text, re.IGNORECASE):
            break
    else:
        if expect.get("cypher_any"):
            failures.append(f"cypher matches none of {expect['cypher_any']}")

    for pat in expect.get("cypher_all", []):
        if not re.search(pat, cypher_text, re.IGNORECASE):
            failures.append(f"cypher does not match {pat!r}")

    if "mutation" in expect and mutation != bool(expect["mutation"]):
        failures.append(f"mutation flag is {mutation}, expected {expect['mutation']}")

    refusal = expect.get("refusal")
    if refusal:
        frag = REFUSAL_FRAGMENTS[refusal]
        if frag.lower() not in answer.lower():
            failures.append(f"expected {refusal!r} refusal ({frag!r}) not in answer")

    return failures
