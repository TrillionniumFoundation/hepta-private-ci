"""Separate frozen cost supplement for the real spike-feedback CTMC policy.

`check` runs only a small API/state/replay contract check; it does not produce
performance estimates. `run` is reserved for the coordinator-authorized stage
after both evaluation matrices and the unchanged main cost matrix finish.

The native CoupledSpikePolicy.step implementation is used unchanged, including
its inference-time path statistics and score calculation. All actual jumps,
trace feedback, observation remaps and the 81-action head are included.
"""
from __future__ import annotations

import argparse
from dataclasses import fields
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
MAIN = ROOT.parent
sys.path.insert(0, str(MAIN.parent))

from rrsnn_v2 import benchmark as main_benchmark
from rrsnn_v2 import benchmark_resource_observer as observer

PROTOCOL = ROOT / "benchmark_protocol.json"
DESTINATION = ROOT / "benchmark_results"
CHECKPOINT = ROOT / "results/equal_cpu/seed_101/model.pt"
RUN_NAME = "rr_coupled_full_path_equal_cpu"


def protocol():
    value = json.loads(PROTOCOL.read_text())
    if (value["seed"] != 101 or value["milestone"] != "equal_cpu"
            or value["rows"] != [64, 256, 1024, 4096]
            or value["warmup_sequences"] != 5 or value["timed_sequences"] != 25
            or value["observations_per_sequence"] != 8
            or value["primary_timed_tick_samples"] != 200
            or value["microbatch"] != 256 or value["cpu_affinity"] != [7]):
        raise ValueError("The independent coupled benchmark contract changed")
    for name, expected in value["frozen_source_sha256"].items():
        if observer.digest(MAIN / name) != expected:
            raise ValueError(f"Frozen execution source changed: {name}")
    return value


def load_policy():
    import torch
    from rrsnn_v2.coupled.model import CoupledSpikePolicy

    contract = protocol()
    receipt_path = CHECKPOINT.with_name("training.json")
    receipt = json.loads(receipt_path.read_text())
    if (receipt["milestone"] != "equal_cpu" or receipt["seed"] != 101
            or receipt["checkpoint_sha256"] != observer.digest(CHECKPOINT)
            or observer.digest(CHECKPOINT) != contract["checkpoint_sha256"]
            or observer.digest(receipt_path) != contract["training_receipt_sha256"]):
        raise ValueError("Coupled benchmark checkpoint/receipt identity changed")
    blob = torch.load(CHECKPOINT, map_location="cpu", weights_only=True)
    model = CoupledSpikePolicy()
    model.load_state_dict(blob["state_dict"])
    model.eval()
    if sum(p.numel() for p in model.parameters()) != 977:
        raise ValueError("The coupled architecture parameter count changed")
    return model, {"checkpoint": str(CHECKPOINT),
                   "checkpoint_sha256": observer.digest(CHECKPOINT),
                   "training_receipt_sha256": observer.digest(receipt_path),
                   "milestone": "equal_cpu", "seed": 101,
                   "train_cpu_seconds": receipt["train_cpu_seconds"],
                   "equal_cpu_target_seconds": receipt["equal_cpu_target_seconds"],
                   "cpu_budget_overshoot_seconds": receipt["cpu_budget_overshoot_seconds"],
                   "trained_weights": True}


def state_storage(states):
    import numpy as np
    import torch

    components = {}
    total_rows = 0
    for state in states:
        total_rows += len(state.indices)
        for field in fields(state):
            item = getattr(state, field.name)
            if isinstance(item, np.ndarray):
                size = item.nbytes
                dtype = str(item.dtype)
            elif torch.is_tensor(item):
                size = item.numel() * item.element_size()
                dtype = str(item.dtype)
            else:
                raise TypeError(f"Unaccounted coupled persistent state: {field.name}")
            entry = components.setdefault(field.name, {"bytes": 0, "dtype": dtype})
            if entry["dtype"] != dtype:
                raise TypeError("Inconsistent state dtype across microbatches")
            entry["bytes"] += size
    total = sum(entry["bytes"] for entry in components.values())
    return {"resident_numeric_components": components,
            "persistent_numeric_state_bytes": total,
            "persistent_numeric_state_bytes_per_row": total / total_rows,
            "resident_rows": total_rows,
            "scope": "Actual persistent numeric arrays/tensors of the native coupled inference state",
            "excluded": "Shared parameters/grid buffer, RNG/Python objects, input/output storage, temporary Q/remap/Nij/dwell/score calculations and process overhead"}


