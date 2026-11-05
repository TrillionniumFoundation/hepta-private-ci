#!/usr/bin/env python3
"""AST, exact argv and fictional binding-fixture checks only; never call main."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
DIRECTORY = Path(__file__).resolve().parent
REVIEW = DIRECTORY.parent
PROGRAM = DIRECTORY / "run_c4_synthetic_census.py"


def main():
    raw = PROGRAM.read_bytes()
    ast.parse(raw, filename=str(PROGRAM))
    specification = importlib.util.spec_from_file_location("c4_synthetic_static_validation", PROGRAM)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    plan = json.loads((REVIEW / "synthetic-census-component-plan.json").read_text())
    checks = []
    for child in plan["children"]:
        index = int(child["argv"][child["argv"].index("--target-index") + 1])
        assert module.native_argv("/fictional/ELF", index)[1:] == child["argv"][1:]
        assert module.ORIGINAL_NATIVE["timeout_seconds"] == child["timeout_seconds"]
        assert module.ORIGINAL_NATIVE["stdout_limit_bytes"] == child["stdout_limit_bytes"]
        assert module.ORIGINAL_NATIVE["stderr_limit_bytes"] == child["stderr_limit_bytes"]
    assert module.build_argv()[:-1] == plan["build"]["original_documented_argv"]
    assert module.build_argv()[-1] == "--message-format=json-render-diagnostics"
    assert module.reader_argv("/fictional/raw", "/fictional/report")[6:] == [
        "--calibration-samples", "2", "--budgets-ns", "1000000", "5000000", "20000000"]
    checks.append("two_native_argv_exact_owner_parameters_and_original_limits")
    checks.append("documented_build_with_only_machine_output_extension")
    checks.append("original_reader_calibration_and_budget_arguments")
    for path, expected in module.BOOTSTRAP_PINS.items():
        assert hashlib.sha256((REVIEW / "source" / path).read_bytes()).hexdigest() == expected
    capture_path = REVIEW.parents[1] / "model_storage/pq_effect_migration/native/test_elf_capture.py"
    assert hashlib.sha256(capture_path.read_bytes()).hexdigest() == module.CAPTURE_SHA256
    checks.append("bootstrap_and_unchanged_capture_source_hashes")
    native = (REVIEW / "source/trillionnium/crates/trnm-crypto-primitives/examples/pon_work_expensive_v1.rs").read_text()
    assert "std::env::args().skip(1)" in native and "current_exe" not in native
    assert "material::materials(None, None)" in native
    checks.append("native_argv_zero_not_used_for_source_or_material_selection")

    # These invented report dictionaries exercise caller-binding functions only.
    # They are not native JSONL, not inputs to the original reader, and never
    # receive execution/measurement credit. No fake streams are written to disk.
    raw_record = {"sha256": "a"*64, "bytes": 1}
    value = dict(schema=module.READER_SCHEMA, native_record_schema=module.NATIVE_SCHEMA,
        status="complete", seed=module.SEED, target="7f" + "ff"*31,
        attempts_per_arm=64, samples=8, reuse_attempts=16, observed_arms=list(module.ARMS),
        raw_sha256=raw_record["sha256"], raw_bytes=1,
        material_identity=[dict(class_=name) for name in ()],
        counts=dict(completed_cells=1080, unsupported_cells=0, failed_cells=0),
        cells=[], budgets={"cpu_ns": [1000000, 5000000, 20000000]},
        calibration_selection=[])
    value["material_identity"] = [{"class": name, "task": "b"*64,
        "a_sha256": "c"*64, "b_sha256": "d"*64} for name in module.CLASSES]
    value["cells"] = [{"class": name, "sample": sample, "arm": arm, "status": "complete",
        "attempts": 64, "setup_count": 4, "trace_sequence_sha256": "e"*64}
        for name in module.CLASSES for sample in range(8) for arm in module.ARMS]
    value["calibration_selection"] = [{"class": name, "calibration_samples": [0, 1],
        "evaluation_samples": [2, 3, 4, 5, 6, 7]} for name in module.CLASSES]
    module.bind_reader_report(value, 0, raw_record)
    checks.append("fictional_binding_shape_positive_control_only")

    def rejected(name, mutation):
        changed = copy.deepcopy(value)
        mutation(changed)
        try:
            module.bind_reader_report(changed, 0, raw_record)
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name + " was accepted")

    rejected("legacy_native_v1_refused", lambda row: row.update(native_record_schema="pon-work-expensive-native-v1"))
    rejected("missing_fifteenth_arm_refused", lambda row: row["observed_arms"].pop())
    rejected("native_default_attempts32_refused", lambda row: row.update(attempts_per_arm=32))
    rejected("native_default_samples3_refused", lambda row: row.update(samples=3))
    rejected("native_default_reuse32_refused", lambda row: row.update(reuse_attempts=32))
    rejected("wrong_seed_refused", lambda row: row.update(seed="0"*64))
    rejected("wrong_target_refused", lambda row: row.update(target="07" + "ff"*31))
    rejected("wrong_raw_digest_refused", lambda row: row.update(raw_sha256="f"*64))
    rejected("missing_material_class_refused", lambda row: row["material_identity"].pop())
    rejected("failed_cell_refused", lambda row: row["counts"].update(completed_cells=1079, failed_cells=1))
    rejected("short_dense_attempt_sequence_refused", lambda row: row["cells"][0].update(attempts=63))
    rejected("missing_dense_setup_epoch_refused", lambda row: row["cells"][0].update(setup_count=3))
    rejected("duplicate_cell_refused", lambda row: row["cells"].__setitem__(1, copy.deepcopy(row["cells"][0])))
    rejected("changed_prefix_budgets_refused", lambda row: row["budgets"].update(cpu_ns=[1, 5, 20]))
    rejected("changed_calibration_split_refused", lambda row: row["calibration_selection"][0].update(calibration_samples=[0]))
    right = copy.deepcopy(value)
    right["target"] = "07" + "ff"*31
    module.bind_reader_report(right, 1, raw_record)
    module.bind_cross_target(value, right)
    checks.append("fictional_cross_target_binding_positive_control_only")
    right["cells"][0]["trace_sequence_sha256"] = "f"*64
    try:
        module.bind_cross_target(value, right)
    except ValueError:
        checks.append("cross_target_trace_change_refused")
    else:
        raise AssertionError("cross target mismatch accepted")
    result = dict(schema="C4-synthetic-external-owner-prelaunch-static-checks-v1",
        status="PASS", coordinator_sha256=hashlib.sha256(raw).hexdigest(),
        checks=checks, count=len(checks), native_executed=False, cargo_executed=False,
        original_reader_executed=False, proc_collector_executed=False,
        qualification=False,
        fixture_scope="Invented Python dictionaries exercise caller binding only; no native streams or model materials generated; main is never called.")
    (DIRECTORY / "prelaunch-static-checks.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
