"""Semantic tables module — applies fastener semantics, runs AOG, extracts transitions.

Phase 2 of the STEP-to-KG pipeline.  Receives the raw geometric data (liaison
matrix, one interference matrix per test direction) from Phase 1 and produces the semantic Connection
and Transition entities that populate the knowledge graph.

Processing steps:
  1. Fastener-mediated connections — for each fastener F contacting non-fastener
     parts, create ScrewJoint connections (2-contact: one pair, 3-contact: all 3
     pairs) and suppress direct contacts in the semantic liaison matrix.
  2. Direct connections — remaining non-fastener contacts become PressFit (editable).
  2b. Fastener group merging — optional: merge identical fastener groups into a
      single representative for AOG generation (reduces combinatorial complexity).
  3. AOG generation — bottom-up BFS on the (possibly reduced) liaison +
     interference matrices (Homem de Mello & Sanderson, 1990).
  4. Transition extraction with four-layer semantic pruning + reachability filter:
       a) Phantom-state guard — skip from-states that are semantically disconnected.
       b) Semantic pruning — skip if no defined connection is actually broken.
       c) Precedence guard — topological constraints from assembly geometry.
       d) Disintegration handling — split disconnected result groups into components,
          but only if every split-off component can geometrically leave the rest
          of its side (a loose part trapped inside a closed housing cannot).
     Followed by a forward-reachability BFS from the full assembly to prune
     transitions from states unreachable via valid transition paths.

Key design decisions:
  - Splits are not restricted to single-part removals. Binary splits into two
    subassemblies are needed for a topologically complete AND/OR graph; a
    restriction to single parts would block valid multi-part transitions.
  - The fastener-edge rule (ScrewJoint active only when ALL THREE participants
    are present) prevents phantom states where a loose screw appears to still
    bind two sub-groups that have already separated.
"""
import logging

from pipeline.part_ids import part_id, MAX_PARTS
from pipeline.aog_generation import (_MAX_AOG_NODES, AOGTooLargeError,
                                         _compute_separable_standalone)

logger = logging.getLogger(__name__)
# ── Connected-components helper ───────────────────────────────────────────────

def get_connected_components(part_letters, defined_connections):
    """Return the semantic connected components of a subassembly.

    Edges are drawn only for joints whose ALL participating parts are present:
      - ScrewJoint (fastener_id set): edge only if p1, p2, AND fastener all present.
        A loose screw that lost one of its secured parts is an isolated node.
      - PressFit (fastener_id None): edge if both p1 and p2 present.

    Args:
        part_letters:       set[str] — letters of the parts in this subassembly.
        defined_connections: list[dict] — connections list from generate_semantic_tables.

    Returns:
        list[list[str]] — one list per connected component.
    """
    import networkx as nx

    G = nx.Graph()
    G.add_nodes_from(part_letters)
    for conn in defined_connections:
        p1 = conn["part1"]
        p2 = conn["part2"]
        fst = conn.get("fastener_id")
        if fst is not None:
            # Screw joint is active only when fastener + BOTH secured parts are present.
            if p1 in part_letters and p2 in part_letters and fst in part_letters:
                G.add_edge(p1, fst)
                G.add_edge(p2, fst)
        else:
            if p1 in part_letters and p2 in part_letters:
                G.add_edge(p1, p2)
    return [list(comp) for comp in nx.connected_components(G)]


# ── Broken-connection helper ──────────────────────────────────────────────────

def find_broken_connection(sub1_letters, sub2_letters, defined_connections,
                           canonical=None):
    """Identify the semantic joint that was severed by the (sub1, sub2) split.

    Fastener joints are evaluated as BUNDLES, one per fastener: a screwed joint
    dissolves only by unscrewing, i.e. when the fastener ends up on one side and
    every still-present part it secures ends up together on the other side. A
    fastener that travels with one of its secured parts has not been unscrewed,
    so none of its pairwise connections count as broken. For a two-part fastener
    this is exactly the classic rule (fastener opposite both secured parts). For
    a fastener clamping three or more parts it prevents the one physical
    unscrewing from being attributed to several pairwise connections, and it
    rejects splits in which a threaded fastener would slide out sideways
    together with one of its flanks.

    The dissolved bundle is recorded as ONE connection id: ``canonical[f]`` if
    given (the load-bearing pair, chosen by generate_semantic_tables),
    otherwise the lexicographically first of the fastener's connections.

    Direct joints (PressFit etc.) are broken when their two parts end up on
    opposite sides.

    Returns:
        str — connection ID if found, else None.
    """
    combined = sub1_letters | sub2_letters

    by_fastener = {}
    for conn in defined_connections:
        f = conn.get("fastener_id")
        if f is not None:
            by_fastener.setdefault(f, []).append(conn)

    for f in sorted(by_fastener):
        if f not in combined:
            continue
        conns = by_fastener[f]
        members = {c["part1"] for c in conns} | {c["part2"] for c in conns}
        present = members & combined
        if not present:
            continue
        other = sub2_letters if f in sub1_letters else sub1_letters
        if present <= other:
            if canonical and f in canonical:
                return canonical[f]
            return min(c["id"] for c in conns)

    for conn in defined_connections:
        if conn.get("fastener_id") is not None:
            continue
        part_a = conn["part1"]
        part_b = conn["part2"]
        if {part_a, part_b}.issubset(combined):
            if ((part_a in sub1_letters and part_b in sub2_letters) or
                    (part_a in sub2_letters and part_b in sub1_letters)):
                return conn["id"]
    return None


