"""Fastener-group suggestions (pipeline/fastener_detection.suggest_fastener_groups).

Single-assembly Phase 1 labels carry an instance counter AND the part letter,
"Hex socket head cap screw M8x1.25 x 14_1 (C)" vs "…_2 (F)". The base-name
normalisation has to strip both, otherwise the Studio's group suggestion does
not fire on the golden assembly. Suggestions are UI sugar: none of this touches
AOG generation or the golden transition counts.
"""
from pipeline.fastener_detection import suggest_fastener_groups, _base_name


# The golden Hypothetical Product: screws C and F both clamp Holder (A) and
# Base plate (D); 9 contacts total.
_LABELS = [
    "Holder (A)", "End plate (B)",
    "Hex socket head cap screw M8x1.25 x 14_1 (C)",
    "Base plate (D)", "Tube_1 (E)",
    "Hex socket head cap screw M8x1.25 x 14_2 (F)",
    "Tube_2 (G)", "Shaft (H)",
]
_LM = [
    [0, 0, 1, 1, 0, 1, 0, 1],
    [0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 1, 0, 0, 0, 0],
    [1, 0, 1, 0, 1, 1, 1, 0],
    [0, 0, 0, 1, 0, 0, 0, 0],
    [1, 0, 0, 1, 0, 0, 0, 0],
    [0, 0, 0, 1, 0, 0, 0, 0],
    [1, 1, 0, 0, 0, 0, 0, 0],
]


def test_base_name_strips_letter_and_instance_counter():
    assert _base_name("Hex socket head cap screw M8x1.25 x 14_1 (C)") == \
           _base_name("Hex socket head cap screw M8x1.25 x 14_2 (F)")
    # the size token itself survives (only ONE trailing counter is stripped)
    assert _base_name("Screw M8 x 14_1 (C)").endswith("x 14")
    assert _base_name("M20 1") == "m20"          # name with a trailing counter after a space
    assert _base_name("Screw-2") == "screw"


def test_golden_screws_are_suggested_as_one_group():
    groups = suggest_fastener_groups([2, 5], _LABELS, _LM)
    assert len(groups) == 1
    assert groups[0]["members"] == [2, 5]
    assert groups[0]["contact_pattern"] == [0, 3]   # Holder + Base plate


def test_different_contact_patterns_do_not_group():
    lm = [row[:] for row in _LM]
    lm[5][3] = lm[3][5] = 0     # screw F no longer touches the Base plate
    assert suggest_fastener_groups([2, 5], _LABELS, lm) == []


def test_different_base_names_do_not_group():
    labels = _LABELS[:]
    labels[5] = "Countersunk screw M6_1 (F)"
    assert suggest_fastener_groups([2, 5], labels, _LM) == []


def test_single_fastener_yields_no_group():
    assert suggest_fastener_groups([2], _LABELS, _LM) == []
