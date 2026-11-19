"""Read-only independent review of a sealed task-value/native study.

This is a post-panel audit, with no imported policy/model/evaluation helpers.
The native subset and full cached panel retain separate uncertainty estimates.
Short-lifetime sensitivity includes the separately recorded final-analysis CPU.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def close(a, b, tolerance=1e-10):
    if abs(float(a) - float(b)) > tolerance:
        raise AssertionError((a, b, tolerance))


def verify_map(root, mapping):
    for name, expected in mapping.items():
        if digest(root / name) != expected:
            raise AssertionError("Frozen identity changed: " + name)
    return len(mapping)


def paired_bootstrap(values, seed):
    rng = np.random.default_rng(seed)
    # One complete three-task stream, averaged over prices, is the unit.
    indices = rng.integers(0, len(values), size=(19999, len(values)))
    means = values[indices].mean(axis=1)
    return {
        "mean": float(values.mean()),
        "nominal_percentile_interval_95": np.quantile(means, [.025, .975]).tolist(),
        "streams": len(values), "resamples": 19999, "seed": seed,
        "positive_streams": int((values > 0).sum()),
        "negative_streams": int((values < 0).sum()),
        "zero_streams": int((values == 0).sum()),
        "scope": "Post-panel descriptive paired bootstrap; no selection or multiplicity-adjusted superiority gate",
    }


def run(source, addendum, output):
    source, addendum, output = (Path(p).resolve() for p in (source, addendum, output))
    repository = Path(__file__).resolve().parents[2]
    output.mkdir(parents=True, exist_ok=False)
    started = time.process_time()
    top_names = ["PROTOCOL.json", "REGISTRATION.json", "SELECTION_LOCK.json",
                 "EVALUATION_SUMMARY.json", "COST_SCENARIOS.json", "COMPLETE.json",
                 "CAMPAIGN_EXECUTION.json", "ANALYSIS_PARENT_EXECUTION.json", "AUDIT.json"]
    inputs = {name: digest(source / name) for name in top_names}
    addendum_inputs = {name: digest(addendum / name) for name in
                       ("REGISTRATION.json", "SUMMARY.json", "EXECUTION.json")}
    write(output / "REGISTRATION.json", {
        "schema": "hcsn-independent-execution-review.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Post-panel independent artifact audit and sensitivity; no new quality selection or training",
        "source_directory": str(source), "source_files": inputs,
        "addendum_directory": str(addendum), "addendum_files": addendum_inputs,
        "analysis_source_sha256": digest(__file__),
        "bootstrap": {"resamples": 19999, "seed": 83071, "unit": "Three-task stream macro averaged over prices"},
        "sensitivity_lifetimes": [1, 10, 100, 1000, 10000, 100000],
        "native_runtime_uncertainty": "CPU costs are plug-in measurements; no runtime-CI or energy estimate",
    })
    protocol, registration, lock, evaluation, cost, complete, campaign, parent, original_audit = (
        read(source / name) for name in top_names)
    reference = lock["best_ordinary_family"]
    if lock["fresh_test_accessed"] or not lock["both_lrs_and_all_candidates_completed"]:
        raise AssertionError("Selection lock did not precede fresh testing")
    identities = {
        "registered_source_and_data_files": verify_map(repository, registration["files"]),
        "selection_locked_files": verify_map(source, lock["files"]),
        "original_audit_files": verify_map(source, original_audit["source_sha256"]),
    }
    with np.load(source / "data/fresh_mnist.npz", allow_pickle=False) as raw:
        labels = raw["labels"].copy()
    with np.load(source / "traces/test.npz", allow_pickle=False) as raw:
        predictions = raw["prediction"].copy()
        np.testing.assert_array_equal(raw["labels"], labels)
    metadata = read(source / "data/fresh_mnist.json")
    queues = np.random.default_rng(protocol["data"]["test_queue_permutation_seed"]).permutation(len(labels)).reshape(-1, 3)
    if len(np.unique(queues)) != len(labels):
        raise AssertionError("Repeated source image in queue assignment")
    families = list(evaluation["actual_native"][str(protocol["prices"][0])])
    native_utilities = {family: [] for family in families}
    cached_utilities = {family: [] for family in families}
    counts = {"native_stream_price_policy_cases": 0, "native_processes": 0,
              "actual_reads": 0, "actual_quiet_ticks": 0, "post_stop_rejections": 0,
              "actual_kernel_calls": 0, "actual_ndu_calls": 0,
              "cache_native_parity_mismatches": 0, "float_q24_action_disagreements": 0}
    native_receipt_identities = {}
    for price in protocol["prices"]:
        for family in families:
            root = source / "evaluation" / ("price_" + str(price))
            with np.load(root / (family + "_counterfactual.npz"), allow_pickle=False) as cached:
                np.testing.assert_array_equal(cached["queues"], queues)
                reads = cached["task_reads"].copy()
                scores = np.zeros_like(reads)
                for stream, queue in enumerate(queues):
                    for task, image in enumerate(queue):
                        prefix = int(reads[stream, task])
                        if prefix:
                            pred = predictions[image, prefix - 1]
                            if pred != cached["task_predictions"][stream, task]:
                                raise AssertionError("Cached prediction differs from full trace")
                            scores[stream, task] = int(pred == labels[image])
                utility = scores.sum(axis=1) - price * reads.sum(axis=1)
                np.testing.assert_array_equal(scores, cached["task_correct"])
                np.testing.assert_allclose(utility, cached["utility"], atol=1e-13, rtol=0)
                if np.any(reads.sum(axis=1) + protocol["refractory_ticks"] * np.maximum((reads > 0).sum(axis=1) - 1, 0)
                          > protocol["deadline_ticks"]):
                    raise AssertionError("Cached deadline violated")
                cached_utilities[family].append(utility)
            observed, child_cpu = [], 0.
            for stream in range(protocol["native_streams"]):
                file = root / family / ("stream_" + str(stream)) / "RESULT.json"
                native_receipt_identities[str(file.relative_to(source))] = digest(file)
                row = read(file)
                events = row["events"]
                if [e["clock"] for e in events] != list(range(1, len(events) + 1)):
                    raise AssertionError("Actual event clock is not sequential")
                if len(events) > protocol["deadline_ticks"] or row["ticks"] != protocol["deadline_ticks"] - len(events):
                    raise AssertionError("Actual event clock exceeds deadline")
                read_events = [e for e in events if e["kind"] == "read_and_decide"]
                quiet = [e for e in events if e["kind"] == "refractory_tick"]
                if len(read_events) != row["actual_reads"] or len(quiet) != row["quiet_ticks"]:
                    raise AssertionError("Actual read/quiet counts differ")
                if len(read_events) + len(quiet) != len(events):
                    raise AssertionError("Unknown event type")
                for event in quiet:
                    if event["model_steps"] or event["owner_ticks"]:
                        raise AssertionError("Model/owner advanced during refractory phase")
                reconstructed_reads, reconstructed_scores = [], []
                previous_fire_clock = None
                for task, result in enumerate(row["task_results"]):
                    task_events = [e for e in read_events if e["task_index"] == task]
                    if [e["prefix"] for e in task_events] != list(range(1, len(task_events) + 1)):
                        raise AssertionError("Task prefix does not restart at one")
                    if previous_fire_clock is not None and task_events[0]["clock"] - previous_fire_clock != protocol["refractory_ticks"] + 1:
                        raise AssertionError("Task reset did not consume exact refractory time")
                    if result["fire_clock"] != task_events[-1]["clock"]:
                        raise AssertionError("Fire clock differs from last actual read")
                    previous_fire_clock = result["fire_clock"]
                    image = queues[stream, task]
                    if result["source_id"] != metadata["image_source_ids"][image] or result["label"] != int(labels[image]):
                        raise AssertionError("Actual native source identity differs")
                    for index, event in enumerate(task_events):
                        native = event["native"]
                        q24 = round(math.tanh(event["score"]) * (1 << 24))
                        if q24 != event["score_q24"] or event["action"] != ("keep" if q24 > 0 else "stop"):
                            raise AssertionError("Actual Q24 action differs")
                        expected_action = "stop" if index == len(task_events) - 1 else "keep"
                        if event["action"] != expected_action or native["effective_action"] != expected_action:
                            raise AssertionError("Native terminal/continuation action differs")
                        if native["terminal"] != (expected_action == "stop") or native["step"] != index + 1:
                            raise AssertionError("Native step/terminal identity differs")
                        if native["actual_model_calls"] != 1 or native["actual_ndu_calls"] != 1:
                            raise AssertionError("Native action did not execute exactly one kernel/NDU step")
                        if index and native["checkpoint_before"] != task_events[index - 1]["native"]["checkpoint_after"]:
                            raise AssertionError("Native checkpoint chain is discontinuous")
                        if event["prediction"] != int(predictions[image, index]):
                            raise AssertionError("Actual prediction differs from cached prefix")
                    correct = int(result["prediction"] == labels[image])
                    if correct != result["correct"] or result["actual_reads"] != len(task_events):
                        raise AssertionError("Actual task count/reward differs")
                    close(result["net_reward"], correct - price * len(task_events))
                    probe = result["terminal_probe"]
                    if not probe["passed"] or probe["before"] != probe["after"] or probe["rejection"]["ok"]:
                        raise AssertionError("Post-STOP request changed terminal state")
                    reconstructed_reads.append(len(task_events))
                    reconstructed_scores.append(correct)
                    counts["post_stop_rejections"] += 1
                full_reads = np.pad(reconstructed_reads, (0, 3 - len(reconstructed_reads)))
                full_scores = np.pad(reconstructed_scores, (0, 3 - len(reconstructed_scores)))
                if not np.array_equal(full_reads, reads[stream]) or not np.array_equal(full_scores, scores[stream]):
                    counts["cache_native_parity_mismatches"] += 1
                actual_utility = sum(reconstructed_scores) - price * sum(reconstructed_reads)
                close(actual_utility, row["utility"])
                if len(row["native_costs"]) != len(row["task_results"]):
                    raise AssertionError("Native process count differs from owners")
                for native_cost, task_reads in zip(row["native_costs"], reconstructed_reads):
                    if native_cost["exit_code"] != 0:
                        raise AssertionError("Failed native process")
                    counter = native_cost["counters"]
                    for key in ("owner_ticks", "actual_kernel_calls", "actual_ndu_calls"):
                        if counter[key] != task_reads:
                            raise AssertionError("Native measured counter differs: " + key)
                    if counter["native_errors"] != 1:
                        raise AssertionError("Unexpected native errors beyond deliberate post-STOP rejection")
                    if native_cost["identity"]["binary_sha256"] != "1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5":
                        raise AssertionError("Native binary changed")
                    counts["actual_kernel_calls"] += counter["actual_kernel_calls"]
                    counts["actual_ndu_calls"] += counter["actual_ndu_calls"]
                    child_cpu += native_cost["child_cpu_seconds"]
                observed.append(actual_utility)
                counts["native_stream_price_policy_cases"] += 1
                counts["native_processes"] += len(row["native_costs"])
                counts["actual_reads"] += len(read_events)
                counts["actual_quiet_ticks"] += len(quiet)
                counts["float_q24_action_disagreements"] += row["float_q24_disagreements"]
            summary = evaluation["actual_native"][str(price)][family]
            close(np.mean(observed), summary["mean_utility"])
            close(child_cpu, summary["native_child_cpu_seconds"])
            close((child_cpu + summary["parent_cpu_seconds"]) / protocol["native_streams"],
                  summary["complete_execution_cpu_per_stream"])
            native_utilities[family].append(np.array(observed))
    if counts["cache_native_parity_mismatches"] or counts["float_q24_action_disagreements"]:
        raise AssertionError("Recorded zero-disagreement claim fails")
    comparison = {}
    for family in families:
        comparison[family] = {}
        for scope, panel in (("actual_native_16", native_utilities), ("cached_counterfactual_128", cached_utilities)):
            difference = np.mean(panel[family], axis=0) - np.mean(panel[reference], axis=0)
            comparison[family][scope] = paired_bootstrap(difference, 83071)
    # Recalculate the complete campaign once. Disjoint phase totals are nested.
    phase_cpu = sum(row["complete_child_cpu_seconds"] for row in complete["phases"].values())
    close(phase_cpu, complete["complete_measured_child_cpu_seconds"])
    close(campaign["complete_child_cpu_seconds"], cost["measured_complete_campaign_cpu_seconds"])
    if phase_cpu > campaign["complete_child_cpu_seconds"]:
        raise AssertionError("Phase receipts exceed enclosing wait4 cost")
    prior_cpu = sum(row["complete_child_cpu_seconds"] for row in protocol["prior_attempts"])
    close(campaign["complete_child_cpu_seconds"] + prior_cpu, cost["total_new_campaign_and_prior_attempt_cpu_seconds"])
    supplementary = read(addendum / "SUMMARY.json")
    recomputed_scenarios = []
    candidate = "tabular_bellman"
    native_mean = {family: float(np.mean(panel)) for family, panel in native_utilities.items()}
    for row in supplementary["scenarios"]:
        n, rate = row["future_stream_lifetime"], row["utility_units_per_cpu_second"]
        if row["allocation"] == "measured_method_components":
            setup = cost["scenario_one_time_setup_by_family"]
        else:
            setup = {candidate: cost["historical_backbone_search_cpu_seconds"] + campaign["complete_child_cpu_seconds"] + prior_cpu,
                     reference: cost["historical_backbone_search_cpu_seconds"]}
        delta_cpu = (cost["native_runtime_cpu_per_stream"][candidate] - cost["native_runtime_cpu_per_stream"][reference]
                     + (setup[candidate] - setup[reference]) / n)
        difference = native_mean[candidate] - native_mean[reference] - rate * delta_cpu
        close(difference, row["difference"])
        recomputed_scenarios.append(difference)
    analysis_cpu = parent["whole_parent_self_cpu_seconds_through_report"]
    addendum_cpu = read(addendum / "EXECUTION.json")["whole_analysis_self_cpu_seconds"]
    conservative_setup_difference = campaign["complete_child_cpu_seconds"] + prior_cpu + analysis_cpu + addendum_cpu
    runtime_difference = cost["native_runtime_cpu_per_stream"][candidate] - cost["native_runtime_cpu_per_stream"][reference]
    quality_difference = native_mean[candidate] - native_mean[reference]
    native_interval = comparison[candidate]["actual_native_16"]["nominal_percentile_interval_95"]
    sensitivity = []
    for n in (1, 10, 100, 1000, 10000, 100000):
        dc = runtime_difference + conservative_setup_difference / n
        for rate in protocol["cost"]["utility_per_cpu_second"]:
            sensitivity.append({"lifetime_streams": n, "utility_per_cpu_second": rate,
                "extra_cpu_per_stream": dc, "net_difference": quality_difference - rate * dc,
                "native_quality_only_nominal_interval_shifted_by_plug_in_cost": [v - rate * dc for v in native_interval]})
    summary = {
        "status": "passed", "scope": "Independent post-panel recomputation, no new task inference/training",
        "identities_verified": identities, "native_evidence": counts,
        "ordinary_reference": reference, "native_mean_utility": native_mean,
        "paired_comparisons": comparison,
        "original_tabular_cost_grid": {"recomputed": len(recomputed_scenarios),
            "positive": sum(v > 0 for v in recomputed_scenarios), "difference_range": [min(recomputed_scenarios), max(recomputed_scenarios)]},
        "costs": {"complete_campaign_cpu": campaign["complete_child_cpu_seconds"], "nested_phase_cpu": phase_cpu,
            "earlier_failed_campaign_cpu": prior_cpu, "separate_original_analysis_cpu": analysis_cpu,
            "separate_tabular_addendum_cpu": addendum_cpu,
            "conservative_extra_setup_cpu_for_candidate": conservative_setup_difference,
            "candidate_minus_reference_runtime_cpu_per_stream": runtime_difference,
            "equal_cpu_lifetime_streams": conservative_setup_difference / -runtime_difference,
            "setup_allocation": "All measured task campaign, failed attempt, outer analysis and addendum charged to candidate; ordinary receives free new setup. Shared historical backbone cancels in difference.",
            "this_audit_cpu": "Recorded separately in EXECUTION.json; no retroactive insertion into sealed studies",
            "not_measured": "Energy, monetary price, production restart latency, runtime variability intervals"},
        "short_lifetime_sensitivity": sensitivity,
        "break_even_cpu_rate_by_lifetime": [{"lifetime_streams": n,
            "utility_per_cpu_second": quality_difference / (runtime_difference + conservative_setup_difference / n)
            if runtime_difference + conservative_setup_difference / n > 0 else None,
            "no_positive_rate_penalty_if_null": True} for n in (1, 10, 100, 1000, 10000, 100000)],
        "native_receipt_sha256": native_receipt_identities,
        "input_sha256": inputs, "analysis_source_sha256": digest(__file__),
        "limitations": ["16 actual native streams; 128 cached streams are not additional actual executions",
                        "One frozen v1 backbone and coarsened confidence-state planner; no v2 architecture advantage",
                        "Bootstrap intervals are descriptive and conditional on observed costs; no corrected significance claim",
                        "Post-panel cost/uncertainty review leaves all selected policies and original studies unchanged"]}
    verify_map(source, inputs)
    verify_map(addendum, addendum_inputs)
    write(output / "SUMMARY.json", summary)
    small_n = [r for r in sensitivity if r["utility_per_cpu_second"] == .01]
    lines = ["# Independent native execution and cost review", "",
        "Post-panel read-only audit. No model, policy, threshold, dataset, selection or sealed result is changed.", "",
        f"Verified {identities['registered_source_and_data_files']} registered source/data identities, {identities['selection_locked_files']} selection-locked artifacts and {identities['original_audit_files']} original audit inputs. Recomputed all 240 native stream/price/policy cases from labels, actual event clocks, quantized decisions, checkpoint chains, stopped-owner probes and native process counters.", "",
        f"Actual execution totals: {counts['actual_reads']} reads and kernel/NDU steps, {counts['native_processes']} successful native processes, {counts['post_stop_rejections']} intentional rejected post-STOP requests; zero cache/native or float/Q24 disagreements. Quiet ticks perform no model or owner steps.", "",
        "## Uncertainty scopes", "", "| Candidate minus validation-selected ordinary reference | Actual native 16 streams | Cached 128 streams |", "| --- | --- | --- |"]
    for family in ("tabular_bellman", "bellman_value_head", "ordinary_action_head"):
        cells = []
        for scope in ("actual_native_16", "cached_counterfactual_128"):
            result = comparison[family][scope]
            lo, hi = result["nominal_percentile_interval_95"]
            cells.append(f"{result['mean']:.8f} [{lo:.8f}, {hi:.8f}]")
        lines.append("| " + family + " | " + " | ".join(cells) + " |")
    lines += ["", "Intervals use 19,999 paired whole-stream bootstrap draws after averaging the three prices. They are post-panel descriptive intervals, without a multiplicity gate. The 128-stream interval must not be attached to native execution or net utility.", "",
        "## Complete cost sensitivity", "",
        f"All 24 original tabular addendum values reproduce. A stricter new allocation adds the separately measured outer analysis ({analysis_cpu:.6f} CPU s) and addendum ({addendum_cpu:.6f} CPU s), charging the candidate {conservative_setup_difference:.6f} extra setup CPU s while giving the ordinary reference free new setup. Historical backbone setup is shared and cancels. Native runtime difference is {runtime_difference:.8f} CPU s/stream.", "",
        "| Lifetime streams | Extra CPU / stream | Net utility difference at 0.01 utility / CPU s |", "| ---: | ---: | ---: |"]
    for row in small_n:
        lines.append(f"| {row['lifetime_streams']} | {row['extra_cpu_per_stream']:.6f} | {row['net_difference']:.8f} |")
    lines += ["", "Short deployments can lose after setup amortization. The positive original 1,000–100,000-stream grid is not a claim of positive net benefit for every lifetime or compute price. Native quality uncertainty is separate from unmeasured runtime/energy variability.", "",
        "The direct planner result concerns one frozen v1 encoder and its finite task controller. The learned value head remains negative on the full cached quality panel. Neither result establishes an advantage for the v2 distributional content model or a foundation model.", ""]
    with (output / "REPORT.md").open("x") as handle:
        handle.write("\n".join(lines))
    write(output / "EXECUTION.json", {"analysis_self_cpu_seconds_from_process_start": time.process_time(),
        "analysis_cpu_seconds_after_inputs": time.process_time() - started, "source_sha256": digest(__file__),
        "summary_sha256": digest(output / "SUMMARY.json"), "report_sha256": digest(output / "REPORT.md"),
        "scope": "This independent analysis only; excluded from sealed original cost tables"})
    print(json.dumps({"status": "passed", "native": counts,
                      "tabular_native_difference": comparison[candidate]["actual_native_16"],
                      "one_stream_net_at_rate_001": small_n[0]["net_difference"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--addendum", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.addendum, args.output)