class CoupledStreamingExecutor:
    def __init__(self, model, x, dt, mask, microbatch=256):
        self.model, self.x, self.dt, self.mask = model, x, dt, mask
        self.batch, self.steps, _ = x.shape
        self.microbatch = min(microbatch, self.batch)
        self.ranges = [(lo, min(lo + self.microbatch, self.batch))
                       for lo in range(0, self.batch, self.microbatch)]

    def run(self, seed, *, measure=True, return_states=False):
        import numpy as np
        import torch

        output = torch.empty(self.batch, self.steps, 81, dtype=self.x.dtype)
        generators = [np.random.default_rng(seed + 100003 * index)
                      for index in range(len(self.ranges))]
        # Construct and retain every row's state before the first timed tick.
        states = [self.model.initial_state(hi - lo, generators[index])
                  for index, (lo, hi) in enumerate(self.ranges)]
        initial_storage = state_storage(states)
        if initial_storage["resident_rows"] != self.batch:
            raise AssertionError("Not all states are simultaneously resident")
        tick_wall, tick_cpu, tick_counts = [], [], []
        for position in range(self.steps):
            if measure:
                start_wall, start_cpu = time.perf_counter(), time.process_time()
            counts = 0
            for index, (lo, hi) in enumerate(self.ranges):
                states[index], current = self.model.step(
                    states[index], self.x[lo:hi, position], self.dt[lo:hi, position],
                    generators[index], self.mask[lo:hi, position],
                    record_spikes=False, record_path=False)
                output[lo:hi, position] = current["logits"]
                counts += int(current["actual_counts"].sum())
            if measure:
                tick_cpu.append(time.process_time() - start_cpu)
                tick_wall.append(time.perf_counter() - start_wall)
            tick_counts.append(counts)
        final_storage = state_storage(states)
        if final_storage != initial_storage:
            raise AssertionError("Persistent numeric state layout changed during inference")
        result = {**final_storage, "rng_objects": len(generators),
                  "tick_wall_seconds": tick_wall, "tick_cpu_seconds": tick_cpu,
                  "tick_counts": tick_counts, "count_sum": sum(tick_counts),
                  "timing_enabled": measure,
                  "all_row_states_resident_simultaneously": True}
        if return_states:
            result["final_states"] = states
        return output, result


def ready_for_formal():
    # The aggregate programs already reject incomplete/unlocked matrices.
    evidence = [MAIN / "results/aggregate.json", ROOT / "results/aggregate.json"]
    for path in evidence:
        if not path.exists():
            raise RuntimeError(f"Wait for coordinated training/evaluation completion: {path}")
    main_cost = MAIN / "benchmark_results/scaling_results.json"
    if not main_cost.exists():
        raise RuntimeError("Run the unchanged main cost matrix before this supplement")
    rows = json.loads(main_cost.read_text()).get("results", [])
    actual = {(row.get("run_name"), row.get("mode"), row.get("rows")) for row in rows
              if row.get("formal") and row.get("seed") == 101
              and row.get("resource_observation")}
    main_protocol = json.loads((MAIN / "benchmark_protocol.json").read_text())
    expected = {(run.split(":")[0], run.split(":")[1], n)
                for run in main_protocol["primary_and_baseline_runs"]
                for n in main_protocol["rows"]}
    if not expected.issubset(actual):
        raise RuntimeError("The resource-observed main cost matrix is not complete")
    return {str(path.relative_to(MAIN)): observer.digest(path)
            for path in evidence + [main_cost]}


