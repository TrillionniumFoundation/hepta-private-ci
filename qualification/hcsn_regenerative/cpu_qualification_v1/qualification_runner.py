"""Fresh CPU numerical qualification with one externally measured budget slot.

The controller executes eight bounded commands.  The earlier 400-update probe
is read from a byte-verified mounted artifact; it is never executed here.
Provider identity and native lifecycle proof are supplied by the observer.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import time
import zipfile

from qualification.hcsn_regenerative.colab_qualification_v4.asset_transport import (
    canonical, regular_bytes, require, safe_error, sha, _new_file)
from qualification.hcsn_regenerative.colab_qualification_v4.qualification_runner import ChildScope

SOURCE35_SHA256 = "ad130bd8cd307ae4e6971a11978863ed6771ccc269b1f40b468d530f1f9f9c4e"
STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-cpu-v1"
ARTIFACTS = ("execution.json", "source-manifest.json", "outer-timing.json", "suite-artifacts.zip", "artifact-manifest.json")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def pin(raw):
    return dict(bytes=len(raw), sha256=sha(raw))


def dump(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    temporary = path.with_name(path.name + ".tmp")
    _new_file(temporary, raw)
    os.replace(temporary, path)


def capability(request_id, output, expected_environment):
    start = time.monotonic()
    report = dict(schema="hcsn-kaggle-cpu-qualification-capability-v1", request_id=request_id,
        status="failed", observed_unix=time.time(), packages={}, formal_training_fits=0,
        task_dataset_reads=0, optimizer_updates=0, device="cpu", full_physical_energy_joules=None)
    try:
        for name in ("torch", "numpy", "scipy"):
            report["packages"][name] = importlib.metadata.version(name)
        import torch
        import scipy
        from qualification.hcsn_regenerative.mechanism_worker import configure_torch
        from qualification.hcsn_regenerative.mechanism_model import environment
        configure_torch("cpu")
        actual = environment("cpu")
        report["environment"] = actual
        report["scipy_version"] = scipy.__version__
        require(actual == expected_environment, "CPU_ENVIRONMENT_DIFFERS_FROM_EXTERNAL_BUDGET")
        require(actual["cpu_threads"] == 1 and actual["deterministic_algorithms"] is True,
                "CPU_EXECUTION_SETTINGS_DIFFER")
        x = torch.arange(4096, dtype=torch.float32).reshape(64, 64)
        report["matrix_identity_pass"] = bool(torch.equal(x @ torch.eye(64, dtype=torch.float32), x))
        report["status"] = "pass" if report["matrix_identity_pass"] else "failed"
    except Exception as error:
        report["error_class"] = safe_error(error)
    report["wall_seconds"] = time.monotonic() - start
    _new_file(Path(output), canonical(report) + b"\n")
    print(json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "pass" else 1


def semantic_check(stage, source, config):
    if stage["name"] == "capability":
        value = json.loads(regular_bytes(source / "evidence/capability.json"))
        return dict(pass_=value.get("status") == "pass" and value.get("request_id") == config["request_id"]
                    and value.get("environment") == config["external_budget"]["environment"]
                    and value.get("matrix_identity_pass") is True)
    if "result_json" not in stage:
        return dict(pass_=True, scope="Actual process terminal and exact unittest observation.")
    value = json.loads(regular_bytes(source / stage["result_json"]))
    result = dict(pass_=value.get("status") in stage["accepted_statuses"],
                  result_json=stage["result_json"], observed_status=value.get("status"))
    if "checks_expected" in stage:
        checks, key = value.get("checks", []), stage["check_key"]
        result.update(checks_run=len(checks), checks_passed=sum(row.get(key) is True for row in checks))
        result["pass_"] &= len(checks) == stage["checks_expected"] and all(row.get(key) is True for row in checks)
    if stage["name"] == "fixed-renewal-audit":
        result["pass_"] &= (value.get("unit_methods_run") == 6 and value.get("unit_errors") == 0
                            and value.get("unit_failures") == 0 and value.get("source_unchanged") is True)
    if stage["name"] == "resolution-s81-fixed":
        selected = value.get("smallest_eligible_configuration") or {}
        result.update(rows_measured=len(value.get("rows", [])), configuration=selected,
                      all_configuration_failures_retained=True, model_selection_changed=False)
        result["pass_"] &= (len(value.get("rows", [])) == 12 and value.get("source_unchanged") is True
            and value.get("task_dataset_reads") == 0 and value.get("task_optimizer_updates") == 0
            and value.get("thresholds") == dict(common_bin_state_l1=.02, cumulative_hit_relative=.03, reference_crosscheck_abs=2e-8)
            and selected.get("active_cells") == 64 and selected.get("phase_cells") == 16 and selected.get("eligible") is True)
    return result


def run_stage(stage, source, out, env, scope, config):
    start, cpu0 = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    row = dict(name=stage["name"], argv=[sys.executable, "-B", *stage["args"]], started_utc=stamp(),
        timeout_seconds=stage["timeout_seconds"], returncode=None, timeout=False, skipped=False,
        semantic_gate_pass=False, child_execution_stopped=False)
    stdout, stderr = out / (stage["name"] + ".stdout.log"), out / (stage["name"] + ".stderr.log")
    process = None
    try:
        _, existing = scope.snapshot()
        require(not existing, "PREEXISTING_CONTROLLER_DESCENDANTS")
        with stdout.open("xb") as a, stderr.open("xb") as b:
            process = subprocess.Popen(row["argv"], cwd=source, env=env, stdin=subprocess.DEVNULL,
                                       stdout=a, stderr=b, start_new_session=True)
            try:
                process.wait(timeout=stage["timeout_seconds"])
            except subprocess.TimeoutExpired:
                row["timeout"] = True
            proof = scope.finish(process, timed_out=row["timeout"])
            row.update(returncode=proof["returncode"], child_execution_stopped=proof["child_execution_stopped"], stop_proof=proof)
        if (row["returncode"] == 0 and not row["timeout"] and row["child_execution_stopped"]
                and not proof["unexpected_live_descendant_after_main_exit"]):
            row["semantic_observation"] = semantic_check(stage, source, config)
            row["semantic_gate_pass"] = row["semantic_observation"]["pass_"]
    except Exception as error:
        row["control_error"] = safe_error(error)
        if process is not None:
            try:
                row["stop_proof"] = scope.finish(process, timed_out=row["timeout"])
                row["child_execution_stopped"] = row["stop_proof"]["child_execution_stopped"]
                row["returncode"] = row["stop_proof"]["returncode"]
            except Exception as stop_error:
                row["stop_proof_error"] = safe_error(stop_error)
    cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    row.update(wall_seconds=time.monotonic() - start, finished_utc=stamp(),
        stdout_sha256=sha(regular_bytes(stdout)) if stdout.exists() else None,
        stderr_sha256=sha(regular_bytes(stderr)) if stderr.exists() else None,
        children_user_cpu_seconds=cpu1.ru_utime - cpu0.ru_utime,
        children_system_cpu_seconds=cpu1.ru_stime - cpu0.ru_stime,
        children_peak_rss_kib=cpu1.ru_maxrss, gpu_device_intervals=[], full_physical_energy_joules=None)
    if "unit_methods_expected" in stage:
        log = regular_bytes(stderr).decode() if stderr.exists() else ""
        matches = re.findall(r"Ran (\d+) tests? in", log)
        counts = {key: int(re.search(key + r"=(\d+)", log).group(1)) if re.search(key + r"=(\d+)", log) else 0
                  for key in ("failures", "errors", "skipped")}
        row["unit_observation"] = dict(methods_run=int(matches[-1]) if matches else None, **counts)
        row["semantic_gate_pass"] &= row["unit_observation"]["methods_run"] == stage["unit_methods_expected"] and not any(counts.values())
    return row


def verify_external_mount(reference):
    producer, name = reference["notebook_ref"], reference["artifact_name"]
    require(re.fullmatch(r"[A-Za-z0-9_-]+/[a-z0-9-]+", producer) is not None and Path(name).name == name,
            "EXTERNAL_INPUT_REFERENCE_INVALID")
    path = Path("/kaggle/input/notebooks") / producer / name
    raw = regular_bytes(path)
    require(pin(raw) == dict(bytes=reference["archive_bytes"], sha256=reference["archive_sha256"]),
            "MOUNTED_EXTERNAL_BUDGET_ARCHIVE_CHANGED")
    member_checks = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(archive.testzip() is None and len(set(archive.namelist())) == len(archive.namelist()),
                "MOUNTED_ARCHIVE_CRC_OR_DUPLICATE")
        require(set(archive.namelist()) == set(reference["archive_members"]), "MOUNTED_ARCHIVE_MEMBER_ROSTER")
        for name, expected in reference["archive_members"].items():
            require(pin(archive.read(name)) == expected, "MOUNTED_ARCHIVE_MEMBER_CHANGED")
            member_checks[name] = expected
        result = json.loads(archive.read(reference["result_member"]))
        require(result["environment"] == reference["environment"] and result["optimizer_updates_completed"] == 400
                and result["status"] == "completed" and type(result["wall_seconds"]) in (float, int)
                and math.isfinite(result["wall_seconds"]) and 0 <= result["wall_seconds"] < 450,
                "MOUNTED_EXTERNAL_BUDGET_RESULT_DIFFERS")
    return dict(status="verified", verified=True, producer_ref=producer, notebook_version=reference["version"],
        bytes=len(raw), sha256=sha(raw), mounted_path=str(path), archive_bytes=len(raw), archive_sha256=sha(raw),
        notebook_ref=producer, kernel_id=reference["kernel_id"], version=reference["version"],
        actual_identity_scope="Mounted bytes match the externally verified immutable producer artifact; latest changed bytes fail closed.",
        members=member_checks, repeated_optimizer_updates=0)


def run_qualification(config_path, public, payload_start, payload_unix):
    source = Path.cwd()
    config = json.loads(regular_bytes(config_path))
    require(config["study_id"] == STUDY_ID and config["provider_timeout_seconds"] == 3000, "QUALIFICATION_IDENTITY")
    sources, controls, reused = (config[k] for k in ("source_files", "control_source_files", "reused_control_source_files"))
    require(len(sources) == 35 and len(controls) == 7 and len(reused) == 3 and
            sha(canonical(sources)) == config["source_set_sha256"] == SOURCE35_SHA256, "SOURCE_ROSTER_IDENTITY")
    all_sources = dict(sources, **controls, **reused)
    require(len(all_sources) == 45, "OVERLAPPING_SOURCE_ROSTERS")
    def source_ok():
        return all(pin(regular_bytes(source / name)) == expected for name, expected in all_sources.items())
    def inputs_ok():
        return all(pin(regular_bytes(source / name)) == expected for name, expected in config["input_files"].items())
    commands = config["commands"]
    require(len(commands) == 8 and sum(x["timeout_seconds"] for x in commands) == 1440, "STAGE_BUDGET_CHANGED")
    out = source / "evidence"
    out.mkdir(mode=0o700, exist_ok=False)
    settings = dict(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                    CUBLAS_WORKSPACE_CONFIG=":4096:8", PYTHONDONTWRITEBYTECODE="1")
    env = dict(os.environ, **settings, PYTHONPATH=str(source))
    source_report = {k:config[k] for k in ("source_files", "source_set_sha256", "input_files", "control_source_files", "reused_control_source_files", "execution_source_scope")}
    source_report.update(schema="hcsn-kaggle-cpu-qualification-source-manifest-v1", request_id=config["request_id"])
    dump(source / "source-manifest.json", source_report)
    start, cpu0 = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    report = dict(source_report, schema="hcsn-kaggle-cpu-qualification-execution-v1", study_id=STUDY_ID,
        commands=commands, started_utc=stamp(), stages=[], status="failed",
        provider_timeout_seconds=3000, stage_wall_budget_seconds=1440, formal_training_fits=0,
        formal_task_dataset_reads=0, formal_task_optimizer_updates=0, task_datasets_read=False, external_task_gain_established=False,
        external_budget_reference=config["external_budget"], external_budget_optimizer_updates_rerun=0,
        worker_children_stopped=False, full_physical_energy_joules=None, monetary_cost=None,
        provider_billed_seconds=None, stage_environment=settings, source_unchanged=False, fixed_input_unchanged=False,
        execution_source_scope=config["execution_source_scope"],
        actual_native_producer_binding="External authoritative Kaggle/native observer proof only.")
    scope = None
    try:
        require(source_ok() and inputs_ok(), "PRE_EXECUTION_SOURCE_OR_INPUT_CHANGED")
        report["mounted_external_budget_input"] = verify_external_mount(config["external_budget"])
        scope = ChildScope()
        for stage in commands:
            if any(row.get("returncode") != 0 or not row.get("semantic_gate_pass") or not row.get("child_execution_stopped") for row in report["stages"]):
                report["stages"].append(dict(name=stage["name"], returncode=None, timeout=False, skipped=True,
                    semantic_gate_pass=False, child_execution_stopped=None, timeout_seconds=stage["timeout_seconds"], wall_seconds=0.,
                    reason="Failed prerequisite; not executed."))
                continue
            print(json.dumps(dict(event="stage_started", name=stage["name"])), flush=True)
            row = run_stage(stage, source, out, env, scope, config)
            if "unit_observation" in row:
                observation = dict(schema="hcsn-unit-observation-v1", request_id=config["request_id"],
                    status="pass" if row["returncode"] == 0 and row["semantic_gate_pass"] else "failed",
                    source_pins={name:item["sha256"] for name,item in sources.items()},
                    stdout_sha256=row["stdout_sha256"], stderr_sha256=row["stderr_sha256"], **row["unit_observation"])
                dump(out / (stage["name"] + ".unit-observation.json"), observation)
                if stage["name"] == "mechanism-unit":
                    dump(out / "mechanism-unit-result.json", dict(observation, schema="hcsn-mechanism-unit-result-v1",
                        derived_from_observation="evidence/mechanism-unit.unit-observation.json",
                        observation_sha256=sha(regular_bytes(out / "mechanism-unit.unit-observation.json")),
                        command=row["argv"], formal_training_fits=0))
            report["stages"].append(row)
            dump(source / "execution.json", report)
            print(json.dumps({k:row[k] for k in ("name", "returncode", "timeout", "wall_seconds", "semantic_gate_pass", "child_execution_stopped")}), flush=True)
    except Exception as error:
        report["orchestration_error_class"] = safe_error(error)
    finally:
        stopped = False
        if scope is not None:
            try:
                _, remaining = scope.snapshot()
                report["remaining_owned_descendants"] = list(remaining.values())
                if not remaining:
                    scope.close()
                    stopped = True
            except Exception as error:
                report["final_stop_error_class"] = safe_error(error)
        report["worker_children_stopped"] = stopped and all(row.get("child_execution_stopped") is True for row in report["stages"] if not row.get("skipped"))
        for stage in commands[len(report["stages"]):]:
            report["stages"].append(dict(name=stage["name"], skipped=True, returncode=None, timeout=False,
                semantic_gate_pass=False, child_execution_stopped=None, timeout_seconds=stage["timeout_seconds"], wall_seconds=0.))
        cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        report.update(finished_utc=stamp(), wall_seconds=time.monotonic()-start,
            children_user_cpu_seconds=cpu1.ru_utime-cpu0.ru_utime, children_system_cpu_seconds=cpu1.ru_stime-cpu0.ru_stime,
            children_peak_rss_kib=cpu1.ru_maxrss, source_unchanged=source_ok(), fixed_input_unchanged=inputs_ok())
        passed = report["source_unchanged"] and report["fixed_input_unchanged"] and report["worker_children_stopped"] and all(
            row["returncode"] == 0 and row["semantic_gate_pass"] and not row["timeout"] and not row["skipped"] for row in report["stages"])
        report["status"] = "pass" if passed else "failed"
        report["exit_zero_scope"] = "Evidence export only; fresh numerical admission requires all gates and external native producer proof."
        dump(source / "execution.json", report)
        with zipfile.ZipFile(public / "suite-artifacts.zip", "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in ("execution.json", "source-manifest.json"):
                archive.writestr(name, regular_bytes(source / name))
            for root in (out, source / "inputs"):
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        archive.writestr(path.relative_to(source).as_posix(), regular_bytes(path))
        for name in ("execution.json", "source-manifest.json"):
            _new_file(public / name, regular_bytes(source / name))
        timing = dict(schema="hcsn-kaggle-cpu-qualification-outer-timing-v1", request_id=config["request_id"],
            started_unix=payload_unix, observed_unix=time.time(), measured_wall_seconds=time.monotonic()-payload_start,
            scope="Payload entry through source unpack, eight stages and completed ZIP/execution/source exports; excludes final timing/manifest writes and provider queue/start/teardown.",
            contains_nested_stage_intervals=True, full_physical_energy_joules=None, monetary_cost=None)
        _new_file(public / "outer-timing.json", canonical(timing)+b"\n")
        rows = [dict(path=name, **pin(regular_bytes(public/name))) for name in ARTIFACTS if name != "artifact-manifest.json"]
        manifest = canonical(dict(schema="hepta-artifact-manifest-v1", request_id=config["request_id"], files=rows))+b"\n"
        require(sum(x["bytes"] for x in rows)+len(manifest) <= 67108864, "ARTIFACT_BUDGET_EXCEEDED")
        _new_file(public / "artifact-manifest.json", manifest)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability", action="store_true")
    parser.add_argument("--config", default="qualification-config.json")
    parser.add_argument("--request-id")
    parser.add_argument("--output")
    args = parser.parse_args()
    require(args.capability, "QUALIFICATION_ENTRY_REQUIRES_PINNED_BOOTSTRAP")
    config = json.loads(regular_bytes(Path(args.config)))
    require(args.request_id == config["request_id"] and args.output == "evidence/capability.json", "CAPABILITY_IDENTITY")
    return capability(args.request_id, args.output, config["external_budget"]["environment"])


if __name__ == "__main__":
    raise SystemExit(main())
