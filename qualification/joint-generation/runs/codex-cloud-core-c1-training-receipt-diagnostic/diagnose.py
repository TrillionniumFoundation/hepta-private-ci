"""Administrative analysis of saved TRAIN receipts; no model/data imports."""

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import statistics
import subprocess
import time


START = datetime.now(timezone.utc).isoformat()
CPU, WALL = time.process_time_ns(), time.perf_counter_ns()
CHILD = resource.getrusage(resource.RUSAGE_CHILDREN)
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
RUN = ROOT / "runs/codex-cloud-core-c1-t2"
COMMAND = ("PYTHONDONTWRITEBYTECODE=1 python "
           "runs/codex-cloud-core-c1-training-receipt-diagnostic/diagnose.py")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    with (OUT / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


inputs = {name: {"sha256": digest(RUN / name), "bytes": (RUN / name).stat().st_size}
          for name in ("selection.json", "telemetry.json")}
selection = json.loads((RUN / "selection.json").read_text())
telemetry = json.loads((RUN / "telemetry.json").read_text())
calibration = selection["common"]["calibrations"]
shared = [phase for phase in telemetry["phases"] if phase["phase"] == "shared_preparation"]
assert len(shared) == 1
save("raw-train-calibration.json", calibration)
save("shared-preparation-telemetry.json", shared[0])
source_files = ("independent/run.py", "independent/refinement.py", "independent/evaluation.py")
source_hashes = {name: {"current_sha256": digest(ROOT / name),
                       "frozen_sha256": selection["sources"][name]}
                 for name in source_files}
assert all(row["current_sha256"] == row["frozen_sha256"] for row in source_hashes.values())
repeat_rows, batch_rows, sample_rows, seed_summary = [], [], [], {}
for seed in selection["plan"]["model_seeds"]:
    item = calibration[str(seed)]
    repeats = item["raw_repeats"]["full"]
    assert len(repeats) == 3
    all_cpu, all_work = [], []
    for receipt in repeats:
        repeat = receipt["repeat"]
        costs = receipt["per_row_cost"]
        assert receipt["observe"] is False and receipt["mode"] == "full"
        assert len(costs["cpu_ns"]) == receipt["rows"] == 72
        all_cpu.extend(costs["cpu_ns"])
        all_work.extend(costs["work_units"])
        for index in range(receipt["rows"]):
            sample_rows.append({"seed": seed, "repeat": repeat, "row": index,
                                **{key: values[index] for key, values in costs.items()}})
        batches = receipt["cost"]["batches"]
        assert sum(batch["cpu_ns"] for batch in batches) == receipt["cost"]["cpu_ns"]
        repeat_rows.append({"seed": seed, "repeat": repeat, "rows": receipt["rows"],
            "median_row_cpu_ns": statistics.median(costs["cpu_ns"]),
            "service_cpu_ns": receipt["cost"]["cpu_ns"],
            "prepare_cpu_ns": receipt["cost"]["prepare_cpu_ns"],
            "prepare_wall_ns": receipt["cost"]["prepare_wall_ns"]})
        for batch in batches:
            assert sum(batch[key] for key in ("native_generation_and_ledger_cpu_ns",
                "output_encoding_and_ledger_cpu_ns", "remaining_service_cpu_ns")) == batch["cpu_ns"]
            batch_rows.append({"seed": seed, "repeat": repeat, **batch,
                "cpu_ns_per_row": batch["cpu_ns"] / batch["rows"],
                "cpu_wall_ratio": batch["cpu_ns"] / batch["wall_ns"]})
    median = statistics.median(all_cpu)
    assert median == item["cpu_ns"]["full"]
    own = [row for row in batch_rows if row["seed"] == seed]
    total = sum(row["cpu_ns"] for row in own)
    seed_summary[str(seed)] = {"flattened_216_row_cpu_median_ns": median,
        "repeat_row_medians_ns": [row["median_row_cpu_ns"] for row in repeat_rows if row["seed"] == seed],
        "service_cpu_ns_sum": total, "work_units_sum": sum(all_work),
        "per_row_work_unique": sorted(set(all_work)),
        "generation_cpu_ns_sum": sum(row["native_generation_and_ledger_cpu_ns"] for row in own),
        "output_cpu_ns_sum": sum(row["output_encoding_and_ledger_cpu_ns"] for row in own),
        "remaining_cpu_ns_sum": sum(row["remaining_service_cpu_ns"] for row in own),
        "output_cpu_fraction": sum(row["output_encoding_and_ledger_cpu_ns"] for row in own) / total,
        "output_byte_arrays_identical_across_repeats": all(
            receipt["per_row_cost"]["output_bytes"] == repeats[0]["per_row_cost"]["output_bytes"]
            for receipt in repeats),
        "cpu_wall_ratio_range": [min(row["cpu_wall_ratio"] for row in own),
                                  max(row["cpu_wall_ratio"] for row in own)]}
assert selection["common"]["reference_full_cpu_ns"] == seed_summary["11"]["flattened_216_row_cpu_median_ns"]
for name, rows in (("raw-row-samples.csv", sample_rows), ("raw-batch-samples.csv", batch_rows),
                   ("raw-repeat-samples.csv", repeat_rows)):
    with (OUT / name).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

plan = selection["plan"]
future_rows = (plan["data_profile"]["sources_per_class"]["validation"] * 12
               * plan["data_profile"]["instructions_per_source"] * plan["data_profile"]["variants"])
service = sum(item["flattened_216_row_cpu_median_ns"] * future_rows for item in seed_summary.values()) / 1e9
prepare = sum(calibration[str(seed)]["prepare_cpu_ns"]["full"] for seed in plan["model_seeds"]) / 1e9
scheduling = {}
for system in plan["systems"]:
    cost = selection["system_cost"][system]
    forecast = cost["refinement"]
    assert abs(service - forecast["service_cpu_seconds"]) < 1e-12
    assert abs(prepare - forecast["preparation_cpu_seconds"]) < 1e-12
    tail = max(forecast["tail_cpu_floor"], service + prepare + forecast["arithmetic_cpu_seconds"])
    assert abs(tail - forecast["tail_cpu_seconds"]) < 1e-12
    scheduling[system] = {"spent_cpu_before_residual": forecast["initial_cpu_seconds"],
        "remaining_units_before_residual": forecast["initial_remaining_units"],
        "predicted_service_seconds": service, "predicted_prepare_seconds": prepare,
        "predicted_observer_seconds": forecast["arithmetic_cpu_seconds"],
        "reserved_tail_seconds": tail,
        "reserved_changed_model_seconds": forecast["changed_model_cpu_seconds"],
        "cpu_without_even_one_update": forecast["initial_cpu_seconds"] + tail + forecast["changed_model_cpu_seconds"],
        "cpu_cap_seconds": plan["cpu_seconds_per_system"],
        "reserved_tail_and_revalidation_units": forecast["tail_units"] + forecast["changed_model_units"],
        "completed_rounds": forecast["completed_rounds"]}
save("analysis.json", {"scope": "Saved TRAIN calibration and existing pre-residual cost receipts only; not qualification",
    "seeds": seed_summary, "future_rows_per_model": future_rows, "scheduling": scheduling,
    "shared_preparation": {"difference": shared[0]["difference"], "gc": shared[0]["gc"]},
    "all_samples_retained": {"rows": len(sample_rows), "batches": len(batch_rows), "repeats": len(repeat_rows)},
    "not_accessed": ["test-result.json", "test-inputs", "models", "dataset construction", "native inference"],
    "no_future_validation_timings_used": True})

report = ["# Saved TRAIN calibration receipt diagnostic", "",
    "Administrative R&D only. No data construction, model execution, new timing measurement, training or qualification retry.",
    "Only the saved training selection receipt, shared-preparation telemetry and unchanged source were read. The t2 archive was not modified.", "",
    "Seed 11 is persistently expensive across all three repeats, not one rejected outlier:", "",
    "| Seed | Repeat 0 row median (ns) | Repeat 1 | Repeat 2 | All 216 rows median | Output fraction of service CPU |",
    "|---|---:|---:|---:|---:|---:|"]
for seed, row in seed_summary.items():
    report.append("| " + " | ".join([seed, *[f"{value:.6f}" for value in row["repeat_row_medians_ns"]],
        f"{row['flattened_216_row_cpu_median_ns']:.6f}", f"{100 * row['output_cpu_fraction']:.2f}%"]) + " |")
report += ["", "All 648 raw row values, 18 batch receipts and nine repeats are retained in CSV and JSON, including every high value.",
    "Each request has the same 19,236 declared operator units. The output-byte arrays are identical across repeats within each seed.",
    "Generation and output component timings both vary. These component boundaries combine multiple operations; they do not identify a primitive or process-level cause.", "",
    f"TRAIN-only future service reservation is {service:.9f}s = 1,152 rows × sum(seed row medians)/1e9. Preparation adds {prepare:.9f}s using the existing one-future-measure rule (observed maximum).",
    "The following original admission totals already exceed the 10s cap before adding any new gradient step or guard; all saved residual-round counts are zero:", "",
    "| Arm | Spent before residual (s) | Tail reserve (s) | Changed-model reserve (s) | Sum before new step (s) |",
    "|---|---:|---:|---:|---:|"]
for system, row in scheduling.items():
    report.append(f"| {system} | {row['spent_cpu_before_residual']:.9f} | {row['reserved_tail_seconds']:.9f} | {row['reserved_changed_model_seconds']:.9f} | {row['cpu_without_even_one_update']:.9f} |")
delta, gc = shared[0]["difference"], shared[0]["gc"]
report += ["", f"Shared-phase telemetry: process CPU {delta['process_cpu_ns']/1e9:.9f}s, wall {delta['wall_ns']/1e9:.9f}s; GC total {gc['cpu_ns_total']/1e6:.6f}ms over {gc['count']} pauses, maximum {gc['cpu_ns_max']/1e6:.6f}ms.",
    "The endpoint snapshots show one process thread. Container throttling and OOM-event deltas are zero. Container counters are not process-causality evidence and phase-wide GC events cannot be localized to a particular calibration batch.", "",
    "This establishes repeat-persistent TRAIN cost variation and conservative admission, not its cause. It does not support deleting outliers, substituting future validation timings, relaxing reserves or repeating a confirmation for a favorable wave.",
    "No new concrete compute-reuse repair is identified: native/output/ledger costs are not separated finely enough to show repeated work. A future optimization would first need source-level reuse with an independent equivalence/cost argument. No new measurement or confirmation is proposed by this report.", "",
    "Source, input-file hashes, exact administrative command, UTC and process/child CPU accounting are in ADMIN.json. No formal result or held-out input was opened."]
(OUT / "REPORT.md").write_text("\n".join(report) + "\n")

for name, original in inputs.items():
    assert digest(RUN / name) == original["sha256"]
child = resource.getrusage(resource.RUSAGE_CHILDREN)
save("ADMIN.json", {"schema": "hepta.saved-training-receipt-diagnostic.v1", "command": COMMAND,
    "cwd": str(ROOT), "started_utc": START, "finished_utc": datetime.now(timezone.utc).isoformat(),
    "process_cpu_ns": time.process_time_ns() - CPU, "wall_ns": time.perf_counter_ns() - WALL,
    "child_cpu_seconds": child.ru_utime + child.ru_stime - CHILD.ru_utime - CHILD.ru_stime,
    "cost_scope": "administrative stdlib-only diagnostic through report creation and input immutability verification; final ADMIN/manifest persistence excluded; never credited to qualification budgets",
    "source_commit": selection["source_commit"], "execution_commit": selection["execution_commit"],
    "source_hashes": source_hashes, "selection_plan_sha256": selection["plan_sha256"],
    "input_files": inputs, "diagnostic_source_sha256": digest(Path(__file__)),
    "input_files_unchanged_after_analysis": True,
    "preliminary_inspection": {"scope": "one stdlib JSON schema/batch/shared-phase read, no model execution",
                               "tool_wall_seconds": 0.016871066, "cpu_not_instrumented": True}})
save("SHA256.json", {path.name: {"sha256": digest(path), "bytes": path.stat().st_size}
                     for path in sorted(OUT.iterdir()) if path.is_file()})
print(json.dumps({"directory": str(OUT), "raw_rows": len(sample_rows), "batches": len(batch_rows),
                  "repeats": len(repeat_rows), "qualification": False}))
