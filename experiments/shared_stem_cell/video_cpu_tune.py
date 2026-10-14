"""Source-disjoint CPU microbatch selection with real UNTRAINED Conv2d work.

A frozen shared Reader is fit on six video sources. Batch sizes 1/2/4 are
compared on two DIFFERENT calibration sources without labels. A policy is
sealed before the final two source videos are evaluated. It is not CLIP,
not an independent future sample, and not a production scheduler.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import statistics
import time

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import media_execution as media
from experiments.shared_stem_cell import video_batch as batch
from experiments.shared_stem_cell import video_cpu_proxy as cpu
from experiments.shared_stem_cell import video_temporal as temporal

BATCHES = (1, 2, 4)
# Each held-out source has four forward and four reverse pairs.
WORKLOADS = (("forward_only", 8, 2), ("forward_only", 8, 8),
             ("paired", 8, 2), ("paired", 8, 8),
             ("paired", 16, 2), ("paired", 16, 8))
MARGIN = .05  # pick smaller batch when its calibrated wall is within 5% of fastest


def split_sources(root, manifest):
    cases, labels = media.read_cases(root, manifest["dataset"], 2)
    cohort, _ = temporal.cohort(root, manifest["cohort"])
    if len(cases) != 80 or [c.case_id for c in cases] != [v["case_id"] for v in cohort]:
        raise e.InputError("exact ten-source paired video cohort required")
    sources = {part: set() for part in ("train", "calibration", "holdout")}
    cases_by_fold = {part: {p: [] for p in cpu.PROFILES} for part in sources}
    for c, meta in zip(cases, cohort):
        if c.split not in sources or meta["split"] != c.split or meta["source_id"] != c.group:
            raise e.InputError("source partition / clip identity drift")
        sources[c.split].add(meta["source_id"])
        cases_by_fold[c.split]["paired"].append(c)
        if meta["direction"] == "forward":
            cases_by_fold[c.split]["forward_only"].append(c)
        elif meta["direction"] != "reverse":
            raise e.InputError("exact two paired presentation orders required")
    if ([len(sources[p]) for p in sources] != [6, 2, 2]
            or len(set.union(*sources.values())) != 10
            or [len(cases_by_fold[p]["paired"]) for p in sources] != [48, 16, 16]
            or [len(cases_by_fold[p]["forward_only"]) for p in sources] != [24, 8, 8]):
        raise e.InputError("source-disjoint 6/2/2 split required")
    return cases, cases_by_fold, labels, {k: sorted(v) for k, v in sources.items()}


def completion_times(observed):
    """All Cell requests available at t=0; group completion excludes wrapper work.

    Each member of a FIFO group finishes when that group's results are ready.
    This is a common-arrival diagnostic, not online traffic arrival latency.
    """
    end = 0
    result = {}
    for group in observed["groups"]:
        elapsed = group["wall"]["wall_ns"]
        if type(elapsed) is not int or elapsed <= 0:
            raise e.InputError("positive measured microbatch-group duration required")
        end += elapsed
        for case_id in group["case_ids"]:
            if case_id in result:
                raise e.InputError("duplicate Cell completion")
            result[case_id] = end
    if set(result) != {r["case_id"] for r in observed["records"]}:
        raise e.InputError("missing group-to-Cell completion mapping")
    if end > observed["physical_work"]["whole_stream_wall"]["wall_ns"]:
        raise e.InputError("group work exceeds the total measured stream wall")
    return [result[r["case_id"]] for r in observed["records"]]


def _rank(samples, percentile):
    ordered = sorted(samples)
    if not ordered or type(percentile) is not int or not 1 <= percentile <= 100:
        raise e.InputError("bounded nonempty latency samples required")
    return ordered[(percentile * len(ordered) + 99) // 100 - 1]


def choose(measurements):
    """Calibration timing only. A slower small batch may win within 5% tolerance."""
    if (set(measurements) != set(BATCHES)
            or any(not isinstance(measurements[b], list) or not 2 <= len(measurements[b]) <= 9
                   or any(type(x) is not int or x <= 0 for x in measurements[b])
                   for b in BATCHES)):
        raise e.InputError("complete fixed microbatch calibration timing grid required")
    medians = {b: int(statistics.median(measurements[b])) for b in BATCHES}
    best = min(medians.values())
    size = min(b for b in BATCHES if medians[b] <= (1 + MARGIN) * best)
    return {"batch_size": size, "median_wall_ns": {str(k): v for k, v in medians.items()},
            "best_observed_median_ns": best, "near_optimal_tolerance": MARGIN,
            "tie_rule": "smallest batch within 5pct of minimum calibration median",
            "uses_accuracy_or_holdout_labels": False,
            "independent_latency_guarantee": False, "production_accepted": False}


def workload_key(profile, n, depth):
    return f"{profile}:{n}:{depth}"


def execute_once(root, network, reader, cases, depth, size):
    tower = cpu.PixelTower(network)
    with e.measured() as timing:
        observed = batch.stream_cases(reader, cases, root, tower,
                                      {"kind": "fixed", "depth": depth}, None, batch_size=size)
    completed = completion_times(observed)
    if [r["case_id"] for r in observed["records"]] != [c.case_id for c in cases]:
        raise e.InputError("exact source-preserving case coverage required")
    if any(r["depth"] != depth for r in observed["records"]):
        raise e.InputError("fixed depth changed")
    work = observed["physical_work"]
    if (tower.calls["clip"] != work["physical_video_calls"]
            or tower.encoded_frames != work["unique_frames"]
            or sum(tower.forward_batch_sizes) != work["unique_frames"]):
        raise e.InputError("physical proxy frame-cost identity drift")
    return {"wall_ns": timing["wall_ns"], "stream_wall_ns":work["whole_stream_wall"]["wall_ns"],
            "process_cpu_ns": timing["process_cpu_ns"],
            "preprocess_ns": tower.preprocess_ns, "conv_forward_ns": tower.conv_forward_ns,
            "source_bytes": tower.loaded_bytes, "unique_frames": work["unique_frames"],
            "requested_frame_rows": work["requested_frame_rows"],
            "physical_forward_calls": work["physical_video_calls"],
            "conv_batch_sizes":tower.forward_batch_sizes,
            "all_arrive_at_zero_group_completion_ns": completed,
            "group_completion_p50_ns": int(statistics.median(completed)),
            "group_completion_p95_ns": _rank(completed, 95),
            "group_completion_p99_ns": _rank(completed, 99),
            "first_group_completion_ns": min(completed),
            "case_count":len(cases),
            "source_rss_start_bytes": timing["rss_start_bytes"],
            "source_rss_end_bytes": timing["rss_end_bytes"],
            "source_rss_is_endpoints_not_peak": True,
            "trace":observed}


def run(root, output, *, workloads=WORKLOADS, calibration_rounds=3,
        evaluation_rounds=5, warmups=1):
    """Report *all* arm costs, calibrate one schedule per source-disjoint workload."""
    root, output = Path(root), Path(output)
    if (type(workloads) is not tuple or not workloads or len(set(workloads)) != len(workloads)
            or any(w not in WORKLOADS for w in workloads)
            or type(calibration_rounds) is not int or not 2 <= calibration_rounds <= 9
            or type(evaluation_rounds) is not int or not 2 <= evaluation_rounds <= 9
            or type(warmups) is not int or not 0 <= warmups <= 2):
        raise e.InputError("predeclared CPU batch tuning grid required")
    if torch.get_num_threads() != 1:
        raise e.InputError("single CPU thread required for controlled comparisons")
    clock_start = time.perf_counter_ns()
    output.mkdir(parents=True, exist_ok=False)
    manifest_raw = (root / "manifest.json").read_bytes()
    manifest = e.decode(manifest_raw)
    network = cpu.FrozenPixelConv()
    frozen_identity = e.parameters(network)
    seal = e.write_once(output / "protocol.json", {
        "schema": "hepta.video-source-disjoint-cpu-autotune-protocol.v1",
        "source_sha256": e.sha(Path(__file__).read_bytes()),
        "manifest_sha256": e.sha(manifest_raw),
        "frozen_proxy_sha256": frozen_identity["sha256"],
        "workloads": workloads, "batch_sizes": BATCHES,
        "calibration_rounds": calibration_rounds, "evaluation_rounds": evaluation_rounds,
        "warmups": warmups, "margin": MARGIN,
        "speaker_or_video_source_disjoint": True, "frozen_random_conv_not_clip": True,
        "label_blind_schedule_selection": True, "production_accepted": False})
    try:
        all_cases, partition, labels, sources = split_sources(root, manifest)
        with e.measured() as fitting:
            reader, training_work = cpu.train_reader(root, manifest, network, all_cases)
        reader_identity = e.parameters(reader)
        e.write_once(output / "training.json", {"reader":reader_identity,
            "frozen_proxy":frozen_identity, "work":training_work,"fitting_wall":fitting,
            "source_groups":sources, "trained_only_on_train_labels":True,
            "holdout_labels_in_original_manifest_but_never_passed_to_selector":True})
        calibration, evaluation, selections, holdout_predictions = {}, {}, {}, {}
        charged_ns = 0; warmup_ns = 0; all_runs = 0
        charged_calls = 0; warmup_calls = 0
        charged_frames = 0; warmup_frames = 0
        charged_conv_ns = 0; warmup_conv_ns = 0
        charged_preprocess_ns = 0; warmup_preprocess_ns = 0
        charged_source_bytes = 0; warmup_source_bytes = 0
        warmup_records = []
        # Rotate order within each round to avoid systematically placing batch-4
        # after warmed batch-1. No holdout results influence the rotation.
        orders = (BATCHES, (4, 2, 1), (2, 4, 1))

        def run_fold(cases, depth, iterations, *, fold, workload):
            nonlocal charged_ns, warmup_ns, all_runs, charged_calls, warmup_calls
            nonlocal charged_frames, warmup_frames, charged_conv_ns, warmup_conv_ns
            nonlocal charged_preprocess_ns, warmup_preprocess_ns
            nonlocal charged_source_bytes, warmup_source_bytes
            measurements = {str(size): [] for size in BATCHES}
            reference = None
            for iteration in range(-warmups, iterations):
                for order_position, size in enumerate(orders[iteration % len(orders)]):
                    entry = execute_once(root, network, reader, cases, depth, size)
                    all_runs += 1
                    if (e.parameters(network) != frozen_identity
                            or e.parameters(reader) != reader_identity):
                        raise e.InputError("frozen model identity drift")
                    observed = entry.pop("trace")
                    entry.update({"fold": fold, "workload": workload, "iteration": iteration,
                                  "order_position": order_position, "batch_size": size})
                    if reference is None: reference = observed["records"]
                    else: _compare_fixed(reference, observed["records"])
                    if iteration < 0:
                        warmup_ns += entry["wall_ns"]
                        warmup_calls += entry["physical_forward_calls"]
                        warmup_frames += entry["unique_frames"]
                        warmup_conv_ns += entry["conv_forward_ns"]
                        warmup_preprocess_ns += entry["preprocess_ns"]
                        warmup_source_bytes += entry["source_bytes"]
                        warmup_records.append(entry)
                    else:
                        charged_ns += entry["wall_ns"]
                        charged_calls += entry["physical_forward_calls"]
                        charged_frames += entry["unique_frames"]
                        charged_conv_ns += entry["conv_forward_ns"]
                        charged_preprocess_ns += entry["preprocess_ns"]
                        charged_source_bytes += entry["source_bytes"]
                        if iteration == 0: entry["trace"] = observed
                        measurements[str(size)].append(entry)
            return measurements, reference

        for profile, count, depth in workloads:
            key = workload_key(profile, count, depth)
            cal_cases = partition["calibration"][profile][:count]
            if len(cal_cases) != count:
                raise e.InputError("source-disjoint calibration workload drift")
            calibration[key], _ = run_fold(cal_cases, depth, calibration_rounds,
                                           fold="calibration", workload=key)
            selections[key] = choose({b:[v["wall_ns"] for v in calibration[key][str(b)]] for b in BATCHES})
        cal_seal = e.write_once(output / "calibration.json", {
            "source_groups":sources["calibration"], "measurements":calibration,
            "workloads":workloads, "batch_sizes":BATCHES,
            "warmup_wall_ns":warmup_ns, "measured_arm_wall_ns":charged_ns})
        choice_seal = e.write_once(output / "selection.json", {
            "schema":"hepta.video-source-disjoint-batch-choice.v1",
            "protocol_sha256":seal,"calibration_sha256":cal_seal,
            "trained_reader_sha256":reader_identity["sha256"],
            "source_sha256":e.sha(Path(__file__).read_bytes()),
            "by_workload":selections,"source_groups":sources,
            "holdout_labels_used":False,"production_accepted":False})
        selected = e.decode(e.bound_file(output / "selection.json", choice_seal))["by_workload"]
        for profile, count, depth in workloads:
            key = workload_key(profile, count, depth)
            test_cases = partition["holdout"][profile][:count]
            if len(test_cases) != count:
                raise e.InputError("source-disjoint evaluation workload drift")
            evaluation[key], comparable_eval = run_fold(test_cases, depth, evaluation_rounds,
                                                       fold="holdout", workload=key)
            holdout_predictions[key] = {
                "case_ids":[c.case_id for c in test_cases],
                "predictions":[r["probabilities"] for r in comparable_eval],
                "selected_batch_size":selected[key]["batch_size"]}
        prediction_sha = e.write_once(output/"holdout-predictions.json",{
            "selection_sha256":choice_seal,"records":holdout_predictions,
            "before_any_holdout_score":True})
        eval_sha = e.write_once(output/"evaluation.json",{
            "selection_sha256":choice_seal, "prediction_sha256":prediction_sha,
            "source_groups":sources["holdout"],"measurements":evaluation,
            "workloads":workloads,"batch_sizes":BATCHES})
        warmup_seal = e.write_once(output/"warmup-records.json", {"records":warmup_records,
            "training_source_groups":sources["train"], "all_arms_included":True})
        # Only now use held-out labels, and never reselect the batch size.
        scoring = {}
        for profile, count, depth in workloads:
            key = workload_key(profile,count,depth)
            cases=partition["holdout"][profile][:count]
            p=holdout_predictions[key]["predictions"]
            matches=[int(max(range(2),key=lambda j: row[j])==labels[c.case_id])
                     for c,row in zip(cases,p)]
            losses=[-math.log(max(row[labels[c.case_id]],1e-12))
                    for c,row in zip(cases,p)]
            scoring[key]={"correct":sum(matches),"total":len(matches),
                "nll":sum(losses)/len(losses),
                "all_three_schedules_share_predictions":True,
                "accuracy_not_pretrained_CLIP":True}
        summaries={}
        for key in evaluation:
            size=selected[key]["batch_size"]
            metrics={str(b):_summary(evaluation[key][str(b)]) for b in BATCHES}
            summaries[key]={"selected_batch_size":size,"holdout":metrics,
                "selected_wall_median_ns":metrics[str(size)]["wall_median_ns"],
                "scalar_wall_median_ns":metrics["1"]["wall_median_ns"],
                "selected_vs_scalar_speed_ratio":metrics["1"]["wall_median_ns"]/metrics[str(size)]["wall_median_ns"],
                "selected_is_faster_on_holdout":metrics[str(size)]["wall_median_ns"] < metrics["1"]["wall_median_ns"]}
        total_wall=time.perf_counter_ns()-clock_start
        report={"schema":"hepta.video-source-disjoint-cpu-autotune.v1",
            "protocol_sha256":seal,"calibration_sha256":cal_seal,
            "selection_sha256":choice_seal,"holdout_prediction_sha256":prediction_sha,
            "evaluation_sha256":eval_sha,"warmup_sha256":warmup_seal,
            "frozen_proxy_sha256":frozen_identity["sha256"],
            "reader_sha256":reader_identity["sha256"],"manifest_sha256":e.sha(manifest_raw),
            "source_groups":sources,"holdout_scores":scoring,"summary":summaries,
            "all_arms_execution_wall_ns":charged_ns,"warmup_wall_ns":warmup_ns,
            "whole_study_wall_ns_excludes_report_write":total_wall,
            "arm_execution_count_including_warmups":all_runs,
            "all_arms_including_warmups_physical_calls": charged_calls + warmup_calls,
            "all_arms_including_warmups_encoded_frames":charged_frames + warmup_frames,
            "all_arms_including_warmups_conv_ns":charged_conv_ns + warmup_conv_ns,
            "all_arms_including_warmups_preprocess_ns":charged_preprocess_ns + warmup_preprocess_ns,
            "all_arms_including_warmups_file_bytes":charged_source_bytes + warmup_source_bytes,
            "all_workload_physical_calls_plus_training":charged_calls + warmup_calls + training_work["training_physical_tower_calls"],
            "all_workload_encoded_frames_plus_training":charged_frames + warmup_frames + training_work["training_unique_frames"],
            "all_reference_arms_and_calibration_included_in_ledger":True,
            "training_and_validation_included_in_study_wall":True,
            "all_reference_arms_physically_executed_and_charged":True,
            "all_cell_arrivals_assumed_at_t0":True,
            "group_completion_times_exclude_non_group_wrapper_overhead":True,
            "pretrained_clip_executed":False,"real_clip_latency_savings_established":False,
            "independent_future_population_quality":False,
            "no_cost_energy_meter":True,"peak_rss_bytes":None,"energy_joules":None,
            "production_accepted":False}
        e.write_once(output/"report.json",report)
        return report
    except Exception as err:
        e.write_once(output/"failure.json",{"error":type(err).__name__,"message":str(err),
                                                  "production_accepted":False})
        raise


def _compare_fixed(reference,candidate):
    if [r["case_id"] for r in reference] != [r["case_id"] for r in candidate]:
        raise e.InputError("different Cell coverage")
    for a,b in zip(reference,candidate):
        if a["prediction"] != b["prediction"] or max(abs(x-y) for x,y in
            zip(a["probabilities"],b["probabilities"]))>2e-5:
            raise e.InputError("fixed reader prediction differs across batch schedules")


def _summary(runs):
    walls=sorted(x["wall_ns"] for x in runs)
    first=sorted(x["first_group_completion_ns"] for x in runs)
    p95=sorted(x["group_completion_p95_ns"] for x in runs)
    return {"wall_median_ns":int(statistics.median(walls)),
            "wall_p95_across_runs_ns":_rank(walls,95),
            "wall_p99_across_runs_ns":_rank(walls,99),
            "first_group_completion_median_ns":int(statistics.median(first)),
            "group_p95_completion_median_ns":int(statistics.median(p95)),
            "physical_call_samples":[x["physical_forward_calls"] for x in runs],
            "unique_frame_samples":[x["unique_frames"] for x in runs],
            "all_percentiles_descriptive_only":True}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--calibration-rounds",type=int,default=3)
    parser.add_argument("--evaluation-rounds",type=int,default=5)
    args=parser.parse_args()
    torch.set_num_threads(1)
    run(args.root,args.output,calibration_rounds=args.calibration_rounds,
        evaluation_rounds=args.evaluation_rounds)
