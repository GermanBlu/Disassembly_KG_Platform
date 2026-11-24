"""Guard the placeholder disassembly-economics constants against id drift.

enrich_economics() applies its values via Cypher MATCH on skill / agent / tool
ids. If one of those ids stops matching a real Library node, the SET silently
does nothing and tasks quietly lose their time/cost. These pure, DB-free checks
catch that the moment the Library and the economics maps disagree.
"""
from models.economics import (
    AGENT_RATES,
    DEFAULT_TASK,
    SKILL_ECONOMICS,
    TOOL_COSTS,
)
from models.library import AGENTS, SKILLS, TOOLS

_DIFFICULTIES = {"low", "medium", "high"}


def test_skill_ids_exist_in_library():
    lib_skill_ids = {s["id"] for s in SKILLS}
    unknown = set(SKILL_ECONOMICS) - lib_skill_ids
    assert not unknown, f"economics references unknown skill ids: {unknown}"


def test_agent_ids_exist_in_library():
    lib_agent_ids = {a["id"] for a in AGENTS}
    unknown = set(AGENT_RATES) - lib_agent_ids
    assert not unknown, f"economics references unknown agent ids: {unknown}"


def test_tool_ids_exist_in_library():
    lib_tool_ids = {t["id"] for t in TOOLS}
    unknown = set(TOOL_COSTS) - lib_tool_ids
    assert not unknown, f"economics references unknown tool ids: {unknown}"


def test_skill_economics_values_are_sane():
    for sid, econ in SKILL_ECONOMICS.items():
        assert econ["duration_s"] > 0, f"{sid} has non-positive duration"
        assert econ["difficulty"] in _DIFFICULTIES, f"{sid} bad difficulty {econ['difficulty']!r}"
        if "force_n" in econ:
            assert econ["force_n"] > 0, f"{sid} has non-positive force"


def test_default_task_and_rates_positive():
    assert DEFAULT_TASK["duration_s"] > 0
    assert DEFAULT_TASK["difficulty"] in _DIFFICULTIES
    assert all(rate > 0 for rate in AGENT_RATES.values())
    assert all(cost >= 0 for cost in TOOL_COSTS.values())
