"""Independent stdlib replay of saved v8 mechanism outcomes and factorials.

This imports neither the campaign aggregation nor the scientific model. It
checks actual recorded predictions against source worlds, fixed-action pairings,
declared count transformations, and independently recomputed task fees.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(run, repo):
    plan = json.loads((run / "PLAN.json").read_text())
    frozen = json.loads((run / "evaluation/FROZEN_INPUTS.json").read_text())
    complete = json.loads((run / "evaluation/COMPLETE.json").read_text())
    summary = json.loads((run / "SUMMARY.json").read_text())
    failures, check_count = [], 0

    def check(condition, name):
        nonlocal check_count
        check_count += 1
        if not condition and len(failures) < 100:
            failures.append(name)

    def close(left, right, name, tolerance=1e-10):
        check(math.isfinite(left) and math.isfinite(right) and abs(left - right) <= tolerance, name)

    check(sha(run / "PLAN.json") == frozen["plan_sha256"], "frozen plan hash")
    check(sha(run / "evaluation/runs.jsonl.gz") == complete["raw_sha256"], "raw outcomes hash")
    check(sha(run / "evaluation/worlds.jsonl.gz") == complete["worlds_sha256"], "worlds hash")
    for relative, digest in plan["source_sha256"].items():
        path = repo / relative
        if relative.startswith("legacy/"):
            path = repo / relative[7:]
            if not path.is_file():
                path = repo / "recovered/v3" / relative[7:]
        check(path.is_file() and sha(path) == digest, "frozen source " + relative)
    for seed in plan["fit_seeds"]:
        fit = run / f"fit_{seed}"
        report = json.loads((fit / "FIT.json").read_text())
        check(sha(fit / "models.pt") == frozen["models"][str(seed)] == report["models_sha256"], f"model hash {seed}")
        check(sha(fit / "sampled_data.npz") == report["sampled_data_sha256"], f"training data hash {seed}")
        selection = min(plan["ordinary_families"], key=lambda f: (report["reports"][f]["validation_nll"], f))
        check(selection == frozen["selected"][str(seed)] == report["selected_family"], f"validation selection {seed}")
    with gzip.open(run / "evaluation/worlds.jsonl.gz", "rt") as stream:
        world_rows = [json.loads(line) for line in stream]
    worlds = {(r["condition"], r["index"]): r["episode"] for r in world_rows}
    n = plan["episodes_per_condition"]
    check(len(world_rows) == len(worlds) == n * len(plan["conditions"]), "world count and uniqueness")
    check(len({w["seed"] for w in worlds.values()}) == len(worlds), "distinct world seeds")
    expected, recorded = set(), {}
    for condition in plan["conditions"]:
        for index in range(n):
            for arm in ("C", "D", "mean_two_point_closed", "mean_two_point_fixed_D", "single_transition_closed", "single_transition_fixed_D"):
                expected.add((condition, index, arm, None, None))
            for seed in plan["fit_seeds"]:
                for family in plan["ordinary_families"]:
                    for arm in ("A", "B", "ordinary_fixed_D"):
                        expected.add((condition, index, arm, seed, family))
    output_count = 0
    with gzip.open(run / "evaluation/runs.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            key = tuple(row[k] for k in ("condition", "index", "arm", "fit_seed", "family"))
            check(key not in recorded, "unique run " + str(key))
            world = worlds[key[:2]]
            check(row["world_seed"] == world["seed"], "paired world " + str(key))
            check([p["tick"] for p in row["predictions"]] == plan["config"]["deadlines"], "mandatory outputs " + str(key))
            actions = {r["tick"]: r["executed_action"] for r in row["trace"]}
            reads = sum(a == "READ" for a in actions.values())
            check(reads == len(row["access"]) == row["summary"]["reads"], "charged revealed reads " + str(key))
            check(reads <= plan["config"]["budget"], "read budget " + str(key))
            check(all(r["reveal_tick"] == r["request_tick"] + 1 and actions.get(r["request_tick"]) == "READ"
                      for r in row["access"]), "read chronology " + str(key))
            recomputed = {"accuracy": [], "nll": [], "brier": []}
            for prediction in row["predictions"]:
                output_count += 1
                tick, probs = prediction["tick"], prediction["probabilities"]
                truth = world["path"]["content"][tick]
                check(truth == prediction["truth_for_scoring_only"], "scoring truth " + str(key))
                close(sum(probs), 1.0, "normalized class probabilities " + str(key))
                check(all(math.isfinite(x) and x >= 0 for x in probs), "valid class law " + str(key))
                available = [r for r in row["access"] if r["reveal_tick"] <= tick]
                obs = available[-1]["observed_state"] if available else {
                    "time": 0.0, "x": world["initial_x"], "refractory_remaining": 0.0,
                    "content_probs": [1 / plan["config"]["classes"]] * plan["config"]["classes"], "has_read": False}
                check(obs == prediction["observed_state"], "latest causal observation " + str(key))
                counts = prediction["count_probabilities"]
                close(sum(counts), 1.0, "normalized count law " + str(key))
                check(all(math.isfinite(x) and x >= 0 for x in counts), "valid count law " + str(key))
                close(sum(i * p for i, p in enumerate(counts)), prediction["expected_events"], "count mean " + str(key))
                z, propagated = list(obs["content_probs"]), [0.0] * len(probs)
                for probability in counts:
                    propagated = [a + probability * b for a, b in zip(propagated, z)]
                    z = [.15 * z[j] + .55 * z[(j - 1) % len(z)] + .30 * z[(j + 1) % len(z)] for j in range(len(z))]
                for actual, target in zip(probs, propagated):
                    close(actual, target, "independent content propagation " + str(key))
                metrics = {"accuracy": int(max(range(len(probs)), key=probs.__getitem__) == truth),
                           "nll": -math.log(max(probs[truth], 1e-12)),
                           "brier": sum((p - int(i == truth)) ** 2 for i, p in enumerate(probs))}
                for name, value in metrics.items():
                    close(value, prediction["correct" if name == "accuracy" else name], "output metric " + str(key))
                    recomputed[name].append(value)
            metrics = {k: fmean(v) for k, v in recomputed.items()}
            metrics["net_reward"] = metrics["accuracy"] - reads * plan["config"]["read_cost"]
            for name, value in metrics.items():
                close(value, row["summary"][name], "summary metric " + str(key))
            recorded[key] = {"metrics": metrics, "actions": actions, "predictions": row["predictions"]}
    check(set(recorded) == expected and len(recorded) == complete["runs"], "complete factorial identity set")
    contrasts = {}
    for condition in plan["conditions"]:
        chosen = []
        for seed in plan["fit_seeds"]:
            family_results = {}
            for family in plan["ordinary_families"]:
                means = {arm: fmean(recorded[(condition, i, arm, seed if arm in ("A", "B", "ordinary_fixed_D") else None,
                                                  family if arm in ("A", "B", "ordinary_fixed_D") else None)]["metrics"]["net_reward"]
                                    for i in range(n)) for arm in ("A", "B", "C", "D", "ordinary_fixed_D")}
                means.update({"B-A": means["B"] - means["A"], "D-C": means["D"] - means["C"],
                              "C-A": means["C"] - means["A"], "D-B": means["D"] - means["B"],
                              "interaction": means["D"] - means["C"] - means["B"] + means["A"]})
                for name, value in means.items():
                    close(value, summary["conditions"][condition]["all_fit_results"][str(seed)][family][name], "factorial " + str((condition, seed, family, name)))
                family_results[family] = means
            chosen.append(family_results[frozen["selected"][str(seed)]])
        contrasts[condition] = {key: fmean(r[key] for r in chosen) for key in chosen[0]}
        for key, value in contrasts[condition].items():
            close(value, summary["conditions"][condition]["validation_selected_ordinary_mean_contrasts"][key], "chosen factorial " + condition + key)
        for index in range(n):
            reference = recorded[(condition, index, "D", None, None)]
            for intervention in plan["interventions"]:
                altered = recorded[(condition, index, intervention + "_fixed_D", None, None)]
                check(altered["actions"] == reference["actions"], "fixed action identity " + str((condition, index, intervention)))
                for original, changed in zip(reference["predictions"], altered["predictions"]):
                    check(original["observed_state"] == changed["observed_state"], "fixed observation identity")
                    p, q = original["count_probabilities"], changed["count_probabilities"]
                    target = [0.0] * len(p)
                    if intervention == "single_transition":
                        target[0], target[1] = p[0], 1 - p[0]
                    else:
                        mean = sum(i * x for i, x in enumerate(p))
                        lower = min(math.floor(mean), len(p) - 1)
                        target[lower] = 1.0 if lower == len(p) - 1 else lower + 1 - mean
                        if lower < len(p) - 1:
                            target[lower + 1] = mean - lower
                    for actual, expected_probability in zip(q, target):
                        close(actual, expected_probability, "actual single-factor count intervention")
    return {"schema": "hcsn-v8-independent-outcome-audit.v1", "checks": check_count,
            "failed_check_examples": failures, "all_checks_passed": not failures,
            "worlds": len(worlds), "runs": len(recorded), "outputs": output_count,
            "independently_recomputed_contrasts": contrasts, "source": str(run),
            "raw_sha256": complete["raw_sha256"], "scientific_confirmation": False,
            "limitations": ["Synthetic known-renewal worlds; no real AV confirmation.",
                            "Five ordinary fits reuse the same 24 worlds per condition; D/C are not five independent analytic fits.",
                            "A/C share a confidence-triggered rule, not an identical fixed observation schedule.",
                            "No device energy or complete deployment-family memory; no candidate economic superiority."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run.resolve(), args.repo.resolve())
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("checks", "all_checks_passed", "worlds", "runs", "outputs")}))
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
