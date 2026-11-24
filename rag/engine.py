"""Unified GraphRAG Engine — product-scoped, streaming via SSE.

Pipeline: Question → Cypher Generation (LLM) → Neo4j Execution → Answer Formatting (LLM)

GROUNDED ANSWERS ONLY:
- The LLM may ONLY use data returned from Neo4j to answer questions.
- If Neo4j returns empty results, the system MUST respond with an explicit
  "I could not find..." message. It must NEVER fall back to general knowledge.
"""
import json
import logging
import re
import traceback
from rag.schema import build_schema_description
from rag.prompts import build_cypher_prompt, build_answer_prompt, build_mutation_prompt, build_reassignment_prompt
from rag.examples import build_examples

logger = logging.getLogger(__name__)

def _get_openai():
    """Lazy import to avoid hard dependency at module load time."""
    from openai import OpenAI
    return OpenAI

# Hard-coded refusal message — never let the LLM generate a fallback answer.
NO_DATA_MSG = ("I could not find relevant information in the Knowledge Graph "
               "to answer your question. Please try rephrasing or ask about "
               "components, connections, assembly/disassembly sequences, tasks, "
               "tools, or agents defined in this product.")

# Single canonical refusal for the read-only demo. Used at the routing layer AND
# at the entry of every write handler, so no path (keyword route, rule-14
# USE_ENRICHMENT_MODE handoff, …) can reach a write while read_only is set.
READ_ONLY_MSG = ("This is a read-only demo: you can ask questions about the "
                 "product, but changing the knowledge graph — property "
                 "enrichment/updates, resource reassignment, creating or "
                 "deleting nodes — is disabled.")



# ── Write guards (code checks applied to generated write Cypher) ─────────────
# Both write paths run their generated query through one of the two check
# functions below before anything is sent to Neo4j. A check returns None when
# the query is accepted, otherwise the reason for the rejection.

PROTECTED_PROPERTIES = ("id", "product_id", "partId", "isRoot", "isState", "name", "taskType")
LIBRARY_LABELS = ("Agent", "Tool", "Skill", "ConnectionType")
REASSIGNABLE_RELATIONSHIPS = ("PERFORMED_BY", "USES_TOOL", "REQUIRES")

_PROTECTED_LOWER = {p.lower() for p in PROTECTED_PROPERTIES}
_LIBRARY_LOWER = {l.lower() for l in LIBRARY_LABELS}
_CLAUSE_KEYWORDS = (
    "MATCH", "OPTIONAL", "WITH", "RETURN", "UNWIND", "WHERE", "SET", "CREATE",
    "MERGE", "DELETE", "DETACH", "REMOVE", "FOREACH", "CALL", "UNION", "ORDER",
    "LIMIT", "SKIP", "ON", "LOAD", "USE", "FINISH",
)
_CLAUSE_RE = re.compile(r"\b(?:%s)\b" % "|".join(_CLAUSE_KEYWORDS), re.IGNORECASE)
_OPEN, _CLOSE = "([{", ")]}"


def _mask_cypher(cypher):
    """Return the query with comments removed, string literals blanked and
    backtick-quoted identifiers unquoted, so that keywords and property names
    can be found without being misled by text inside literals."""
    out = []
    i, n = 0, len(cypher)
    while i < n:
        ch = cypher[i]
        if cypher.startswith("//", i):
            j = cypher.find("\n", i)
            i = n if j < 0 else j
        elif cypher.startswith("/*", i):
            j = cypher.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif ch in "'\"":
            j = i + 1
            while j < n and cypher[j] != ch:
                j += 2 if cypher[j] == "\\" else 1
            out.append("''")
            i = j + 1
        elif ch == "`":
            j = cypher.find("`", i + 1)
            j = n if j < 0 else j
            name = cypher[i + 1:j]
            out.append(name if re.fullmatch(r"\w+", name) else "_quoted_identifier_")
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _clauses(masked, keyword):
    """Bodies of every `keyword` clause: the text from the keyword up to the
    next clause keyword outside brackets (or a closing bracket or `;`)."""
    bodies = []
    for m in re.finditer(rf"\b{keyword}\b", masked, re.IGNORECASE):
        depth, i, start = 0, m.end(), m.end()
        while i < len(masked):
            ch = masked[i]
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE:
                if depth == 0:
                    break
                depth -= 1
            elif ch == ";" and depth == 0:
                break
            elif depth == 0 and (ch.isalpha() or ch == "_"):
                word = re.match(r"\w+", masked[i:])
                if (i == 0 or not (masked[i - 1].isalnum() or masked[i - 1] in "_.$")) \
                        and _CLAUSE_RE.fullmatch(word.group(0)):
                    break
                i += len(word.group(0))
                continue
            i += 1
        bodies.append(masked[start:i])
    return bodies