def tears_fastener_joint(sub1_letters, sub2_letters, defined_connections):
    """True if the split separates parts held by a fastener without removing it.

    Mechanical feasibility after Homem de Mello & Sanderson (1991, p. 235; 1988,
    CMU-RI-TR-88-19, Section 4): contacts held by an attachment cannot be
    detached while its agent is present. For a fastener f this means: if any of
    the parts f clamps is on f's own side, all of its present clamped parts must
    be on that side too. Otherwise one clamped part would be pulled away while
    f still holds the joint (the shaft pulled out of a screwed-on nut).
    """
    combined = sub1_letters | sub2_letters
    members = {}
    for conn in defined_connections:
        f = conn.get("fastener_id")
        if f is not None and f in combined:
            members.setdefault(f, set()).update((conn["part1"], conn["part2"]))
    for f, mem in members.items():
        present = mem & combined
        own = sub1_letters if f in sub1_letters else sub2_letters
        if present & own and present - own:
            return True
    return False


def dissolved_connections(sub1_letters, sub2_letters, defined_connections, canonical=None):
    """Every connection a split dissolves, as ids (one per fastener bundle).

    A step dissolves all connections between its two sides (Homem de Mello &
    Sanderson 1991, p. 234: the contacts of the decomposition): every direct
    joint whose parts end on opposite sides, and every fastener joint whose
    fastener ends up on one side with all of its present clamped parts on the
    other. A fastener bundle is reported once, by its canonical connection.
    Order: fastener bundles first (by fastener letter), then direct joints in
    connection-list order, so the first entry equals find_broken_connection().
    """
    combined = sub1_letters | sub2_letters
    out = []
    by_fastener = {}
    for conn in defined_connections:
        f = conn.get("fastener_id")
        if f is not None:
            by_fastener.setdefault(f, []).append(conn)
    for f in sorted(by_fastener):
        if f not in combined:
            continue
        conns = by_fastener[f]
        present = ({c["part1"] for c in conns} | {c["part2"] for c in conns}) & combined
        if not present:
            continue
        other = sub2_letters if f in sub1_letters else sub1_letters
        if present <= other:
            out.append(canonical[f] if canonical and f in canonical else min(c["id"] for c in conns))
    for conn in defined_connections:
        if conn.get("fastener_id") is not None:
            continue
        a, b = conn["part1"], conn["part2"]
        if (a in sub1_letters and b in sub2_letters) or (a in sub2_letters and b in sub1_letters):
            out.append(conn["id"])
    return out


# ── Trapped-component check ──────────────────────────────────────────────────

def has_trapped_component(components, aog_index, interference_bitmasks):
    """True if the components of one side cannot all be separated geometrically.

    Disintegration splits a side into its semantic components: a part held by a
    fastener alone (the impeller behind its cap nut) becomes its own result once
    the fastener is gone. Semantically loose is not geometrically free, though —
    the impeller still sits between volute casing and cover. Emitting it as a
    separate result would claim it has left the assembly.

    The components are peeled off one at a time: a component may leave if it is
    separable from the union of the remaining ones in at least one direction
    (same test the AOG applies to binary splits). Removing a component only
    removes obstacles, so the greedy order is complete. Components sharing a
    grouped representative (identical fasteners) form one unit.

    Args:
        components:            list of letter collections (one side's components).
        aog_index:             letter → AOG part index (group members → their
                               representative's index).
        interference_bitmasks: AOG.interference_bitmasks ([direction][part] →
                               bitmask of blockers).

    Returns:
        bool — True if at least one component cannot get out.
    """
    units = []
    for comp in components:
        bm = 0
        for letter in comp:
            bm |= 1 << aog_index[letter]
        for u in [u for u in units if u & bm]:
            units.remove(u)
            bm |= u
        units.append(bm)

    n = len(interference_bitmasks[0]) if interference_bitmasks else 0
    while len(units) > 1:
        for u in units:
            rest = 0
            for v in units:
                if v != u:
                    rest |= v
            if (_compute_separable_standalone(u, rest, interference_bitmasks, n) or
                    _compute_separable_standalone(rest, u, interference_bitmasks, n)):
                units.remove(u)
                break
        else:
            return True
    return False


# ── Bitmask / group helpers ──────────────────────────────────────────────────

def _bitmask_to_letters(bitmask, letters):
    """Convert bitmask to sorted letter string."""
    result = []
    temp = bitmask
    idx = 0
    while temp:
        if temp & 1:
            result.append(letters[idx])
        temp >>= 1
        idx += 1
    return "".join(sorted(result))


