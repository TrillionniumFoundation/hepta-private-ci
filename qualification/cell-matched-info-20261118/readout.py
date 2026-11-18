"""Rebuild the four-arm readout from original, complete on-disk receipts."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main(originals, owned):
    freeze = read(originals / "FREEZE.json")
    identity = digest(freeze)
    require(freeze["code_commit"] == "992f2b3de51902448abf5743f94179bf40e11b6d",
            "readout belongs to the original prospective candidate")
    require(read(owned / "COMPLETE.json")["status"] == "COMPLETE", "owner incomplete")
    require(not list(owned.rglob("*FAILED.json")), "owner contains a failed stage")
    for name, expected in freeze["payloads"].items():
        require(hashlib.sha256((originals / name).read_bytes()).hexdigest() == expected,
                "frozen input changed: " + name)
    panels = read(originals / "PANELS.json")
    comparison = read(originals / "TRAINING_COMPARISON.json")
    require(comparison["status"] == "MATCHED" and comparison["freeze_digest"] == identity,
            "training comparison is not matched")
    training = {}
    for mode in ("final_only", "all_actions"):
        directory = originals / "training" / mode
        stats, manifest = read(directory / "TRAINING.json"), read(directory / "manifest.json")
        steps = [json.loads(line) for line in (directory / "STEPS.jsonl").read_bytes().splitlines()]
        require(stats["status"] == "COMPLETE" and stats["steps"] == len(steps) == 64,
                "incomplete fixed training schedule")
        require(stats["model_digest"] == digest(manifest) == comparison["arms"][mode]["model_digest"],
                "trained model identity differs")
        require(manifest["freeze_digest"] == identity, "trained model belongs to another freeze")
        checks = read(directory / "REFERENCE_RECHECKS.json")
        require(len(checks) == 6 and all(row["success"] for row in checks),
                "all training references must actually execute")
        training[mode] = stats
    modes = ("frozen", "retrieval", "final_only", "all_actions")
    results, vectors, failures = {}, {}, {}
    for mode in modes:
        directory = originals / "evaluation" / mode
        result = read(directory / "RESULT.json")
        expected_model = (freeze["base_model_digest"] if mode in modes[:2]
                          else training[mode]["model_digest"])
        require(result["status"] == "COMPLETE" and result["freeze_digest"] == identity,
                "evaluation is incomplete or belongs to another candidate")
        require(result["cost"]["model_calls"] == result["cost"]["verifier_calls"] == 24,
                "fixed evaluation budget differs")
        require(len(result["rows"]) == 12, "incomplete task denominator")
        counted = {"input_tokens": 0, "output_tokens": 0, "output_limit_hits": 0,
                   "executed_business_checks": 0, "business_successful_calls": 0}
        reasons = Counter()
        vectors[mode] = {}
        row_index = 0
        for panel, records in panels.items():
            outcomes = []
            for index, record in enumerate(records):
                row = result["rows"][row_index]
                row_index += 1
                taskdir = directory / panel / str(index)
                require(row["task_id"] == record["task_id"] and row["panel"] == panel,
                        "task order or identity differs")
                require(read(taskdir / "ORIGINAL_RECORD.json") == record,
                        "original task record differs")
                require(read(taskdir / "RESULT.json") == row, "task receipt differs")
                require(len(row["steps"]) == 2, "each task requires exactly two actual calls")
                outcomes.append({key: row[key] for key in
                                 ("task_id", "first", "last", "selected", "recovered", "regressed")})
                success = []
                for attempt, step in enumerate(row["steps"]):
                    request = read(taskdir / f"REQUEST-{attempt}.json")
                    output = read(taskdir / f"OUTPUT-{attempt}.json")
                    verified = read(taskdir / f"VERIFICATION-{attempt}.json")
                    require(digest(request) == step["request_digest"] and
                            digest(output) == step["output_digest"] and
                            verified == step["verification"], "raw call receipt differs")
                    require(output["loaded_model_digest"] == expected_model and
                            output["messages_sha256"] == digest(request["task"]["messages"]),
                            "call used a different model or visible history")
                    require(hashlib.sha256(output["answer"].encode()).hexdigest() ==
                            verified["answer_sha256"], "verification is for another answer")
                    success.append(verified["success"])
                    reasons[verified["result"].get("reason", "success" if verified["success"] else "unknown")] += 1
                    counted["executed_business_checks"] += bool(verified["result"].get("executed"))
                    counted["business_successful_calls"] += verified["success"]
                    counted["output_limit_hits"] += output["hit_output_limit"]
                    for key in ("input_tokens", "output_tokens"):
                        counted[key] += output[key]
                        require(step["model_call_cost"][key] == output[key], "call cost differs")
                first, last = success
                require((row["first"], row["last"], row["selected"], row["recovered"], row["regressed"])
                        == (first, last, first or last, not first and last, first and not last),
                        "reported outcome differs from original business verification")
            vectors[mode][panel] = outcomes
            expected = {"tasks": len(outcomes), **{key: sum(row[key] for row in outcomes)
                        for key in ("first", "last", "selected", "recovered", "regressed")}}
            require(result["by_panel"][panel] == expected, "aggregate denominator differs")
        for key in ("input_tokens", "output_tokens"):
            require(result["cost"][key] == counted[key], "aggregate token cost differs")
        results[mode] = {"by_panel": result["by_panel"], "cost": result["cost"],
                         "observed": counted}
        failures[mode] = dict(sorted(reasons.items()))
    paired = {}
    for panel in panels:
        left, right = vectors["final_only"][panel], vectors["all_actions"][panel]
        paired[panel] = {metric: {
            "all_actions_only": sum(b[metric] and not a[metric] for a, b in zip(left, right)),
            "final_only_only": sum(a[metric] and not b[metric] for a, b in zip(left, right)),
            "both": sum(a[metric] and b[metric] for a, b in zip(left, right)),
            "neither": sum(not a[metric] and not b[metric] for a, b in zip(left, right)),
        } for metric in ("first", "last", "selected")}
    stage_costs = [read(path) for path in sorted(owned.glob("*/EXIT.json"))]
    require(len(stage_costs) == 8 and all(x["wait_returncode"] == 0 and not x["timed_out"]
                                        for x in stage_costs), "eight actual stage completions required")
    return {
        "schema": "hepta.matched-information-e1-readout.v1", "status": "COMPLETE",
        "source_commit": freeze["code_commit"], "freeze_digest": identity,
        "training": training, "evaluation": results, "paired_objective_comparison": paired,
        "task_outcomes": vectors, "verification_reasons": failures,
        "candidate_cost": {
            "model_calls": 96, "evaluation_verifier_calls": 96,
            "freeze_reference_verifier_calls": 12, "training_reference_verifier_calls": 12,
            "optimizer_updates": 128,
            "stage_child_wall_seconds": sum(row["wall_seconds"] for row in stage_costs),
            "stage_child_cpu_seconds": sum(row["completed_child_user_cpu_seconds"] +
                                           row["completed_child_system_cpu_seconds"] for row in stage_costs),
            "cost_scope": "sum of disjoint child stage windows; excludes owner checkpoint IO and prior engineering",
            "nested_training_or_evaluation_costs_must_not_be_added": True,
            "full_system_cost_known": False, "energy_joules": None,
        },
        "source_scope": {"upstream_tasks": 6, "repositories": 3, "maintainer_groups": 2,
                         "independent_users": 0, "external_teachers": 0,
                         "pretraining_overlap_known": False, "B_training_allowed": False},
        "selection": "both candidate objectives fixed before B evaluation; no selection from B",
        "student_experience_scope": "actual updated-policy execution and recovery; no training on these new rollouts",
        "scientific_confirmation_qualified": False, "native_adoption": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("originals", type=Path)
    parser.add_argument("owned", type=Path)
    args = parser.parse_args()
    print(json.dumps(main(args.originals, args.owned), sort_keys=True, indent=2, allow_nan=False))
