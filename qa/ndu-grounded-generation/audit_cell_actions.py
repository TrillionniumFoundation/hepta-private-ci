"""Post-hoc, fail-closed token-action audit of the immutable negative NDU v1 test.

This is *not* a Cell causal-effect estimator. It reads the original, SHA256-pinned
journal but never reruns frozen model inference or revises pre-registered scores.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

ORIGINAL_JOURNAL_SHA256 = "b9e7e0a53622b9b87e29507684684389aaf798e97bf53b0d4e93f44570786e39"
METHODS = frozenset((
    "base", "static_cells", "learned_router", "best_of_n", "mean_only",
    "risk_actor_critic", "ndu", "ablate_covariance", "ablate_fixed_weights",
    "ablate_crossmodal", "ablate_missing_modality", "ablate_shuffled_pair",
))
ACTIONS = (
    ("no_cell", (0., 0., 0., 0.)),
    ("four_cell_average", (.25, .25, .25, .25)),
    ("vocab_cell", (1., 0., 0., 0.)),
    ("horizontal_cell", (0., 1., 0., 0.)),
    ("vertical_cell", (0., 0., 1., 0.)),
    ("stop_cell", (0., 0., 0., 1.)),
)


def _must(condition, description):
    if not condition:
        raise ValueError(description)


def _finite_float(value):
    return type(value) in (int, float) and math.isfinite(value)


def audit_rows(rows, expected_sources=64):
    """Require a complete paired method roster before reporting post-hoc counts."""
    _must(type(expected_sources) is int and expected_sources > 0, "invalid source count")
    _must(type(rows) is list and len(rows) == expected_sources * len(METHODS), "incomplete 12-method roster")
    by_task = {}
    for row in rows:
        _must(isinstance(row, dict), "invalid episode row")
        task, method = row.get("task_id"), row.get("method")
        _must(isinstance(task, str) and task, "invalid task ID")
        _must(method in METHODS, "unregistered method")
        _must(row.get("seed") == 23 and type(row.get("seed")) is int, "mismatched decoder seed")
        _must(row.get("split") == "test", "non-test episode")
        _must(row.get("budget_cap") == 10.0 and row.get("budget_unit") == "wall_seconds", "modified budget")
        score = row.get("score")
        _must(isinstance(score, dict) and _finite_float(score.get("quality"))
              and 0. <= score["quality"] <= 1., "invalid quality")
        _must(score.get("task_id") == task and score.get("method") == method, "score identity mismatch")
        controls = row.get("controls")
        _must(isinstance(controls, list), "missing token controls")
        entry = by_task.setdefault(task, {})
        _must(method not in entry, "duplicate method for task")
        entry[method] = row
    _must(len(by_task) == expected_sources, "unexpected source groups")
    _must(all(set(methods) == METHODS for methods in by_task.values()), "missing comparison arm")
    out = {
        "schema": "hepta.ndu-v1-posthoc-cell-action-audit.v1",
        "audit_scope": "pinned historical token logs; observed local argmax switches only",
        "scientific_authorization": False,
        "observed_method_roster": len(METHODS),
        "observed_source_count": len(by_task),
        "observed_test_rows": len(rows),
    }
    steps = {name: 0 for name, _ in ACTIONS}
    switches = {name: 0 for name, _ in ACTIONS}
    touched_sources = {name: set() for name, _ in ACTIONS}
    decision_histogram = Counter()
    total_decisions = 0
    equal_completed = 0
    paired_completed = 0
    incomplete_count = 0
    for task, methods in by_task.items():
        ndu, mean = methods["ndu"], methods["mean_only"]
        completed = ndu.get("termination") == "completed"
        if completed and mean.get("termination") == "completed":
            paired_completed += 1
            equal_completed += (ndu["score"]["quality"] == mean["score"]["quality"])
        else:
            incomplete_count += 1
        decisions = 0
        for control in ndu["controls"]:
            _must(isinstance(control, dict), "malformed NDU control")
            action = control.get("action")
            applied = control.get("modifier_applied")
            changed = control.get("argmax_changed")
            _must(type(applied) is bool and type(changed) is bool, "non-boolean control receipt")
            _must(type(control.get("checkpoint_changed")) is bool, "invalid checkpoint receipt")
            _must(type(control.get("base_argmax")) is int
                  and type(control.get("controlled_argmax")) is int, "missing token IDs")
            _must(changed == (control["base_argmax"] != control["controlled_argmax"]),
                  "argmax identity flag mismatch")
            if control["checkpoint_changed"]:
                _must(type(action) is int and 0 <= action < len(ACTIONS), "unregistered control decision")
                decisions += 1
            if applied:
                _must(type(action) is int and 0 <= action < len(ACTIONS), "unregistered applied action")
                _must(isinstance(control.get("weights"), list), "no Cell weight vector")
                _must(tuple(control["weights"]) == ACTIONS[action][1], "action/weights mismatch")
                name = ACTIONS[action][0]
                steps[name] += 1
                switches[name] += int(changed)
                touched_sources[name].add(task)
            else:
                _must(not changed, "changed token without registered modifier")
        _must(0 <= decisions <= 8, "decision count exceeds registered cap")
        decision_histogram[decisions] += 1
        total_decisions += decisions
    out.update({
        "ndu_decisions_total": total_decisions,
        "ndu_decisions_per_episode_histogram": {str(k): v for k, v in sorted(decision_histogram.items())},
        "ndu_modifier_applied_steps": sum(steps.values()),
        "actions": {name: {"token_steps": steps[name], "argmax_changes": switches[name],
                            "source_episodes_exposed": len(touched_sources[name])}
                    for name, _ in ACTIONS},
        "ndu_mean_only_jointly_completed": paired_completed,
        "ndu_mean_only_equal_quality_on_completed": equal_completed,
        "ndu_mean_only_not_jointly_completed": incomplete_count,
        "all_four_individual_cells_changed_argmax": all(switches[name] > 0 for name in
            ("vocab_cell", "horizontal_cell", "vertical_cell", "stop_cell")),
        "independent_per_cell_terminal_contribution_proven": False,
        "four_cell_cooperation_or_synergy_proven": False,
        "long_horizon_8_to_16_decisions_proven": False,
    })
    return out


def audit_pinned_journal(path):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    _must(digest == ORIGINAL_JOURNAL_SHA256, "journal SHA256 is not the original frozen v1 test")
    # Decode only after matching pinned historical original bytes.
    lines = raw.decode("utf-8").splitlines()
    _must(len(lines) == 768, "unexpected row count")
    result = audit_rows([json.loads(line) for line in lines])
    result["source_sha256"] = digest
    result["source_provenance"] = "original frozen 2026-10-22 v1 test journal"
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--journal", required=True, help="original frozen raw/test.episodes.jsonl")
    ap.add_argument("--output", required=True, help="write a NEW supplemental receipt, never overwrite v1")
    args = ap.parse_args()
    target = Path(args.output)
    if target.exists():
        ap.error("refusing to overwrite an existing receipt")
    if target.resolve() == Path(args.journal).resolve():
        ap.error("output cannot overwrite frozen journal")
    result = audit_pinned_journal(args.journal)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"source_sha256": result["source_sha256"],
                      "ndu_decisions_total": result["ndu_decisions_total"],
                      "scientific_authorization": False}, sort_keys=True))


if __name__ == "__main__":
    main()
