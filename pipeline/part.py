"""Part: one solid of the assembly with its shape, bounding box, id and name.

The projection attributes (corners_Bbox, p_min, p_max, depth_intervall) are
filled by pipeline.bbox_projection for the interference check.
"""
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh


class Part:
    def __init__(self,shape_p:TopoDS_Shape, part_id_p= None, part_name_p = None):
        self.Shape = shape_p
        self.BoundingBox = self.get_BoundingBox(use_mesh= False)
        #corners_Bbox = [lower_left_back_corner, lower_right_back_corner, upper_left_back_corner, upper_right_back_corner, ... samer for front ]
        self.id = part_id_p
        self.name = part_name_p
        
        ## attributes for interference check
        self.corners_Bbox = []
        self.transformed_corners = []
        self.depth_intervall = []
        self.p_min = 0
        self.p_max = 0
        
        ## attributes for liaison check
        self.pass_to_2nd_stage_liaison = False
        self.volume = 0
        self.bbox_volume = 0

        ## attributes for subassembly detection
        self.visited = False
        pass

    def get_BoundingBox(self, tol=1e-6, use_mesh=True):
        """return the bounding box of the TopoDS_Shape `shape`
        Parameters
        ----------
        shape : TopoDS_Shape or a subclass such as TopoDS_Face
        the shape to compute the bounding box from
        tol: float
        tolerance of the computed boundingbox
        use_mesh : bool
        a flag that tells whether or not the shape has first to be meshed before the bbox
        computation. This produces more accurate results
        """
        bbox = Bnd_Box()
        bbox.SetGap(tol)
        if use_mesh:
            mesh = BRepMesh_IncrementalMesh()
            mesh.SetParallelDefault(True)
            mesh.SetShape(self.Shape)
            mesh.Perform()
            if not mesh.IsDone():
                raise AssertionError("Mesh not done.")
        brepbndlib.Add(self.Shape, bbox, use_mesh)
        return bbox
