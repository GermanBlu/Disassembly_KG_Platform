"""Free travel along a direction (pipeline.two_step.free_travel).

Boxes built with Open CASCADE primitives, no STEP file needed. The two-step
release itself is checked end to end on the Hypothetical Product
(test_prasad_config_e2e.py).
"""
import pytest

from conftest import requires_occ

pytestmark = [requires_occ]


def _box(x, y, z, dx, dy, dz):
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCC.Core.gp import gp_Pnt
    return BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), dx, dy, dz).Shape()


def _hit_at(t, expected):
    """The search returns the first overlapping shift: at most RESOLUTION late."""
    from pipeline.two_step import RESOLUTION
    return t is not None and expected - 1e-6 <= t <= expected + RESOLUTION + 1e-6


def test_head_on_obstacle_is_hit_after_the_gap():
    from pipeline.two_step import free_travel
    part = _box(0, 0, 0, 10, 10, 10)
    wall = _box(-5, 30, -5, 20, 5, 20)            # 20 mm ahead along +Y
    assert _hit_at(free_travel(part, wall, (0, 1, 0)), 20)
    assert free_travel(part, wall, (0, -1, 0)) is None


def test_obstacle_beside_the_path_is_never_hit():
    from pipeline.two_step import free_travel
    part = _box(0, 0, 0, 10, 10, 10)
    beside = _box(20, 30, 0, 10, 10, 10)
    assert free_travel(part, beside, (0, 1, 0)) is None


def test_part_sliding_along_the_obstacle_stops_at_its_step():
    from pipeline.two_step import free_travel
    # L-shaped obstacle as one solid: a plate the part rests on and a wall 40 mm ahead
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Fuse
    obstacle = BRepAlgoAPI_Fuse(_box(0, 0, 0, 100, 20, 10), _box(50, 0, 10, 5, 20, 30)).Shape()
    part = _box(0, 5, 10, 10, 10, 10)             # touches the plate, slides along +X
    assert _hit_at(free_travel(part, obstacle, (1, 0, 0)), 40)


def test_thin_obstacle_head_on_is_hit():
    # Two 0.1 mm plates 0.1 mm apart: a coarse step would pass through both.
    from pipeline.two_step import free_travel
    part = _box(0, 0, 0, 0.1, 1, 1)
    wall = _box(0.2, 0, 0, 0.1, 1, 1)
    assert _hit_at(free_travel(part, wall, (1, 0, 0)), 0.1)


def test_thin_lip_is_hit_while_sliding():
    # A 0.08 mm part slides along a plate into a 0.06 mm lip at x = 5.2: the
    # collision lasts 0.14 mm of travel, between two samples 0.5 mm apart.
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from pipeline.two_step import STEP, free_travel
    obstacle = BRepAlgoAPI_Fuse(_box(0, 0, 0, 10, 10, 1), _box(5.2, 0, 1, 0.06, 10, 1)).Shape()
    part = _box(0, 2, 1, 0.08, 5, 0.5)
    assert STEP < 0.14
    assert _hit_at(free_travel(part, obstacle, (1, 0, 0)), 5.12)


# ── Full Phase 1 on a synthetic assembly (nothing taken from the HP) ─────────

def _write_assembly(path, parts):
    """STEP assembly with one named component per (name, shape)."""
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.STEPCAFControl import STEPCAFControl_Writer
    from OCC.Core.STEPControl import STEPControl_AsIs
    from OCC.Core.TDataStd import TDataStd_Name
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
    doc = TDocStd_Document("MDTV-XCAF")
    tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    assembly = tool.NewShape()
    TDataStd_Name.Set(assembly, "Synthetic")
    for name, shape in parts:
        label = tool.AddShape(shape, False)
        TDataStd_Name.Set(label, name)
        tool.AddComponent(assembly, label, TopLoc_Location())
    tool.UpdateAssemblies()
    writer = STEPCAFControl_Writer()
    writer.Transfer(doc, STEPControl_AsIs)
    assert writer.Write(str(path)) == IFSelect_RetDone


def _collar_on_post(wall_gap):
    """Collar 15 mm deep on a post end; a wall wall_gap mm above the collar.

    Base plate y∈[-10,0], post y∈[0,40] (10×10), collar y∈[25,40] with a 10×10
    through hole, wall from y = 40 + wall_gap, held by a column at the side.
    """
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
    top = 40 + wall_gap
    collar = BRepAlgoAPI_Cut(_box(-15, 25, -15, 30, 15, 30), _box(-5, 20, -5, 10, 25, 10)).Shape()
    return [("Base", _box(-40, -10, -40, 80, 10, 80)),
            ("Post", _box(-5, 0, -5, 10, 40, 10)),
            ("Collar", collar),
            ("Column", _box(30, 0, -40, 10, top, 10)),
            ("Wall", _box(-40, top, -40, 80, 10, 80))]


def _phase1(tmp_path, parts):
    from models.step_pipeline import run_step_phase1
    from pipeline.settings import STANDARD_SETTINGS
    path = tmp_path / "synthetic.step"
    _write_assembly(path, parts)
    p1 = run_step_phase1([str(path)], ["Synthetic"], settings=STANDARD_SETTINGS)
    assert p1["success"], p1["error"]
    return p1


@pytest.mark.slow
def test_collar_is_released_when_it_clears_the_post_before_the_wall(tmp_path):
    p1 = _phase1(tmp_path, _collar_on_post(wall_gap=20))
    ids = {lbl.split(" (")[0]: lbl[-2] for lbl in p1["parts"]}
    rel = p1["two_step_releases"]
    assert [(r["part"], r["direction"], r["ignore"]) for r in rel] == [
        (ids["Collar"], [0.0, 1.0, 0.0], [ids["Wall"]])]
    assert rel[0]["min_shift"] == pytest.approx(15.0, abs=0.1)
    assert rel[0]["free_travel"] == pytest.approx(20.0, abs=0.1)
    assert sorted(map(tuple, rel[0]["second_move"])) == sorted(
        [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)])


@pytest.mark.slow
def test_collar_is_not_released_when_the_wall_is_closer_than_its_engagement(tmp_path):
    p1 = _phase1(tmp_path, _collar_on_post(wall_gap=10))
    assert p1["two_step_releases"] == []
    assert any("minimum shift 15.0 >= free travel 10.0" in line for line in p1["log"])