def _split_top_level(text, sep=","):
    """Split on `sep` outside brackets."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _map_keys(map_literal):
    """Top-level keys of a `{key: value, ...}` literal (already masked)."""
    inner = map_literal.strip()[1:-1]
    keys = []
    for entry in _split_top_level(inner):
        key = entry.split(":", 1)[0].strip()
        keys.append(key)
    return keys


def _balanced(text, start):
    """The bracketed expression that opens at text[start]."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] in _OPEN:
            depth += 1
        elif text[i] in _CLOSE:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def _node_bindings(masked):
    """{variable: [labels]} for every node pattern `(var:Label ...)` or `(var)`."""
    nodes = {}
    for m in re.finditer(r"\(\s*([A-Za-z_]\w*)\s*((?::\s*[\w|&!:\s]+?)?)\s*(?=[){])", masked):
        labels = [l.strip() for l in re.split(r"[:|&!\s]+", m.group(2)) if l.strip()]
        nodes.setdefault(m.group(1), []).extend(labels)
    return nodes


def _relationship_bindings(masked):
    """{variable: [types]} for every relationship pattern `[var:TYPE ...]`."""
    rels = {}
    for m in re.finditer(r"\[\s*([A-Za-z_]\w*)\s*((?::\s*[\w|:\s]+?)?)\s*(?=[\]{*])", masked):
        types = [t.strip() for t in re.split(r"[:|\s]+", m.group(2)) if t.strip()]
        rels.setdefault(m.group(1), []).extend(types)
    return rels


def _blocked_keyword(masked, keywords):
    for kw in keywords:
        if re.search(rf"\b{kw}\b", masked, re.IGNORECASE):
            return kw
    return None


def check_enrichment_query(cypher):
    """Code check of the enrichment path.

    Accepted: queries that only SET properties on existing, product-specific
    nodes. Rejected: structural keywords, a query without SET, SET of one of
    the PROTECTED_PROPERTIES (compared without regard to case, in `n.key = v`
    items, in `n += {...}` maps and in the `props` maps of an UNWIND list), SET
    forms whose keys cannot be read from the query, SET on a relationship
    variable, and SET on a shared library node (a variable with one of the
    LIBRARY_LABELS or reached over PERFORMED_BY / USES_TOOL / REQUIRES).
    """
    masked = _mask_cypher(cypher)
    kw = _blocked_keyword(masked, ["CREATE", "MERGE", "DELETE", "DETACH", "REMOVE",
                                   "DROP", "FOREACH", "CALL", "LOAD"])
    if kw:
        return f"Blocked: {kw} not allowed in enrichment mode"
    set_bodies = _clauses(masked, "SET")
    if not set_bodies:
        return "No SET clause found — not a valid enrichment query"

    nodes = _node_bindings(masked)
    rels = _relationship_bindings(masked)
    library_vars = {v for v, labels in nodes.items()
                    if any(l.lower() in _LIBRARY_LOWER for l in labels)}
    rel_types = "|".join(REASSIGNABLE_RELATIONSHIPS)
    for m in re.finditer(rf"\[[^\]]*:\s*(?:{rel_types})\b[^\]]*\]\s*->\s*\(\s*([A-Za-z_]\w*)",
                         masked, re.IGNORECASE):
        library_vars.add(m.group(1))
    for m in re.finditer(rf"\(\s*([A-Za-z_]\w*)[^()]*\)\s*<-\s*\[[^\]]*:\s*(?:{rel_types})\b",
                         masked, re.IGNORECASE):
        library_vars.add(m.group(1))

    for body in set_bodies:
        items = _split_top_level(body)
        if not items:
            return "Blocked: empty SET clause"
        for item in items:
            m = re.match(r"^([A-Za-z_]\w*)\s*\.\s*(\w+)\s*=(?!=)", item)
            if m:
                var, keys = m.group(1), [m.group(2)]
            else:
                m = re.match(r"^([A-Za-z_]\w*)\s*\+=\s*(.+)$", item, re.DOTALL)
                if not m:
                    return ("Blocked: only `SET n.key = value` and `SET n += {map}` "
                            "are allowed in enrichment mode")
                var, expr = m.group(1), m.group(2).strip()
                if expr.startswith("{"):
                    keys = _map_keys(_balanced(expr, 0))
                else:
                    ref = re.fullmatch(r"[A-Za-z_]\w*\s*\.\s*(\w+)", expr)
                    literals = [_balanced(masked, lm.end() - 1) for lm in re.finditer(
                        rf"\b{ref.group(1)}\s*:\s*\{{", masked)] if ref else []
                    if not literals:
                        return "Blocked: the properties set by `+=` cannot be read from the query"
                    keys = [k for lit in literals for k in _map_keys(lit)]
            if var in rels and var not in nodes:
                return "Blocked: SET on a relationship is not allowed in enrichment mode"
            if var in library_vars:
                return ("Blocked: cannot SET properties on shared library nodes "
                        "(Agent/Tool/Skill/ConnectionType)")
            if any(k.lower() in _PROTECTED_LOWER for k in keys):
                return "Blocked: cannot modify protected property"
    return None


