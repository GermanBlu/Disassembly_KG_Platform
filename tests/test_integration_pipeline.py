"""Integration test: real STEP geometry through OpenCASCADE.

Marked `integration` and skipped without the 'occ' env. It guards the
geometry/distance code: part extraction and contact count on the Hypothetical
Product STEP file, which is part of the repository.
"""
import numpy as np
import pytest

from conftest import requires_occ

pytestmark = [pytest.mark.integration, requires_occ]

_HYPO = "sample_data/Hypothetical Product STEP/Hypothetical Product.step"


def _counts(path):
    from pipeline.geometry import load_parts_from_assembly
    from pipeline.liaison_matrix import compute_contacts
    parts = [p for p, _, _ in load_parts_from_assembly(path)]
    cd = compute_contacts(parts)
    contacts = int(np.array(cd["liaison_matrix"]).sum()) // 2
    return len(parts), contacts


def test_hypothetical_golden():
    """Hypothetical product: 8 parts and 9 contacts (module default: threshold
    from the gap distribution)."""
    n_parts, n_contacts = _counts(_HYPO)
    assert n_parts == 8
    assert n_contacts == 9