# ── Fastener grouping cycle ──────────────────────────────────────────────────
# When fastener_groups is provided by the caller, the pipeline reduces the AOG
# input matrices before running the BFS, then expands the results afterward:
#
#   Step 2b: _merge_fastener_groups()
#     OR-merge liaison/interference rows for all group members onto the
#     representative (members[0]).  Delete non-representative rows/cols.
#     Produces: reduced_lm, reduced_ims, reduced_labels, reduced_letters,
#               reduced_fastener_set, group_expansion {rep_letter → [all letters]}
#
#   Step 3: AOG runs on the *reduced* matrices (e.g. 25 parts → 17 after
#     merging 6 identical M20 bolts). The representative stands in for the group.
#
#   Step 4: Transition extraction calls _bitmask_to_letters(node.contained_parts,
#     aog_letters) to convert reduced bitmasks to letters, then _expand_letters()
#     to replace each representative with all member letters.
#
#   Step 4b: _expand_group_transitions() applies expansion to every transition,
#     so the final output always uses original (non-reduced) part letters.
#
#   Reachability filter: full_assembly = "".join(sorted(letters)) always uses
#     the original letter set (not reduced), because transitions are already
#     expanded at this point.
def _merge_fastener_groups(liaison_matrix, interference_matrices, part_labels,
                           fastener_groups, letters, fastener_set):
    """Merge fastener groups: OR-merge liaison/interference rows onto representative,
    delete remaining member rows/cols.

    Returns:
        (reduced_lm, reduced_ims, reduced_labels, reduced_letters,
         reduced_fastener_set, group_expansion)
    """
    import numpy as np

    n = len(part_labels)
    lm = liaison_matrix.copy() if hasattr(liaison_matrix, 'copy') else np.array(liaison_matrix, dtype=float)
    ims = [m.copy() for m in interference_matrices]

    indices_to_delete = set()
    group_expansion = {}  # rep_letter → [all member letters]

    for fg in fastener_groups:
        members = sorted(fg["members"])
        if len(members) < 2:
            continue
        rep = members[0]
        rest = members[1:]
        group_expansion[letters[rep]] = [letters[m] for m in members]

        # OR-merge rows/cols onto representative
        for m in rest:
            for x in range(n):
                if lm[m, x] == 1:
                    lm[rep, x] = 1
                    lm[x, rep] = 1
            # Interference is directional: row = blocked by, column = blocks.
            for im in ims:
                for x in range(n):
                    if im[m, x] == 1:
                        im[rep, x] = 1
                    if im[x, m] == 1:
                        im[x, rep] = 1
            indices_to_delete.add(m)

    # Delete rows/cols (descending to keep indices stable)
    for idx in sorted(indices_to_delete, reverse=True):
        lm = np.delete(lm, idx, axis=0)
        lm = np.delete(lm, idx, axis=1)
        for i in range(len(ims)):
            ims[i] = np.delete(ims[i], idx, axis=0)
            ims[i] = np.delete(ims[i], idx, axis=1)

    surviving = sorted(set(range(n)) - indices_to_delete)
    old_to_new = {old: new for new, old in enumerate(surviving)}

    reduced_labels = [part_labels[i] for i in surviving]
    reduced_letters = [letters[i] for i in surviving]
    reduced_fastener_set = {old_to_new[i] for i in fastener_set if i in old_to_new}

    return lm, ims, reduced_labels, reduced_letters, reduced_fastener_set, group_expansion


def _expand_group_transitions(transitions, group_expansion):
    """Replace group representative letters with all member letters in-place."""
    for t in transitions:
        t["from_parts"] = _expand_letters(t["from_parts"], group_expansion)
        t["results_in"] = [_expand_letters(r, group_expansion) for r in t["results_in"]]


def _expand_letters(letter_str, group_expansion):
    """Replace representative letters with all group member letters."""
    result = set(letter_str)
    for rep_letter, member_letters in group_expansion.items():
        if rep_letter in result:
            result.discard(rep_letter)
            result.update(member_letters)
    return "".join(sorted(result))


# ── AOG complexity guard ────────────────────────────────────────────────────
# A star/hub topology (many parts touching one shared base, none blocking each
# other) makes the AND/OR graph grow as 2^k in the number of independent parts —
# a 100-part PCB would need 2^100 states. We estimate this cheaply from the
# liaison matrix and refuse before building, rather than hang or run out of memory.
_AOG_TRANSITION_CAP = 5_000_000   # refuse above this estimated transition count
_AOG_PART_CAP = 80                # refuse above this part count (post-grouping)


def estimate_aog_complexity(liaison_matrix):
    """Rough upper bound on AOG size from the largest 'independent fan'.

    A hub part with k mutually-non-adjacent neighbours (a star) yields ~2^k
    subassembly states and ~k·2^(k-1) transitions — the dominant exponential
    term. The independent set is found greedily (a lower bound on the true max,
    so this under- rather than over-estimates). Returns (k, est_nodes, est_trans).
    """
    import numpy as np
    lm = np.array(liaison_matrix)
    n = lm.shape[0] if lm.ndim == 2 else 0
    best_k = 0
    for hub in range(n):
        nbrs = [j for j in range(n) if j != hub and lm[hub][j]]
        indep = []  # greedy maximal independent set among the hub's neighbours
        for j in nbrs:
            if all(not lm[j][m] for m in indep):
                indep.append(j)
        best_k = max(best_k, len(indep))
    est_nodes = 1 << best_k
    est_trans = best_k * (1 << (best_k - 1)) if best_k > 0 else 0
    return best_k, est_nodes, est_trans


# ── Main function ─────────────────────────────────────────────────────────────

