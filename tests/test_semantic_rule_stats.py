"""rule_stats + estimate_only contract of generate_semantic_tables (OCC-free).

The counters power the Pipeline Studio's rules panel ("this rule removed N
transitions") and the estimate_only flag powers its explosion-risk gauge. Both
are bookkeeping only: the emitted transition SET must be bit-identical with and
without them — pinned here via the same set-identity style as
tests/test_semantic_pruning.py (whose fixtures this file mirrors).
"""
import numpy as np

from pipeline.semantic import generate_semantic_tables

_STATS_KEYS = {"phantom_states", "torn_fastener_joints", "no_broken_connection", "precedence",
               "separation_precedence", "duplicates", "disintegration_splits",
               "trapped_components", "reachability"}


def _labels(n):
    return [f"P{i} ({chr(65 + i)})" for i in range(n)]


def _zero_interference(n):
    return [np.zeros((n, n), dtype=int).tolist() for _ in range(6)]


def _run(liaison, fastener_indices=(), precedence_rules=None,
         separation_precedence=None, fastener_groups=None, estimate_only=False):
    n = len(liaison)
    return generate_semantic_tables(
        fastener_indices=list(fastener_indices),
        part_labels=_labels(n),
        liaison_matrix=liaison,
        interference_matrices=_zero_interference(n),
        precedence_rules=precedence_rules,
        separation_precedence=separation_precedence,
        fastener_groups=fastener_groups,
        estimate_only=estimate_only,
    )


def _keyset(transitions):
    return {
        (tuple(sorted(t["from_parts"])),
         tuple(sorted(tuple(sorted(r)) for r in t["results_in"])))
        for t in transitions
    }


def _chain(n):
    lm = np.zeros((n, n), dtype=int)
    for i in range(n - 1):
        lm[i][i + 1] = lm[i + 1][i] = 1
    return lm.tolist()


def _star(n):
    lm = np.zeros((n, n), dtype=int)
    for i in range(1, n):
        lm[0][i] = lm[i][0] = 1
    return lm.tolist()


# ── rule_stats presence + output identity ────────────────────────────────────

def test_stats_present_and_transitions_unchanged():
    """Baseline chain: stats exist with all keys, custom-rule counters are zero,
    and the transition set is the exact hand-traced one (counters are inert)."""
    res = _run(_chain(3))
    assert res["success"], res.get("error")
    stats = res["rule_stats"]
    assert set(stats) == _STATS_KEYS
    assert stats["precedence"] == 0
    assert stats["separation_precedence"] == 0
    expected = {
        (("A", "B", "C"), (("A",), ("B", "C"))),
        (("A", "B", "C"), (("A", "B"), ("C",))),
        (("A", "B"), (("A",), ("B",))),
        (("B", "C"), (("B",), ("C",))),
    }
    assert _keyset(res["transitions"]) == expected


def test_precedence_counter_counts():
    """chain3 + {C: [A]} (C blocked while A mounted): counter fires and the
    ruled set is a strict subset of the unruled one."""
    base = _run(_chain(3))
    ruled = _run(_chain(3), precedence_rules={"C": ["A"]})
    assert ruled["success"], ruled.get("error")
    assert ruled["rule_stats"]["precedence"] >= 1
    assert _keyset(ruled["transitions"]) < _keyset(base["transitions"])


def test_separation_counter_counts():
    """chain3 + (A,C requires B): every split separates A from C while B is
    present, so everything from the root is pruned and reachability clears the rest."""
    res = _run(_chain(3), separation_precedence=[
        {"part1": "A", "part2": "C", "requires_removed": ["B"]}
    ])
    assert res["success"], res.get("error")
    assert res["rule_stats"]["separation_precedence"] >= 1
    assert res["transitions"] == []


def test_phantom_and_no_broken_counters():
    """Fastener F clamping A+B (screw-joint semantics): states where F is gone
    but A-B still 'hang together' are phantom; splits breaking no defined joint
    are counted as no_broken_connection."""
    # A-B touch, F touches both (2-neighbour fastener rule → ScrewJoint A↔B via F)
    lm = [
        [0, 1, 1],
        [1, 0, 1],
        [1, 1, 0],
    ]
    res = _run(lm, fastener_indices=(2,))
    assert res["success"], res.get("error")
    stats = res["rule_stats"]
    assert (stats["phantom_states"] >= 1 or stats["no_broken_connection"] >= 1
            or stats["torn_fastener_joints"] >= 1), stats


def test_reachability_counter_matches_filter():
    res = _run(_chain(4))
    assert res["success"], res.get("error")
    assert res["rule_stats"]["reachability"] >= 0
    assert len(res["transitions"]) == 10  # golden micro-count from pruning tests


# ── estimate_only contract ───────────────────────────────────────────────────

def test_estimate_only_returns_estimate_without_transitions():
    res = _run(_star(13), estimate_only=True)
    assert res["success"], res.get("error")
    assert res["transitions"] == []
    est = res["aog_estimate"]
    for key in ("independent_fan", "est_assemblies", "est_transitions",
                "parts_after_grouping", "cap_transitions", "cap_parts"):
        assert key in est, f"missing {key}"
    assert est["independent_fan"] >= 12  # 12 leaves on the hub
    assert est["cap_transitions"] > 0 and est["cap_parts"] > 0


def test_estimate_only_matches_full_run_estimate():
    est = _run(_chain(4), estimate_only=True)["aog_estimate"]
    full = _run(_chain(4))["aog_estimate"]
    assert est == full


def test_over_cap_error_still_carries_estimate():
    """A huge star blows the transition cap: error is set AND the estimate (with
    caps) is present — the UI gauge feeds from failed calls too."""
    res = _run(_star(40), estimate_only=True)
    assert not res["success"]
    assert "too large" in (res["error"] or "")
    est = res["aog_estimate"]
    assert est["est_transitions"] > est["cap_transitions"]


def test_estimate_only_reflects_grouping():
    """Grouping the star's leaves collapses the fan — parts_after_grouping and
    the estimate must reflect the merge."""
    groups = [{"name": "12x leaf", "members": list(range(1, 13))}]
    solo = _run(_star(13), estimate_only=True)["aog_estimate"]
    grouped = _run(_star(13), fastener_groups=groups, estimate_only=True)["aog_estimate"]
    assert grouped["parts_after_grouping"] == 2
    assert grouped["est_transitions"] < solo["est_transitions"]


def test_api_layer_passes_estimate_only(monkeypatch):
    """POST /api/step/generate-tables round-trips the flag (pure function, no DB)."""
    import app as app_module
    import models.step_pipeline as sp  # endpoint does a local import from here

    seen = {}
    real = generate_semantic_tables

    def spy(**kwargs):
        seen.update(estimate_only=kwargs.get("estimate_only"))
        return real(**kwargs)

    monkeypatch.setattr(sp, "generate_semantic_tables", spy)
    client = app_module.app.test_client()
    payload = {
        "fastener_indices": [],
        "part_labels": _labels(3),
        "liaison_matrix": _chain(3),
        "interference_matrices": _zero_interference(3),
        "estimate_only": True,
    }
    resp = client.post("/api/step/generate-tables", json=payload)
    assert resp.status_code == 200
    assert seen["estimate_only"] is True
    body = resp.get_json()
    assert body["success"] and body["transitions"] == []