def check_reassignment_query(cypher):
    """Code check of the reassignment path.

    Accepted: queries that DELETE relationship variables and CREATE
    relationships between already matched nodes, where every deleted and every
    created relationship has one of the REASSIGNABLE_RELATIONSHIPS types.
    Rejected: SET, MERGE, REMOVE, DROP, DETACH, FOREACH, CALL, LOAD, a query
    without DELETE, deletion of anything that is not a relationship variable
    of an allowed type, and any CREATE that introduces a node or a
    relationship of another type.
    """
    masked = _mask_cypher(cypher)
    kw = _blocked_keyword(masked, ["SET", "MERGE", "REMOVE", "DROP", "DETACH",
                                   "FOREACH", "CALL", "LOAD"])
    if kw:
        return f"Blocked: {kw} not allowed in reassignment mode"
    delete_bodies = _clauses(masked, "DELETE")
    if not delete_bodies:
        return "No DELETE clause found — not a valid reassignment query"
    create_bodies = _clauses(masked, "CREATE")

    allowed = set(REASSIGNABLE_RELATIONSHIPS)
    only_msg = "Only PERFORMED_BY, USES_TOOL, and REQUIRES relationships can be reassigned"

    # Variables bound outside the CREATE clauses (MATCH patterns, WITH ... AS).
    outside = masked
    for body in create_bodies:
        outside = outside.replace(body, " ", 1)
    nodes = _node_bindings(outside)
    rels = _relationship_bindings(outside)
    bound = set(nodes) | set(re.findall(r"\bAS\s+([A-Za-z_]\w*)", outside, re.IGNORECASE))

    for body in delete_bodies:
        for item in _split_top_level(body):
            if item not in rels:
                return ("Blocked: DELETE is only allowed on a matched relationship "
                        "(deleting nodes is not allowed in reassignment mode)")
            types = rels[item]
            if not types or any(t not in allowed for t in types):
                return only_msg

    for body in create_bodies:
        rel_patterns = re.findall(r"\[([^\[\]]*)\]", body)
        if not rel_patterns:
            return "Blocked: CREATE of new nodes is not allowed in reassignment mode"
        for rel in rel_patterns:
            m = re.fullmatch(r"\s*(?:[A-Za-z_]\w*)?\s*:\s*(\w+)\s*", rel)
            if not m:
                return "Blocked: CREATE must name exactly one relationship type and no properties"
            if m.group(1) not in allowed:
                return only_msg
        for node in re.findall(r"\(([^()]*)\)", body):
            if not re.fullmatch(r"\s*[A-Za-z_]\w*\s*", node) or node.strip() not in bound:
                return "Blocked: CREATE of new nodes is not allowed in reassignment mode"
    return None