def row_child(args):
    contract = protocol()
    readiness = ready_for_formal()
    if args.rows not in contract["rows"]:
        raise ValueError("Size is outside the frozen coupled protocol")
    torch = main_benchmark.setup(7)
    import numpy as np
    if sorted(os.sched_getaffinity(0)) != [7]:
        raise RuntimeError("Formal coupled costs require CPU 7")
    baseline_rss = main_benchmark.rss()
    model, provenance = load_policy()
    after_model_rss = main_benchmark.rss()
    x, dt, mask, input_provenance = main_benchmark.observed_inputs(args.rows)
    executor = CoupledStreamingExecutor(model, x, dt, mask, 256)
    before_run_rss = main_benchmark.rss()
    load_before = os.getloadavg()
    sequence_wall, sequence_cpu, checksums, counts = [], [], [], []
    tick_wall, tick_cpu, tick_counts = [], [], []
    with torch.inference_mode():
        for repetition in range(5):
            result, state_info = executor.run(101 + 7000000 + repetition)
            _ = float(result.sum())
            del result
        for repetition in range(25):
            start_wall, start_cpu = time.perf_counter(), time.process_time()
            result, state_info = executor.run(101 + 8000000 + repetition)
            checksum = float(result.sum())
            sequence_cpu.append(time.process_time() - start_cpu)
            sequence_wall.append(time.perf_counter() - start_wall)
            checksums.append(checksum)
            counts.append(state_info["count_sum"])
            tick_wall.append(state_info["tick_wall_seconds"])
            tick_cpu.append(state_info["tick_cpu_seconds"])
            tick_counts.append(state_info["tick_counts"])
            del result
    after_rss = main_benchmark.rss()
    tick_array = np.asarray(tick_wall)
    if tick_array.shape != (25, 8):
        raise AssertionError("The formal tick sample count changed")
    tick_quantiles = np.percentile(tick_array * 1000, [50, 95, 99])
    sequence_quantiles = np.percentile(np.asarray(sequence_wall) * 1000, [50, 95, 99])
    positions = []
    for index in range(8):
        values, multiplicity = np.unique(dt[:, index].numpy(), return_counts=True)
        quantiles = np.percentile(tick_array[:, index] * 1000, [50, 95, 99])
        positions.append({"position": index, "latency_samples": 25,
                          "latency_ms_p50": float(quantiles[0]),
                          "latency_ms_p95": float(quantiles[1]),
                          "latency_ms_p99_exploratory": float(quantiles[2]),
                          "dt_histogram": [{"dt": float(v), "rows": int(n)}
                                           for v, n in zip(values, multiplicity)]})
    state_info = {key: value for key, value in state_info.items()
                  if key not in ["tick_wall_seconds", "tick_cpu_seconds", "tick_counts"]}
    row = {"schema": "rrsnn.coupled.tick-and-sequence-cost.v1", "formal": True,
           "run_name": RUN_NAME, "mode": "coupled_real_ctmc_path", "milestone": "equal_cpu",
           "seed": 101, "rows": args.rows, "observations_per_row": 8,
           "microbatch": executor.microbatch, "microbatches": len(executor.ranges),
           "scope": "Scratch CPU policy instances with actual spike-trace feedback, not production Hepta Cells",
           "parameters_shared": True, "row_states_independent": True,
           "primary_tick_cost_unit": "One observation for all N resident rows, including every microbatch's real CTMC propagation, trace feedback, remap, native path score and 81-action head",
           "secondary_sequence_cost_unit": "Initialize all row states, stream eight observations, retain logits and reduce checksums/counts",
           "initialization_in_sequence_timing": True, "initialization_in_tick_timing": False,
           "spike_timestamp_recording": False, "full_path_record_retained": False,
           "inference_path_score_computed": True,
           "inference_path_statistics_computed": "Native implementation allocates Nij and dwell statistics and computes interval/initial/remap log scores even under inference_mode; this avoidable reference-implementation work is included, not optimized away",
           "event_semantics": "All finite-CTMC jump times are sampled; actual spike times update trace, which controls future observations and the current readout",
           "feedback_semantics": "Coefficients held within intervals; true-observation boundaries refresh control from actual trace; current remap spikes enter head now and recurrent feedback at the next observation",
           "warmup_sequences": 5, "timed_sequences": 25, "timed_tick_samples": 200,
           "tick_latency_ms_raw_25_by_8": (tick_array * 1000).tolist(),
           "tick_latency_ms_p50": float(tick_quantiles[0]),
           "tick_latency_ms_p95": float(tick_quantiles[1]),
           "tick_latency_ms_p99": float(tick_quantiles[2]),
           "tick_latency_ms_mean": float(tick_array.mean() * 1000),
           "tick_process_cpu_seconds_raw": tick_cpu,
           "tick_process_cpu_seconds_mean": float(np.asarray(tick_cpu).mean()),
           "tick_positions_and_dt_mixture": positions,
           "whole_sequence_latency_ms_raw": [v * 1000 for v in sequence_wall],
           "whole_sequence_latency_ms_p50": float(sequence_quantiles[0]),
           "whole_sequence_latency_ms_p95": float(sequence_quantiles[1]),
           "whole_sequence_latency_ms_p99_exploratory": float(sequence_quantiles[2]),
           "whole_sequence_latency_ms_mean": float(np.mean(sequence_wall) * 1000),
           "process_cpu_seconds_raw": sequence_cpu,
           "process_cpu_seconds_mean": float(np.mean(sequence_cpu)),
           "row_ticks_per_second": float(args.rows / tick_array.mean()),
           "eight_step_rows_per_second": float(args.rows / np.mean(sequence_wall)),
           "internal_count_sum_raw": counts, "internal_count_by_tick": tick_counts,
           "internal_counts_per_tick_processing_second": float(np.sum(counts) / tick_array.sum()),
           "output_checksum_min": min(checksums), "output_checksum_max": max(checksums),
           "model_metadata": model.metadata(), "trainable_parameters_including_head": 977,
           "shared_parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
           "shared_constant_buffer_bytes": sum(b.numel() * b.element_size() for b in model.buffers()),
           **state_info,
           "input_tensor_bytes": sum(t.numel() * t.element_size() for t in [x, dt, mask]),
           "retained_logit_output_bytes": args.rows * 8 * 81 * x.element_size(),
           "temporary_allocation_accounting": "Temporary Q/remap/path statistics/score workspace, RNG, Python and allocator overhead are included in isolated-process RSS, not an asserted exact temporary tensor sum",
           "rss_after_imports_bytes": baseline_rss, "rss_after_model_bytes": after_model_rss,
           "rss_before_warmup_bytes": before_run_rss, "rss_after_measurement_bytes": after_rss,
           "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
           "rss_high_water_increase_from_pre_run_bytes": max(0, after_rss["VmHWM"] - before_run_rss["VmRSS"]),
           "checkpoint": provenance, "input_provenance": input_provenance,
           "source_sha256": contract["frozen_source_sha256"],
           "benchmark_protocol_sha256": observer.digest(PROTOCOL),
           "completion_evidence_sha256": readiness,
           "runtime": {"python": platform.python_version(), "torch": str(torch.__version__),
                       "platform": platform.platform(), "threads": torch.get_num_threads(),
                       "affinity": list(os.sched_getaffinity(0)),
                       "loadavg_before": list(load_before), "loadavg_after": list(os.getloadavg())},
           "limitations": contract["limitations"]}
    observer.write_json(args.output, row)
    print(json.dumps({"completed_row": args.rows, "output": str(args.output),
                      "tick_p99_ms": row["tick_latency_ms_p99"],
                      "persistent_numeric_bytes_per_row": row["persistent_numeric_state_bytes_per_row"]}), flush=True)


