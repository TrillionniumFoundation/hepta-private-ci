"""Independent standard-library replay of frozen V9 service-task records.

This does not import the producer, model libraries, or the original aggregator.
It verifies observed causal transitions and record arithmetic, not the simulator's
financial law, model training, or optimality of the one-read controller.
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def audit(repo, directory):
    checks, failures = 0, []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 30:
            failures.append(label)

    def close(a, b):
        return math.isclose(a, b, abs_tol=2e-10, rel_tol=2e-10)

    plan = json.loads((directory / "PLAN.json").read_text())
    freeze = json.loads((directory / "EVALUATION_FREEZE.json").read_text())
    complete = json.loads((directory / "COMPLETE.json").read_text())
    fits = json.loads((directory / "ANALYTIC_FITS.json").read_text())
    for name, key in (("PLAN.json", "plan_sha256"), ("ANALYTIC_FITS.json", "fit_sha256"),
                      ("SERVICE_FIT.json", "service_sha256")):
        check(digest(directory / name) == freeze[key], "evaluation frozen identity: " + name)
    for path, sha in {**plan["source_sha256"], **plan["historical_assets"]}.items():
        check(digest(repo / path) == sha, "frozen source or historical input: " + path)
    for seed, modes in fits.items():
        for mode, record in modes.items():
            selected = min(record["candidates"], key=lambda r: (r["train_nll"], r["drift_scale"]))
            check(record["selected_scale"] == selected["drift_scale"], "training-only selection " + seed + mode)
    for path, key in (("runs.jsonl.gz", "raw_sha256"), ("worlds.jsonl.gz", "worlds_sha256")):
        check(digest(directory / path) == complete[key], "complete raw hash: " + path)
    worlds = {(r["condition"], r["index"]): r["episode"] for r in read_rows(directory / "worlds.jsonl.gz")}
    runs = read_rows(directory / "runs.jsonl.gz")
    check(len(worlds) == complete["worlds"] == 24, "complete world count")
    check(len(runs) == complete["runs"] == 2040, "complete run count")
    index = {}
    counts = defaultdict(int)
    for run in runs:
        identity = tuple(run[k] for k in ("condition", "index", "family", "fit_seed", "mode", "controller", "risk", "fixed"))
        check(identity not in index, "duplicate run identity")
        index[identity] = run
        condition, world_index = run["condition"], run["index"]
        world = worlds[condition, world_index]
        counts[condition, world_index] += 1
        trace = run["trace"]
        read_ticks = [r["tick"] for r in trace if r["action"] == "READ"]
        check(len(read_ticks) <= plan["config"]["budget"], "read budget")
        check([r["arrival_tick"] for r in run["access"]] == [t + 1 for t in read_ticks], "issued read arrival inventory")
        successful = {}
        for access in run["access"]:
            t = access["arrival_tick"]
            expected = world["service_uniform"][t] < .9 - .7*t/20
            check(access["success"] == expected, "actual service law")
            check(close(access["fee_charged"], plan["config"]["read_cost"]), "failed and successful read fees")
            if expected:
                successful[t] = {
                    "time": t * plan["config"]["dt"], "x": world["path"]["x"][t],
                    "refractory_remaining": world["path"]["refractory_remaining"][t],
                    "content_probs": [float(k == world["path"]["content"][t]) for k in range(5)], "has_read": True,
                }
        initial = {"time": 0., "x": world["initial_x"], "refractory_remaining": 0.,
                   "content_probs": [.2]*5, "has_read": False}

        def expected_obs(t):
            history = [v for key, v in sorted(successful.items()) if key <= t]
            return history[-1] if history else initial

        for access in run["access"]:
            check(access["observed_state_after"] == expected_obs(access["arrival_tick"]), "causal observation after service")
        for step in trace:
            check(step["observation"] == expected_obs(step["tick"]), "causal controller observation")
        check([r["tick"] for r in run["predictions"]] == plan["config"]["deadlines"], "mandatory outputs after STOP")
        for prediction in run["predictions"]:
            t = prediction["tick"]
            check(prediction["observed_state"] == expected_obs(t), "causal output observation")
            p, z = [0.]*5, expected_obs(t)["content_probs"]
            cp = prediction["count_probabilities"]
            check(close(sum(cp), 1.) and min(cp) >= 0., "count distribution")
            for weight in cp:
                p = [a + weight*b for a, b in zip(p, z)]
                z = [.15*z[j] + .55*z[(j-1) % 5] + .30*z[(j+1) % 5] for j in range(5)]
            check(all(close(a, b) for a, b in zip(p, prediction["probabilities"])), "independent count-to-content propagation")
            truth = world["path"]["content"][t]
            check(prediction["truth_for_scoring_only"] == truth, "scoring truth")
            recorded = prediction["probabilities"]
            check(prediction["correct"] == int(max(range(5), key=recorded.__getitem__) == truth), "actual scored prediction")
        accuracy = statistics.mean(r["correct"] for r in run["predictions"])
        summary = run["summary"]
        fee = len(read_ticks)*plan["config"]["read_cost"]
        check(summary["reads"] == len(read_ticks), "issued read count")
        check(close(summary["accuracy"], accuracy), "output accuracy")
        check(close(summary["read_fees"], fee), "charged read fees")
        check(close(summary["net_reward"], accuracy-fee), "net utility")
        if run["fixed"]:
            ref_key = (condition, world_index, "analytic", run["fit_seed"], "original", "task_value", True, False)
            reference = index.get(ref_key)
            check(reference is not None, "original D reference precedes fixed schedule")
            if reference is not None:
                check([(r["tick"], r["action"]) for r in trace] ==
                      [(r["tick"], r["action"]) for r in reference["trace"]], "exact fixed D action schedule")
    check(set(counts.values()) == {85}, "complete 85-run inventory in every world")
    contrasts = {}
    for condition in plan["conditions"]:
        for risk in (True, False):
            cells = defaultdict(list)
            for world_index in range(plan["worlds_per_condition"]):
                ordinary, analytic = defaultdict(list), defaultdict(list)
                for row in runs:
                    if (row["condition"], row["index"], row["risk"], row["fixed"]) != (condition, world_index, risk, False):
                        continue
                    if row["family"] == "analytic" and row["mode"] == "original":
                        analytic[row["controller"]].append(row["summary"]["net_reward"])
                    elif row["family"] == freeze["ordinary_selections"].get(row["fit_seed"]):
                        ordinary[row["controller"]].append(row["summary"]["net_reward"])
                for name, group, controller in (("A", ordinary, "lightweight"), ("B", ordinary, "task_value"),
                                                 ("C", analytic, "lightweight"), ("D", analytic, "task_value")):
                    check(len(group[controller]) == (3 if name in "CD" else 5), "all preselected fit replicates")
                    cells[name].append(statistics.mean(group[controller]))
            means = {k: statistics.mean(v) for k, v in cells.items()}
            means["D-B"] = statistics.mean(d-b for d, b in zip(cells["D"], cells["B"]))
            means["world_count"] = len(cells["D"])
            contrasts[condition + "/risk=" + str(risk)] = means
    replay = read_rows(directory / "fixed_risk_replay.jsonl.gz")
    replay_freeze = json.loads((directory / "FIXED_RISK_FREEZE.json").read_text())
    replay_complete = json.loads((directory / "FIXED_RISK_COMPLETE.json").read_text())
    check(digest(repo / "experiments/hcsn_v9_followup_20261101/mechanisms/fixed_risk_replay.py") == replay_freeze["source_sha256"], "fixed-risk replay source")
    check(digest(directory / "runs.jsonl.gz") == replay_freeze["runs_sha256"], "fixed-risk frozen main runs")
    check(digest(directory / "worlds.jsonl.gz") == replay_freeze["worlds_sha256"], "fixed-risk frozen worlds")
    check(digest(directory / "fixed_risk_replay.jsonl.gz") == replay_complete["raw_sha256"], "fixed-risk raw bytes")
    check(len(replay) == replay_complete["replayed_runs"] == 72, "complete fixed-risk inventory")
    for row in replay:
        reference = index[row["condition"], row["index"], "analytic", row["fit_seed"], "original", "task_value", True, False]
        check(row["predictions"] == reference["predictions"], "fixed-risk exact output probabilities")
        check(row["access"] == reference["access"], "fixed-risk exact actual access")
        check([(r["tick"], r["action"]) for r in row["trace"]] == [(r["tick"], r["action"]) for r in reference["trace"]], "fixed-risk exact actions")
        check(all(row["summary"][k] == reference["summary"][k] for k in ("accuracy", "reads", "read_fees", "net_reward")), "fixed-risk exact fees and reward")
    return {"schema": "hcsn-v9-independent-raw-review.v1", "checks": checks,
            "all_checks_passed": not failures, "failed_examples": failures, "worlds": len(worlds), "runs": len(runs),
            "contrasts": contrasts, "fixed_risk_replays": len(replay),
            "scope": "Frozen record semantics and world-paired point estimates only; no acceptance or optimality claim"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.repo, args.directory)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
