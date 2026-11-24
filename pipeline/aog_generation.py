"""AND/OR Graph generation via bottom-up BFS (Homem de Mello & Sanderson, 1990).

Bitmask-based implementation: each subassembly is represented as an integer
bitmask (bit i set ↔ part i is present). This gives O(1) disjointness checks
(`(bm1 & bm2) == 0`) and O(1) union (`bm1 | bm2`).

For large candidate-pair counts (>50K), pair validation is parallelized via
ProcessPoolExecutor with `spawn` context (macOS-safe — no OCC in this module).
"""
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

import numpy as np

logger = logging.getLogger(__name__)

_PARALLEL_THRESHOLD = 50_000   # Min. candidate pairs before parallelizing
_CHUNK_SIZE = 20_000           # Pairs per worker chunk

# Hard backstop on AOG size. The pre-flight estimate in semantic.py catches star
# topologies, but dense / clustered / grid graphs also blow up (the number of
# connected subassemblies, not any single hub's fan, drives the cost) and that
# estimate misses them. This in-loop cap aborts cleanly regardless of topology
# before memory/time runs away.
# The defaults let moderately dense assemblies (after reasonable component
# grouping) be enumerated, for example the pump with its two bolt groups.
# Overridable per run via pipeline_settings (aog.max_nodes /
# aog.max_candidate_pairs). Pure star/clustered explosions still trip these.
_MAX_AOG_NODES = 1_000_000
_MAX_CANDIDATE_PAIRS = 50_000_000   # abort a single layer expansion above this


class AOGTooLargeError(RuntimeError):
    """Raised when the AND/OR graph exceeds the tractable size cap."""


# ── Module-level worker functions (must be top-level for pickle) ─────────────

def _compute_separable_standalone(bm_moving, bm_remaining, interference_bitmasks, n):
    """Pure-function separability check for a binary split.

    Returns True if there exists at least one direction d where
    NO part in bm_remaining blocks ANY part in bm_moving.
    """
    for d in range(len(interference_bitmasks)):
        blocked = False
        temp = bm_moving
        while temp:
            lsb = temp & (-temp)
            i = lsb.bit_length() - 1
            temp ^= lsb
            if interference_bitmasks[d][i] & bm_remaining:
                blocked = True
                break
        if not blocked:
            return True
    return False


def _is_connected_standalone(bm_union, liaison_bitmasks, n):
    """Pure-function connectivity check via BFS on bitmask adjacency."""
    first_bit = (bm_union & -bm_union).bit_length() - 1
    visited = 1 << first_bit
    frontier = visited
    while frontier:
        next_frontier = 0
        temp = frontier
        while temp:
            lsb = temp & (-temp)
            i = lsb.bit_length() - 1
            temp ^= lsb
            neighbours = liaison_bitmasks[i] & bm_union & ~visited
            next_frontier |= neighbours
        visited |= next_frontier
        frontier = next_frontier
    return visited == bm_union


def _batch_check_pairs(args):
    """Worker: validate a chunk of (bm1, bm2) candidate pairs.

    Returns list of valid (bm1, bm2, bm_union) tuples.
    """
    pairs, liaison_bitmasks, interference_bitmasks, n = args
    valid = []
    for bm1, bm2 in pairs:
        bm_union = bm1 | bm2
        if not _is_connected_standalone(bm_union, liaison_bitmasks, n):
            continue
        if (_compute_separable_standalone(bm1, bm2, interference_bitmasks, n) or
            _compute_separable_standalone(bm2, bm1, interference_bitmasks, n)):
            valid.append((bm1, bm2, bm_union))
    return valid


# ── AOG class ────────────────────────────────────────────────────────────────