def aggregate():
    rows = []
    for sidecar in sorted((DESTINATION / "resource_observations").glob("*.json")):
        record = json.loads(sidecar.read_text())
        path = DESTINATION / "runs" / sidecar.name
        if (record.get("status") != "child_finished" or not path.exists()
                or record.get("row_sha256") != observer.digest(path)):
            continue
        row = json.loads(path.read_text())
        row["resource_observation"] = {"path": str(sidecar), "sha256": observer.digest(sidecar),
                                       **record["resource_window"]}
        rows.append(row)
    complete = {r["rows"] for r in rows} == {64, 256, 1024, 4096}
    observer.write_json(DESTINATION / "scaling_results.json", {
        "schema": "rrsnn.coupled.resource-observed-cost-matrix.v1", "formal": True,
        "separate_from_frozen_main_matrix": True, "run_name": RUN_NAME, "seed": 101,
        "results": rows, "primary_resource_results": [r for r in rows
            if r["resource_observation"]["primary_resource_table_eligible"]],
        "pressure_or_unknown_rows": sum(not r["resource_observation"]["primary_resource_table_eligible"]
                                        for r in rows),
        "requested_rows": [64, 256, 1024, 4096], "all_rows_complete": complete,
        "protocol_sha256": observer.digest(PROTOCOL),
        "observer_sha256": observer.digest(MAIN / "benchmark_resource_observer.py"),
        "qualification": "Same observer snapshots/classification as the main matrix. All completed windows and raw ticks retained; pressure is not attributed uniquely to the child. No outlier removal."})


