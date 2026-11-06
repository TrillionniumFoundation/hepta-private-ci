"""Read-only Bellman decomposition of the already frozen 144-cell study."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..ndu_learned_stateful.model import Kernel, Policy, Task, quality

ROOT = Path(__file__).parent
OLD = ROOT.parent / "ndu_learned_stateful"
RESULT_SHA = "5e3c479a257da5776219227690cdaeef03ee7fb33ee3b0a8c8f69040f1f9d221"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decompose(kernel, task):
    policy = Policy(kernel, task)
    rows = [{"choice": [-1, 0], "one_step": .275, "continuation_lift": 0., "two_step": .275}]
    for action in range(2):
        for cap in range(1, task.deadline + 1):
            immediate, lift = -task.fee, 0.
            for event, p0, p1 in kernel.events(0, action, cap):
                mass = (p0 + p1) / 2
                if not mass:
                    continue
                belief = policy.update(.5, 0, action, cap, event)
                stop = quality(event[2]) * max(belief, 1 - belief)
                immediate += mass * (stop - task.time_price * event[1])
                future = policy.solve(belief, event[2], task.deadline - event[1], 1)[0]
                lift += mass * (future - stop)
            assert lift >= -1e-12
            rows.append({"choice": [action, cap], "one_step": immediate,
                         "continuation_lift": lift, "two_step": immediate + lift})
    assert abs(max(r["two_step"] for r in rows) - policy.solve(.5, 0, task.deadline, 2)[0]) < 1e-12
    return rows


def diagnose():
    source = OLD / "evidence/registered_v1/results.json"
    if not source.exists():
        from ..ndu_learned_stateful.materialize import materialize
        materialize()
    assert digest(source) == RESULT_SHA
    frozen = json.loads((OLD / "freeze.json").read_text())["source_sha256"]
    assert {name: digest(OLD / name) for name in frozen} == frozen
    old = json.loads(source.read_text())
    fitted = {(b["world"], b["seed"], b["n_per_row"]): Kernel(b["estimated_kernel"])
              for b in old["learning"]}
    summary, comparisons, cases = Counter(), Counter(), []
    maximum_identity_error = 0.
    for case in old["cases"]:
        key = tuple(case[k] for k in ("world", "seed", "n_per_row"))
        task = Task(case["deadline"], case["fee"], .02, 2)
        rows = decompose(fitted[key], task)
        recorded = {p["policy"]: p for p in case["policies"]}
        full, greedy = recorded["plugin_dp"], recorded["myopic"]
        selected = [next(r for r in rows if r["choice"] == p["initial_action"]) for p in (full, greedy)]
        for row, p in zip(selected, (full, greedy)):
            error = abs(row["two_step"] - p["exact_fitted"]["utility"])
            maximum_identity_error = max(maximum_identity_error, error)
            assert error < 1e-12
        if case["deadline"] <= 1:
            group = "at_most_one_effective_query"
            assert max(r["continuation_lift"] for r in rows) < 1e-12
        elif full["initial_action"][0] == greedy["initial_action"][0] == -1:
            group = "long_deadline_both_stop"
        elif full["initial_action"] == greedy["initial_action"]:
            group = "long_deadline_same_first_action"
        else:
            group = "long_deadline_different_first_action"
        summary[group] += 1
        true_gap = full["exact_true"]["utility"] - greedy["exact_true"]["utility"]
        comparisons["win" if true_gap > 1e-12 else "loss" if true_gap < -1e-12 else "tie"] += 1
        fitted_gain = selected[0]["two_step"] - selected[1]["two_step"]
        assert fitted_gain >= -1e-12
        cases.append({**{k: case[k] for k in ("world", "seed", "n_per_row", "deadline", "fee")},
                      "group": group, "dp_choice": full["initial_action"], "myopic_choice": greedy["initial_action"],
                      "fitted_gain_from_lookahead_choice": fitted_gain, "true_gain": true_gap,
                      "maximum_lift": max(r["continuation_lift"] for r in rows), "action_decomposition": rows})
    assert digest(source) == RESULT_SHA
    assert {name: digest(OLD / name) for name in frozen} == frozen
    return {"schema": "ndu.decision-diagnosis.v1", "at_utc": datetime.now(timezone.utc).isoformat(),
            "source_sha256": digest(Path(__file__)), "frozen_scientific_sources": frozen,
            "original_result_sha256": RESULT_SHA, "cases": cases, "groups": dict(summary),
            "wins_ties_losses": {k: comparisons[k] for k in ("win", "tie", "loss")},
            "maximum_bellman_identity_error": maximum_identity_error, "old_sources_and_results_unchanged": True,
            "scope": "Post-result analytic diagnosis of existing frozen data. No new calibration, confirmation, task selection or scientific endpoint change."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"groups": report["groups"], "wins_ties_losses": report["wins_ties_losses"],
                      "maximum_bellman_identity_error": report["maximum_bellman_identity_error"]}))
