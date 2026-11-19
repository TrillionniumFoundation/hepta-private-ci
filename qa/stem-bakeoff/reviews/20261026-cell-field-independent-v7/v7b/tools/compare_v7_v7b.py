"""Compare both complete sealed development grids without replacing any row."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import time

import numpy as np

from v7_audit_records import array_hash, canonical, file_hash, read, require


ORIGINAL_PROTOCOL = "75def1fe5a2610f76f5fe02db082bb4f0d01d02f683da0ee500a9af1f7e5e0e6"
CORRECTED_PROTOCOL = "e1827b6a0a4de9a083fca5c9401751b6063e63b447617a90719e64a089b4da7d"


def array_changes(original, corrected):
    """Preserve unequal trace lengths; metrics refer to each actual endpoint."""
    a, b = original["actions"], corrected["actions"]
    common = min(len(a), len(b))
    same_actions = a.shape == b.shape and np.array_equal(a, b)
    future = corrected["future_losses"]-original["future_losses"]
    old = corrected["old_differences"]-original["old_differences"]
    require(future.shape == old.shape == (512,) and all(np.isfinite(x).all() for d in (original, corrected) for x in d.values()),
        "complete finite source arrays and physical action/state evidence")
    return {"original_action_steps": len(a), "corrected_action_steps": len(b), "common_action_steps": common,
        "actions_identical": same_actions, "common_action_prefix_identical": np.array_equal(a[:common], b[:common]),
        "action_bytes_identical": array_hash(a) == array_hash(b),
        "common_action_prefix_bytes_identical": array_hash(a[:common]) == array_hash(b[:common]),
        "maximum_common_action_absolute_difference": float(np.max(np.abs(a[:common]-b[:common]))) if common else 0.,
        "terminal_state_vector_identical": np.array_equal(original["terminal_vector"], corrected["terminal_vector"]),
        "terminal_state_vector_bytes_identical": array_hash(original["terminal_vector"]) == array_hash(corrected["terminal_vector"]),
        "maximum_terminal_state_absolute_difference": float(np.max(np.abs(corrected["terminal_vector"]-original["terminal_vector"]))),
        "future_source_losses_identical": np.array_equal(original["future_losses"], corrected["future_losses"]),
        "old_source_differences_identical": np.array_equal(original["old_differences"], corrected["old_differences"]),
        "future_mean_nll_change_corrected_minus_original": float(future.mean()),
        "old_mean_difference_change_corrected_minus_original": float(old.mean()),
        "maximum_future_source_loss_absolute_change": float(np.max(np.abs(future))),
        "maximum_old_source_difference_absolute_change": float(np.max(np.abs(old)))}


def verified_report(path, grid, expected_protocol):
    report = read(path)
    require(report["status"] == "PASS" and report["primary_records"] == 864
        and report["protocol_sha256"] == expected_protocol
        and report["development_seal_sha256"] == file_hash(grid/"development_seal.json")
        and file_hash(grid/"protocol.json") == expected_protocol, "complete independent audit bound to the selected grid")
    seal = read(grid/"development_seal.json")
    inventory = {path.relative_to(grid).as_posix() for path in grid.rglob("*")
        if path.is_file() and path.relative_to(grid).as_posix() != "development_seal.json"}
    require(inventory == set(seal["files"]), "complete unchanged file census; no added or dropped slots")
    for name, pin in seal["files"].items():
        require(file_hash(grid/name) == pin["sha256"] and (grid/name).stat().st_size == pin["bytes"], "unaltered sealed grid file: "+name)
    census_path = path.with_name("case-census.json")
    require(file_hash(census_path) == report["case_census_sha256"], "independent source metric/census receipt")
    census = read(census_path)
    cases = {(row["index"], row["fit_id"], row["policy"]): row for row in census}
    require(len(census) == len(cases) == 864, "exact unique864 slots with no filtering")
    return report, cases


def compare_grids(original_grid, corrected_grid, original_audit, corrected_audit, output):
    original_grid, corrected_grid, original_audit, corrected_audit, output = map(Path,
        (original_grid, corrected_grid, original_audit, corrected_audit, output))
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    sources = {path.name: file_hash(path) for path in (Path(__file__), Path(__file__).with_name("test_compare_v7_v7b.py"))}
    old_report, old_cases = verified_report(original_audit, original_grid, ORIGINAL_PROTOCOL)
    new_report, new_cases = verified_report(corrected_audit, corrected_grid, CORRECTED_PROTOCOL)
    require(set(old_cases) == set(new_cases), "every original slot has exactly one corrective rerun counterpart")
    old_plan, new_plan = read(original_grid/"protocol.json"), read(corrected_grid/"protocol.json")
    require(set(new_plan)-set(old_plan) == {"engineering_erratum", "revision"}
        and all(new_plan[key] == value for key, value in old_plan.items()), "all original data/configuration/selection/cost rules unchanged")
    erratum = new_plan["engineering_erratum"]
    require(erratum["original_development_seal_sha256"] == old_report["development_seal_sha256"]
        and erratum["original_protocol_sha256"] == ORIGINAL_PROTOCOL and erratum["original_outputs_retained"] == 864,
        "disclosed engineering erratum binds the complete original run")
    old_sources, new_sources = read(original_grid/"executed_source.json"), read(corrected_grid/"executed_source.json")
    require(set(old_sources) == set(new_sources) and len(old_sources) == 103, "identical source closure filename census")
    changed = [name for name in old_sources if old_sources[name] != new_sources[name]]
    require(set(changed) == {"cell_field_planner_v7.py", "cell_field_development_artifacts_v7.py"}, "only declared planner interpolation and terminal-artifact implementation changed")
    for input_path in (original_grid/"inputs").glob("*.json"):
        old, new = read(input_path), read(corrected_grid/"inputs"/input_path.name)
        require({k: v for k, v in old.items() if k not in {"cpu_ns", "wall_ns"}}
            == {k: v for k, v in new.items() if k not in {"cpu_ns", "wall_ns"}}, "all actual data, role and panel identities unchanged")
    require(read(original_grid/"execution-order.json") == read(corrected_grid/"execution-order.json"), "same288 balanced actual execution orders")
    rows = []
    for key in sorted(old_cases):
        config, fit, policy = key
        old, new = old_cases[key], new_cases[key]
        relative = Path(f"config{config:02d}")/fit/policy
        row = {"configuration_index": config, "fit_id": fit, "policy": policy,
            "original_status": old["status"], "corrected_status": new["status"],
            "original_completed_steps": old["completed_steps"], "corrected_completed_steps": new["completed_steps"],
            "original_actual_errors": old["actual_errors"], "corrected_actual_errors": new["actual_errors"],
            "original_cpu_ns": old["cpu_ns"], "corrected_cpu_ns": new["cpu_ns"],
            "original_wall_ns": old["wall_ns"], "corrected_wall_ns": new["wall_ns"],
            "original_terminal_preimage_available": old["terminal_controller_preimage_available"],
            "corrected_terminal_preimage_available": new["terminal_controller_preimage_available"],
            "source_metrics_available_in_both": False}
        if "unavailable_execution_error" not in (old["status"], new["status"]):
            with np.load(original_grid/relative/"compact.npz", allow_pickle=False) as data:
                a = {name: data[name] for name in data.files}
            with np.load(corrected_grid/relative/"compact.npz", allow_pickle=False) as data:
                b = {name: data[name] for name in data.files}
            row.update(source_metrics_available_in_both=True, **array_changes(a, b))
            old_header, new_header = read(original_grid/relative/"result.json"), read(corrected_grid/relative/"result.json")
            row.update(original_terminal_state_sha256=old_header["terminal_state_sha256"],
                corrected_terminal_state_sha256=new_header["terminal_state_sha256"],
                complete_terminal_state_identical=old_header["terminal_state_sha256"] == new_header["terminal_state_sha256"])
            old_trace, new_trace = read(original_grid/relative/"trace.json.gz", True), read(corrected_grid/relative/"trace.json.gz", True)
            common = row["common_action_steps"]
            row.update(common_receipt_prefix_identical=old_trace["receipts"][:common] == new_trace["receipts"][:common],
                common_full_state_hash_prefix_identical=old_trace["state_sha256"][:common+1] == new_trace["state_sha256"][:common+1],
                complete_receipt_trace_identical=old_trace["receipts"] == new_trace["receipts"],
                complete_full_state_hash_trace_identical=old_trace["state_sha256"] == new_trace["state_sha256"])
        rows.append(row)
    table = []
    for index in range(12):
        a = next(row for row in old_report["configuration_table"] if row["index"] == index)
        b = next(row for row in new_report["configuration_table"] if row["index"] == index)
        selected = [row for row in rows if row["configuration_index"] == index]
        table.append({"index": index, "original": a, "corrected": b,
            "statuses_changed": sum(row["original_status"] != row["corrected_status"] for row in selected),
            "actual_action_traces_identical": sum(row.get("actions_identical", False) for row in selected),
            "actual_action_bytes_identical": sum(row.get("action_bytes_identical", False) for row in selected),
            "terminal_physical_states_identical": sum(row.get("complete_terminal_state_identical", False) for row in selected),
            "complete_receipt_and_state_traces_identical": sum(row.get("complete_receipt_trace_identical", False)
                and row.get("complete_full_state_hash_trace_identical", False) for row in selected),
            "source_metric_endpoints_identical": sum(row.get("future_source_losses_identical", False)
                and row.get("old_source_differences_identical", False) for row in selected)})
    output.mkdir(parents=True, exist_ok=False)
    with (output/"all864-comparisons.json.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            compressed.write(canonical(rows)+b"\n")
    transitions = Counter((row["original_status"], row["corrected_status"]) for row in rows)
    report = {"schema": "hepta.cell-field-complete-corrective-run-comparison.v7b", "status": "PASS",
        "registered_slots": 864, "compared_slots": len(rows), "source_metrics_available_in_both": sum(row["source_metrics_available_in_both"] for row in rows),
        "original_audit_sha256": file_hash(original_audit), "corrected_audit_sha256": file_hash(corrected_audit),
        "original_development_seal_sha256": old_report["development_seal_sha256"],
        "corrected_development_seal_sha256": new_report["development_seal_sha256"],
        "original_protocol_sha256": ORIGINAL_PROTOCOL, "corrected_protocol_sha256": CORRECTED_PROTOCOL,
        "changed_executed_sources": {name: {"original": old_sources[name], "corrected": new_sources[name]} for name in changed},
        "source_data_roles_panels_initial_states_and_selection_rules_unchanged": True,
        "post_run_comparison_sources": sources,
        "status_transitions": [{"original": a, "corrected": b, "count": count} for (a, b), count in sorted(transitions.items())],
        "original_actual_error_records": sum(bool(row["original_actual_errors"]) for row in rows),
        "corrected_actual_error_records": sum(bool(row["corrected_actual_errors"]) for row in rows),
        "original_policy_cpu_ns": sum(row["original_cpu_ns"] for row in rows),
        "corrected_policy_cpu_ns": sum(row["corrected_cpu_ns"] for row in rows),
        "actual_action_traces_identical": sum(row.get("actions_identical", False) for row in rows),
        "actual_action_bytes_identical": sum(row.get("action_bytes_identical", False) for row in rows),
        "terminal_physical_states_identical": sum(row.get("complete_terminal_state_identical", False) for row in rows),
        "complete_receipt_and_state_traces_identical": sum(row.get("complete_receipt_trace_identical", False)
            and row.get("complete_full_state_hash_trace_identical", False) for row in rows),
        "source_metric_endpoints_identical": sum(row.get("future_source_losses_identical", False)
            and row.get("old_source_differences_identical", False) for row in rows),
        "original_selection": old_report["selection"], "corrected_selection": new_report["selection"],
        "configuration_comparison": table,
        "all_slot_comparisons_sha256": file_hash(output/"all864-comparisons.json.gz"),
        "primary_original_outputs_replaced": False, "rows_selected_or_dropped": False,
        "new_confirmation_executed": False, "scientific_acceptance": False,
        "interpretation": "Both complete development runs remain separate. Stopped endpoints are compared descriptively; ratios from unequal completed work are not claims of scientific eligibility or a causal speedup.",
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall,
        "completed_at": datetime.now(timezone.utc).isoformat()}
    (output/"comparison.json").write_bytes(canonical(report)+b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-grid", "corrected-grid", "original-audit", "corrected-audit", "output"):
        parser.add_argument("--"+name, required=True)
    result = compare_grids(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("status", "compared_slots", "original_actual_error_records",
        "corrected_actual_error_records", "actual_action_traces_identical", "source_metric_endpoints_identical")}))
