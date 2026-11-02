"""Standard-library independent posterior/clock/seal replay of V10 AV logs.

No fitter, producer, Torch, NumPy, or SciPy import is used. Full latent paths
are enumerated from sealed law parameters, with a separately implemented
Poisson-series transition and log likelihood. This audits the declared finite
law, not its adequacy for the real recording population.
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transition(q):
    k = len(q)
    rate = max(-q[i][i] for i in range(k))
    identity = [[float(i == j) for j in range(k)] for i in range(k)]
    if not rate:
        return identity
    kernel = [[identity[i][j] + q[i][j]/rate for j in range(k)] for i in range(k)]
    power, weight = identity, math.exp(-rate)
    total = [[weight*v for v in row] for row in power]
    mass = weight
    for order in range(1, 1000):
        power = [[math.fsum(power[i][m]*kernel[m][j] for m in range(k)) for j in range(k)] for i in range(k)]
        weight *= rate/order
        mass += weight
        total = [[total[i][j] + weight*power[i][j] for j in range(k)] for i in range(k)]
        if order > 2*rate and weight < 2e-17:
            return total
    raise ArithmeticError("Independent Poisson sum failed")


def posterior(law, matrix, time, observations):
    k, likelihoods = len(law["prior"]), []
    for source, modality, value in observations:
        scores = []
        for mean, variance in zip(law["mean"][modality], law["variance"][modality]):
            scores.append(-.5*math.fsum(math.log(2*math.pi*v)+(x-m)**2/v for x, m, v in zip(value, mean, variance)))
        likelihoods.append((source, scores))
    log_weights = []
    for path in itertools.product(range(k), repeat=time+1):
        score = math.log(law["prior"][path[0]])
        score += math.fsum(math.log(matrix[a][b]) for a, b in zip(path[:-1], path[1:]))
        score += math.fsum(scores[path[source]] for source, scores in likelihoods)
        log_weights.append(score)
    offset = max(log_weights)
    weights = [math.exp(value-offset) for value in log_weights]
    normalizer = math.fsum(weights)
    return [value/normalizer for value in weights]


def audit(directory):
    checks, failures = 0, []

    def check(ok, name):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 30:
            failures.append(name)

    def close(a, b):
        return math.isclose(a, b, rel_tol=2e-10, abs_tol=2e-10)

    frozen = json.loads((directory / "FROZEN.json").read_text())
    sealed = json.loads((directory / "INDEPENDENT_PRECHECK.json").read_text())
    summary = json.loads((directory / "SUMMARY.json").read_text())
    root = directory.resolve().parents[3]
    suffix = "/experiments/hcsn_v10_followup_20261101/persistent_av/candidate.py"
    original = next(p for p in frozen["sources"] if p.endswith(suffix))
    oldroot = Path(original[:-len(suffix)])
    for path, expected in frozen["sources"].items():
        check(sha(root / Path(path).relative_to(oldroot)) == expected, "frozen source")
    check(sha(root / "experiments/hcsn_v10_followup_20261101/persistent_av/root_precheck.py") == sealed["precheck_source_sha256"], "independent precheck source seal")
    for path, expected in sealed["artifact_sha256"].items():
        check(sha(directory / path) == expected, "pre-evaluation artifact seal: " + path)
    laws = {}
    for task in ("async_av", "av_binding"):
        for seed in (91101, 91103):
            record = json.loads((directory / task / f"LAW-{seed}.json").read_text())
            best = max(record["all_candidates"], key=lambda row: row["validation_log_likelihood"])
            check(record["selected"] == best["law"], "law historical-validation selection")
            law = record["selected"]
            check(law["k"] in (2, 4), "declared bounded state count")
            laws[task, seed] = law, transition(law["q"])
    for model in frozen["models"]:
        check(sha(directory / model["path"]) == model["sha256"], "selected reader identity")
        fit = json.loads((directory / model["task"] / f"{model['family']}-{model['seed']}-FIT.json").read_text())
        check(fit["selected_epoch"] == min(fit["history"], key=lambda r: r["validation_bce"])["epoch"], "reader historical-validation selection")
    with gzip.open(directory / "TRACES.jsonl.gz", "rt") as stream:
        rows = list(map(json.loads, stream))
    check(len(rows) == len(summary["rows"]) == summary["executions"] == 720, "complete 720 execution inventory")
    identities, groups, common_head, same_law = set(), defaultdict(list), {}, {}
    maximum, late, appends, filter_updates = 0., 0, 0, 0
    same_law_error, value_error, same_law_pairs = 0., 0., 0
    smallest_nonzero_margin = None
    for row in rows:
        key = tuple(row[k] for k in ("task", "index", "seed", "family", "implementation", "policy"))
        check(key not in identities, "unique AV execution")
        identities.add(key)
        run, history = row["execution"], row["updates"]
        accepted = [r for r in run["events"] if r.get("status") == "accepted"]
        check(len(accepted) == len(history) == row["requests"] == run["requested_observations"], "one history append per actual accepted request")
        check(len(history) <= 6, "history capacity bound")
        slots, levels, observations, previous = [], {"audio": 0, "video": 0}, [], 0
        law, matrix = laws[row["task"], row["seed"]]
        for update, event in zip(history, accepted):
            _, modality, source = event["action"].split(":")
            source = int(source)
            check(source == levels[modality]+1 == update["source_time"], "incremental modality source clock")
            levels[modality] = source
            current = max(levels.values())
            check(update["global_source_increment"] == current-previous == update["row"][40], "global source increment follows accepted maximum")
            check(update["content_fingerprint"] == event["after"], "accepted cache binding")
            value = update["row"]
            check(len(value) == 58 and all(math.isfinite(v) for v in value), "same-information 58-value observation")
            check(value[38:40] == [levels["audio"]/3, levels["video"]/3], "accepted modality levels")
            slots.append(value)
            if row["family"] == "filter":
                if value[-1]:
                    observations.append((source, int(modality == "video"), value[41:57]))
                expected = posterior(law, matrix, current, observations)
                actual = update["path_probability"]
                check(update["path_shape"] == [law["k"]]*(current+1) and len(actual) <= 256, "retained source-time path axes and storage bound")
                check(len(actual) == len(expected) and min(actual) >= 0 and close(math.fsum(actual), 1.), "path mass conservation")
                error = max(abs(a-b) for a, b in zip(actual, expected))
                maximum = max(maximum, error)
                check(error <= 2e-10, "independent full-path posterior enumeration")
                late += int(source < current)
                filter_updates += 1
            else:
                check(not update["path_shape"] and not update["path_probability"], "ordinary references have no undeclared path belief")
            payload = [update["content_fingerprint"], slots, update["hidden"],
                       update["path_probability"] if row["family"] == "filter" else None]
            check(list(hashlib.sha256(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()).digest()) == update["digest"], "snapshot digest binds complete state and history")
            appends += 1
            previous = current
        output = run["output"]
        probabilities = output["probabilities"]
        predicted = max(range(len(probabilities)), key=probabilities.__getitem__)
        check(output["predicted_class"] == predicted and row["correct"] == (predicted == row["label"]), "actual common-head scoring")
        check(close(row["utility"], float(row["correct"]) - run["observation_fee"] - run["latency_fee"] - run["deadline_penalty"]), "actual full logical fees")
        if row["policy"] == "value":
            for decision in run["decisions"]:
                for plan in decision["plans"]:
                    expected = plan["correctness"] - .02*plan["expected_requested_reads"] - .005*plan["expected_seconds"] - plan["deadline_miss_probability"]
                    check(close(plan["score"], expected) and close(plan["increment_over_stop"], expected-decision["stop_score"]), "priced candidate value arithmetic")
                best = max(decision["plans"], key=lambda p: (p["score"], p["plan"]), default=None)
                selected = best["plan"] if best is not None and best["score"] > decision["stop_score"] else None
                check(selected == decision["selected"], "strict STOP threshold and lexical plan ties")
                values = sorted([decision["stop_score"]] + [p["score"] for p in decision["plans"]], reverse=True)
                if len(values) > 1 and values[0] > values[1]:
                    gap = values[0]-values[1]
                    smallest_nonzero_margin = gap if smallest_nonzero_margin is None else min(smallest_nonzero_margin, gap)
        head_key = row["task"], row["index"], levels["audio"], levels["video"]
        if head_key in common_head:
            check(probabilities == common_head[head_key], "exact same-prefix common-head probabilities")
        common_head[head_key] = probabilities
        if row["family"] == "filter":
            pair_key = row["task"], row["index"], row["seed"], row["policy"]
            if row["implementation"] == "expm":
                same_law[pair_key] = row
            else:
                reference = same_law[pair_key]
                check([(r["tick"] if "tick" in r else r.get("action"), r.get("status")) for r in run["events"]] ==
                      [(r["tick"] if "tick" in r else r.get("action"), r.get("status")) for r in reference["execution"]["events"]], "same-law implementation actual action sequence")
                check(probabilities == reference["execution"]["output"]["probabilities"] and row["utility"] == reference["utility"], "same-law exact output and reward")
                check(len(run["decisions"]) == len(reference["execution"]["decisions"]), "same-law decision count")
                for left, right in zip(run["decisions"], reference["execution"]["decisions"]):
                    if row["policy"] == "fixed":
                        check(left["selected"] == right["selected"] and left["mode"] == right["mode"] == "fixed", "same-law fixed-policy decision record")
                        continue
                    check(left["selected"] == right["selected"] and left["stop_score"] == right["stop_score"], "same-law selected threshold decision")
                    check([p["plan"] for p in left["plans"]] == [p["plan"] for p in right["plans"]], "same-law candidate inventory")
                    for a, b in zip(left["plans"], right["plans"]):
                        error = max(abs(a[k]-b[k]) for k in ("correctness", "score", "increment_over_stop"))
                        value_error = max(value_error, error)
                        check(error <= 2e-10, "same-law candidate values before threshold")
                for left, right in zip(history, reference["updates"]):
                    check(left["source_time"] == right["source_time"] and left["row"] == right["row"], "same-law identical accepted information")
                    error = max(abs(a-b) for a, b in zip(left["path_probability"], right["path_probability"]))
                    same_law_error = max(same_law_error, error)
                    check(error <= 2e-10, "same-law entire posterior distribution")
                same_law_pairs += 1
        if row["implementation"] == "expm":
            groups[row["task"], row["family"], row["policy"]].append(row)
    for group in summary["groups"]:
        group_rows = groups[group["task"], group["family"], group["policy"]]
        values = {"accuracy": statistics.mean(r["correct"] for r in group_rows),
                  "mean_utility": statistics.mean(r["utility"] for r in group_rows),
                  "mean_requests": statistics.mean(r["requests"] for r in group_rows)}
        check(len(group_rows) == group["runs"] and all(close(group[k], v) for k, v in values.items()), "group arithmetic")
    indexed = {tuple(row[k] for k in ("task", "index", "seed", "family", "policy")): row
               for row in rows if row["implementation"] == "expm"}
    paired = {}
    for task in ("async_av", "av_binding"):
        indices = sorted({row["index"] for row in rows if row["task"] == task})
        for family in ("history", "gru", "ssm"):
            by_recording = []
            for index in indices:
                differences = []
                for seed in (91101, 91103):
                    left = indexed[task, index, seed, "filter", "value"]
                    right = indexed[task, index, seed, family, "value"]
                    differences.append(left["utility"] - right["utility"])
                by_recording.append(statistics.mean(differences))
            paired[task + "/filter_minus_" + family] = {
                "mean_utility_difference": statistics.mean(by_recording),
                "recordings": len(indices), "per_recording_two_seed_mean": by_recording,
                "scope": "Historical exposed recordings; paired point estimate without population inference"}
    return {"schema": "hcsn-v10-independent-path-raw-audit.v1", "checks": checks,
            "all_checks_passed": not failures, "failed_examples": failures, "executions": len(rows),
            "accepted_updates": appends, "filter_updates": filter_updates, "late_source_axis_updates": late,
            "largest_independent_path_posterior_difference": maximum,
            "same_law_pairs": same_law_pairs, "largest_same_law_posterior_difference": same_law_error,
            "largest_same_law_candidate_value_difference": value_error,
            "smallest_positive_observed_winner_margin": smallest_nonzero_margin,
            "paired_value_policy_differences": paired,
            "scope": "Sealed finite-law path posterior, causal storage, common-head equality and actual logical fees; no empirical law/financial HX/independent-recording/energy qualification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.directory)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