def generate_semantic_tables(fastener_indices, part_labels, liaison_matrix,
                             interference_matrices, precedence_rules=None,
                             fastener_groups=None, separation_precedence=None,
                             settings=None, estimate_only=False):
    """Apply fastener semantics, run AOG, and extract transitions.

    Args:
        fastener_indices:      list[int] — 0-based indices of fastener parts.
        part_labels:           list[str] — e.g. ["Tube (A)", "Screw (B)", ...].
        liaison_matrix:        list[list[int]] — geometric contact matrix (N×N).
        interference_matrices: list[list[list[int]]] — one N×N interference
                               matrix per test direction.
        precedence_rules:      dict[str, list[str]] | None — topological constraints.
        fastener_groups:       list[dict] | None — groups of identical fasteners
                               to merge for AOG generation.
        separation_precedence: list[dict] | None — connection-level constraints.
                               Each dict: {"part1": str, "part2": str,
                               "requires_removed": [str, ...]}
                               Meaning: part1 and part2 cannot be separated while
                               any of requires_removed is still present.
        estimate_only:         return right after the pre-flight complexity
                               estimate (aog_estimate) without building the AOG —
                               used by the size estimate of the Studio.
                               transitions stays empty.

    Returns:
        dict with keys:
          success, connections, semantic_liaison_matrix, transitions,
          aog_estimate, rule_stats, log, error
    """
    result = {
        "success": False,
        "connections": [],
        "semantic_liaison_matrix": [],
        "transitions": [],
        "log": [],
        "error": None,
    }

    def log(msg):
        result["log"].append(msg)
        logger.info(msg)

    try:
        import numpy as np
        from pipeline.aog_builder import build_aog

        n = len(part_labels)
        if n > MAX_PARTS:
            result["error"] = (
                f"This product has {n} parts; the pipeline supports at most "
                f"{MAX_PARTS}. Group identical components or split the model."
            )
            log(result["error"])
            return result
        letters = [part_id(i) for i in range(n)]
        fastener_set = set(int(f) for f in fastener_indices)

        lm = np.array(liaison_matrix, dtype=float)
        semantic_lm = lm.copy()
        connections = []

        # ── Step 1: Fastener-mediated connections ─────────────────────────────
        log("Applying fastener semantics...")
        for f_idx in sorted(fastener_set):
            neighbours = [
                j for j in range(n)
                if lm[f_idx, j] == 1 and j not in fastener_set
            ]
            label_f = part_labels[f_idx].split(" (")[0]

            if len(neighbours) == 2:
                a_idx, b_idx = neighbours[0], neighbours[1]
                label_a = part_labels[a_idx].split(" (")[0]
                label_b = part_labels[b_idx].split(" (")[0]

                conn_id = f"Conn_{letters[a_idx]}{letters[b_idx]}_{letters[f_idx]}"
                connections.append({
                    "id": conn_id,
                    "part1": letters[a_idx],
                    "part2": letters[b_idx],
                    "connectionType_id": "CT_ScrewJoint",
                    "agent_id": "Agent_HumanWorker",
                    "tool_id": "Tool_None",
                    "fastener_id": letters[f_idx],
                })
                log(f"  {label_f} → Connection({label_a} ↔ {label_b}, ScrewJoint, "
                    f"fastener={letters[f_idx]})")

                # Suppress direct A↔B clamping-surface contact in semantic_lm
                # to prevent spurious PressFit from being generated.
                if semantic_lm[a_idx][b_idx] == 1:
                    semantic_lm[a_idx][b_idx] = 0
                    semantic_lm[b_idx][a_idx] = 0
                    log(f"  Suppressed direct contact {letters[a_idx]}↔{letters[b_idx]}")

            elif len(neighbours) == 1:
                nb_idx = neighbours[0]
                nb_label = part_labels[nb_idx].split(" (")[0]
                conn_id = f"Conn_{letters[f_idx]}{letters[nb_idx]}"
                connections.append({
                    "id": conn_id,
                    "part1": letters[f_idx],
                    "part2": letters[nb_idx],
                    "connectionType_id": "CT_PressFit",
                    "agent_id": "Agent_HumanWorker",
                    "tool_id": "Tool_None",
                    "fastener_id": None,
                })
                log(f"  {label_f} ({letters[f_idx]}) contacts 1 non-fastener → "
                    f"PressFit to {nb_label} ({letters[nb_idx]})")

            elif len(neighbours) == 3:
                a_idx, b_idx, c_idx = neighbours[0], neighbours[1], neighbours[2]
                label_a = part_labels[a_idx].split(" (")[0]
                label_b = part_labels[b_idx].split(" (")[0]
                label_c = part_labels[c_idx].split(" (")[0]

                # 3-contact fastener: create ALL 3 pair-connections
                for (i1, i2, l1, l2) in [
                    (a_idx, b_idx, label_a, label_b),
                    (a_idx, c_idx, label_a, label_c),
                    (b_idx, c_idx, label_b, label_c),
                ]:
                    conn_id = f"Conn_{letters[i1]}{letters[i2]}_{letters[f_idx]}"
                    connections.append({
                        "id": conn_id,
                        "part1": letters[i1],
                        "part2": letters[i2],
                        "connectionType_id": "CT_ScrewJoint",
                        "agent_id": "Agent_HumanWorker",
                        "tool_id": "Tool_None",
                        "fastener_id": letters[f_idx],
                    })
                    log(f"  {label_f} → Connection({l1} ↔ {l2}, ScrewJoint, "
                        f"fastener={letters[f_idx]})")

                    # Suppress direct contact to avoid duplicate PressFit
                    if semantic_lm[i1][i2] == 1:
                        semantic_lm[i1][i2] = 0
                        semantic_lm[i2][i1] = 0
                        log(f"  Suppressed direct contact {letters[i1]}↔{letters[i2]}")

            elif len(neighbours) >= 4:
                # A fastener clamping four or more parts has no pairwise
                # decomposition the bundle rule can attribute, and silently
                # skipping it would emit NO connection at all — the clamped
                # parts would look unconnected and the AOG would happily pull
                # them apart. Refuse the model instead of losing the joint.
                nb_names = ", ".join(part_labels[j].split(" (")[0]
                                     for j in neighbours)
                result["error"] = (
                    f"Fastener '{label_f}' ({letters[f_idx]}) contacts "
                    f"{len(neighbours)} non-fastener parts ({nb_names}). The "
                    f"pipeline models fastener joints for up to 3 clamped "
                    f"parts. Split the joint, group identical parts, or model "
                    f"this connection manually."
                )
                log(result["error"])
                return result

            else:
                log(f"  WARNING: {label_f} contacts {len(neighbours)} non-fastener parts"
                    " — skipping")

        # ── Step 2: Direct non-fastener connections ───────────────────────────
        log("Generating direct (PressFit) connections...")
        seen_pairs = set()
        for i in range(n):
            for j in range(i + 1, n):
                if i in fastener_set or j in fastener_set:
                    continue
                if semantic_lm[i][j] == 1:
                    pair = (i, j)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        conn_id = f"Conn_{letters[i]}{letters[j]}"
                        connections.append({
                            "id": conn_id,
                            "part1": letters[i],
                            "part2": letters[j],
                            "connectionType_id": "CT_PressFit",  # user edits afterwards
                            "agent_id": "Agent_HumanWorker",
                            "tool_id": "Tool_None",
                            "fastener_id": None,
                        })
                        log(f"  Direct contact: {letters[i]}↔{letters[j]}")

        result["connections"] = connections
        result["semantic_liaison_matrix"] = semantic_lm.tolist()
        log(f"Generated {len(connections)} connections "
            f"({len(fastener_set)} fastener joints + {len(seen_pairs)} direct)")

        # ── Canonical connection per fastener ────────────────────────────────
        # A fastener clamping 3+ parts owns several pairwise connections, but a
        # dissolved bundle is recorded against exactly one of them: the pair of
        # LOAD-BEARING parts, identified as the two members with the most
        # geometric contacts outside the joint family (the clamped intermediate
        # — e.g. a gasket — touches nothing but the joint). Ties break on the
        # lexicographically smallest connection id, so the choice is stable.
        canonical_conn = {}
        _idx = {ch: i for i, ch in enumerate(letters)}
        _by_f = {}
        for c in connections:
            if c.get("fastener_id") is not None:
                _by_f.setdefault(c["fastener_id"], []).append(c)
        for f, conns in _by_f.items():
            if len(conns) == 1:
                canonical_conn[f] = conns[0]["id"]
                continue
            members = {c["part1"] for c in conns} | {c["part2"] for c in conns}
            family = members | {f}
            def _externals(p):
                pi = _idx[p]
                return sum(1 for q, qi in _idx.items()
                           if q not in family and lm[pi][qi])
            best = max(conns, key=lambda c: (_externals(c["part1"])
                                             + _externals(c["part2"]),
                                             [-ord(ch) for ch in c["id"]]))
            canonical_conn[f] = best["id"]
            log(f"  Canonical joint for fastener {f}: {best['id']} "
                f"(load-bearing pair of {len(conns)} pairwise connections)")

        # ── Connection bundles ───────────────────────────────────────────────
        # A transition records ONE canonical connection, but a single unscrewing
        # dissolves every connection of the bundle: all pairwise connections of
        # the fastener (three when it clamps three parts) and, when identical
        # fasteners are grouped, those of every group member as well. This map
        # lets the knowledge graph link the transition to every connection of
        # the bundle, so that each of them has a transition and a task.
        # Keyed by the canonical connection of the group REPRESENTATIVE, because
        # that is the id the transitions carry: generation runs on the reduced
        # part set where the representative stands in for the whole group.
        group_of, group_rep = {}, {}
        for fg in (fastener_groups or []):
            members = sorted(fg["members"])
            fam = [letters[m] for m in members]
            rep = letters[members[0]]
            for m in fam:
                group_of[m] = fam
                group_rep[m] = rep
        connection_bundles = {}
        for f in _by_f:
            rep = group_rep.get(f, f)
            if rep not in canonical_conn:
                continue
            fam = group_of.get(rep, [rep])
            connection_bundles[canonical_conn[rep]] = sorted(
                {c["id"] for m in fam for c in _by_f.get(m, [])})
        # Direct joints. A joint of a GROUPED part dissolves with the group, not
        # on its own: the two gland halves move as one unit, so Conn_MT mirrors
        # Conn_BT and neither can be broken separately. Rewriting both endpoints
        # to their group representative collapses the mirrors onto one bundle;
        # ungrouped joints rewrite to themselves and stay bundles of one.
        rep_of = {}
        for fg in (fastener_groups or []):
            members = sorted(fg["members"])
            for m in members:
                rep_of[letters[m]] = letters[members[0]]
        direct = {}
        internal = []
        for c in connections:
            if c.get("fastener_id") is not None:
                continue
            a = rep_of.get(c["part1"], c["part1"])
            b = rep_of.get(c["part2"], c["part2"])
            if a == b:
                # Both endpoints are in the same group. The joint is interior to
                # a unit that is never split, so no operation ever dissolves it.
                internal.append(c["id"])
                continue
            direct.setdefault(tuple(sorted((a, b))), []).append(c["id"])
        for pair, ids in direct.items():
            # Prefer the joint between the representatives themselves as the key,
            # since that is the id a transition records.
            canon = next((i for i in ids
                          if {c["part1"] for c in connections if c["id"] == i} |
                             {c["part2"] for c in connections if c["id"] == i} == set(pair)),
                         sorted(ids)[0])
            connection_bundles[canon] = sorted(ids)
        if internal:
            log(f"  {len(internal)} joint(s) interior to a grouped unit have no "
                f"dissolving operation by construction: {sorted(internal)}")
        result["connection_bundles"] = connection_bundles
        # member connection -> its bundle key, so every dissolved connection is
        # recorded once, under the id the knowledge graph keys its task by
        bundle_of = {m: key for key, members in connection_bundles.items() for m in members}
        log(f"Connection bundles: {len(connection_bundles)} canonical joint(s) "
            f"covering {len(set().union(*connection_bundles.values())) if connection_bundles else 0} "
            f"connection(s)")

        # ── Step 2b: Merge fastener groups for AOG ───────────────────────────
        im_list = [np.array(m, dtype=float) for m in interference_matrices]
        group_expansion = {}
        if fastener_groups:
            log(f"Merging {len(fastener_groups)} fastener groups...")
            for fg in fastener_groups:
                member_letters = [letters[m] for m in fg["members"]]
                log(f"  {fg['name']}: {','.join(member_letters)} → {member_letters[0]}")

            (aog_lm, aog_ims, aog_labels, aog_letters,
             reduced_fastener_set, group_expansion) = _merge_fastener_groups(
                lm, im_list, part_labels, fastener_groups, letters, fastener_set
            )
            aog_n = len(aog_labels)
            log(f"Reduced: {n} parts → {aog_n} parts")
        else:
            aog_lm = lm
            aog_ims = im_list
            aog_labels = part_labels
            aog_letters = letters
            aog_n = n
            reduced_fastener_set = fastener_set

        # ── Step 3: AOG on (possibly reduced) matrices ───────────────────────
        log("Running AOG on geometric liaison matrix...")

        class _DummyPart:
            def __init__(self, idx):
                self.name = aog_labels[idx]
                self.id = idx

        dummy_parts = [_DummyPart(i) for i in range(aog_n)]

        # ── Explosion guard: estimate AOG size before building ───────────────
        fan_k, est_nodes, est_trans = estimate_aog_complexity(aog_lm)
        from pipeline.settings import resolve_settings, get
        _s = resolve_settings(settings)  # validate: bad values degrade to default
        max_trans = int(get(_s, "aog.max_transitions", _AOG_TRANSITION_CAP))
        max_parts_cap = int(get(_s, "aog.max_parts", _AOG_PART_CAP))
        result["aog_estimate"] = {
            "independent_fan": fan_k,
            "est_assemblies": est_nodes,
            "est_transitions": est_trans,
            "parts_after_grouping": aog_n,
            # resolved caps, so the UI gauge scales against what THIS run enforces
            "cap_transitions": max_trans,
            "cap_parts": max_parts_cap,
            # the in-loop backstop of the enumeration; the star estimate above
            # does not see dense, clustered assemblies that hit this one
            "cap_nodes": int(get(_s, "aog.max_nodes", None) or _MAX_AOG_NODES),
        }
        log(f"AOG estimate: ~{est_nodes:,} states, ~{est_trans:,} transitions "
            f"(largest independent fan: {fan_k} parts, {aog_n} parts after grouping)")
        if est_trans > max_trans or aog_n > max_parts_cap:
            result["error"] = (
                f"Assembly too large to enumerate fully: the AND/OR graph would have "
                f"~{est_nodes:,} states and ~{est_trans:,} transitions. The cause is "
                f"{fan_k} parts that each only attach to a shared base (a star "
                f"topology — every removal order is valid, so the graph grows as 2^k). "
                f"Group identical components (e.g. via the contact-pattern grouping) "
                f"or split the model, then retry. Parts after grouping: {aog_n}."
            )
            log(result["error"])
            return result

        if estimate_only:
            log("Estimate-only: stopping before AOG build")
            result["success"] = True
            return result

        tree = build_aog(
            parts=dummy_parts,
            liaison_matrix=aog_lm,
            interference_matrices=aog_ims,
            fastener_indices=list(reduced_fastener_set) if reduced_fastener_set else None,
            max_nodes=get(_s, "aog.max_nodes", None),
            max_candidate_pairs=get(_s, "aog.max_candidate_pairs", None),
        )
        log(f"AOG: {len(tree.nodes)} reachable nodes")

        # Letter → AOG part index for the trapped-component check; members of a
        # merged fastener group map to their representative.
        aog_index = {letter: k for k, letter in enumerate(aog_letters)}
        for rep_letter, member_letters in group_expansion.items():
            for m in member_letters:
                aog_index[m] = aog_index[rep_letter]

        # ── Step 4: Extract transitions with semantic pruning ─────────────────
        log("Extracting transitions...")
        transitions = []
        seen_steps = set()

        # Per-guard pruning counters — read-only bookkeeping for the UI's rules
        # panel ("this rule removed N transitions"); they cannot alter which
        # transitions are emitted.
        rule_stats = {
            "phantom_states": 0,
            "torn_fastener_joints": 0,
            "no_broken_connection": 0,
            "precedence": 0,
            "separation_precedence": 0,
            "duplicates": 0,
            "disintegration_splits": 0,
            "trapped_components": 0,
            "reachability": 0,
        }

        # PRECEDENCE RULES — topological constraints derived from assembly geometry.
        # Format: {moving_part_letter: [blocker_letter, ...]}
        # A part cannot be separated from the assembly while its listed blockers are
        # still present in the remaining subassembly.
        _rules: dict[str, list[str]] = precedence_rules or {}
        _sep_rules: list[dict] = separation_precedence or []

        def _violates_precedence(sub1: set, sub2: set) -> bool:
            """Check if a binary split violates precedence rules.

            Rule "X": ["Y"] means X and Y must end up on the same side,
            UNLESS Y is alone (removed as a single part). This models the
            physical reality that X cannot be pulled away while Y is installed,
            but Y itself CAN be removed individually.
            """
            for part, blockers in _rules.items():
                for blocker in blockers:
                    # part and blocker on different sides?
                    if part in sub1 and blocker in sub2:
                        # blocker is alone → it's being removed → OK
                        if len(sub2) > 1:
                            return True
                    if part in sub2 and blocker in sub1:
                        if len(sub1) > 1:
                            return True
            return False

        def _violates_separation_precedence(sub1: set, sub2: set) -> bool:
            """Check if a binary split violates separation precedence rules.

            Rule {"part1": "H", "part2": "A", "requires_removed": ["B"]}
            means: H and A cannot end up on opposite sides while B is still
            present in the assembly. B must be removed first.

            Example: EndPlate must be removed before Shaft can separate
            from Holder — because the EndPlate blocks the extraction path.
            """
            for rule in _sep_rules:
                p1 = rule["part1"]
                p2 = rule["part2"]
                req = rule["requires_removed"]
                # Are p1 and p2 being separated?
                if (p1 in sub1 and p2 in sub2) or (p1 in sub2 and p2 in sub1):
                    # Check if any required part is still present
                    all_present = sub1 | sub2
                    if any(r in all_present for r in req):
                        return True
            return False

        def _violates_after_split(groups, present):
            """Re-apply BOTH rule kinds to the groups a transition actually
            produces, rather than to the two sides it was derived from.

            The binary checks above see only the first cut. A side may then fall
            apart and put the constrained parts into different results anyway.
            On the pump this is not a corner case: unscrewing the cap nut splits
            {nut} | {rest}, both checks pass because the impeller and its
            blockers are all still in {rest}, and the remainder then
            disintegrates — the impeller was held by that nut alone.

            Returns the rule_stats key that rejected the split, or None.
            """
            for rule in _sep_rules:
                p1, p2 = rule["part1"], rule["part2"]
                if not any(r in present for r in rule["requires_removed"]):
                    continue
                g1 = next((g for g in groups if p1 in g), None)
                g2 = next((g for g in groups if p2 in g), None)
                if g1 is not None and g2 is not None and g1 != g2:
                    return "separation_precedence"

            for part, blockers in _rules.items():
                gp = next((g for g in groups if part in g), None)
                if gp is None:
                    continue
                for blocker in blockers:
                    gb = next((g for g in groups if blocker in g), None)
                    if gb is None or gb == gp:
                        continue
                    # The blocker leaving on its own is the legitimate move —
                    # that IS removing it first. Anything else means the part
                    # got out past a blocker that is still mounted.
                    if len(gb) > 1:
                        return "precedence"
            return None

        for node in tree.nodes.values():
            if not node.is_reachable or node.is_part:
                continue
            if not hasattr(node, 'AND_arc_list'):
                continue

            from_str = _bitmask_to_letters(node.contained_parts, aog_letters)
            from_parts_set = set(from_str)

            # Expand for semantic checks when groups are active
            expanded_from = set(_expand_letters(from_str, group_expansion)) if group_expansion else from_parts_set

            # PHANTOM-STATE GUARD: skip states that are not semantically connected.
            from_components = get_connected_components(expanded_from, connections)
            if len(from_components) > 1:
                rule_stats["phantom_states"] += 1
                continue

            for and_arc in node.AND_arc_list:
                if len(and_arc.children) != 2:
                    continue

                c1, c2 = and_arc.children[0], and_arc.children[1]
                sub1_str = _bitmask_to_letters(c1.contained_parts, aog_letters)
                sub2_str = _bitmask_to_letters(c2.contained_parts, aog_letters)
                sub1_letters = set(sub1_str)
                sub2_letters = set(sub2_str)

                # Expand for semantic checks
                expanded_sub1 = set(_expand_letters(sub1_str, group_expansion)) if group_expansion else sub1_letters
                expanded_sub2 = set(_expand_letters(sub2_str, group_expansion)) if group_expansion else sub2_letters

                # MECHANICAL FEASIBILITY: a fastener joint is dissolved only by
                # removing the fastener (tears_fastener_joint). Checked on its
                # own, because the "no joint broken" check below passes as soon
                # as any second joint is broken in the same split.
                if tears_fastener_joint(expanded_sub1, expanded_sub2, connections):
                    rule_stats["torn_fastener_joints"] += 1
                    continue

                # SEMANTIC PRUNING: skip if no defined joint is actually broken.
                dissolved = list(dict.fromkeys(
                    bundle_of.get(c, c) for c in dissolved_connections(
                        expanded_sub1, expanded_sub2, connections, canonical_conn)))
                broken_conn = dissolved[0] if dissolved else None
                if broken_conn is None:
                    rule_stats["no_broken_connection"] += 1
                    continue

                # PRECEDENCE GUARD: skip transitions that violate topological ordering.
                if _violates_precedence(expanded_sub1, expanded_sub2):
                    rule_stats["precedence"] += 1
                    continue

                # SEPARATION PRECEDENCE: skip if required parts not yet removed.
                if _violates_separation_precedence(expanded_sub1, expanded_sub2):
                    rule_stats["separation_precedence"] += 1
                    continue

                # DISINTEGRATION HANDLING: each resulting subassembly may split
                # into multiple disconnected components after the transition.
                comp1 = get_connected_components(expanded_sub1, connections)
                comp2 = get_connected_components(expanded_sub2, connections)
                results_in_list = [
                    "".join(sorted(comp))
                    for comp in comp1 + comp2
                ]
                if len(results_in_list) > 2:
                    # Every component split off by disintegration must be able
                    # to leave geometrically (see has_trapped_component).
                    if ((len(comp1) > 1 and has_trapped_component(
                            comp1, aog_index, tree.interference_bitmasks)) or
                            (len(comp2) > 1 and has_trapped_component(
                                comp2, aog_index, tree.interference_bitmasks))):
                        rule_stats["trapped_components"] += 1
                        continue
                    rule_stats["disintegration_splits"] += len(results_in_list) - 2

                # Re-check both rule kinds against the groups actually produced
                # (see _violates_after_split for why the binary check is not
                # sufficient).
                _rejected_by = _violates_after_split(results_in_list, expanded_from)
                if _rejected_by:
                    rule_stats[_rejected_by] += 1
                    continue

                # Use expanded from_str for transition recording
                expanded_from_str = "".join(sorted(expanded_from))

                tr_dict = {
                    "id": None,  # assigned after all filtering
                    "from_parts": expanded_from_str,
                    "results_in": results_in_list,
                    "broken_connection_id": broken_conn,
                    # every connection the step dissolves (bundles by canonical id)
                    "broken_connection_ids": dissolved,
                }

                # Convenience field for single-part removals (read by clients that expect removed_part)
                if len(expanded_sub1) == 1:
                    tr_dict["removed_part"] = "".join(sorted(expanded_sub1))
                elif len(expanded_sub2) == 1:
                    tr_dict["removed_part"] = "".join(sorted(expanded_sub2))

                # Deduplicate: the same step means the same from-state AND the
                # same results. The recorded connection is not part of the key:
                # different removals can break the same first joint.
                _key = (tr_dict["from_parts"], tuple(sorted(tr_dict["results_in"])))
                dup = _key in seen_steps
                seen_steps.add(_key)
                if dup:
                    rule_stats["duplicates"] += 1
                else:
                    transitions.append(tr_dict)

        # REACHABILITY FILTER: prune transitions from states that cannot be
        # reached from the complete assembly via valid transition paths.
        full_assembly = "".join(sorted(letters))  # always original letters
        reachable_states = {full_assembly}
        changed = True
        while changed:
            changed = False
            for t in transitions:
                if t["from_parts"] in reachable_states:
                    for r in t["results_in"]:
                        if len(r) > 1 and r not in reachable_states:
                            reachable_states.add(r)
                            changed = True

        before_count = len(transitions)
        transitions = [t for t in transitions if t["from_parts"] in reachable_states]
        pruned = before_count - len(transitions)
        rule_stats["reachability"] = pruned
        if pruned:
            log(f"Reachability filter pruned {pruned} transitions from unreachable states")

        # Assign sequential IDs after all filtering
        for i, t in enumerate(transitions, start=1):
            t["id"] = f"T{i:02d}"

        result["transitions"] = transitions
        result["rule_stats"] = rule_stats
        log(f"Extracted {len(transitions)} transitions")
        result["success"] = True

    except AOGTooLargeError as e:
        # Topology-independent backstop tripped inside the AOG build (the cheap
        # pre-flight estimate missed a dense/clustered blowup). Surface the clean
        # guidance message, not a generic error.
        result["error"] = str(e)
        log(result["error"])
    except Exception as e:
        import traceback
        result["error"] = f"Semantic tables error: {str(e)}"
        result["log"].append(f"ERROR: {traceback.format_exc()}")
        logger.exception("generate_semantic_tables failed")

    return result