def run_rows(args):
    protocol()
    ready_for_formal()
    observation_dir = DESTINATION / "resource_observations"
    for n in [64, 256, 1024, 4096]:
        key = f"{RUN_NAME}_coupled_real_ctmc_path_seed101_b{n}"
        output = DESTINATION / "runs" / f"{key}.json"
        sidecar = observation_dir / f"{key}.json"
        expected = {"checkpoint_sha256": observer.digest(CHECKPOINT),
                    "benchmark_sha256": observer.digest(Path(__file__).resolve()),
                    "protocol_sha256": observer.digest(PROTOCOL),
                    "observer_sha256": observer.digest(MAIN / "benchmark_resource_observer.py")}
        if output.exists() and sidecar.exists() and not args.rerun:
            saved = json.loads(sidecar.read_text())
            if (saved.get("expected_sources") == expected
                    and saved.get("row_sha256") == observer.digest(output)
                    and saved.get("resource_window", {}).get("primary_resource_table_eligible")):
                continue
        old_row = observer.retain_preexisting(output, observation_dir / "retained_prior_attempts")
        old_sidecar = observer.retain_preexisting(sidecar, observation_dir / "retained_prior_attempts")
        log = observation_dir / "logs" / f"{key}.log"
        old_log = observer.retain_preexisting(log, observation_dir / "retained_prior_attempts")
        log.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(Path(__file__).resolve()), "_row",
                   "--rows", str(n), "--output", str(output)]
        before = observer.snapshot()
        record = {"schema": "rrsnn.coupled.benchmark-resource-window.v1", "status": "child_starting",
                  "run_name": RUN_NAME, "mode": "coupled_real_ctmc_path", "rows": n, "seed": 101,
                  "expected_sources": expected, "before": before, "command": command,
                  "child_log": str(log), "prior_row_preserved_as": old_row,
                  "prior_sidecar_preserved_as": old_sidecar, "prior_log_preserved_as": old_log}
        observer.write_json(sidecar, record)
        print(json.dumps({"starting_observed_coupled_row": n,
                          "memory_current": before["memory"].get("memory.current")}), flush=True)
        error, code = None, -1
        try:
            with log.open("w") as handle:
                code = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT,
                                      check=False).returncode
        except Exception as exception:
            error = repr(exception)
        after = observer.snapshot()
        record.update(status="child_finished", after=after, execution_error=error,
                      resource_window=observer.summarize_window(before, after, code),
                      row_sha256=observer.digest(output) if output.exists() and code == 0 else None,
                      observer_sha256=observer.digest(MAIN / "benchmark_resource_observer.py"))
        observer.write_json(sidecar, record)
        aggregate()
        print(json.dumps({"completed_observed_coupled_row": n, "returncode": code,
                          "resource_condition": record["resource_window"]["condition"]}), flush=True)
        if code != 0:
            raise RuntimeError(f"Coupled benchmark failed; raw log/window preserved: {sidecar}")
    aggregate()


