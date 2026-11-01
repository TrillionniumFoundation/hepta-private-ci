"""Historical fitted-head execution integration, never independent confirmation.

Calibration and a simple cache-level value table use the old validation objects
already used to select the V3 head. This verifies executable integration and
records diagnostic quality; it does not establish calibrated generalization.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, CacheBudget, CorrectnessValue, Modality,
)
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import BinnedCorrectness, LegacyV3Head
from experiments.hcsn_v8_execution_20261101.frontend.replay import episode_arrays, legacy_data, populated_cache
from experiments.hcsn_causal_execution_v3.av_probe import labels_of
from .execution import LogicalClock, RealClock, run_episode
from .historical_service import PreparedPrefixService
from .planning import Plan, Read, ServiceEstimate, Wait


TASKS = ("async_av", "av_binding")
METHODS = ("audio_only_common_head", "common_full", "cache_value")
LEVELS = tuple((a, v) for a in range(4) for v in range(4))


def source_hashes():
    directory = Path(__file__).resolve().parent
    paths = list(directory.glob("*.py")) + list((directory.parent / "frontend").glob("*.py"))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def forecast_key(a, v, probabilities, goal_a, goal_v):
    p = np.asarray(probabilities)
    return f"{a}:{v}:{int(p.argmax())}:{min(4, int(p.max() * 5))}:{goal_a}:{goal_v}"


class EmpiricalForecast:
    kind = BackendKind.DIRECT_HISTORY

    def __init__(self, head, table, fallback):
        self.head, self.table, self.fallback = head, table, fallback
        self.reader_id = "historical-val-cache-table-" + head.task

    def evaluate(self, content, state, plan):
        if plan.requested_reads == 0:
            return self.head.evaluate(content).calibrated_correctness
        a, v = int(content.level(Modality.AUDIO)), int(content.level(Modality.VIDEO))
        goal_a, goal_v = a, v
        for step in plan.steps:
            if type(step) is Read:
                if step.modality == Modality.AUDIO:
                    goal_a = step.prefix_end
                else:
                    goal_v = step.prefix_end
        key = forecast_key(a, v, self.head.classify(content), goal_a, goal_v)
        rate = self.table.get(key, self.fallback[f"{goal_a}:{goal_v}"])
        return CorrectnessValue(rate, self.head.head_id)


class FixedServiceModel:
    """Declared 1 ms/read logical service; not an empirical latency model."""

    def estimate(self, content, plan, now, deadline):
        t, requests = now, 0
        for step in plan.steps:
            if t >= deadline:
                break
            if type(step) is Read:
                requests += 1
                t = max(t, step.prefix_end) + 0.001
            else:
                t += step.seconds
        return ServiceEstimate(min(t, deadline) - now, 0.0, requests)


def fit_development_adapters(task, validation, out):
    start_cpu, start_wall = time.process_time(), time.monotonic()
    head = LegacyV3Head(task)
    labels = labels_of(validation)
    probabilities = {(a, v): np.asarray([head.classify(populated_cache(validation, i, a, v))
                                        for i in range(len(labels))]) for a, v in LEVELS}
    source = hashlib.sha256(json.dumps({"array": validation["metadata"]["array_sha256"],
                                      "head": head.checkpoint_sha256}, sort_keys=True).encode()).hexdigest()
    head.calibrator = BinnedCorrectness.fit(
        head.head_id, np.concatenate([probabilities[level] for level in LEVELS]),
        np.tile(labels, len(LEVELS)), source_sha256=source,
        data_role="historical validation already used for original head selection; development only")
    correct = {level: (p.argmax(1) == labels).astype(float) for level, p in probabilities.items()}
    fallback = {f"{a}:{v}": float((correct[a, v].sum() + 1) / (len(labels) + 2)) for a, v in LEVELS}
    values = {}
    pairs = 0
    for a, v in LEVELS:
        for ga, gv in LEVELS:
            if ga < a or gv < v or (ga, gv) == (a, v):
                continue
            for i in range(len(labels)):
                key = forecast_key(a, v, probabilities[a, v][i], ga, gv)
                count, successes = values.get(key, (0, 0.0))
                values[key] = count + 1, successes + float(correct[ga, gv][i])
                pairs += 1
    table = {key: float((successes + 1) / (count + 2))
             for key, (count, successes) in values.items()}
    record = {"head_id": head.head_id, "calibrator": asdict(head.calibrator),
              "table": table, "table_counts_and_successes": values, "fallback": fallback,
              "validation_objects": len(labels), "paired_training_rows": pairs,
              "independent_fit_count": 0, "scope": "One deterministic development integration fit; not GRU/SSM/analytic fits",
              "source": source, "cpu_seconds": time.process_time() - start_cpu,
              "wall_seconds": time.monotonic() - start_wall,
              "current_and_future_target": "actual 0/1 correctness of the same frozen legacy head",
              "future_feature_access_during_inference": False,
              "known_limitation": "Cache table is a simple diagnostic, not a validated strongest no-core comparator"}
    write_json(out / f"{task}_ADAPTERS.json", record)
    return head, EmpiricalForecast(head, table, fallback), record


def selected_rows(data):
    labels = labels_of(data)
    groups = data["group_ids"].astype(str)
    selected = []
    for actor in sorted(set(groups)):
        for label in sorted(set(labels[groups == actor].tolist())):
            indices = [i for i in range(len(labels)) if groups[i] == actor and labels[i] == label]
            selected.append(min(indices, key=lambda i: str(data["ids"][i])))
    return selected


def source_recordings(data, indices):
    if "audio_source_ids" in data:
        return sorted({str(data[key][i]) for key in ("audio_source_ids", "video_source_ids") for i in indices})
    return sorted({str(data["ids"][i]) for i in indices})


def fixed_plans(method):
    if method == "cache_value":
        return None
    steps = ((Read(Modality.AUDIO, 2), Read(Modality.AUDIO, 3))
             if method == "audio_only_common_head" else
             (Read(Modality.VIDEO, 1), Read(Modality.AUDIO, 2), Read(Modality.VIDEO, 2),
              Read(Modality.AUDIO, 3), Read(Modality.VIDEO, 3)))
    return (Plan(steps),)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--logical-only", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    before = source_hashes()
    data = {task: legacy_data(task, "test") for task in TASKS}
    cohorts = {task: selected_rows(data[task]) for task in TASKS}
    live = {}
    for task in TASKS:
        labels = labels_of(data[task])
        actors = sorted(set(data[task]["group_ids"].astype(str)))[:2]
        selected_labels = sorted(set(labels.tolist()))[:2]
        live[task] = [i for i in cohorts[task] if str(data[task]["group_ids"][i]) in actors
                      and int(labels[i]) in selected_labels]
    protocol = {"schema": "hcsn-v8-historical-scheduler-protocol.v1", "sources": before,
                "tasks": list(TASKS), "methods": list(METHODS),
                "cohort_rule": "First lexicographic historical object ID within every actor/label cell; chosen before prediction",
                "logical_indices": cohorts, "live_indices": live, "live_method": "common_full",
                "live_rule": "First two actors crossed with first two available labels, each task",
                "deadline_seconds": 4.0, "logical_service_seconds": 0.001,
                "clock_scope": "Logical replay quality and real source-release/array-copy execution measured separately",
                "raw_acquisition_and_original_feature_preparation_measured": False,
                "calibration_role": "Old validation already used by original head selection; not out-of-fit qualification",
                "strong_audio_reference_available": False,
                "audio_mode_scope": "Audio-only execution of the shared old joint head; not the missing V6 strong audio head",
                "source_recordings": {task: source_recordings(data[task], cohorts[task]) for task in TASKS},
                "input_array_sha256": {task: data[task]["metadata"]["array_sha256"] for task in TASKS},
                "scientific_confirmation": False, "fresh_cohort": False,
                "quality_gate_admitted": False, "independent_training_fits": 0,
                "source_time_semantics": "Global max accepted source prefix; second modality at same prefix adds zero propagation time"}
    write_json(args.out / "PROTOCOL.json", protocol)
    rows, live_rows, adapter_records = [], [], {}
    for task in TASKS:
        head, forecast, fit = fit_development_adapters(task, legacy_data(task, "val"), args.out)
        adapter_records[task] = {k: fit[k] for k in ("cpu_seconds", "wall_seconds", "validation_objects", "paired_training_rows")}
        labels = labels_of(data[task])
        for index in cohorts[task]:
            arrays = episode_arrays(data[task], index)
            for method in METHODS:
                object_id = f"historical-{task}-{index}-{method}"
                captured = []
                result = run_episode(
                    object_id, CacheBudget(65536), head, forecast, FixedServiceModel(),
                    PreparedPrefixService(*arrays, object_id), captured.append, clock=LogicalClock(),
                    horizon=6 if method != "cache_value" else 2,
                    wait_seconds=() if method != "cache_value" else (0.05,), fixed_plans=fixed_plans(method))
                correct = result["output"]["predicted_class"] == int(labels[index])
                expected = None
                if method != "cache_value":
                    cache = populated_cache(data[task], index, 3, 0 if method == "audio_only_common_head" else 3)
                    expected = head.classify(cache)
                    if not np.array_equal(np.asarray(result["output"]["probabilities"]), expected):
                        raise AssertionError("Actual scheduler and standalone head disagree")
                row = {"task": task, "index": index, "actor": str(data[task]["group_ids"][index]),
                       "method": method, "label": int(labels[index]), "correct": bool(correct),
                       "prediction": result["output"]["predicted_class"], "requests": result["requested_observations"],
                       "logical_output_seconds": result["output_elapsed_seconds"],
                       "utility": float(correct - result["observation_fee"] - result["latency_fee"] - result["deadline_penalty"]),
                       "source_id": str(data[task]["ids"][index]), "frozen_schedule_parity": expected is not None}
                rows.append(row)
                write_json(args.out / f"logical-{task}-{index}-{method}.json", result)
            if not args.logical_only and index in live[task]:
                object_id = f"historical-live-{task}-{index}"
                result = run_episode(
                    object_id, CacheBudget(65536), head, forecast, FixedServiceModel(),
                    PreparedPrefixService(*arrays, object_id),
                    lambda payload: (sys.stdout.buffer.write(payload), sys.stdout.buffer.flush()),
                    clock=RealClock(), horizon=6, fixed_plans=fixed_plans("common_full"))
                print(json.dumps({"kind": "episode_output", "episode_id": object_id,
                                  "source_monotonic_ns": result["source_monotonic_ns"],
                                  "output_flush_monotonic_ns": result["output_flush_monotonic_ns"]}), flush=True)
                expected = head.classify(populated_cache(data[task], index, 3, 3))
                row = {"task": task, "index": index, "actor": str(data[task]["group_ids"][index]),
                       "label": int(labels[index]), "requests": result["requested_observations"],
                       "accepted_events": len(result["source_window_updates"]),
                       "correct": result["output"]["predicted_class"] == int(labels[index]),
                       "source_to_flush_seconds": result["output_elapsed_seconds"],
                       "timely": result["timely_output"],
                       "standalone_parity": bool(np.array_equal(result["output"]["probabilities"], expected))}
                live_rows.append(row)
                write_json(args.out / f"live-{task}-{index}.json", result)
    groups = []
    for task in TASKS:
        for method in METHODS:
            selected = [r for r in rows if r["task"] == task and r["method"] == method]
            groups.append({"task": task, "method": method, "objects": len(selected),
                           "correct": sum(r["correct"] for r in selected),
                           "accuracy": float(np.mean([r["correct"] for r in selected])),
                           "mean_logical_utility": float(np.mean([r["utility"] for r in selected])),
                           "mean_requested_reads": float(np.mean([r["requests"] for r in selected]))})
    summary = {"scope": "Historical development execution integration; no new confirmation or architecture claim",
               "logical_groups": groups, "logical_rows": rows, "live_rows": live_rows,
               "live_count": len(live_rows), "all_live_complete": all(r["requests"] == r["accepted_events"] == 6 for r in live_rows),
               "all_live_timely": all(r["timely"] for r in live_rows),
               "all_live_head_parity": all(r["standalone_parity"] for r in live_rows),
               "source_unchanged": before == source_hashes(), "adapter_fit_costs_nested": adapter_records,
               "unique_source_recordings_per_task": {t: len(protocol["source_recordings"][t]) for t in TASKS},
               "unique_source_recordings_union": len(set(sum(protocol["source_recordings"].values(), []))),
               "actual_model_cpu_scope": "Use enclosing complete process receipt once; fits, head calls and traces are nested",
               "complete_economic_claim": False, "strong_audio_reference_available": False,
               "energy_joules": None, "fresh_confirmation": False, "D_minus_B_measured": False}
    write_json(args.out / "SUMMARY.json", summary)
    print(json.dumps({"kind": "summary", "logical_groups": groups,
                      "live_count": len(live_rows), "source_unchanged": summary["source_unchanged"]}), flush=True)
    if not summary["source_unchanged"] or not summary["all_live_complete"] or not summary["all_live_head_parity"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
