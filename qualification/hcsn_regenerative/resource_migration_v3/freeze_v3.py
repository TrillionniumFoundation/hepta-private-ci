"""Freeze distinct Colab resource V3 from fresh native evidence; preserve original42 science bytes."""

import argparse
from collections import Counter
from pathlib import Path

from qualification.hcsn_regenerative.mechanism_analysis import STATISTICAL_CONTRACT
from qualification.hcsn_regenerative.mechanism_contract import (ARMS, TASKS, STATE_COUNT, EXPECTED_PARAMETERS, ENVIRONMENT_KEYS,
    digest, file_sha, load_contract, ordered_roster, read_json, utc_now,
    validate_plan, validate_execution_environment, verify_sources, write_json)

from .rawdiff_guard import preflight, add_prospective_pins, audit_diff


STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-v3"
GRADIENT_ARMS = ("regenerative_dual", "risk_only", "conditional_boundary")
PARAMETERS = ("encoder.0.weight", "encoder.2.weight", "gate.weight", "readout.weight")


def verify_case_roster(record, sequence=False):
    expected = Counter()
    forward = "64_step_forward_vs_independent_fp64" if sequence else "represented_fp32_forward_vs_fp64_mirror"
    gradient = "64_step_selected_parameter_gradient" if sequence else "parameter_gradient"
    input_name = "64_step_first_input_fd_agreement" if sequence else "first_step_input_gradient"
    for arm in ARMS:
        expected[(forward, arm, None)] = 1
        if not sequence:
            expected[("state_carry", arm, None)] = 1
    for arm in GRADIENT_ARMS:
        expected[(input_name, arm, None)] = 1
        for parameter in PARAMETERS:
            expected[(gradient, arm, parameter)] = 2
        if sequence:
            expected[("64_step_first_input_nonzero_resolved", arm, None)] = 1
    if sequence:
        expected[("fresh_process_next_full_episode_exact", None, None)] = 1
        expected[("source_unchanged", None, None)] = 1
    actual = Counter((row.get("name"), row.get("arm"), row.get("parameter")) for row in record.get("checks", []))
    if actual != expected:
        raise ValueError("Incomplete, duplicated or changed qualification case roster")
    for arm in GRADIENT_ARMS:
        for parameter in PARAMETERS:
            indices = [tuple(row["index"]) for row in record["checks"]
                       if row["name"] == gradient and row["arm"] == arm and row["parameter"] == parameter]
            if len(set(indices)) != 2:
                raise ValueError("Duplicated selected parameter derivative")
    if sequence:
        sensitivity = record.get("sensitivity_checks", [])
        if (len(sensitivity) != 3 or {row.get("arm") for row in sensitivity} != set(GRADIENT_ARMS)
                or not all(row.get("passed") and row.get("resolved") and row.get("fd_agreement") for row in sensitivity)):
            raise ValueError("The three resolved long-range input gates are not complete")
        recovery = record.get("recovery", {})
        if (recovery.get("status") != "pass" or recovery.get("exact_next_block") is not True
                or recovery.get("actual_optimizer_updates") != 3 or recovery.get("child_exit_code") != 0
                or recovery.get("child_execution_stopped") is not True or recovery.get("child_updates_unknown") is not False):
            raise ValueError("Fresh-process actual-bundle episode recovery is incomplete")


