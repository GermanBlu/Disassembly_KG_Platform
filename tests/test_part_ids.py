"""Canonical part-ID scheme (pipeline/part_ids.py)."""
import pytest

from pipeline.part_ids import part_id, is_valid_part_id, MAX_PARTS, PART_ALPHABET


def test_first_26_are_AZ_benchmark_identical():
    # The first 26 IDs MUST be A-Z (chr(65+i)): the sample products and the
    # paper benchmarks use these identifiers.
    assert [part_id(i) for i in range(26)] == [chr(65 + i) for i in range(26)]


def test_extends_into_lowercase_then_digits():
    assert part_id(26) == "a"
    assert part_id(51) == "z"
    assert part_id(52) == "0"
    assert part_id(61) == "9"


def test_max_parts_is_62():
    assert MAX_PARTS == 62 == len(PART_ALPHABET)


def test_alphabet_is_unique():
    assert len(set(PART_ALPHABET)) == len(PART_ALPHABET)


@pytest.mark.parametrize("i", [-1, 62, 100])
def test_out_of_range_raises(i):
    with pytest.raises(ValueError):
        part_id(i)


@pytest.mark.parametrize("pid,ok", [
    ("A", True), ("Z", True), ("a", True), ("z", True), ("0", True), ("9", True),
    ("AA", False), (" ", False), ("", False), ("[", False), (None, False), (1, False),
])
def test_is_valid_part_id(pid, ok):
    assert is_valid_part_id(pid) is ok
