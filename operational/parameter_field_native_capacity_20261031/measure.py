"""Outcome-free original runtime/capacity qualification with an actual owner."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery07 import process as p  # noqa: E402


EPISODE = "visited_counterfactual_capacity_20261031"
ROOT = Path("/work/native_capacity")
GIB = 1024**3


def source_identity(head, contract):
    actual = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True
    ).strip()
    p.require(
        actual == head and SOURCE == Path("/work/source"),
        "Actual capacity source head/path differs",
    )
    status = subprocess.check_output(
        ["git", "-C", str(SOURCE), "status", "--porcelain", "--untracked-files=all"]
    )
    ignored = subprocess.check_output(
        [
            "git",
            "-C",
            str(SOURCE),
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
        ]
    )
    p.require(not status and not ignored, "Capacity source checkout is not pristine")
    result = {}
    for relative, expected in contract["source_files"].items():
        item = p.descriptor(SOURCE / relative)
        p.require(item["sha256"] == expected, "Original scientific source byte changed")
        result[relative] = item
    p.require(len(result) == 167, "Original scientific source population differs")
    for relative in (
        "operational/parameter_field_native_capacity_20261031/measure.py",
        "operational/parameter_field_recovery07/process.py",
        "operational/parameter_field_recovery06/owned_children.py",
        "tools/parameter_field_executor/diagnose.py",
        "tools/parameter_field_executor/runtime_contract.json",
        "tools/parameter_field_executor/packages.txt",
        "tools/parameter_field_executor/torch-wheel.txt",
        ".github/workflows/parameter-field-native-capacity.yml",
    ):
        result[relative] = p.descriptor(SOURCE / relative)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    p.require(
        re.fullmatch("[0-9a-f]{40}", args.source_commit),
        "Actual immutable source is required",
    )
    producer = {
        key: os.environ.get(name)
        for key, name in (
            ("repository", "GITHUB_REPOSITORY"),
            ("run_id", "GITHUB_RUN_ID"),
            ("run_attempt", "GITHUB_RUN_ATTEMPT"),
            ("head_sha", "GITHUB_SHA"),
            ("job", "GITHUB_JOB"),
        )
    }
    p.require(
        producer["repository"] == "TrillionniumFoundation/hepta-private-ci"
        and producer["head_sha"] == args.source_commit
        and producer["job"] == "capacity"
        and all(
            producer[key] and producer[key].isdigit()
            for key in ("run_id", "run_attempt")
        ),
        "Real capacity producer identity is required",
    )
    p.require(
        not ROOT.exists()
        and not Path("/work/assets").exists()
        and not Path("/work/execution07").exists(),
        "Capacity qualification must precede scientific inputs",
    )
    ROOT.mkdir()
    (ROOT / "empty_cwd").mkdir()
    target = ROOT / "INPUT_CONTRACT.json"
    shutil.copyfile(
        SOURCE / "operational/parameter_field_recovery07/INPUT_CONTRACT.json", target
    )
    item = p.descriptor(target)
    contract = p.read(item)
    source_before = source_identity(args.source_commit, contract)
    p.write(ROOT / "SOURCE_BEFORE.json", source_before)
    p.require(
        Path("/sys/fs/cgroup/memory.max").read_text().strip() == str(8 * GIB),
        "A real finite eight-GiB cgroup is required",
    )
    core = p.descriptor(
        SOURCE / "operational/parameter_field_recovery06/owned_children.py"
    )
    binding = {
        "execution_episode": EPISODE,
        "phase": "capacity",
        "component_schema_is_implementation_version_not_execution_episode": True,
        "source_commit": args.source_commit,
        "owned_core_sha256": core["sha256"],
        "input_contract": item,
        "measurement_program": p.descriptor(Path(__file__).resolve()),
    }
    p.write(
        ROOT / "PLAN.json",
        {
            "schema": "hepta.visited-counterfactual.capacity-plan.1",
            "binding": binding,
            "current_producer": producer,
            "scientific_inputs_requested": False,
            "scientific_models_created": False,
            "diagnose_source": source_before[
                "tools/parameter_field_executor/diagnose.py"
            ],
            "diagnose_only_deadline_seconds": 300,
            "environment_setup_cpu_measured_here": False,
        },
    )
    started = time.monotonic()

    def health():
        p.require(time.monotonic() - started < 300, "Capacity probe deadline exhausted")
        p.require(
            Path("/sys/fs/cgroup/memory.max").read_text().strip() == str(8 * GIB),
            "Capacity cgroup changed",
        )
        p.require(
            not Path("/work/assets").exists()
            and not Path("/work/execution07").exists(),
            "Capacity-only process encountered scientific input roots",
        )

    argv = [
        "/opt/runtime/venv/bin/python",
        "-B",
        str(SOURCE / "tools/parameter_field_executor/diagnose.py"),
        "--output",
        str(ROOT / "RUNTIME.json"),
    ]
    log = ROOT / "diagnose.log"
    log.touch(exist_ok=False)
    measured = p.run_owned(
        argv,
        directory=ROOT / "measurement",
        cwd=str(ROOT / "empty_cwd"),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        log=log,
        health=health,
        binding=binding,
    )
    p.require(measured["exit_code"] == 0, "Actual capacity probe failed")
    observed = p.read(ROOT / "RUNTIME.json")
    p.require(
        observed["schema"] == "hepta.executor-qualification.engineering.1"
        and observed["science_admission"] is False
        and observed["sample_interval_seconds"] == 10
        and observed["original_thresholds"]
        == {"ram_bytes": 1879048192, "disk_bytes": 2415919104, "samples": 3}
        and len(observed["capacity_samples"]) == 3,
        "Original capacity probe changed",
    )
    capacity = all(
        row["original_joint_pass"] is True for row in observed["capacity_samples"]
    )
    p.require(
        observed["three_original_joint_passes"] is capacity,
        "Capacity summary differs from its actual samples",
    )
    runtime = observed["runtime"]
    exact = runtime.get("exact_match") is True
    if exact:
        p.require(
            runtime["runtime_sha256"] == contract["runtime_expected"]["runtime_sha256"]
            and runtime["descriptor"] == contract["runtime_expected"]["descriptor"]
            and runtime["package_versions"]
            == contract["runtime_expected"]["package_versions"]
            and runtime["model_created"] is False
            and runtime["scientific_inputs_opened"] is False,
            "Actual capacity runtime does not equal the original target",
        )
    supported = observed["process"].get("supported") is True and all(
        observed["filesystem"].get(key) is True
        for key in ("xattr", "fsync", "atomic_rename", "flock", "byte_readback")
    )
    after = source_identity(args.source_commit, contract)
    p.require(source_before == after, "Qualification changed source bytes")
    p.write(ROOT / "SOURCE_AFTER.json", after)
    health()
    measurement = {
        key: p.descriptor(ROOT / "measurement" / name)
        for key, name in (
            ("intent", "INTENT.json"),
            ("attempt_intent", "001.INTENT.json"),
            ("start", "001.START.json"),
            ("wait4", "001.WAIT4.json"),
            ("closure", "CLOSURE.json"),
        )
    }
    complete = capacity and exact and supported
    p.write(
        ROOT / "COMPLETE.json",
        {
            "schema": "hepta.visited-counterfactual.capacity-complete.1",
            "execution_episode": EPISODE,
            "complete": complete,
            "current_producer": producer,
            "source_commit": args.source_commit,
            "input_contract": item,
            "engineering_receipt": p.descriptor(ROOT / "RUNTIME.json"),
            "engineering_measurement": measurement,
            "engineering_expected_binding": binding,
            "actual_result": measured,
            "finite_cgroup_memory_bytes": 8 * GIB,
            "scientific_inputs_requested": False,
            "scientific_models_created": False,
            "scientific_values_decoded": False,
            "scientific_training_microsteps": 0,
            "full_completion_within_deadline_guaranteed": False,
            "cost_scope": "Real diagnose child and reaped descendants only. Earlier container/runtime setup and later workflow artifact delivery CPU remain separate unknown scopes.",
        },
    )
    print(
        json.dumps(
            {
                "capacity_qualified": complete,
                "exact_runtime": exact,
                "three_original_joint_passes": capacity,
                "scientific_values_decoded": False,
            }
        )
    )
    return 0 if complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
