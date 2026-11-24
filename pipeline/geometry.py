"""Geometry module: STEP file loading, part extraction, and liaison matrix generation.

Handles both single-file assemblies (XCAF traversal) and multi-file part collections.
"""
import os
import re

from pipeline.part_ids import part_id


def _split_disconnected_solids(shape, tol=0.1):
    """Split a shape into one shape per *physically connected* group of solids.

    A single-shape component can be a body-container holding several physically
    separate solids (e.g. a "Buttons" body that is really three distinct
    buttons). Solids whose bounding boxes are within ``tol`` (model units) are
    treated as one part (touching / fused); disconnected groups become separate
    parts. Returns the original shape unchanged when it has 0–1 solids or all
    solids form a single connected group.

    A cheap bounding-box prefilter discards clearly-separate pairs; the remaining
    near pairs are decided by a fast point-to-triangle mesh distance (the same
    primitive the liaison gap matrix uses), not exact BRepExtrema. The gap between
    fused solids of one part is ~0 while distinct bodies are millimetres apart, so
    the test is not sensitive to ``tol``.
    """
    import math
    import numpy as np
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.TopoDS import TopoDS_Compound
    from OCC.Core.BRep import BRep_Builder
    from pipeline.mesh_distance import tessellate, mesh_min_distance

    solids, boxes = [], []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        s = exp.Current()
        b = Bnd_Box()
        brepbndlib.Add(s, b)
        solids.append(s)
        boxes.append(b.Get())  # (xmin, ymin, zmin, xmax, ymax, zmax)
        exp.Next()

    if len(solids) <= 1:
        return [shape]

    def bbox_gap(a, b):
        dx = max(0.0, a[0] - b[3], b[0] - a[3])
        dy = max(0.0, a[1] - b[4], b[1] - a[4])
        dz = max(0.0, a[2] - b[5], b[2] - a[5])
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    # Union-find over bbox adjacency
    parent = list(range(len(solids)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Tessellate each solid once, then decide near bbox-pairs by mesh distance —
    # the same fast point-to-triangle primitive the liaison gap matrix uses,
    # in place of the exact O(S²) BRepExtrema, which is slow on detailed
    # solids. Fused solids of one part sit at ~0 gap while distinct bodies are
    # millimetres apart, so the mesh approximation preserves the connectivity
    # split into separate analysis units.
    dims = [min(b[3] - b[0], b[4] - b[1], b[5] - b[2]) for b in boxes]
    dims = [d for d in dims if d > 1e-9]
    cs = float(np.median(dims)) if dims else 1.0
    deflection = max(0.05, min(0.5, 0.01 * cs))
    meshes = [tessellate(s, deflection) for s in solids]

    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            # bbox gap is a cheap lower bound: boxes already > tol apart ⇒ the
            # solids are certainly separate (skip the mesh check). Boxes can
            # overlap while solids are far apart (interleaving buttons), so close
            # boxes are decided by the mesh distance.
            if bbox_gap(boxes[i], boxes[j]) > tol:
                continue
            if mesh_min_distance(meshes[i], meshes[j]) <= tol:
                parent[find(i)] = find(j)

    groups = {}
    for i in range(len(solids)):
        groups.setdefault(find(i), []).append(solids[i])

    if len(groups) <= 1:
        return [shape]

    parts = []
    for members in groups.values():
        comp = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(comp)
        for s in members:
            builder.Add(comp, s)
        parts.append(comp)
    return parts


def load_parts_from_assembly(assembly_filepath, log_fn=None):
    """Load the top-level parts from a STEP assembly file via XCAF traversal.

    Uses the flat (non-recursive) approach: iterates direct children of the
    root assembly label, resolves each component instance to its prototype
    label, and reads the part name from the prototype using GetLabelName().
    Each direct child becomes one part — including children that are themselves
    sub-assemblies, whose full compound geometry is taken as a single opaque
    part. We do not recurse: many exporters (e.g. KiCad/ECAD boards) wrap every
    component in its own sub-assembly, and skipping those would drop every real
    part and leave only a stray top-level solid.

    This is critical for correct name extraction: in XCAF, component instance
    labels do not carry TDataStd_Name attributes — the name lives on the
    prototype (referred) label. Reading TDataStd_Name from an instance label
    returns nothing and falls back to "Unnamed".

    Returns list of (Part, named_label, temp_filepath) tuples.
    """
    from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
    from OCC.Core.TDF import TDF_LabelSequence, TDF_Label
    from OCC.Core.TopoDS import TopoDS_Shape
    from OCC.Core.IFSelect import IFSelect_RetDone
    from pipeline.part import Part

    def _log(msg):
        if log_fn:
            log_fn(msg)

    doc = TDocStd_Document("MDTV-XCAF")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    reader_caf = STEPCAFControl_Reader()
    if reader_caf.ReadFile(assembly_filepath) != IFSelect_RetDone:
        _log(f"  Failed to read assembly: {assembly_filepath}")
        return []
    reader_caf.Transfer(doc)

    # GetShapes() returns all labels; Value(1) is the root assembly label
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    if labels.Length() == 0:
        return []
    root_label = labels.Value(1)

    # Flat iteration: direct children only (subchilds=False)
    top_components = TDF_LabelSequence()
    shape_tool.GetComponents(root_label, top_components, False)

    raw_parts = []
    for j in range(top_components.Length()):
        c_label = top_components.Value(j + 1)   # instance label (has location, no name)
        ref_label = TDF_Label()
        if not shape_tool.GetReferredShape(c_label, ref_label):
            continue                              # not a reference — skip

        # Shape geometry from prototype; positional transform from instance.
        # GetShape works for both simple-shape and sub-assembly prototypes — for
        # a sub-assembly it returns the compound of all leaf solids, so the whole
        # component is treated as one flat part (we intentionally do not recurse).
        shape = TopoDS_Shape()
        shape_tool.GetShape(ref_label, shape)
        if shape.IsNull():
            continue                              # empty prototype — nothing to add
        location = shape_tool.GetLocation(c_label)
        transformed_shape = shape.Located(location)

        # GetLabelName() on the prototype label reliably returns the STEP part name
        raw_name = ref_label.GetLabelName().strip() or "Unnamed"
        clean_name = re.sub(r'\s*\([^)]*\)$', '', raw_name).strip()

        # A sub-assembly is an explicit "these belong together" grouping → keep it
        # as ONE part. A simple shape holding several physically-separate solids
        # is several parts in one body-container → split by connectivity. Repeated
        # names are suffixed _1/_2/... by the de-duplication step below.
        if shape_tool.IsAssembly(ref_label):
            sub_shapes = [transformed_shape]
        else:
            sub_shapes = _split_disconnected_solids(transformed_shape)
        for ss in sub_shapes:
            raw_parts.append((ss, clean_name))

    if not raw_parts:
        return []

    # Deduplicate names for repeated parts (e.g. multiple screws → Screw_1, Screw_2)
    name_counts = {}
    for _, name in raw_parts:
        name_counts[name] = name_counts.get(name, 0) + 1

    seen_counts = {}
    results = []
    for i, (shape, clean_name) in enumerate(raw_parts):
        seen_counts[clean_name] = seen_counts.get(clean_name, 0) + 1
        display_name = (
            f"{clean_name}_{seen_counts[clean_name]}"
            if name_counts[clean_name] > 1
            else clean_name
        )
        letter = part_id(i)
        named_label = f"{display_name} ({letter})"

        part = Part(shape_p=shape, part_name_p=named_label, part_id_p=i)

        _log(f"    Extracted part {i}: {named_label}")
        results.append((part, named_label, None))

    return results


def load_parts_from_files(step_files, part_labels, log_fn=None):
    """Load individual STEP files as separate parts.

    Skips any file that turns out to be an assembly itself. Parts that are
    successfully read are assigned sequential letters (A, B, C, ...).
    """
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.STEPCAFControl import STEPCAFControl_Reader as CAFReader
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
    from OCC.Core.TDF import TDF_LabelSequence
    from OCC.Core.IFSelect import IFSelect_RetDone
    from pipeline.part import Part

    def _log(msg):
        if log_fn:
            log_fn(msg)

    results = []
    for filepath, label in zip(step_files, part_labels):
        # Skip nested assemblies
        doc = TDocStd_Document("MDTV-XCAF")
        st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
        caf = CAFReader()
        if caf.ReadFile(filepath) == IFSelect_RetDone:
            caf.Transfer(doc)
            lbls = TDF_LabelSequence()
            st.GetShapes(lbls)
            if lbls.Length() > 0 and st.IsAssembly(lbls.Value(1)):
                _log(f"  Skipping assembly file: {label}")
                continue

        reader = STEPControl_Reader()
        if reader.ReadFile(filepath) != IFSelect_RetDone:
            raise RuntimeError(f"Failed to read STEP file: {filepath}")
        reader.TransferRoots()
        shape = reader.OneShape()

        clean_label = re.sub(r'\s*\([^)]*\)$', '', label).strip()
        letter = part_id(len(results))
        named_label = f"{clean_label} ({letter})"

        part = Part(shape_p=shape, part_name_p=named_label, part_id_p=len(results))
        _log(f"  Loaded: {named_label}")
        results.append((part, named_label, filepath))

    return results


def is_assembly_file(filepath):
    """Return True if the STEP file contains an assembly as its root shape."""
    from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
    from OCC.Core.TDF import TDF_LabelSequence
    from OCC.Core.IFSelect import IFSelect_RetDone

    doc = TDocStd_Document("test")
    st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    rd = STEPCAFControl_Reader()
    if rd.ReadFile(filepath) != IFSelect_RetDone:
        return False
    rd.Transfer(doc)
    rts = TDF_LabelSequence()
    st.GetFreeShapes(rts)
    return rts.Length() > 0 and st.IsAssembly(rts.Value(1))


# Overlap volume (model units³, mm³) above which two parts count as penetrating.
# Boolean intersections of merely touching parts return slivers far below this.
OVERLAP_MIN_VOLUME = 0.01


def volume_overlaps(parts, liaison_matrix, min_volume=OVERLAP_MIN_VOLUME):
    """Pairs of touching parts whose solids overlap (BRepAlgoAPI_Common).

    The interference check needs an overlap-free assembly: two overlapping
    parts (a thread modelled at nominal diameter in its hole, a press fit with
    overlap) occlude each other in every direction, so neither can ever be
    separated. Only contacting pairs are checked; parts that overlap are always
    in contact.

    Returns:
        list of (i, j, volume) with i < j, volume in model units³.
    """
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    found = []
    n = len(parts)
    for i in range(n):
        for j in range(i + 1, n):
            if not liaison_matrix[i][j]:
                continue
            common = BRepAlgoAPI_Common(parts[i].Shape, parts[j].Shape)
            if not common.IsDone():
                continue
            props = GProp_GProps()
            brepgprop.VolumeProperties(common.Shape(), props)
            volume = abs(props.Mass())
            if volume > min_volume:
                found.append((i, j, volume))
    return found


def load_and_extract(step_files, part_labels, manual_liaison=None,
                     contact_tol=None, log_fn=None, settings=None):
    """Top-level entry point: load parts and compute liaison matrix.

    Automatically detects if step_files contains a single assembly file and
    uses XCAF traversal; otherwise loads files individually.

    Args:
        step_files:      List of STEP file paths.
        part_labels:     Corresponding list of human-readable part labels.
        manual_liaison:  Optional N×N list-of-lists to use instead of computing.
        contact_tol:     Optional explicit contact gap threshold (model units).
                         None → derive it automatically from the gap distribution
                         (see liaison_matrix.auto_contact_threshold).
        log_fn:          Optional logging callback.

    Returns:
        dict with keys: parts, part_labels, liaison_matrix, gap_matrix,
        contact_threshold, contact_info, contacts, timing.
    """
    import numpy as np
    import time

    def _log(msg):
        if log_fn:
            log_fn(msg)

    t0 = time.time()
    parts = []
    active_labels = []

    # Try to find a master assembly among the provided files
    master_assembly = None
    for fp in step_files:
        if os.path.exists(fp) and is_assembly_file(fp):
            master_assembly = fp
            break

    if master_assembly:
        _log(f"  Detected master assembly: {os.path.basename(master_assembly)}")
        extracted = load_parts_from_assembly(master_assembly, log_fn=log_fn)
        if extracted:
            for part, label, _ in extracted:
                parts.append(part)
                active_labels.append(label)
        else:
            _log("  Assembly extraction returned no parts. Falling back to individual files.")
            master_assembly = None

    if not master_assembly:
        extracted = load_parts_from_files(step_files, part_labels, log_fn=log_fn)
        for part, label, _ in extracted:
            parts.append(part)
            active_labels.append(label)

    t_read = time.time() - t0
    _log(f"Loaded {len(parts)} parts in {t_read:.2f}s")

    if not parts:
        raise RuntimeError("No parts loaded from the provided STEP files.")

    # Liaison matrix
    t1 = time.time()
    gap_matrix = None
    contact_threshold = None
    contact_info = None
    if manual_liaison is not None:
        _log("  Using manual liaison matrix.")
        lm = np.array(manual_liaison)
        if lm.shape != (len(parts), len(parts)):
            raise ValueError(
                f"Manual liaison matrix shape {lm.shape} does not match "
                f"parts count {len(parts)}"
            )
        contact_info = {"mode": "manual_matrix"}
    else:
        from pipeline.liaison_matrix import compute_contacts
        cd = compute_contacts(parts, tol=contact_tol, log_fn=log_fn, settings=settings)
        lm = cd["liaison_matrix"]
        gap_matrix = cd["gap_matrix"]
        contact_threshold = cd["threshold"]
        contact_info = cd["info"]
    t_liaison = time.time() - t1

    contacts = [
        {"part1_idx": i, "part2_idx": j, "part1": active_labels[i], "part2": active_labels[j]}
        for i in range(len(parts))
        for j in range(i + 1, len(parts))
        if lm[i][j]
    ]
    _log(f"Found {len(contacts)} contacts in {t_liaison:.2f}s")

    return {
        "parts": parts,
        "part_labels": active_labels,
        "liaison_matrix": lm,
        "gap_matrix": gap_matrix,
        "contact_threshold": contact_threshold,
        "contact_info": contact_info,
        "contacts": contacts,
        "timing": {"step_reading": round(t_read, 2), "liaison": round(t_liaison, 2)},
    }
