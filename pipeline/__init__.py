"""Public pipeline API — re-exports used by seed_benchmark and tests."""
from pipeline.geometry import load_and_extract
from pipeline.interference import check_interference, build_directions
from pipeline.aog_builder import build_aog
from pipeline.semantic import (
    generate_semantic_tables,
    get_connected_components,
    find_broken_connection,
)

__all__ = [
    "load_and_extract",
    "check_interference",
    "build_directions",
    "build_aog",
    "generate_semantic_tables",
    "get_connected_components",
    "find_broken_connection",
]
