"""A pair whose moving part renders no pixel is blocked, never free.

_occlusion_ratio() returns -1.0 when the moving part is not visible at all. The
decision must not read that as "nothing covered". The renderer is replaced by a
stub, so only the decision logic runs.
"""
from unittest.mock import patch

import numpy as np

from conftest import requires_occ

pytestmark = [requires_occ]


class _Viewer:
    def Create(self, **kw):
        pass

    def SetModeShaded(self):
        pass


class _Part:
    Shape = None


def test_not_measurable_pair_is_blocked():
    from OCC.Core.gp import gp_Dir
    import pipeline.interference as m
    with patch("OCC.Display.OCCViewer.Viewer3d", _Viewer), \
            patch.object(m, "_visual_check_with_tolerance", return_value=-1.0):
        binary, ratios = m._stage2_with_tolerance(
            [_Part(), _Part()], np.array([[0, 1], [0, 0]]), gp_Dir(1, 0, 0), pixel_tol=0.01)
    assert binary[0][1] == 1
    assert ratios[0][1] == -1.0
    assert binary[1][0] == 0                      # not flagged by Stage 1: stays free


def test_occlusion_ratio_of_an_invisible_part():
    from pipeline.interference import _occlusion_ratio
    empty = np.zeros((4, 4), dtype=bool)
    assert _occlusion_ratio(empty, empty) == -1.0
