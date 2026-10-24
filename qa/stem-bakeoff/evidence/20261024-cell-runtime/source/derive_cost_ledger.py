"""Seal the completed runtime phase's measured main costs without new ML work.

Archive, restore, later publication and this derivation's own execution belong
to an external closing receipt. Missing costs stay unknown; nested costs are
observations rather than additive activities. All outputs are new files.
"""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from cell_cost_ledger import summarize


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def at(value, pointer):
    for key in pointer.split("/")[1:]:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def nanoseconds(value, multiplier=1):
    if value is None:
        return None
    if type(value) not in (int, float) or value < 0:
        raise ValueError("nonnegative observed duration or explicit null required")
    result = Decimal(str(value))*multiplier
    if not result.is_finite() or result != result.to_integral_value():
        raise ValueError("duration conversion must preserve integral nanoseconds")
    return int(result)


def main(phase, bounded_tests, output):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    phase, bounded_tests, output = Path(phase).absolute(), Path(bounded_tests).absolute(), Path(output).absolute()
    if output.exists():
        raise ValueError("new cost cutoff directory required")
    implementation = sha(__file__)
    receipts, documents, measurements = {}, {}, []

    def register(name, path):
        path = Path(path).absolute()
        if name in receipts or any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("unique receipt identity and ordinary source file required")
        documents[name] = read(path)
        receipts[name] = {"path": str(path), "sha256": sha(path)}
        return documents[name]

    def measurement(name, receipt, wall, cpu_fields, scope, *, wall_multiplier=1):
        document = documents[receipt]
        values = {pointer: nanoseconds(at(document, pointer)) for pointer in cpu_fields}
        known = [value for value in values.values() if value is not None]
        measurements.append({"id": name, "source_receipt": receipt,
            "source_sha256": receipts[receipt]["sha256"], "wall_source_pointer": wall,
            "wall_source_multiplier": wall_multiplier,
            "wall_ns": nanoseconds(at(document, wall), wall_multiplier),
            "cpu_source_values_ns": values, "known_cpu_ns": sum(known) if known else None,
            "cpu_complete": len(known) == len(values),
            "unmeasured_cpu_source_fields": [key for key, value in values.items() if value is None],
            "scope": scope})

    def outer(name, path, *, child="child_cpu_ns"):
        value = register(name, path)
        if type(value.get("exit_code", 0)) is not int:
            raise ValueError("completed command return code must be an integer")
        measurement(name, name, "/wall_ns", ["/parent_cpu_ns", "/"+child],
            "One disjoint outer command/process tree. Parent and reaped-child CPU are added once; all nested fits, checks, subprocesses and serialization inside that command are included.")

    for name in ("bundle-preparation", "training", "serving", "queue"):
        outer("stage_"+name.replace("-", "_"), phase/"stages"/(name+"-attempt-1.json"))
    for name in ("bundle-attempt-1", "bundle-attempt-2", "serving-bundle-attempt-1", "combined-final-before-recovery"):
        outer("test_"+name.replace("-", "_"), phase/"tests"/(name+".json"))
    outer("test_microbatch_review_fix", phase/"tests/microbatch-review-fix-receipt.json", child="reaped_child_tree_cpu_ns")
    for number in (1, 2):
        outer(f"test_bounded_runtime_{number}", bounded_tests/f"attempt-{number}.json")
    for number in range(1, 6):
        outer(f"test_queue_{number:02d}", phase/f"audit/test-queue-{number:02d}.json", child="reaped_child_cpu_ns")
    outer("source_alignment_12", phase/"publication/source-alignment-12.json")
    register("data_audit", phase/"audit/next-data-audit.json")
    measurement("data_audit", "data_audit", "/wall_ns_before_serialization",
        ["/parent_cpu_ns_before_serialization", "/git_child_cpu_ns"],
        "Read-only source/exposure audit. Parent CPU is observed; Git child CPU is explicitly unknown. Receipt self-write is excluded.")
    development = register("microbatch_development", phase/"tests/microbatch-development-receipts.json")
    if len(development["executions"]) != 3:
        raise ValueError("exact three preserved early development commands required")
    for index in range(3):
        prefix = f"/executions/{index}"
        measurement(f"test_microbatch_development_{index+1}", "microbatch_development",
            prefix+"/tool_reported_wall_seconds", [prefix+"/parent_cpu_ns", prefix+"/child_cpu_ns"],
            "Preserved tool-reported command wall duration, converted exactly from seconds. Parent/child CPU were not observed. Rounded nested unittest seconds are not added.", wall_multiplier=1_000_000_000)
    publication = register("publication_intervals", phase/"publication/tool-intervals.json")
    if publication["published_stages"] != 12 or publication["remote_ci_consulted"] is not False:
        raise ValueError("main publication cutoff is exactly twelve stages without CI")
    for index, observation in enumerate(publication["observations"]):
        prefix = f"/observations/{index}"
        measurement(observation["id"], "publication_intervals", prefix+"/wall_ns", [prefix+"/cpu_ns"],
                    observation["scope"])

    for name, relative in (("bundle_manifest", "bundle/manifest.json"), ("bundle", "bundle/bundle.json"),
        ("bundle_preparation", "bundle-preparation.json"), ("training_report", "training/report.json"),
        ("serving_report", "serving/report.json"), ("queue_report", "queue/report.json"),
        ("training_manifest", "training/manifest.json"), ("serving_manifest", "serving/manifest.json"),
        ("queue_plan", "queue/plan.json"), ("source_local_stages", "publication/local-stages.json")):
        register(name, phase/relative)
    for number in range(1, 13):
        register(f"source_publication_{number:02d}", phase/f"publication/published-{number:02d}.json")
    if (documents["source_alignment_12"]["published_and_fetched_commit"] != publication["source_commit"]
            or documents["test_combined_final_before_recovery"]["source_commit"] != publication["source_commit"]
            or len(documents["source_local_stages"]) != 12):
        raise ValueError("source, focused gate and publication cutoff differ")
    for receipt, pointer in (("bundle_preparation", "/manifest_sha256"),
        ("training_report", "/plan/bundle_manifest_sha256"),
        ("serving_report", "/plan/bundle_manifest_sha256"), ("queue_report", "/bundle_manifest_sha256")):
        if at(documents[receipt], pointer) != receipts["bundle_manifest"]["sha256"]:
            raise ValueError("research work uses a different input bundle")
        receipts[receipt]["receipt_bindings"] = {pointer: "bundle_manifest"}
    training, serving, queue = (documents[name] for name in ("training_report", "serving_report", "queue_report"))
    if (training["task_count"] != 1 or queue["logical_tasks"] != 1 or documents["bundle"]["task_id"] != "action_usefulness"
            or training["encoder_forwards"] != 0 or serving["encoder_calls"] != 0
            or queue["encoder_forward_calls"] != 0 or documents["bundle_preparation"]["encoder_calls"] != 0):
        raise ValueError("one task and zero new Encoder invocations must remain explicit")

    output.mkdir(parents=True, exist_ok=False)
    arithmetic = {"schema": "hepta.runtime-main-cost-arithmetic.v1", "measurements": measurements,
        "source_helper_sha256": implementation, "source_receipt_pins": receipts,
        "partial_cpu_accounting": "Known CPU parts are added; each missing part also gets an explicit unknown CPU component. Its incremental wall is zero because the enclosing wall interval was already charged.",
        "zero_incremental_wall_ns": 0,
        "wall_unit_note": "Tool-reported seconds keep their tool semantics; exact Decimal conversion does not add precision or create a physical measurement."}
    write(output/"arithmetic-v1.json", arithmetic)
    notes = {"schema": "hepta.runtime-main-cost-notes.v1", "source_commit": publication["source_commit"],
        "main_cutoff": "Four main stages, all specifically listed development gates, source audit, publication1..12, fetch/alignment and final44-test focused gate before recovery.",
        "actual_logical_task_count": 1, "task_id": "action_usefulness",
        "legacy_logical_task_count": "The unchanged generic ledger counts tasks only from legacy calibrated-study schemas. Here it reports0; use this explicit task1 and the raw reports, never interpret0 as no task or physical Cells as tasks.",
        "training_work": {"main_private_updates_both_methods": training["actual_total_private_optimizer_updates_both_methods"],
            "queue_real_updates": queue["actual_optimizer_updates"],
            "main_and_queue_real_updates": training["actual_total_private_optimizer_updates_both_methods"]+queue["actual_optimizer_updates"],
            "main_and_queue_real_example_updates": training["actual_total_example_updates_both_methods"]+queue["example_updates"],
            "synthetic_test_optimizer_updates": None,
            "test_scope": "Synthetic optimizer work is charged through every test process receipt; its update count is not reconstructed or represented as zero."},
        "encoder": {"new_invocations": 0, "new_training_updates": 0,
            "historical_work_recharged": False,
            "scope": "Frozen features and27 learned calibrated states came from the prior research phase. Zero new Encoder work is not zero original encoding/training cost or zero total system cost.",
            "upstream_source_pins": documents["bundle"]["upstream_source_pins"]},
        "resource_limits": {"rss_peaks_are_additive": False, "energy_joules": None,
            "price": None, "network_bytes": None, "whole_system_peak_memory_bytes": None},
        "exclusions_to_external_closing": ["this helper and ledger verification execution", "later recovery",
            "archive/restore", "report facts/figures", "publication13 and later", "terminal formatting/serialization"],
        "unmetered_work": "Remaining source edits, review, tool discovery, inspections and orchestration are explicit unknowns in the supplied publication observations; registered command CPU and wall are not charged again.",
        "quality_qualified": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
    write(output/"notes-v1.json", notes)
    for name, filename in (("arithmetic", "arithmetic-v1.json"), ("notes", "notes-v1.json")):
        register(name, output/filename)
    registry = {"schema": "hepta.cell-cost-registry.v1", "datasets": {}, "receipts": receipts,
        "owners": [], "features": [], "studies": [], "serving": [], "operational_acquisitions": [],
        "inclusive_rollups": [], "activities": [], "observations": [],
        "timing_context": "Main cutoff of one real task with770D state training and calibrated serving. Outer command work is disjoint, nested values remain observations. Wall sums are work, not concurrent elapsed or isolated capacity. Unknown costs remain null; closing costs are external."}
    for index, item in enumerate(measurements):
        prefix = f"/measurements/{index}"
        registry["activities"].append({"id": item["id"], "receipt": "arithmetic", "scope": item["scope"],
            "wall": None if item["wall_ns"] is None else {"pointer": prefix+"/wall_ns", "unit": "ns"},
            "cpu": None if item["known_cpu_ns"] is None else {"pointer": prefix+"/known_cpu_ns", "unit": "ns"}})
        if item["known_cpu_ns"] is not None and not item["cpu_complete"]:
            registry["activities"].append({"id": item["id"]+"_unmeasured_child_cpu", "receipt": "arithmetic",
                "scope": "Unmeasured CPU component only; enclosing wall already charged. This zero is incremental accounting, not a claimed zero-duration child.",
                "wall": {"pointer": "/zero_incremental_wall_ns", "unit": "ns"}, "cpu": None})
    observe = [("task_identity", "notes", "/actual_logical_task_count"),
        ("training_work", "notes", "/training_work"), ("historical_encoder_boundary", "notes", "/encoder"),
        ("bundle_storage", "bundle_preparation", "/bytes"), ("training_bank", "training_report", "/feature_bank_construction"),
        ("training_nested_total", "training_report", "/inclusive_probe"),
        ("training_parameter_archives", "training_report", "/parameter_archives_total_bytes"),
        ("training_process_rss", "training_report", "/process_lifetime_peak_rss_bytes"),
        ("serving_nested_total", "serving_report", "/inclusive_probe"),
        ("serving_process_rss", "serving_report", "/process_lifetime_peak_rss_bytes"),
        ("queue_memory", "queue_report", "/memory"),
        ("queue_storage", "queue_report", "/persisted_file_bytes_before_report"),
        ("queue_resume_scope", "queue_report", "/resume_semantics")]
    observe += [(f"training_private_state_{index}", "training_report", f"/conditions/{index}/executions/batched/accounting")
                for index in range(len(training["conditions"]))]
    for name, receipt, pointer in observe:
        registry["observations"].append({"id": name, "receipt": receipt, "pointer": pointer,
            "scope": "Non-additive source observation; tensor byte categories and lifetime RSS are separate; nested timing is already in its outer activity."})
    write(output/"registry-v1.json", registry)
    ledger = summarize(output/"registry-v1.json", output/"ledger-v1.json")

    # Re-read source receipts, independently reconstruct totals using exact decimal
    # arithmetic, and compare the existing ledger's individual budget components.
    raw_wall, raw_cpu, missing_wall, missing_cpu = 0, 0, [], []
    for item in read(output/"arithmetic-v1.json")["measurements"]:
        source = read(receipts[item["source_receipt"]]["path"])
        wall_value = at(source, item["wall_source_pointer"])
        wall = None if wall_value is None else int(Decimal(str(wall_value))*item["wall_source_multiplier"])
        cpu_values = [at(source, pointer) for pointer in item["cpu_source_values_ns"]]
        known = [int(value) for value in cpu_values if value is not None]
        total_cpu = sum(known) if known else None
        if (wall, total_cpu) != (item["wall_ns"], item["known_cpu_ns"]):
            raise ValueError("independent raw source arithmetic differs")
        name = "activity:"+item["id"]
        actual = ledger["budget_components"][name]
        if (actual["wall_ns"], actual["cpu_ns"]) != (wall, total_cpu):
            raise ValueError("ledger component differs from independent arithmetic")
        if wall is None: missing_wall.append(name)
        else: raw_wall += wall
        if total_cpu is None: missing_cpu.append(name)
        else: raw_cpu += total_cpu
        if known and any(value is None for value in cpu_values):
            missing_cpu.append(name+"_unmeasured_child_cpu")
    totals = {"wall_ns": {"sum_measured": raw_wall, "unmeasured_components": missing_wall},
              "cpu_ns": {"sum_measured": raw_cpu, "unmeasured_components": missing_cpu}}
    if ledger["measured_work_totals"] != totals or len(set(ledger["active_budget_component_ids"])) != len(registry["activities"]):
        raise ValueError("ledger totals or active activity identities differ")
    if sha(__file__) != implementation or any(sha(path) != digest for path, digest in ledger["artifact_bindings"].items()):
        raise ValueError("derivation or bound source bytes changed")
    write(output/"verification-v1.json", {"schema": "hepta.runtime-main-cost-verification.v1",
        "registry_sha256": sha(output/"registry-v1.json"), "ledger_sha256": sha(output/"ledger-v1.json"),
        "arithmetic_sha256": sha(output/"arithmetic-v1.json"), "notes_sha256": sha(output/"notes-v1.json"),
        "source_helper_sha256": implementation, "all_source_pins_reverified": True,
        "independent_raw_source_totals": totals, "active_components": len(registry["activities"]),
        "logical_task_count_actual": 1, "legacy_ledger_task_count": ledger["logical_task_count"],
        "nested_costs_added_twice": False, "archive_or_closing_costs_included": False})
    return {"schema": "hepta.runtime-main-cost-derivation-external.v1", "output": str(output),
        "registry_sha256": sha(output/"registry-v1.json"), "ledger_sha256": sha(output/"ledger-v1.json"),
        "verification_sha256": sha(output/"verification-v1.json"), "source_helper_sha256": implementation,
        "wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
        "scope": "Registry/arithmetic/notes derivation, existing ledger execution and independent raw-source/pin verification through final outputs. Excludes printing this external receipt; not added into its own main ledger.",
        "measured_work_totals": totals, "new_training_or_prediction_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--bounded-tests", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(main(args.phase, args.bounded_tests, args.output), sort_keys=True))
