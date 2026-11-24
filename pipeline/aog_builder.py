"""AOG builder module — wrapper around the bitmask-based AOG class.

Provides a clean interface for running the AND/OR Graph generation algorithm.
Uses direct bottom-up BFS for all assembly sizes, without partitioning.
"""
import numpy as np


def build_aog(parts, liaison_matrix, interference_matrices, fastener_indices=None,
              max_nodes=None, max_candidate_pairs=None):
    """Build and return a fully computed AND/OR Graph.

    Runs the bitmask-based bottom-up BFS algorithm (Homem de Mello & Sanderson
    1990) with optional parallelization for large candidate pair counts.

    The four DSP rules are enforced by:
      - Rule A (fastener atomicity): enforced in semantic.py transition extraction
      - Rule B (connected components): enforced in semantic.py transition extraction
      - Rule C (subassembly splitting): enforced in semantic.py transition extraction
      - Rule D (interference guard): enforced here via separability checks
        using the interference_matrices produced by pipeline/interference.py

    Args:
        parts:                List of Part objects (or _DummyPart with .name/.id).
        liaison_matrix:       N×N numpy array or list-of-lists (geometric contact).
        interference_matrices: List of N×N arrays, one per test direction.
        fastener_indices:     Optional list[int] of fastener part indices.

    Returns:
        AOG tree object with .nodes (dict) and .valid_subassemblies (list of sets).
        All nodes have .is_reachable set.
    """
    from pipeline.aog_generation import AOG

    lm = liaison_matrix if hasattr(liaison_matrix, 'shape') else np.array(liaison_matrix)
    im = [m if hasattr(m, 'shape') else np.array(m) for m in interference_matrices]

    tree = AOG(
        parts=parts,
        liaison_matrix=lm,
        interference_matrices=im,
        fastener_indices=fastener_indices,
        max_nodes=max_nodes,
        max_candidate_pairs=max_candidate_pairs,
    )
    tree.bottom_up_method()
    return tree
