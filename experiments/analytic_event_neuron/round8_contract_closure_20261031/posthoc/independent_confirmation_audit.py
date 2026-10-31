"""Post-freeze raw-record audit; never fits, selects, or edits a candidate.

The bootstrap is reconstructed with multinomial multiplicities rather than the
analysis module's ordered index tuples. MC errors condition on the five frozen
fits and use the balanced configuration strata. They are realized sampling
deviations, not estimates of systematic algorithmic bias.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from ...round7.task import ACTIONS, generate_episode, initial_state, legal_actions, step
from ..protocol import configurations


SEEDS = (11, 12, 13, 14, 15)
MODES = ("direct", "continuous", "clocked", "first_passage")
STAGES = ("baseline", "readout", "content_readout")
STARTS = {"nominal": 81000000, "heldout": 82000000}
METRICS = ("registered_return", "task_return", "quality", "event_count", "decisions",
           "prediction_ns", "process_cpu_ns", "kernel_ns", "wire_bytes", "guard_fallbacks")
PRIMARY = (("first_passage/content_readout/hard", "direct/content_readout/hard"),
           ("first_passage/content_readout/hard", "clocked/content_readout/hard"),
           ("first_passage/content_readout/hard", "first_passage/baseline/hard"))


def compositions(total, parts):
    if parts == 1:
        yield (total,)
    else:
        for first in range(total + 1):
            for tail in compositions(total - first, parts - 1):
                yield (first,) + tail


def independent_interval(values, alpha):
    samples = []
    for counts in compositions(5, 5):
        repetitions = math.factorial(5)
        for count in counts:
            repetitions //= math.factorial(count)
        mean = math.fsum(count * value for count, value in zip(counts, values)) / 5
        samples.extend([mean] * repetitions)
    if len(samples) != 3125:
        raise AssertionError("incorrect multinomial bootstrap mass")
    samples.sort()
    result = []
    for probability in (alpha / 2, 1 - alpha / 2):
        position = probability * (len(samples) - 1)
        lower, upper = math.floor(position), math.ceil(position)
        result.append(samples[lower] + (position - lower) * (samples[upper] - samples[lower]))
    return result


def expected_arms():
    result = {f"{mode}/{stage}/{deployment}" for mode in MODES for stage in STAGES
              for deployment in ("hard", "mean")}
    result.update(("task_DP", "myopic_DP"))
    result.update(f"brownian_anchor/{mode}/{deployment}" for mode in MODES[1:]
                  for deployment in ("hard", "mean"))
    result.update(f"unbounded/{operator}/{deployment}" for operator in ("gaussian", "probit")
                  for deployment in ("hard", "mean"))
    return result


def assert_close(left, right, name, tolerance=2e-12):
    if not math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError(f"{name}: {left} != {right}")


def verify_frozen(root):
    path = root / "FREEZE.json"
    manifest = json.loads(path.read_text())
    for relative, digest in manifest["files"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            raise AssertionError("frozen dependency changed: " + relative)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_error(values_by_configuration):
    if set(values_by_configuration) != set(range(8)):
        raise AssertionError("configuration stratum missing")
    if any(len(values) != 16 for values in values_by_configuration.values()):
        raise AssertionError("expected 16 worlds in each configuration stratum")
    return sum(statistics.variance(values) / len(values) / 64
               for values in values_by_configuration.values())


def exact_values(root):
    records = {}
    for mode in MODES:
        for seed in SEEDS:
            fit = json.loads((root / f"evidence/calibration_{mode}_{seed}.json").read_text())
            for stage in STAGES:
                records["nominal", f"{mode}/{stage}/hard", seed] = fit["audits"][stage]["greedy_return_mean"]
    heldout = json.loads((root / "evidence/heldout_exact.json").read_text())
    for fit in heldout["records"]:
        records["heldout", f"{fit['mode']}/{fit['stage']}/hard", fit["fit_seed"]] = fit["registered_return"]
        mean = statistics.mean(row["registered_return"] for row in fit["configurations"])
        assert_close(mean, fit["registered_return"], "heldout forward versus backward return")
        assert_close(fit["optimal_return"] - fit["registered_return"], fit["optimality_gap"], "heldout gap")
    if len(records) != 120:
        raise AssertionError("expected all 120 nominal/heldout hard-fit expectations")
    return records


def run(root, output):
    root, output = Path(root), Path(output)
    if output.exists():
        raise FileExistsError(output)
    started, cpu_started = time.perf_counter(), time.process_time()
    freeze = verify_frozen(root)
    summary = json.loads((root / "evidence/confirmation_v1/summary.json").read_text())
    analysis = json.loads((root / "evidence/confirmation_analysis.json").read_text())
    if summary["freeze_sha256"] != freeze or analysis["freeze_sha256"] != freeze:
        raise AssertionError("result freeze identities disagree")
    arms, values, pair_records = expected_arms(), {}, {}
    episodes, counts, groups = {}, Counter(), defaultdict(list)
    maximum_cost_error, transitions = 0.0, 0
    raw_path = root / "evidence/confirmation_v1/trajectories.jsonl.gz"
    with gzip.open(raw_path, "rt", encoding="utf8") as stream:
        for line in stream:
            row = json.loads(line)
            regime, seed, world, arm = row["regime"], row["fit_seed"], row["world_seed"], row["arm"]
            identity = (regime, seed, world, arm)
            if identity in values or row["status"] != "complete" or row["freeze_sha256"] != freeze:
                raise AssertionError("duplicate, failed, or foreign-freeze trajectory")
            if seed not in SEEDS or arm not in arms or regime not in STARTS:
                raise AssertionError("unregistered fit, arm or regime")
            fit_index = SEEDS.index(seed)
            index = world - STARTS[regime] - fit_index * 10000
            if not 0 <= index < 128 or row["configuration_index"] != index % 8:
                raise AssertionError("world/configuration identity mismatch")
            if row["latent_seed"] != 930000000 + list(STARTS).index(regime) * 1000000 + fit_index * 10000 + index:
                raise AssertionError("paired latent seed mismatch")
            world_identity = (regime, seed, world)
            if world_identity not in episodes:
                episodes[world_identity] = generate_episode(world, configurations(regime)[index % 8])
            episode, state = episodes[world_identity], initial_state(episodes[world_identity])
            rewards, costs, events = [], [], []
            for trace in row["steps"]:
                if trace["before"] != state.to_dict():
                    raise AssertionError("public prefix differs from independent environment replay")
                prediction = trace["prediction"]
                allowed = legal_actions(state)
                chosen = max((a for a in ACTIONS if a in allowed), key=lambda a: prediction["q"][ACTIONS.index(a)])
                if chosen != trace["requested_action"]:
                    raise AssertionError("recorded action is not the legal greedy readout decision")
                result = step(state, trace["requested_action"], episode)
                if result.to_dict() != trace["result"]:
                    raise AssertionError("external transition or cost differs on replay")
                rewards.append(result.reward)
                costs.append(result.cost)
                events.append(prediction["event_count"])
                state = result.state
                transitions += 1
            quality = 1.0 if state.answer == episode.truth else -1.0
            if not state.terminated or state.to_dict() != row["final_state"] or quality != row["quality"]:
                raise AssertionError("terminal outcome mismatch")
            if len(row["steps"]) != row["decisions"]:
                raise AssertionError("decision count mismatch")
            for field in ("prediction_ns", "kernel_ns", "wire_bytes"):
                if sum(trace["prediction"][field] for trace in row["steps"]) != row[field]:
                    raise AssertionError("per-step cost counter mismatch: " + field)
            if sum(trace["result"]["info"]["guard_fallback"] for trace in row["steps"]) != row["guard_fallbacks"]:
                raise AssertionError("guard fallback counter mismatch")
            if row["process_cpu_ns"] < 0:
                raise AssertionError("negative measured process CPU")
            assert_close(math.fsum(rewards), row["task_return"], "task reward")
            assert_close(math.fsum(costs), row["action_cost"], "action cost")
            assert_close(math.fsum(events), row["event_count"], "event count")
            assert_close(row["quality"] - row["action_cost"], row["task_return"], "quality less task costs")
            assert_close(0.0005 * row["decisions"], row["compute_proxy_cost"], "compute fee")
            assert_close(0.0002 * row["event_count"], row["event_proxy_cost"], "event fee")
            recomputed = row["task_return"] - 0.0005 * row["decisions"] - 0.0002 * row["event_count"]
            maximum_cost_error = max(maximum_cost_error, abs(recomputed - row["registered_return"]))
            assert_close(recomputed, row["registered_return"], "registered utility")
            values[identity] = {key: row[key] for key in METRICS}
            groups[regime, arm, seed].append(identity)
            counts[regime, seed, arm, index % 8] += 1
            if arm.startswith("unbounded/"):
                pair_records[identity] = {
                    "actions": [trace["requested_action"] for trace in row["steps"]],
                    "q": [trace["prediction"]["q"] for trace in row["steps"]],
                    "moments": [trace["prediction"]["moments"] for trace in row["steps"]],
                    "endpoint_partition": [trace["prediction"]["endpoint_partition_put_idle_call"] for trace in row["steps"]],
                }
    expected_count = len(STARTS) * len(SEEDS) * 128 * len(arms)
    if len(values) != expected_count or summary["attempts"] != expected_count or summary["failures"]:
        raise AssertionError("incomplete declared matrix")
    if len(counts) != 2 * 5 * 36 * 8 or set(counts.values()) != {16}:
        raise AssertionError("unbalanced registered configuration coverage")
    means = {key: {metric: math.fsum(values[identity][metric] for identity in identities) / len(identities)
                   for metric in METRICS} for key, identities in groups.items()}
    summary_errors = defaultdict(float)
    for entry in summary["fit_arm_sums"]:
        key = entry["regime"], entry["arm"], entry["fit_seed"]
        if entry["count"] != 128:
            raise AssertionError("fit block is not complete")
        for metric in METRICS:
            error = abs(means[key][metric] * 128 - entry[metric])
            summary_errors[metric] = max(summary_errors[metric], error)
            assert_close(means[key][metric] * 128, entry[metric], "fit summary " + metric)
    for entry in analysis["tables"]:
        for metric in METRICS:
            actual = statistics.mean(means[entry["regime"], entry["arm"], seed][metric] for seed in SEEDS)
            assert_close(actual, entry[metric], "analysis table " + metric)
    contrast_rows, exact, max_interval_error = [], exact_values(root), 0.0
    for entry in analysis["contrasts"]:
        regime, left, right = entry["regime"], entry["left"], entry["right"]
        differences = [means[regime, left, seed]["registered_return"] - means[regime, right, seed]["registered_return"] for seed in SEEDS]
        primary = (left, right) in PRIMARY
        if primary != entry["primary"]:
            raise AssertionError("primary family changed")
        alpha = 0.05 / 6 if primary else 0.05
        interval = independent_interval(differences, alpha)
        assert_close(entry["confidence_level"], 1 - alpha, "multiplicity label")
        assert_close(statistics.mean(differences), entry["mean"], "contrast mean")
        for actual, recorded in zip(differences, entry["fit_differences"], strict=True):
            assert_close(actual, recorded, "fit difference")
        for actual, recorded in zip(interval, entry["interval"], strict=True):
            max_interval_error = max(max_interval_error, abs(actual - recorded))
            assert_close(actual, recorded, "bootstrap quantile")
        if primary:
            exact_difference = [exact[regime, left, seed] - exact[regime, right, seed] for seed in SEEDS]
            variance = 0.0
            for seed in SEEDS:
                strata = defaultdict(list)
                for identity in groups[regime, left, seed]:
                    _, _, world, _ = identity
                    value = values[identity]["registered_return"] - values[regime, seed, world, right]["registered_return"]
                    strata[(world - STARTS[regime] - SEEDS.index(seed) * 10000) % 8].append(value)
                variance += sample_error(strata) / 25
            residual = statistics.mean(differences) - statistics.mean(exact_difference)
            contrast_rows.append({"regime": regime, "left": left, "right": right,
                                  "five_fit_MC_differences": differences, "MC_mean": statistics.mean(differences),
                                  "registered_bootstrap_interval": interval,
                                  "five_fit_exact_differences": exact_difference, "exact_mean": statistics.mean(exact_difference),
                                  "MC_minus_exact": residual, "conditional_paired_stratified_MC_SE": math.sqrt(variance),
                                  "residual_over_SE": residual / math.sqrt(variance) if variance else None})
    mc_exact = []
    for regime in STARTS:
        for mode in MODES:
            for stage in STAGES:
                arm = f"{mode}/{stage}/hard"
                mc = [means[regime, arm, seed]["registered_return"] for seed in SEEDS]
                deterministic = [exact[regime, arm, seed] for seed in SEEDS]
                variance = 0.0
                for seed in SEEDS:
                    strata = defaultdict(list)
                    for identity in groups[regime, arm, seed]:
                        _, _, world, _ = identity
                        strata[(world - STARTS[regime] - SEEDS.index(seed) * 10000) % 8].append(values[identity]["registered_return"])
                    variance += sample_error(strata) / 25
                residual = statistics.mean(mc) - statistics.mean(deterministic)
                mc_exact.append({"regime": regime, "arm": arm, "MC_mean": statistics.mean(mc),
                                 "exact_mean": statistics.mean(deterministic), "MC_minus_exact": residual,
                                 "five_fit_MC_minus_exact": [a - b for a, b in zip(mc, deterministic)],
                                 "conditional_stratified_MC_SE": math.sqrt(variance),
                                 "residual_over_SE": residual / math.sqrt(variance) if variance else None})
    identity_pairs = 0
    for identity, record in pair_records.items():
        regime, seed, world, arm = identity
        if "/gaussian/" in arm:
            partner = (regime, seed, world, arm.replace("/gaussian/", "/probit/"))
            if record != pair_records[partner]:
                raise AssertionError("Gaussian/probit action, Q, moment or endpoint partition mismatch")
            for metric in ("registered_return", "task_return", "quality", "event_count", "decisions", "wire_bytes"):
                if values[identity][metric] != values[partner][metric]:
                    raise AssertionError("Gaussian/probit outcome mismatch")
            identity_pairs += 1
    if identity_pairs != analysis["gaussian_probit_identity"]["paired_trajectories"]:
        raise AssertionError("Gaussian/probit identity-pair count mismatch")
    exchange = json.loads((root / "evidence/contract_exchange_v1/summary.json").read_text())
    by_case = {row["case"]: row for row in exchange["cases"]}
    exchange_error, exchange_count = 0.0, 0
    with gzip.open(root / "evidence/contract_exchange_v1/state_records.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            gap = math.fsum(p * regret for mass, regrets in zip(row["occupancy"], row["regret"], strict=True)
                            for p, regret in zip(mass, regrets, strict=True))
            exchange_error = max(exchange_error, abs(gap - by_case[row["case"]]["optimality_gap"]))
            exchange_count += 1
    if exchange_count != 90 or exchange_error > 1e-10:
        raise AssertionError("counterfactual occupancy-regret decomposition failed")
    if verify_frozen(root) != freeze:
        raise AssertionError("frozen inputs changed during independent audit")
    report = {"schema": "round8-posthoc-independent-confirmation-audit-v1", "passed": True,
              "freeze_sha256": freeze, "raw_records": len(values), "external_transitions_replayed": transitions,
              "fit_blocks": len(groups), "configuration_strata": len(counts), "worlds_per_stratum": 16,
              "maximum_registered_cost_error": maximum_cost_error,
              "raw_vs_summary_maximum_absolute_errors": dict(summary_errors),
              "contrasts_recomputed": len(analysis["contrasts"]), "maximum_bootstrap_interval_error": max_interval_error,
              "bootstrap_method": "126 count compositions weighted by multinomial multiplicities, total 3125",
              "gaussian_probit_identity_pairs": identity_pairs,
              "primary_contrasts": contrast_rows, "MC_vs_exact_hard_policy": mc_exact,
              "exchange_cases_recomputed": exchange_count, "maximum_exchange_regret_error": exchange_error,
              "MC_SE_scope": "Conditional on the frozen fits; independent worlds stratified into 8 configurations x 16 worlds per fit. Pairwise contrasts use within-world differences. These SEs do not describe training-seed uncertainty or prove absence of bias.",
              "independence_limit": "External transitions replay frozen environment semantics; aggregate arithmetic and multinomial bootstrap are independent of analysis.py. Exact expectations use already audited finite Bellman solver outputs, not an additional continuum oracle.",
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "raw_archive_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
              "wall_seconds": time.perf_counter() - started, "process_cpu_seconds": time.process_time() - cpu_started}
    with output.open("x", encoding="utf8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("passed", "raw_records", "external_transitions_replayed", "wall_seconds")}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run(args.root, args.output or args.root / "evidence/final_independent_audit.json")