class GraphRAGEngine:
    """Product-scoped GraphRAG engine with SSE streaming."""

    def __init__(self, driver, product_id, product_name, part_names,
                 api_key, model="gpt-5.4-mini", read_only=False):
        self.driver = driver
        self.product_id = product_id
        self.product_name = product_name
        self.part_names = part_names
        self.model = model
        # read_only (demo mode): refuse any enrichment/reassignment so testers
        # can ask questions but never modify the graph through the chat.
        self.read_only = read_only
        OpenAI = _get_openai()
        self.client = OpenAI(api_key=api_key)

        # Build product-scoped schema and examples
        root_asm = "Asm_" + "".join(sorted(part_names.keys()))
        self.schema = build_schema_description(product_id, product_name, part_names)
        self.examples = build_examples(product_id, product_name, part_names, root_asm)

        # Debug log for the current query (populated during ask())
        self.debug_log = []

    def _log(self, stage, detail):
        """Append a debug entry visible in the debug panel."""
        self.debug_log.append({"stage": stage, "detail": detail})

    def _call_responses(self, messages, max_tokens=1000, stream=False, verbosity="low"):
        """Wrapper for OpenAI Responses API (GPT-5.4+).

        Uses client.responses.create() with the new parameter schema:
        - 'input' replaces 'messages'
        - 'reasoning.effort' controls thinking depth
        - 'text.verbosity' controls output conciseness
        - Assistant messages in history require a 'phase' tag
        """
        input_messages = []
        for msg in messages:
            entry = {"role": msg["role"], "content": msg["content"]}
            if msg["role"] == "assistant":
                entry["phase"] = "final_answer"
            input_messages.append(entry)

        kwargs = {
            "model": self.model,
            "input": input_messages,
            "stream": stream,
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": "low"},
            "text": {"verbosity": verbosity},
        }

        return self.client.responses.create(**kwargs)

    # ── Mutation (Enrichment) Pipeline ──────────────────────────────────────────

    _REASSIGNMENT_SIGNALS = [
        "change the agent", "change agent", "reassign the agent", "reassign agent",
        "replace the agent", "replace agent", "switch the agent", "switch agent",
        "change the tool", "replace the tool", "reassign the tool", "switch the tool",
        "assign a different agent", "assign a different tool",
        "change who performs", "change which agent", "change which tool",
    ]

    _MUTATION_SIGNALS = [
        "add the property", "add property", "set the property", "set property",
        "assign", "update the", "change the", "enrich", "annotate",
        "add a cost", "add a weight", "add material", "add toxicity",
        "setze", "füge hinzu", "ändere", "eigenschaft",
    ]

    def _is_reassignment_request(self, question):
        """Detect if the user wants to reassign a resource relationship (PERFORMED_BY/USES_TOOL/REQUIRES)."""
        q_lower = question.lower()
        return any(signal in q_lower for signal in self._REASSIGNMENT_SIGNALS)

    def _is_mutation_request(self, question):
        """Detect if the user wants to enrich/modify the graph."""
        q_lower = question.lower()
        # "assign" counts as a whole word only, so that questions such as
        # "Which agent is assigned to ...?" stay on the read path.
        return any(re.search(r"\bassign\b", q_lower) if signal == "assign" else signal in q_lower
                   for signal in self._MUTATION_SIGNALS)

    def _split_multi_match(self, cypher):
        """Split a multi-MATCH query (no WITH between blocks) into individual SET statements.

        Neo4j requires WITH between SET and the next MATCH. When the LLM generates multiple
        MATCH...SET blocks in sequence, we split them and add a RETURN to each block.
        """
        upper = cypher.upper()
        # Only split if there are multiple MATCH blocks AND SET appears before a second MATCH
        if upper.count("MATCH") <= 1:
            return [cypher]
        # If already has WITH between SET and next MATCH, it's valid — don't split
        if re.search(r'\bSET\b.+\bWITH\b.+\bMATCH\b', upper, re.DOTALL):
            return [cypher]
        # Check the pattern: SET ... MATCH (without WITH) — i.e., needs splitting
        if not re.search(r'\bSET\b.+\bMATCH\b', upper, re.DOTALL):
            return [cypher]

        # Strip the joint RETURN at the end (if any)
        return_match = re.search(r'\n\s*RETURN\b.*$', cypher, re.DOTALL | re.IGNORECASE)
        body = cypher[:return_match.start()].strip() if return_match else cypher.strip()

        # Split on newlines that are immediately followed by MATCH
        raw_blocks = re.split(r'\n(?=\s*MATCH\b)', body, flags=re.IGNORECASE)

        statements = []
        for block in raw_blocks:
            block = block.strip()
            if not block:
                continue
            # Extract the node variable from this block's MATCH clause
            m = re.search(r'\bMATCH\s*\((\w+)', block, re.IGNORECASE)
            var = m.group(1) if m else "n"
            block += f"\nRETURN {var}.id AS id, {var}.name AS name, properties({var}) AS props"
            statements.append(block)

        return statements if len(statements) > 1 else [cypher]

    def _execute_mutation(self, cypher):
        """Execute an enrichment query after check_enrichment_query() accepts it."""
        error = check_enrichment_query(cypher)
        if error:
            return None, error

        # Split multi-MATCH queries that lack WITH connectors
        statements = self._split_multi_match(cypher)

        try:
            with self.driver.session() as session:
                all_records = []
                for stmt in statements:
                    result = session.run(stmt)
                    for record in result:
                        row = {}
                        for key in record.keys():
                            val = record[key]
                            if hasattr(val, "items"):
                                row[key] = dict(val)
                            else:
                                row[key] = val
                        all_records.append(row)
                # Deduplicate by node id — graph-traversal MATCH patterns can return the
                # same node multiple times when multiple paths lead to it in the AOG.
                seen_ids: set = set()
                deduped = []
                for row in all_records:
                    nid = row.get("id")
                    if nid is None or nid not in seen_ids:
                        if nid is not None:
                            seen_ids.add(nid)
                        deduped.append(row)
                return deduped, None
        except Exception as e:
            return None, str(e)

    def _handle_mutation(self, question, history=None):
        """Handle a graph enrichment request. Yields SSE events."""
        # Hard read-only gate: every route into enrichment passes through here
        # (keyword detector, rule-14 USE_ENRICHMENT_MODE handoff, …), so this is
        # the single guarantee that a read-only demo never writes or claims to.
        if self.read_only:
            self._log("read_only", "Refused enrichment in read-only mode")
            yield self._sse("token", READ_ONLY_MSG)
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": None, "rows": 0, "mutation": False}))
            return
        yield self._sse("status", "Detected enrichment request. Generating SET query...")
        self._log("mode", "ENRICHMENT (mutation)")
        self._log("input", f"Question: {question}")

        messages = build_mutation_prompt(self.schema, question, self.product_id, history)
        resp = self._call_responses(messages, max_tokens=2000, verbosity="low")
        text = resp.output_text or ""

        if "CANNOT_ENRICH" in text:
            self._log("mutation", "LLM refused — not an enrichment-safe operation")
            yield self._sse("token", "This request cannot be handled as a property enrichment. "
                            "I can only ADD or UPDATE properties on existing nodes. "
                            "I cannot create, delete, or restructure nodes or relationships.")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": None, "rows": 0, "mutation": False}))
            return

        cypher = self._extract_cypher(text)
        if not cypher:
            self._log("mutation", f"No Cypher extracted from: {text[:200]}")
            yield self._sse("token", "I could not generate a valid enrichment query. Please try rephrasing.")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": None, "rows": 0, "mutation": False}))
            return

        self._log("mutation_cypher", cypher)
        yield self._sse("cypher", cypher)

        yield self._sse("status", "Executing enrichment query...")
        records, error = self._execute_mutation(cypher)

        if error:
            self._log("mutation_error", error)
            yield self._sse("token", f"Enrichment blocked: {error}")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": cypher, "rows": 0, "mutation": False}))
            return

        if not records:
            self._log("mutation", "No matching nodes found")
            yield self._sse("token", "No matching node found for the enrichment. "
                            "Please check the node name or ID and try again.")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": cypher, "rows": 0, "mutation": False}))
            return

        self._log("mutation_result", json.dumps(records[:3], default=str))
        yield self._sse("graph_data", json.dumps(records, default=str))

        confirm_msg = (f"The following enrichment was applied to {len(records)} node(s):\n\n"
                       f"```json\n{json.dumps(records, indent=2, default=str)}\n```")
        yield self._sse("token", confirm_msg)

        yield self._sse("debug", json.dumps(self.debug_log, default=str))
        yield self._sse("done", json.dumps({"cypher": cypher, "rows": len(records), "mutation": True}))

    # ── Reassignment Pipeline ────────────────────────────────────────────────────

    def _execute_reassignment(self, cypher):
        """Execute a reassignment query after check_reassignment_query() accepts it."""
        error = check_reassignment_query(cypher)
        if error:
            return None, error
        try:
            with self.driver.session() as session:
                result = session.run(cypher)
                records = []
                for record in result:
                    row = {}
                    for key in record.keys():
                        val = record[key]
                        row[key] = dict(val) if hasattr(val, "items") else val
                    records.append(row)
                return records, None
        except Exception as e:
            return None, str(e)

    def _handle_reassignment(self, question, history=None):
        """Handle a resource relationship reassignment request. Yields SSE events."""
        # Hard read-only gate (see _handle_mutation): the single guarantee that a
        # read-only demo never reassigns a relationship regardless of how routed.
        if self.read_only:
            self._log("read_only", "Refused reassignment in read-only mode")
            yield self._sse("token", READ_ONLY_MSG)
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": None, "rows": 0, "mutation": False}))
            return
        yield self._sse("status", "Detected relationship reassignment request. Generating query...")
        self._log("mode", "REASSIGNMENT")
        self._log("input", f"Question: {question}")

        messages = build_reassignment_prompt(self.schema, question, self.product_id, history)
        resp = self._call_responses(messages, max_tokens=2000, verbosity="low")
        text = resp.output_text or ""

        if "RESOURCE_NOT_FOUND" in text:
            self._log("reassignment", "LLM could not find target resource")
            yield self._sse("token", "Could not find the specified resource in the library. "
                            "Please check the agent/tool name and try again.")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": None, "rows": 0, "mutation": False}))
            return

        cypher = self._extract_cypher(text)
        if not cypher:
            self._log("reassignment", f"No Cypher extracted from: {text[:200]}")
            yield self._sse("token", "Could not generate a valid reassignment query. Please try rephrasing.")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": None, "rows": 0, "mutation": False}))
            return

        self._log("reassignment_cypher", cypher)
        yield self._sse("cypher", cypher)
        yield self._sse("status", "Executing reassignment...")

        records, error = self._execute_reassignment(cypher)
        if error:
            self._log("reassignment_error", error)
            yield self._sse("token", f"Reassignment blocked: {error}")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": cypher, "rows": 0, "mutation": False}))
            return

        if not records:
            self._log("reassignment", "No matching tasks found")
            yield self._sse("token", "No matching tasks found. Please check the task name and try again.")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": cypher, "rows": 0, "mutation": False}))
            return

        self._log("reassignment_result", json.dumps(records[:3], default=str))
        confirm_msg = (f"Relationship reassigned for {len(records)} task(s):\n\n"
                       f"```json\n{json.dumps(records, indent=2, default=str)}\n```")
        yield self._sse("token", confirm_msg)
        yield self._sse("debug", json.dumps(self.debug_log, default=str))
        yield self._sse("done", json.dumps({"cypher": cypher, "rows": len(records), "mutation": True}))

    # ── Main Ask Pipeline ────────────────────────────────────────────────────────

    def ask(self, question, history=None):
        """Generator that yields SSE events: status, cypher, graph_data, subgraph, token, debug, error, done."""
        self.debug_log = []
        try:
            # Hard-block destructive structural requests before any pipeline runs.
            # Only block destructive GRAPH operations; the word "remove" alone is
            # ambiguous (disassembly uses it semantically, e.g. "which transitions
            # remove the End plate?").
            destructive_signals = [
                "delete", "destroy", "truncate",
                "detach delete",
                "drop the ", "drop all ",
                "remove all ", "remove the node", "remove the component",
                "remove the connection", "remove the transition",
                "lösche", "entferne den knoten", "entferne die",
            ]
            q_lower = question.lower()
            if any(sig in q_lower for sig in destructive_signals):
                yield self._sse("token",
                    "I cannot delete or remove nodes or relationships from the Knowledge Graph. "
                    "The chat interface supports READ queries and property enrichment (SET) only. "
                    "To restructure the graph, please re-upload the product or use Neo4j Browser directly.")
                yield self._sse("debug", json.dumps(self.debug_log, default=str))
                yield self._sse("done", json.dumps({"cypher": None, "rows": 0}))
                return

            # Route reassignment requests before generic mutation (more specific check first)
            # Read-only demo: answer questions, but never enrich/reassign.
            if self.read_only and (self._is_reassignment_request(question)
                                   or self._is_mutation_request(question)):
                yield self._sse("token", READ_ONLY_MSG)
                yield self._sse("debug", json.dumps(self.debug_log, default=str))
                yield self._sse("done", json.dumps({"cypher": None, "rows": 0, "mutation": False}))
                return

            if self._is_reassignment_request(question):
                yield from self._handle_reassignment(question, history)
                return

            # Route mutation requests to the enrichment pipeline
            if self._is_mutation_request(question):
                yield from self._handle_mutation(question, history)
                return

            yield self._sse("status", "Generating Cypher query...")
            self._log("input", f"Question: {question}")
            self._log("model", self.model)
            self._log("product", f"{self.product_name} ({self.product_id})")

            # 1. Generate Cypher
            cypher = self._generate_cypher(question, history)

            # LLM rule-14 handoff: read pipeline detected an enrichment request
            if cypher and "USE_ENRICHMENT_MODE" in cypher.upper():
                self._log("cypher_gen", "Rule-14 handoff → enrichment pipeline")
                yield from self._handle_mutation(question, history)
                return

            if not cypher:
                # Grounded answers only: no Cypher → fixed refusal, no LLM fallback
                self._log("cypher_gen", "FAILED — No valid Cypher generated")
                yield self._sse("status", "Could not generate a valid query.")
                yield self._sse("token", NO_DATA_MSG)
                yield self._sse("debug", json.dumps(self.debug_log, default=str))
                yield self._sse("done", json.dumps({"cypher": None, "rows": 0}))
                return
            self._log("cypher_gen", cypher)
            yield self._sse("cypher", cypher)

            # 2. Execute against Neo4j
            yield self._sse("status", "Executing query against Neo4j...")
            raw_data, error = self._execute_cypher(cypher)

            if error:
                self._log("neo4j_error", error)
                yield self._sse("status", f"Query error: {error}. Attempting auto-correction...")
                cypher = self._retry_cypher(question, cypher, error, history)
                if cypher:
                    self._log("cypher_retry", cypher)
                    yield self._sse("cypher", cypher)
                    raw_data, error = self._execute_cypher(cypher)
                if error or raw_data is None:
                    self._log("neo4j_fatal", error or "No data returned")
                    yield self._sse("error", f"Could not execute query: {error}")
                    yield self._sse("debug", json.dumps(self.debug_log, default=str))
                    return

            self._log("neo4j_rows", f"{len(raw_data)} rows returned")
            self._log("neo4j_sample", json.dumps(raw_data[:3], default=str))
            yield self._sse("graph_data", json.dumps(raw_data, default=str))

            # Grounded answers only: empty Neo4j result → fixed refusal
            if not raw_data or len(raw_data) == 0:
                self._log("answer", "EMPTY result set → hard refusal (grounded answers only)")
                yield self._sse("status", "No data found in Knowledge Graph.")
                yield self._sse("token", NO_DATA_MSG)
                yield self._sse("debug", json.dumps(self.debug_log, default=str))
                yield self._sse("done", json.dumps({"cypher": cypher, "rows": 0}))
                return

            # 2b. Extract subgraph for visualization
            subgraph = self._extract_subgraph(cypher, raw_data)
            if subgraph:
                yield self._sse("subgraph", json.dumps(subgraph, default=str))

            # 3. Format answer (streaming) — LLM only formats, KG data is the single source of truth
            yield self._sse("status", "Formatting answer from KG data...")
            self._log("answer", f"Formatting {len(raw_data)} rows via LLM")
            yield from self._format_answer_stream(question, cypher, raw_data)

            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            yield self._sse("done", json.dumps({"cypher": cypher, "rows": len(raw_data)}))

        except Exception as e:
            self._log("exception", traceback.format_exc())
            yield self._sse("error", f"Pipeline error: {str(e)}")
            yield self._sse("debug", json.dumps(self.debug_log, default=str))
            logger.exception("graphrag ask() crashed")

    def _sse(self, event_type, data):
        return f"data: {json.dumps({'type': event_type, 'data': data})}\n\n"

    def _generate_cypher(self, question, history=None):
        messages = build_cypher_prompt(self.schema, self.examples, question, history)
        response = self._call_responses(messages, max_tokens=2000, verbosity="low")
        text = response.output_text or ""
        self._log("llm_raw_cypher", text[:500] if text else "[EMPTY]")
        if "USE_ENRICHMENT_MODE" in text.upper():
            return "USE_ENRICHMENT_MODE"
        return self._extract_cypher(text)

    def _extract_cypher(self, text):
        match = re.search(r"```(?:cypher)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        stripped = text.strip()
        if stripped.upper().startswith(("MATCH", "OPTIONAL", "WITH", "CALL", "RETURN")):
            return stripped
        return None

    def _execute_cypher(self, cypher):
        # Block write operations
        # Word-boundary match: a bare substring test would block legitimate
        # read queries on this schema — removed_part contains REMOVE, and a
        # created_at property would contain CREATE.
        import re as _re
        upper = cypher.upper()
        for kw in ["CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP", "DETACH"]:
            if _re.search(rf"\b{kw}\b", upper):
                return None, f"Write operation blocked: {kw}"
        try:
            with self.driver.session() as session:
                result = session.run(cypher)
                records = []
                for record in result:
                    row = {}
                    for key in record.keys():
                        val = record[key]
                        if hasattr(val, "items"):
                            row[key] = dict(val)
                        elif isinstance(val, list):
                            row[key] = [str(v) if hasattr(v, "element_id") else v for v in val]
                        elif hasattr(val, "element_id"):
                            row[key] = dict(val)
                        else:
                            row[key] = val
                    records.append(row)
                return records, None
        except Exception as e:
            return None, str(e)

    def _retry_cypher(self, question, original_cypher, error, history=None):
        fix_prompt = (
            f"The following Cypher query failed:\n```cypher\n{original_cypher}\n```\n"
            f"Error: {error}\n\n"
            f"Please generate a corrected query for: {question}"
        )
        messages = build_cypher_prompt(self.schema, self.examples, fix_prompt, history)
        response = self._call_responses(messages, max_tokens=2000, verbosity="low")
        text = response.output_text or ""
        return self._extract_cypher(text)

    def _extract_subgraph(self, cypher, raw_data):
        """Extract actual Neo4j subgraph nodes & edges for visualization."""
        if not raw_data:
            return None
        try:
            # Collect all node IDs mentioned in the results
            node_ids = set()
            for row in raw_data:
                for val in row.values():
                    if isinstance(val, str):
                        for prefix in ["Asm_", "Comp_", "Conn_", "Trans_", "Task_",
                                       "Prod_", "CT_", "Skill_", "Agent_", "Tool_"]:
                            if val.startswith(prefix) or prefix in val:
                                node_ids.add(val)
                    elif isinstance(val, list):
                        for item in val:
                            if isinstance(item, str):
                                for prefix in ["Asm_", "Comp_", "Conn_"]:
                                    if item.startswith(prefix):
                                        node_ids.add(item)

            if not node_ids:
                return None

            # Enrich with Transition nodes that connect the identified Assembly/Component nodes.
            # These don't appear as IDs in raw_data string values (only human-readable names do),
            # but without them the Assembly nodes have no edges and the graph looks disconnected.
            try:
                with self.driver.session() as sess:
                    result = sess.run(
                        "MATCH (from)-[:TRANSFORMS]->(trans:Transition)-[:RESULTS_IN]->(to) "
                        "WHERE (from.id IN $ids OR to.id IN $ids) AND trans.product_id = $pid "
                        "RETURN DISTINCT trans.id AS tid",
                        ids=list(node_ids), pid=self.product_id
                    )
                    for rec in result:
                        if rec["tid"]:
                            node_ids.add(rec["tid"])
            except Exception:
                logger.debug("Subgraph: task-expansion lookup failed", exc_info=True)

            # Query Neo4j for actual graph representation
            with self.driver.session() as session:
                nodes = []
                edges = []

                for rec in session.run(
                    "UNWIND $ids AS nid "
                    "MATCH (n) WHERE n.id = nid AND n.product_id = $pid "
                    "RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props",
                    ids=list(node_ids), pid=self.product_id
                ):
                    nodes.append({
                        "id": rec["eid"],
                        "labels": rec["labels"],
                        "display": rec["props"].get("name", rec["props"].get("id", "")),
                        "properties": dict(rec["props"])
                    })

                node_eids = [n["id"] for n in nodes]
                if node_eids:
                    for rec in session.run(
                        "MATCH (a)-[r]->(b) "
                        "WHERE elementId(a) IN $eids AND elementId(b) IN $eids "
                        "RETURN DISTINCT elementId(a) AS src, elementId(b) AS tgt, type(r) AS rel",
                        eids=node_eids
                    ):
                        if rec["rel"] == "TRANSFORMS":
                            # Flip: render Assembly → Transition so the input assembly
                            # appears above the transition in the dagre top-down layout.
                            edges.append({
                                "source": rec["tgt"],
                                "target": rec["src"],
                                "type": "TRANSFORMS"
                            })
                        else:
                            edges.append({
                                "source": rec["src"],
                                "target": rec["tgt"],
                                "type": rec["rel"]
                            })

                return {"nodes": nodes, "edges": edges} if nodes else None
        except Exception:
            logger.debug("Subgraph extraction failed", exc_info=True)
            return None

    def _format_answer_stream(self, question, cypher, raw_data):
        data_str = json.dumps(raw_data, default=str, indent=2)
        if len(data_str) > 100000:
            data_str = data_str[:100000] + "\n... (truncated)"

        component_list = ", ".join(f"{pid}={name}" for pid, name in sorted((self.part_names or {}).items()))
        messages = build_answer_prompt(question, cypher, data_str, self.product_name, component_list)
        response = self._call_responses(messages, max_tokens=4000, stream=True, verbosity="medium")

        for event in response:
            if event.type == "response.output_text.delta":
                yield self._sse("token", event.delta)
