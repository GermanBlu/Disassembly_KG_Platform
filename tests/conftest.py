"""Shared test fixtures. Ensures the repo root is importable and provides an
OpenCASCADE-availability check so integration tests skip cleanly without OCC."""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def occ_available():
    try:
        import OCC.Core.STEPControl  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not occ_available(),
                                  reason="OpenCASCADE not importable (run in the 'occ' conda env)")
