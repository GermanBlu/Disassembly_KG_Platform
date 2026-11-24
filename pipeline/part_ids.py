"""Canonical part identifiers.

Every part gets a short ID that is used as its node key throughout the pipeline
*and* as a single token inside the concatenated subassembly-state strings the
AOG works with (e.g. a state "ABF" means parts A, B and F are present).

That state representation requires each ID to be exactly ONE character, so the
alphabet is a 62-symbol safe set — uppercase, lowercase, digits. The first 26
IDs are A–Z (``chr(65 + i)``), the identifiers of the sample products and the
paper benchmarks; parts 27–62 use
a–z then 0–9 instead of running off the end of the alphabet into punctuation and
control characters.

Assemblies with more than 62 parts are rejected upstream (Phase 1 load and the
semantic guard) — they are either too large to enumerate (see the AOG
complexity guard) or must be grouped first. Lifting that ceiling would require
switching the state strings from character concatenation to a delimited / set
representation across the pipeline.
"""
import string

PART_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits
MAX_PARTS = len(PART_ALPHABET)  # 62


def part_id(i):
    """Return the canonical single-character ID for 0-based part index ``i``."""
    if not 0 <= i < MAX_PARTS:
        raise ValueError(
            f"part index {i} is out of range for the {MAX_PARTS}-symbol ID scheme; "
            f"this assembly has too many parts to enumerate — group identical "
            f"components or split the model"
        )
    return PART_ALPHABET[i]


def is_valid_part_id(pid):
    """True if ``pid`` is a valid single-character part ID."""
    return isinstance(pid, str) and len(pid) == 1 and pid in PART_ALPHABET