def freeze(args):
    paths = {name: Path(getattr(args, name)) for name in
             ("bundle", "unit", "graph_cpu", "graph_cuda", "sequence_cpu", "sequence_cuda",
              "resolution", "fixed_renewal", "budget", "output")}
    if paths["output"].exists():
        raise FileExistsError("The prospective plan is immutable; use a distinct study identity for amendments")
    parent_plan, resource_lineage = preflight(args, paths)
    metadata_path = paths["bundle"].with_suffix(".json")
    metadata = read_json(metadata_path)
    bundle_sha, metadata_sha = file_sha(paths["bundle"]), file_sha(metadata_path)
    if metadata["bundle_sha256"] != bundle_sha or metadata["state_count"] != STATE_COUNT:
        raise ValueError("The actual selected S81 operator bundle is required")
    source_pins = dict(metadata["source_pins"])
    receipts = {}

    def merge(pins):
        verify_sources(pins)
        for path, sha in pins.items():
            if path in source_pins and source_pins[path] != sha:
                raise ValueError("Qualification source snapshots disagree: " + path)
            source_pins[path] = sha

    def remember(name, record):
        receipts[name] = dict(filename=paths[name].name, sha256=file_sha(paths[name]),
                              schema=record.get("schema"), status=record.get("status"))

    unit = read_json(paths["unit"])
    if (unit.get("schema") != "hcsn-mechanism-unit-result-v1" or unit.get("status") != "pass"
            or unit.get("methods_run") != 13
            or any(unit.get(k) != 0 for k in ("failures", "errors", "skipped"))):
        raise ValueError("The final consuming runner needs actual no-skip Torch unit evidence")
    merge(unit["source_pins"]); remember("unit", unit)
    environments = {}
    for name, device, schema in (("graph_cpu", "cpu", "hcsn-mechanism-graph-qualification-v1"),
                                 ("graph_cuda", "cuda", "hcsn-mechanism-graph-qualification-v1"),
                                 ("sequence_cpu", "cpu", "hcsn-mechanism-sequence-qualification-v1"),
                                 ("sequence_cuda", "cuda", "hcsn-mechanism-sequence-qualification-v1")):
        record = read_json(paths[name])
        if (record.get("schema") != schema or record.get("status") != "pass" or record.get("device") != device
                or record.get("bundle_sha256") != bundle_sha or record.get("bundle_metadata_sha256") != metadata_sha
                or not record.get("checks") or not all(row.get("passed") is True for row in record["checks"])):
            raise ValueError("Failed, incomplete or mismatched actual-bundle qualification: " + name)
        merge(record["source_pins"]); remember(name, record)
        verify_case_roster(record, sequence=name.startswith("sequence_"))
        if name.startswith("graph_"):
            environments[device] = record["environment"]
        if name.startswith("sequence_") and not record.get("recovery", {}).get("passed"):
            raise ValueError("Actual-bundle next-episode optimizer recovery failed: " + name)
    resolution = read_json(paths["resolution"])
    if (resolution.get("status") != "complete" or not resolution.get("source_unchanged") or resolution.get("task_dataset_reads") != 0
            or resolution.get("task_optimizer_updates") != 0 or len(resolution.get("rows", [])) != 12
            or resolution.get("thresholds") != dict(common_bin_state_l1=.02, cumulative_hit_relative=.03, reference_crosscheck_abs=2e-8)
            or len(resolution.get("reference_crosscheck", [])) != 4
            or {row.get("horizon") for row in resolution.get("reference_crosscheck", [])} != {.08, .1, .32, .7}
            or not all(row.get("pass_") is True for row in resolution.get("reference_crosscheck", []))):
        raise ValueError("Numerical-only pretraining resolution selection is incomplete or changed")
    required_rows = {(active, phase, dtype, schedule) for active, phase in ((16, 8), (64, 16), (128, 32))
                     for dtype in ("torch.float32", "torch.float64") for schedule in ("unequal", "equal")}
    if {(row.get("active_cells"), row.get("phase_cells"), row.get("dtype"), row.get("schedule")) for row in resolution["rows"]} != required_rows:
        raise ValueError("The full twelve-row numerical resolution roster changed")
    eligible = []
    for active, phase in ((16, 8), (64, 16), (128, 32)):
        cases = [row for row in resolution["rows"] if row["active_cells"] == active and row["phase_cells"] == phase]
        if all(row["passes_configuration"] and row["state_l1_error"] <= .02 and row["hit_relative_error"] <= .03 for row in cases):
            eligible.append((active, phase))
    if not eligible or eligible[0] != (64, 16):
        raise ValueError("Recorded numerical errors do not select the declared S81 grid")
    if digest(resolution["sources"]) != resolution["source_set_sha256"]:
        raise ValueError("Resolution source-map digest differs from the actual source pins")
    selected = resolution.get("smallest_eligible_configuration", {})
    if selected.get("active_cells") != 64 or selected.get("phase_cells") != 16 or not selected.get("eligible"):
        raise ValueError("The registered smallest passing grid is not S81")
    if not any(not row["passes_configuration"] for row in resolution["rows"] if row["active_cells"] == 16):
        raise ValueError("Retain the observed failed coarse configuration")
    merge(resolution["sources"]); remember("resolution", resolution)
    fixed = read_json(paths["fixed_renewal"])
    if (fixed.get("status") != "BOUNDED_FP64_CONSTRUCTION_CHECKS_PASS" or not fixed.get("source_unchanged")
            or fixed.get("unit_methods_run") != 6 or fixed.get("unit_failures") != 0 or fixed.get("unit_errors") != 0):
        raise ValueError("True zero-delay construction requires its own passed bounded audit")
    merge(fixed["source_files_sha256"]); remember("fixed_renewal", fixed)
    budget = read_json(paths["budget"])
    if (budget.get("schema") != "hcsn-mechanism-nontask-budget-probe-v1" or budget.get("status") != "completed"
            or budget.get("bundle_sha256") != bundle_sha or budget.get("bundle_metadata_sha256") != metadata_sha
            or budget.get("state_count") != STATE_COUNT or budget.get("expected_parameter_count") != EXPECTED_PARAMETERS
            or budget.get("optimizer_updates_completed") != 400 or budget.get("sequence_length") != 64
            or budget.get("batch_size") != 64 or budget.get("device") != "cuda"
            or budget.get("task_datasets_read") is not False or budget.get("formal_training_fits") != 0
            or not budget.get("within_480_second_probe_window") or budget.get("wall_seconds", 480) >= 450):
        raise ValueError("A successful actual-bundle non-task budget probe is required")
    merge(budget["source_pins"]); remember("budget", budget)
    directory = Path(__file__).parent.parent  # Original numerical package, unchanged.
    for name in ("freeze_mechanism_plan.py", "mechanism_analysis.py", "tests/test_mechanism_analysis.py",
                 "MECHANISM_PILOT_PROTOCOL.md", "MECHANISM_EXECUTION_AMENDMENT_20261107.md",
                 "MECHANISM_RESOLUTION_RESULT.json", "MECHANISM_RESOLUTION_RESULT.md"):
        path = directory / name
        source_pins[str(path.relative_to(directory.parents[1]))] = file_sha(path)
    for name in ("run_resolution_probe.py", "resolution_reference.py", "RESOLUTION_PROTOCOL.md"):
        path = directory.parents[1] / "resolution_scope" / name
        source_pins[str(path.relative_to(directory.parents[1]))] = file_sha(path)
    verify_sources(source_pins)
    execution = {key: environments["cuda"][key] for key in ENVIRONMENT_KEYS}
    execution["gpu"] = {key: environments["cuda"]["gpu"][key] for key in ("name", "total_memory", "compute_capability")}
    execution["gpu_uuid_policy"] = "same_model_new_lease"
    plan = dict(schema="hcsn-mechanism-pilot-plan-v1", status="FROZEN", study_id=STUDY_ID, frozen_at=utc_now(),
                arms=list(ARMS), tasks=list(TASKS), training_seeds=[1103, 2207, 3301, 4409],
                learning_rates=[.001, .003], test_episode_seeds=[4703, 5801], sequence_length=64,
                batch_size=64, train_updates=400, train_count=2048, validation_count=512, test_count=1024,
                split_seed=20261107, max_fit_wall_seconds=480, mass_tolerance=5e-5, schedule_seed=78137,
                state_count=STATE_COUNT, expected_parameter_count=EXPECTED_PARAMETERS,
                latency_warmup=10, latency_repeats=100, throughput_batch=64, throughput_repeats=20,
                bundle_sha256=bundle_sha, bundle_metadata_sha256=metadata_sha, source_pins=source_pins,
                statistical_contract=STATISTICAL_CONTRACT, qualification_receipts=receipts,
                numerical_resolution=selected, canonical_numerical_parent="bcbb75d218addc6c129a8a98a87a562744a2c18d",
                execution_environment=execution,
                bundle_construction_environment={k: metadata[k] for k in ("schema", "python", "numpy", "scipy")},
                runtime_feasibility_policy=dict(non_task_probe_max_wall_seconds=450, fit_timeout_seconds=480,
                                                provider="colab", cloud_job_max_seconds=3000,
                                                minimum_remaining_before_operation_seconds=720,
                                                supervisor_startup_and_drain_reserve_seconds=60,
                                                export_and_close_reserve_seconds=180,
                                                one_statistical_group_and_phase_per_provider_job=True,
                                                operations_per_runner_invocation=1,
                                                execution_gpu_index=0, concurrent_fits=1,
                                                selection_in_separate_provider_phase=True,
                                                evaluation_after_verified_selection_lock=True,
                                                exact_verified_history_before_next_provider_job=True,
                                                halt_owner_on_unknown_or_identity_environment_integrity_failure=True,
                                                replay_failed_or_timeout_fits=False,
                                                replay_unknown_fits=False),
                original_campaign_completion_credit=0, hepta_ndu_completion_credit=0,
                formal_training_attempts_before_freeze=0, full_physical_energy_joules=None,
                external_retention_status="unmeasured", expansion_admission="HOLD")
    plan["resource_migration"] = resource_lineage
    add_prospective_pins(plan, directory.parents[1])
    plan["ordered_fit_roster_sha256"] = digest(ordered_roster(plan))
    validate_execution_environment(plan, environments["cuda"], metadata)
    validate_execution_environment(plan, budget["environment"], metadata)
    validate_plan(plan)
    audit_diff(parent_plan, plan)
    candidate_path = paths["output"].with_name("freeze-check-" + digest(plan) + ".json")
    write_json(candidate_path, plan)
    load_contract(paths["bundle"], candidate_path)
    write_json(paths["output"], plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "unit", "graph-cpu", "graph-cuda", "sequence-cpu", "sequence-cuda",
                 "resolution", "fixed-renewal", "budget", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("parent-plan", "qualification-manifest", "artifact-root", "native-receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("qualification-manifest-sha256", "native-receipt-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    plan = freeze(args)
    print(plan["study_id"], file_sha(args.output), plan["ordered_fit_roster_sha256"])


if __name__ == "__main__":
    main()