class AOG:
    """Generates the AND/OR Graph representing all valid disassembly sequences
    using a bottom-up BFS approach with bitmask-based subassembly representation.
    """
    def __init__(self, parts, liaison_matrix, interference_matrices, fastener_indices=None,
                 max_nodes=None, max_candidate_pairs=None):
        n = len(parts)
        self.num_layers = n
        self.parts = parts
        # Explosion backstops — overridable per run (None → the module defaults).
        self.max_nodes = int(max_nodes) if max_nodes else _MAX_AOG_NODES
        self.max_candidate_pairs = int(max_candidate_pairs) if max_candidate_pairs else _MAX_CANDIDATE_PAIRS

        # Pre-compute bitmask arrays for O(1) lookups
        lm = np.array(liaison_matrix, dtype=int)
        self.liaison_bitmasks = [
            sum((1 << j) for j in range(n) if lm[i][j]) for i in range(n)
        ]

        ims = [np.array(m, dtype=int) for m in interference_matrices]
        self.interference_bitmasks = [
            [sum((1 << j) for j in range(n) if im[i][j]) for i in range(n)]
            for im in ims
        ]

        # Layer storage: list of sets of bitmasks
        self.valid_subassemblies = [set() for _ in range(n)]
        for i in range(n):
            self.valid_subassemblies[0].add(1 << i)

        # Bitmask → Node lookup
        self.nodes = {}
        for i in range(n):
            node = Node(part_id=i, part_shape=parts[i])
            self.nodes[1 << i] = node

        self._cache = {}
        self._executor = None

    def bottom_up_method(self):
        """Iteratively build the AOG from the bottom up."""
        for node1_layer in range(self.num_layers):
            layer1 = self.valid_subassemblies[node1_layer]
            # Münker & Schmitt 2022, Algorithm 3: every level up to N is built.
            # An empty layer does not end the loop, since a larger layer can
            # still be formed from two smaller ones (e.g. 2 + 2 parts).
            if not layer1:
                continue
            logger.info("Layer %d/%d: %d subassemblies",
                        node1_layer + 1, self.num_layers, len(layer1))

            for node2_layer in range(node1_layer + 1):
                build_layer = (node1_layer + 1) + (node2_layer + 1)
                if build_layer > self.num_layers:
                    break
                self._expand_layer_pair(node1_layer, node2_layer, build_layer - 1)

        self._shutdown_pool()
        self.delete_unreachable_subassemblies()

    def _expand_layer_pair(self, l1_idx, l2_idx, target_idx):
        """Generate and validate all candidate pairs from two layers."""
        layer1 = list(self.valid_subassemblies[l1_idx])
        layer2 = list(self.valid_subassemblies[l2_idx])

        # Abort before materialising an intractable number of candidate pairs
        # (dense/clustered graphs that the pre-flight star estimate misses).
        n_pairs = ((len(layer1) * (len(layer1) - 1)) // 2 if l1_idx == l2_idx
                   else len(layer1) * len(layer2))
        if n_pairs > self.max_candidate_pairs:
            raise AOGTooLargeError(
                f"AND/OR graph expansion would generate {n_pairs:,} candidate pairs "
                f"(> {self.max_candidate_pairs:,}) — the assembly is too densely connected "
                f"to enumerate. Group identical components or split the model."
            )

        # Build candidate pairs
        if l1_idx == l2_idx:
            bm1_arr = []
            bm2_arr = []
            for i in range(len(layer1)):
                for j in range(i + 1, len(layer2)):
                    bm1_arr.append(layer1[i])
                    bm2_arr.append(layer2[j])
        else:
            bm1_arr = []
            bm2_arr = []
            for bm1 in layer1:
                for bm2 in layer2:
                    bm1_arr.append(bm1)
                    bm2_arr.append(bm2)

        if not bm1_arr:
            return

        # Disjoint pre-filter using Python ints. Subassembly bitmasks exceed 64
        # bits for assemblies with >63 parts, so np.int64 would raise
        # OverflowError; Python ints are arbitrary-precision. (The explosion
        # guard in semantic.py stops huge combinatorial cases before this path.)
        pairs = [(b1, b2) for b1, b2 in zip(bm1_arr, bm2_arr) if (b1 & b2) == 0]

        if not pairs:
            return

        # Dispatch: parallel if enough pairs, else sequential
        if len(pairs) >= _PARALLEL_THRESHOLD:
            valid = self._check_pairs_parallel(pairs)
        else:
            valid = self._check_pairs_sequential(pairs)

        # Register valid nodes
        for bm1, bm2, bm_union in valid:
            if bm_union in self.nodes:
                node = self.nodes[bm_union]
            else:
                node = Node(contained_parts=bm_union)
                self.nodes[bm_union] = node
                self.valid_subassemblies[target_idx].add(bm_union)

            node1 = self.nodes[bm1]
            node2 = self.nodes[bm2]
            arc = AND_arc(children=[node1, node2])
            node.AND_arc_list.append(arc)

        if len(self.nodes) > self.max_nodes:
            raise AOGTooLargeError(
                f"AND/OR graph exceeded {self.max_nodes:,} subassembly states — the "
                f"assembly is too densely connected to enumerate fully. Group "
                f"identical components or split the model."
            )

    def _check_pairs_sequential(self, pairs):
        valid = []
        n = self.num_layers
        for bm1, bm2 in pairs:
            bm_union = bm1 | bm2
            if not _is_connected_standalone(bm_union, self.liaison_bitmasks, n):
                continue
            if (self._check_separable(bm1, bm2) or self._check_separable(bm2, bm1)):
                valid.append((bm1, bm2, bm_union))
        return valid

    def _check_pairs_parallel(self, pairs):
        """Dispatch pair validation to ProcessPoolExecutor with spawn context.

        Only called when len(pairs) >= _PARALLEL_THRESHOLD (50K). Pairs are
        split into chunks of _CHUNK_SIZE (20K) and distributed across workers.
        Results are mathematically identical to _check_pairs_sequential() —
        parallelism only affects execution speed, not the set of valid pairs.

        spawn context is required on macOS: fork inherits Cocoa/OpenGL state
        from the parent process and causes SIGSEGV. This module imports no OCC,
        so spawn startup overhead is minimal.
        """
        try:
            if self._executor is None:
                ctx = multiprocessing.get_context("spawn")
                self._executor = ProcessPoolExecutor(
                    max_workers=min(8, (multiprocessing.cpu_count() or 4) - 1),
                    mp_context=ctx,
                )

            chunks = [
                pairs[i:i + _CHUNK_SIZE] for i in range(0, len(pairs), _CHUNK_SIZE)
            ]
            args = [
                (chunk, self.liaison_bitmasks, self.interference_bitmasks, self.num_layers)
                for chunk in chunks
            ]

            logger.info("Parallel: %d pairs in %d chunks (%d workers)",
                        len(pairs), len(chunks), self._executor._max_workers)

            valid = []
            for result in self._executor.map(_batch_check_pairs, args):
                valid.extend(result)
            return valid

        except Exception as e:
            logger.warning("Parallel check failed (%s), falling back to sequential", e)
            return self._check_pairs_sequential(pairs)

    def _shutdown_pool(self):
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    def _check_separable(self, bm_moving, bm_remaining):
        key = (bm_moving, bm_remaining)
        if key not in self._cache:
            self._cache[key] = _compute_separable_standalone(
                bm_moving, bm_remaining,
                self.interference_bitmasks, self.num_layers
            )
        return self._cache[key]

    def delete_unreachable_subassemblies(self):
        """Mark reachable nodes via top-down BFS from root."""
        full_bitmask = (1 << self.num_layers) - 1
        if full_bitmask not in self.nodes:
            return
        root = self.nodes[full_bitmask]
        root.is_reachable = True
        queue = [root]
        while queue:
            current = queue.pop(0)
            for arc in current.AND_arc_list:
                for child in arc.children:
                    if not child.is_reachable:
                        child.is_reachable = True
                        if not child.is_part:
                            queue.append(child)
        # Prune unreachable nodes
        self.nodes = {key: node for key, node in self.nodes.items() if node.is_reachable}


# ── Node class ───────────────────────────────────────────────────────────────

class Node:
    def __init__(self, part_id=None, part_shape=None, contained_parts=None):
        if part_id is not None:
            self.contained_parts = 1 << part_id
            self.is_part = True
        else:
            self.contained_parts = contained_parts
            self.is_part = False

        self.AND_arc_list = []
        self.is_reachable = False

    def __hash__(self):
        return hash(self.contained_parts)

    def __eq__(self, other):
        return self.contained_parts == other.contained_parts


# ── AND_arc class ────────────────────────────────────────────────────────────

class AND_arc:
    def __init__(self, children=None):
        self.children = children or []
