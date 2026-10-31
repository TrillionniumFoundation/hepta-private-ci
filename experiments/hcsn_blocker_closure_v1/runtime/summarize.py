"""Describe an existing runtime cohort; never run or select experiments."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time


T975_DF31 = 2.0395134463964077


def interval(values):
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    half = T975_DF31*sd/len(values)**.5
    return dict(n=len(values), mean=mean, sample_sd=sd,
                descriptive_seed_cluster_t95=[mean-half, mean+half])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start = time.process_time()
    raw = (args.directory/"RESULT.json").read_bytes()
    result = json.loads(raw)
    cost = json.loads((args.directory/"WHOLE_WORKER_COST.json").read_bytes())
    records = result["records"]
    if len({row["seed"] for row in records}) != 32 or len(records) != 160 or result["preflight"]:
        raise ValueError("The descriptive interval is declared only for the 32-seed main cohort")
    summaries = {}
    for arm in result["summary"]:
        group = [row for row in records if row["arm"] == arm]
        summaries[arm] = dict(result["summary"][arm],
            return_interval=interval([row["infinite_horizon_estimate"] for row in group]),
            observed_only_interval=interval([row["observed_discounted_return"] for row in group]),
            mean_model_based_tail=statistics.mean(row["model_based_tail"] for row in group))
    paired = {arm: {row["seed"]: row for row in records if row["arm"] == arm} for arm in summaries}
    differences = {}
    for control in ("best_fixed_threshold", "reset_omitted", "always_fire", "fixed_confidence_0.8"):
        differences[control] = {
            key: interval([paired["task_qvi"][seed][key]-paired[control][seed][key]
                           for seed in sorted(paired["task_qvi"])])
            for key in ("infinite_horizon_estimate", "observed_discounted_return")}
        differences[control]["exact_value_difference"] = summaries["task_qvi"]["exact_policy_value"]-summaries[control]["exact_policy_value"]
    counters = {key: sum(row["native_execution"]["counters"][key] for row in records)
                for key in records[0]["native_execution"]["counters"]}
    summary = dict(schema="hcsn-task-runtime-summary.v1", source_result_sha256=hashlib.sha256(raw).hexdigest(),
        checks=result["checks"], all_execution_gates_pass=result["all_execution_gates_pass"],
        protocol_sha256=result["protocol_sha256"], native_binary_sha256=result["runtime_binary_sha256"],
        native_processes=len(records), regenerative_cycles=sum(row["cycles"] for row in records),
        counters=counters, summary=summaries, paired_qvi_minus_control=differences,
        whole_worker_cost=cost, analysis_self_cpu_seconds=time.process_time()-start,
        multiple_testing="Descriptive only; no generalization or architecture-superiority gate is based on these intervals.",
        hardware_energy_joules=None, gpu_executed=False, trained_content_model=False,
        statistical_units="32 fixed seeds per arm; four cycles within each seed, not 128 independent estimates",
        tail_warning="Return estimates include an exact model-based continuation after the fourth refractory period. Observed-only values are separate.")
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps(dict(native_processes=len(records), cycles=summary["regenerative_cycles"],
                         actual_ticks=counters["owner_ticks"], paired=differences), sort_keys=True))


if __name__ == "__main__":
    main()
