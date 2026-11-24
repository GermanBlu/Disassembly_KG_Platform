"""Approximate solid-to-solid distance via triangle meshes.

The alternative to the exact ``BRepExtrema_DistShapeShape`` distance (the
default, see pipeline/liaison_matrix.py:compute_gap_matrix). This module
tessellates each solid once and computes a point-to-triangle distance between
the two meshes. Per pair it is faster than the exact distance on detailed
solids, and (unlike a vertex-only distance) it detects flat face-to-face
contacts, where the contact lies on a triangle interior with no nearby mesh
vertex. Curved mating faces are faceted, so a contact between them can read as
a gap of roughly the deflection.

Accuracy is bounded by the mesh deflection. KD-tree candidate selection keeps
the search near O(N) in points.
"""
import numpy as np
from scipy.spatial import cKDTree


def tessellate(shape, deflection):
    """Mesh a shape; return (vertices (V,3) float, triangles (T,3) int)."""
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.TopoDS import topods
    BRepMesh_IncrementalMesh(shape, deflection).Perform()
    verts, tris = [], []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = topods.Face(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            base = len(verts)
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                tris.append((base + a - 1, base + b - 1, base + c - 1))
        exp.Next()
    if not verts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)
    return np.asarray(verts, dtype=float), np.asarray(tris, dtype=int)


def _point_triangle_dist2(p, a, b, c):
    """Squared distance from points p (N,3) to triangles given by a,b,c (N,3).

    Vectorised closest-point-on-triangle (Ericson, Real-Time Collision Detection).
    """
    ab = b - a
    ac = c - a
    ap = p - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    # Barycentric coords of the in-face projection (guard denom==0)
    safe = np.where(denom == 0.0, 1.0, denom)
    v = vb / safe
    w = vc / safe
    closest = a + ab * v[:, None] + ac * w[:, None]

    # Region overrides (vertex / edge cases). Later assignments win where masked.
    def put(mask, pt):
        np.copyto(closest, pt, where=mask[:, None])

    put((d1 <= 0) & (d2 <= 0), a)                      # vertex A
    put((d3 >= 0) & (d4 <= d3), b)                     # vertex B
    put((d6 >= 0) & (d5 <= d6), c)                     # vertex C
    m_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = np.where((d1 - d3) == 0, 0.0, d1 / np.where((d1 - d3) == 0, 1.0, d1 - d3))
    put(m_ab, a + ab * t[:, None])                     # edge AB
    m_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = np.where((d2 - d6) == 0, 0.0, d2 / np.where((d2 - d6) == 0, 1.0, d2 - d6))
    put(m_ac, a + ac * t[:, None])                     # edge AC
    m_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    dd = (d4 - d3) + (d5 - d6)
    t = np.where(dd == 0, 0.0, (d4 - d3) / np.where(dd == 0, 1.0, dd))
    put(m_bc, b + (c - b) * t[:, None])                # edge BC

    diff = p - closest
    return np.einsum("ij,ij->i", diff, diff)


def _min_point_to_mesh(points, verts, tris, vtree, k):
    """Min distance from each of `points` to the triangle mesh (verts, tris)."""
    if len(points) == 0 or len(tris) == 0:
        return np.inf
    # Candidate triangles: those touching the k nearest vertices of each point.
    _, vidx = vtree.query(points, k=min(k, len(verts)))
    vidx = np.atleast_2d(vidx.T).T  # (Npoints, k)
    # Map each near vertex to triangles that contain it.
    vert_tris = [[] for _ in range(len(verts))]
    for ti, (a, b, c) in enumerate(tris):
        vert_tris[a].append(ti); vert_tris[b].append(ti); vert_tris[c].append(ti)
    best = np.full(len(points), np.inf)
    for pi in range(len(points)):
        cand = set()
        for vi in np.atleast_1d(vidx[pi]):
            cand.update(vert_tris[int(vi)])
        if not cand:
            continue
        ct = tris[list(cand)]
        p = np.repeat(points[pi][None, :], len(ct), axis=0)
        d2 = _point_triangle_dist2(p, verts[ct[:, 0]], verts[ct[:, 1]], verts[ct[:, 2]])
        best[pi] = d2.min()
    return float(np.sqrt(best.min()))


def mesh_min_distance(mesh_a, mesh_b, k=6):
    """Approximate min surface distance between two (verts, tris) meshes."""
    va, ta = mesh_a
    vb, tb = mesh_b
    if len(va) == 0 or len(vb) == 0:
        return np.inf
    tree_a = cKDTree(va)
    tree_b = cKDTree(vb)
    return min(_min_point_to_mesh(vb, va, ta, tree_a, k),
               _min_point_to_mesh(va, vb, tb, tree_b, k))