def contract_check(args):
    contract = protocol()
    torch = main_benchmark.setup(args.cpu)
    import numpy as np
    model, provenance = load_policy()
    x, dt, mask, input_provenance = main_benchmark.observed_inputs(3)
    executor = CoupledStreamingExecutor(model, x, dt, mask, microbatch=2)
    seed = 880101
    max_logit_error, max_state_error = 0., 0.
    with torch.inference_mode():
        streamed, info = executor.run(seed, measure=False, return_states=True)
        direct_count = 0
        for index, (lo, hi) in enumerate(executor.ranges):
            rng = np.random.default_rng(seed + 100003 * index)
            direct = model(x[lo:hi], dt[lo:hi], mask[lo:hi], rng=rng,
                           record_spikes=False, record_path=False)
            max_logit_error = max(max_logit_error,
                                  float((streamed[lo:hi] - direct["logits"]).abs().max()))
            direct_count += int(direct["actual_counts"].sum())
            for field in fields(direct["state"]):
                left = getattr(info["final_states"][index], field.name)
                right = getattr(direct["state"], field.name)
                if torch.is_tensor(left):
                    error = float((left - right).abs().max())
                else:
                    error = float(np.max(np.abs(left.astype(float) - right.astype(float))))
                max_state_error = max(max_state_error, error)
            if direct["spike_times"]:
                raise AssertionError("Performance API unexpectedly retained timestamp dictionaries")
        if (max_logit_error != 0 or max_state_error != 0 or direct_count != info["count_sum"]
                or info["persistent_numeric_state_bytes_per_row"] != 305
                or info["rng_objects"] != 2 or info["resident_rows"] != 3
                or info["tick_wall_seconds"] or info["tick_cpu_seconds"]):
            raise AssertionError("Native coupled streaming/replay/accounting contract failed")
    report = {"schema": "rrsnn.coupled.benchmark-contract-check.v1", "passed": True,
              "utc": datetime.now(timezone.utc).isoformat(),
              "scope": "One three-row, eight-observation API/replay/state-accounting check; no formal cost estimates",
              "rows": 3, "microbatch": 2, "observations": 8,
              "streamed_vs_native_forward_logit_max_abs": max_logit_error,
              "streamed_vs_native_forward_state_max_abs": max_state_error,
              "actual_spike_count_equal": True, "actual_spikes": direct_count,
              "all_states_resident_before_first_tick": True,
              "persistent_numeric_state_bytes_per_row": info["persistent_numeric_state_bytes_per_row"],
              "state_components": info["resident_numeric_components"],
              "inference_score_calculation_retained": True,
              "performance_measurement_run": False,
              "checkpoint": provenance, "input_provenance": input_provenance,
              "frozen_source_sha256": contract["frozen_source_sha256"],
              "protocol_sha256": observer.digest(PROTOCOL)}
    observer.write_json(args.output, report)
    print(json.dumps({"contract_passed": True, "numeric_bytes_per_row": 305,
                      "logit_error": max_logit_error, "state_error": max_state_error,
                      "formal_benchmark_started": False, "output": str(args.output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Minimal replay/accounting contract, no cost benchmark")
    check.add_argument("--cpu", type=int, default=6)
    check.add_argument("--output", type=Path, default=ROOT / "benchmark_contract_validation.json")
    run = commands.add_parser("run", help="Only after coordinator authorization and completed main costs")
    run.add_argument("--rerun", action="store_true")
    row = commands.add_parser("_row", help=argparse.SUPPRESS)
    row.add_argument("--rows", type=int, required=True)
    row.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check":
        contract_check(args)
    elif args.command == "run":
        run_rows(args)
    else:
        row_child(args)


if __name__ == "__main__":
    main()
