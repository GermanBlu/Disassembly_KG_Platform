"""Fastener detection (Tier 1: name-matching only) and grouping.

Classifies parts as fasteners using regex matching on part names for standard
fastener nomenclature (bolt, screw, nut, washer, pin, rivet, ISO/DIN codes).
There are no geometric heuristics: the user confirms or selects fasteners in the UI.

Also provides fastener grouping: identical fasteners (same base name + same
non-fastener contact pattern) are grouped for matrix reduction in the AOG.
"""
import re
from collections import defaultdict

# Tier 1: Regex patterns for fastener name matching
_FASTENER_NAME_PATTERNS = [
    re.compile(r'\bscrew\b', re.I),
    re.compile(r'\bbolt\b', re.I),
    re.compile(r'\bnut\b', re.I),
    re.compile(r'\bwasher\b', re.I),
    re.compile(r'\brivet\b', re.I),
    re.compile(r'\bclip\b', re.I),
    re.compile(r'\bpin\b', re.I),
    re.compile(r'\bM\d+', re.I),               # M6, M20, etc.
    re.compile(r'\bISO\s*\d{3,5}\b', re.I),    # ISO 4762, etc.
    re.compile(r'\bDIN\s*\d{3,5}\b', re.I),    # DIN 912, etc.
    re.compile(r'\bSchraube\b', re.I),          # German
    re.compile(r'\bMutter\b', re.I),            # German
    re.compile(r'\bhex\s*socket\b', re.I),
    re.compile(r'\bcap\s*screw\b', re.I),
    re.compile(r'\bfastener\b', re.I),
    re.compile(r'\bfixing\b', re.I),
    # Sealing elements (gasket, seal, O-ring) are not listed. The schema
    # reserves the Fastener label for components with a connecting or fixing
    # function, and a seal has neither: it closes a gap, it does not hold parts
    # together. A gasket between two parts would otherwise be read as the
    # fastener of a ScrewJoint between them.
    re.compile(r'\bset\s*screw\b', re.I),
    re.compile(r'\bgrub\s*screw\b', re.I),
    re.compile(r'\bwing\s*nut\b', re.I),
    re.compile(r'\bflange\s*nut\b', re.I),
    re.compile(r'\bBolzen\b', re.I),            # German
    re.compile(r'\bScheibe\b', re.I),           # German
    re.compile(r'\bStift\b', re.I),             # German
    re.compile(r'\bNiet\b', re.I),              # German
]

_STRIP_LETTER = re.compile(r'\s*\([A-Za-z0-9]\)\s*$')  # "…_1 (C)" → "…_1"
_STRIP_SUFFIX = re.compile(r'[\s_-]*\d+$')             # "m20 1"/"screw_2" → "m20"/"screw"


def _base_name(label):
    """Normalise a part label to its instance-independent base name.

    Single-assembly Phase 1 labels carry the part letter and an instance
    counter — "Hex socket head cap screw M8x1.25 x 14_1 (C)" — so identical
    fasteners only match once both are stripped (letter suffix first, then
    one trailing counter; the size token "…x 14" itself survives)."""
    return _STRIP_SUFFIX.sub('', _STRIP_LETTER.sub('', label.strip().lower()))


def detect_fasteners(parts, part_labels):
    """Identify likely fastener parts by name matching (Tier 1 only).

    Args:
        parts:       list of Part objects (not used by the name matching).
        part_labels: list[str] — human-readable labels (e.g., "Screw_1 (A)").

    Returns:
        dict with keys:
          fastener_indices: list[int] — 0-based indices of detected fasteners.
          detections: list[dict] — per-part detection info for UI display.
          log: list[str] — detection log messages.
    """
    n = len(part_labels)
    log_msgs = []
    detections = []
    fastener_indices = []

    for i in range(n):
        label = part_labels[i]
        # Strip the canonical part-ID suffix "(X)" — X is one char from the
        # part alphabet (A-Z, a-z, 0-9), not only uppercase.
        base_name = re.sub(r'\s*\([A-Za-z0-9]\)$', '', label)

        detection = {
            "index": i,
            "label": label,
            "method": None,
            "confidence": 0.0,
            "is_fastener": False,
        }

        name_match = any(p.search(base_name) for p in _FASTENER_NAME_PATTERNS)
        if name_match:
            detection["method"] = "name"
            detection["confidence"] = 0.95
            detection["is_fastener"] = True
            fastener_indices.append(i)
            log_msgs.append(f"  [{label}] → fastener (name match, confidence=0.95)")
        else:
            detection["method"] = "none"
            log_msgs.append(f"  [{label}] → structural part")

        detections.append(detection)

    log_msgs.append(f"Detected {len(fastener_indices)}/{n} parts as fasteners")

    return {
        "fastener_indices": fastener_indices,
        "detections": detections,
        "log": log_msgs,
    }


def suggest_fastener_groups(fastener_indices, part_labels, liaison_matrix):
    """Group fasteners with identical contact patterns and same base name.

    Args:
        fastener_indices: list[int] — 0-based indices of fastener parts
        part_labels: list[str] — all part labels
        liaison_matrix: NxN matrix

    Returns:
        list[dict] with group_id, name, members (0-based), contact_pattern
    """
    import numpy as np
    lm = np.array(liaison_matrix, dtype=int)
    fastener_set = set(int(i) for i in fastener_indices)

    # For each fastener: compute contact signature = frozenset of non-fastener neighbours
    signatures = {}
    for f_idx in fastener_indices:
        f_idx = int(f_idx)
        neighbours = frozenset(
            j for j in range(len(part_labels))
            if lm[f_idx][j] == 1 and j not in fastener_set
        )
        base_name = _base_name(part_labels[f_idx])
        signatures[f_idx] = (base_name, neighbours)

    # Group by (base_name, contact_pattern)
    groups_dict = defaultdict(list)
    for f_idx, (base_name, contact) in signatures.items():
        groups_dict[(base_name, contact)].append(f_idx)

    # Only keep groups with 2+ members
    groups = []
    for gid, ((base_name, contact), members) in enumerate(groups_dict.items()):
        if len(members) < 2:
            continue
        groups.append({
            "group_id": gid,
            "name": f"{len(members)}x {base_name} *{len(contact)}",
            "members": sorted(members),
            "contact_pattern": sorted(contact),
        })

    return groups
