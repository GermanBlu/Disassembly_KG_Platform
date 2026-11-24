"""Placeholder disassembly-economics enrichment.

Assigns placeholder time, cost, difficulty (and, where relevant, required
force) to disassembly tasks, plus labor rates to agents and acquisition and
usage costs to tools. It is used by seed_demo_product.py for the demo product.

The labor cost of a task is derived: duration in hours × labor rate of the
performing agent; the usage cost of the task's tool is added. The per-task
figures are keyed by the disassembly skill each task requires. All values are
illustrative defaults, not measured values.

All writes are SET; the function can be run repeatedly.
"""

# skill_id -> {duration seconds, difficulty, [force in N]}
SKILL_ECONOMICS = {
    "Skill_Unscrewing":  {"duration_s": 25, "difficulty": "medium"},
    "Skill_Unclamping":  {"duration_s": 15, "difficulty": "low"},
    "Skill_PullingOff":  {"duration_s": 12, "difficulty": "low",    "force_n": 90},
    "Skill_SnappingOut": {"duration_s": 8,  "difficulty": "low"},
    "Skill_DrivingOut":  {"duration_s": 30, "difficulty": "medium", "force_n": 150},
    "Skill_Separating":  {"duration_s": 40, "difficulty": "medium"},
    "Skill_CuttingOff":  {"duration_s": 60, "difficulty": "high"},
    "Skill_Desoldering": {"duration_s": 45, "difficulty": "high"},
    "Skill_Unbending":   {"duration_s": 35, "difficulty": "medium"},
    "Skill_RippingSeam": {"duration_s": 50, "difficulty": "high"},
    "Skill_CuttingOpen": {"duration_s": 40, "difficulty": "high"},
    "Skill_GrindingOff": {"duration_s": 55, "difficulty": "high"},
    "Skill_Draining":    {"duration_s": 90, "difficulty": "low"},
    "Skill_Picking":     {"duration_s": 6,  "difficulty": "low"},
}

DEFAULT_TASK = {"duration_s": 20, "difficulty": "low"}

# agent_id -> labor rate (EUR / hour)
AGENT_RATES = {
    "Agent_HumanWorker":      45.0,
    "Agent_Robot":            75.0,
    "Agent_AutomatedStation": 120.0,
}

# tool_id -> acquisition cost (EUR)
TOOL_COSTS = {
    "Tool_Tweezers":        15.0,
    "Tool_FlatScrewdriver":  8.0,
    "Tool_AllenKey5mm":      6.0,
    "Tool_PullOffTool":    120.0,
    "Tool_None":             0.0,
}

# tool_id -> usage ("deployment") cost per task use (EUR): wear, consumables and
# energy attributable to a single disassembly step. Placeholder figures — this is
# what folds into a task's cost on top of labor (see enrich_economics step 5).
TOOL_USAGE_COSTS = {
    "Tool_Tweezers":        0.01,
    "Tool_FlatScrewdriver": 0.02,
    "Tool_AllenKey5mm":     0.02,
    "Tool_PullOffTool":     0.10,
    "Tool_None":            0.0,
}


def enrich_economics(driver, product_id):
    """Apply placeholder time/cost/difficulty to one product's disassembly tasks
    and derive task cost from the performing agent's labor rate.

    Also sets agent labor rates + tool acquisition costs (shared Library nodes)
    and product-level full-teardown totals. Returns a small summary dict.
    """
    with driver.session() as s:
        # 1. Agent labor rates (shared Library)
        for aid, rate in AGENT_RATES.items():
            s.run("MATCH (a:Agent {id:$id}) SET a.labor_rate_eur_h=$r", id=aid, r=rate)
        # 2. Tool acquisition + per-use "deployment" cost (shared Library)
        for tid, cost in TOOL_COSTS.items():
            s.run("MATCH (t:Tool {id:$id}) SET t.cost_eur=$c", id=tid, c=cost)
        for tid, ucost in TOOL_USAGE_COSTS.items():
            s.run("MATCH (t:Tool {id:$id}) SET t.usage_cost_eur=$c", id=tid, c=ucost)
        # 3. Default task economics (fallback for tasks whose skill isn't mapped)
        s.run(
            "MATCH (t:DisassemblyTask {product_id:$pid}) "
            "SET t.duration_s = coalesce(t.duration_s, $d), "
            "    t.difficulty = coalesce(t.difficulty, $diff)",
            pid=product_id, d=DEFAULT_TASK["duration_s"], diff=DEFAULT_TASK["difficulty"],
        )
        # 4. Per-skill task economics (duration / difficulty / force)
        rows = [{"sid": sid, "duration_s": e["duration_s"], "difficulty": e["difficulty"],
                 "force_n": e.get("force_n")} for sid, e in SKILL_ECONOMICS.items()]
        s.run(
            "UNWIND $rows AS r "
            "MATCH (t:DisassemblyTask {product_id:$pid})-[:REQUIRES]->(sk:Skill {id:r.sid}) "
            "SET t.duration_s = r.duration_s, t.difficulty = r.difficulty, t.force_n = r.force_n",
            rows=rows, pid=product_id,
        )
        # 5. Derived task cost = labor (duration_h × agent rate) + tool usage cost.
        #    labor_cost_eur / tool_cost_eur are broken out so the chat and the
        #    node panel can explain the split; cost_eur is the total.
        s.run(
            "MATCH (t:DisassemblyTask {product_id:$pid})-[:PERFORMED_BY]->(a:Agent) "
            "WHERE t.duration_s IS NOT NULL AND a.labor_rate_eur_h IS NOT NULL "
            "OPTIONAL MATCH (t)-[:USES_TOOL]->(tl:Tool) "
            "WITH t, a, coalesce(tl.usage_cost_eur, 0.0) AS tool_use "
            "SET t.labor_cost_eur = round(100.0 * t.duration_s/3600.0 * a.labor_rate_eur_h)/100.0, "
            "    t.tool_cost_eur = round(100.0 * tool_use)/100.0, "
            "    t.cost_eur = round(100.0 * (t.duration_s/3600.0 * a.labor_rate_eur_h + tool_use))/100.0",
            pid=product_id,
        )
        # 6. Product-level full-teardown totals (break every connection once)
        rec = s.run(
            "MATCH (t:DisassemblyTask {product_id:$pid}) "
            "WITH sum(t.duration_s) AS ts, sum(coalesce(t.cost_eur,0)) AS tc, count(t) AS n "
            "MATCH (p:Product {id:$pid}) "
            "SET p.full_teardown_time_s = ts, "
            "    p.full_teardown_cost_eur = round(100.0*tc)/100.0, "
            "    p.disassembly_task_count = n "
            "RETURN ts AS ts, tc AS tc, n AS n",
            pid=product_id,
        ).single()
        return {"task_count": rec["n"], "total_time_s": rec["ts"],
                "total_cost_eur": round(rec["tc"], 2)} if rec else {}
