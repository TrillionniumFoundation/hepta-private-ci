"""Fresh Colab qualification of unchanged S81 sources; never task training."""
from contextlib import redirect_stderr, redirect_stdout
import argparse
import ctypes
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
import signal
import subprocess
import sys
import time
import zipfile

from qualification.hcsn_regenerative.colab_qualification_v3.asset_transport import (
    AssetError, canonical, regular_bytes, require, safe_error, sha, _new_file)

CONTRACT_SHA256 = "c5cfa61cea013ca719713e3e46d9158904288cfbb44b2c13705b7e9d7a504d77"
REQUEST_ID = "hcsn-s81-colab-v3-qualification-20261107-1631115f163f"
STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-v3"
SOURCE35_SHA256 = "ad130bd8cd307ae4e6971a11978863ed6771ccc269b1f40b468d530f1f9f9c4e"
# Linux uapi /usr/include/linux/prctl.h defines these two constants.
PR_SET_CHILD_SUBREAPER, PR_GET_CHILD_SUBREAPER = 36, 37


def stamp():
    return datetime.now(timezone.utc).isoformat()


def dump(path, value):
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    tmp = path.with_name(path.name + ".tmp")
    _new_file(tmp, raw)
    os.replace(tmp, path)


def capability(request_id, output):
    require(request_id == REQUEST_ID and output == "evidence/capability.json", "CAPABILITY_IDENTITY")
    start, stage = time.monotonic(), "DEPENDENCY_METADATA"
    report = dict(schema="hcsn-colab-qualification-capability-v3", request_id=request_id,
        observed_unix=time.time(), python=platform.python_version(), packages={}, gpu_devices=[],
        cuda_verified=False, full_physical_energy_joules=None, formal_training_fits=0,
        optimizer_updates=0, task_dataset_reads=0, diagnostic_only=True,
        gpu_count_scope="PyTorch interface only, not a physical host GPU count.")
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for name in ("torch", "numpy", "scipy", "nvidia-ml-py"):
                try:
                    report["packages"][name] = importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError:
                    report["packages"][name] = None
            stage = "DEPENDENCY_IMPORT"
            import numpy
            import scipy
            import torch
            report.update(torch_version=str(torch.__version__), cuda_version=torch.version.cuda,
                numpy_version=numpy.__version__, scipy_version=scipy.__version__,
                cuda_available=torch.cuda.is_available(), gpu_count=torch.cuda.device_count())
            stage = "CUDA_MATRIX_PROBE"
            for index in range(torch.cuda.device_count()):
                device = "cuda:" + str(index)
                p = torch.cuda.get_device_properties(index)
                x = torch.arange(4096, dtype=torch.float32, device=device).reshape(64, 64)
                y = x @ torch.eye(64, dtype=torch.float32, device=device)
                torch.cuda.synchronize(index)
                report["gpu_devices"].append(dict(index=index, name=p.name, memory_bytes=p.total_memory,
                    compute_capability=list(torch.cuda.get_device_capability(index)),
                    matrix_identity_pass=bool(torch.equal(x, y)),
                    probe_peak_allocated_bytes=torch.cuda.max_memory_allocated(index)))
            report["cuda_verified"] = bool(report["gpu_devices"]) and all(
                x["matrix_identity_pass"] and "T4" in x["name"] for x in report["gpu_devices"])
    except Exception as error:
        report["error"] = dict(exception_class=safe_error(error), category=stage + "_FAILED")
    report.update(status="pass" if report["cuda_verified"] else "failed", wall_seconds=time.monotonic() - start)
    _new_file(Path(output), json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n")
    print(json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["cuda_verified"] else 1


def proc_stat(pid):
    fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
    return dict(pid=pid, state=fields[0], ppid=int(fields[1]), pgid=int(fields[2]), start_ticks=int(fields[19]))


class ChildScope:
    """Own descendants by ancestry and start ticks, including escaped sessions."""
    def __init__(self):
        self.pid = os.getpid()
        require(int(Path("/proc/self").resolve().name) == self.pid, "PROC_NAMESPACE_UNVERIFIED")
        require(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "PIDFD_REQUIRED")
        self.start_ticks = proc_stat(self.pid)["start_ticks"]
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        self.libc.prctl.restype = ctypes.c_int
        self.previous = self.get_subreaper()
        require(self.libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0 and self.get_subreaper() == 1,
                "SUBREAPER_NOT_ESTABLISHED")

    def get_subreaper(self):
        value = ctypes.c_int()
        pointer = ctypes.cast(ctypes.byref(value), ctypes.c_void_p).value
        require(self.libc.prctl(PR_GET_CHILD_SUBREAPER, pointer, 0, 0, 0) == 0, "SUBREAPER_GET_FAILED")
        return value.value

    def snapshot(self):
        require(int(Path("/proc/self").resolve().name) == self.pid
                and proc_stat(self.pid)["start_ticks"] == self.start_ticks and self.get_subreaper() == 1,
                "CONTROLLER_IDENTITY_CHANGED")
        table = {}
        for path in Path("/proc").iterdir():
            if not path.name.isdigit():
                continue
            try:
                row = proc_stat(int(path.name))
            except (FileNotFoundError, ProcessLookupError):
                continue
            table[row["pid"]] = row
        owned, changed = {self.pid}, True
        while changed:
            added = {pid for pid, row in table.items() if row["ppid"] in owned} - owned
            changed = bool(added)
            owned.update(added)
        return table, {pid: row for pid, row in table.items() if pid in owned and pid != self.pid}

    def signal_owned(self, records, sig):
        actions = []
        for pid, expected in records.items():
            handle = None
            try:
                _, current = self.snapshot()
                if pid not in current:
                    continue
                require(current[pid]["start_ticks"] == expected["start_ticks"], "DESCENDANT_PID_REUSED")
                handle = os.pidfd_open(pid, 0)
                require(proc_stat(pid)["start_ticks"] == expected["start_ticks"], "DESCENDANT_PID_REUSED")
                signal.pidfd_send_signal(handle, sig, None, 0)
                actions.append(dict(pid=pid, start_ticks=expected["start_ticks"], signal=int(sig)))
            except (FileNotFoundError, ProcessLookupError):
                pass
            finally:
                if handle is not None:
                    os.close(handle)
        return actions

    @staticmethod
    def reap():
        reaped = []
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
            reaped.append(dict(pid=pid, wait_status=status))
        return reaped

    def finish(self, process, *, timed_out, grace_seconds=3.0):
        table, descendants = self.snapshot()
        unexpected = process.poll() is not None and any(row["state"] != "Z" for row in descendants.values())
        proof = dict(controller_pid=self.pid, controller_start_ticks=self.start_ticks,
            subreaper_verified=True, proc_namespace_verified=True, initial_owned=list(descendants.values()),
            unexpected_live_descendant_after_main_exit=unexpected, actions=[], reaped=[])
        for sig in (signal.SIGTERM, signal.SIGKILL):
            live = {pid: row for pid, row in descendants.items() if row["state"] != "Z"}
            if live:
                proof["actions"].extend(self.signal_owned(live, sig))
            deadline = time.monotonic() + grace_seconds
            while True:
                process.poll()
                if process.returncode is not None:
                    proof["reaped"].extend(self.reap())
                table, descendants = self.snapshot()
                group_live = any(row["pgid"] == process.pid and row["state"] != "Z" for row in table.values())
                if process.returncode is not None and not descendants and not group_live:
                    proof.update(child_execution_stopped=True, process_group_alive=False,
                                 remaining_owned=[], returncode=process.returncode, timed_out=timed_out)
                    return proof
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
        proof.update(child_execution_stopped=False, process_group_alive=group_live,
                     remaining_owned=list(descendants.values()), returncode=process.returncode, timed_out=timed_out)
        return proof

    def close(self):
        _, descendants = self.snapshot()
        require(not descendants, "LIVE_DESCENDANTS_PREVENT_SCOPE_CLOSE")
        require(self.libc.prctl(PR_SET_CHILD_SUBREAPER, self.previous, 0, 0, 0) == 0,
                "SUBREAPER_RESTORE_FAILED")


def energy():
    rows = []
    try:
        import pynvml
        pynvml.nvmlInit()
        for index in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            row = dict(index=index, uuid=str(pynvml.nvmlDeviceGetUUID(handle)))
            try:
                row["millijoules"] = int(pynvml.nvmlDeviceGetTotalEnergyConsumption(handle))
            except Exception as error:
                row.update(millijoules=None, error_type=safe_error(error))
            rows.append(row)
    except Exception as error:
        return dict(available=False, devices=rows, error_type=safe_error(error))
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    return dict(available=bool(rows) and all(row["millijoules"] is not None for row in rows), devices=rows)


def delta(before, after):
    previous = {row["uuid"]: row for row in before["devices"]}
    result = []
    for row in after["devices"]:
        old = previous.get(row["uuid"])
        valid = old is not None and old["millijoules"] is not None and row["millijoules"] is not None and row["millijoules"] >= old["millijoules"]
        result.append(dict(index=row["index"], uuid=row["uuid"],
            device_interval_joules=(row["millijoules"] - old["millijoules"]) / 1000 if valid else None))
    return result


def semantic_check(stage, source):
    if "result_json" not in stage:
        if stage["name"] == "capability":
            value = json.loads(regular_bytes(source / "evidence/capability.json"))
            return dict(pass_=value.get("cuda_verified") is True and value.get("request_id") == REQUEST_ID
                        and value.get("schema") == "hcsn-colab-qualification-capability-v3")
        return dict(pass_=True, scope="Process exit and exact unit observation.")
    value = json.loads(regular_bytes(source / stage["result_json"]))
    result = dict(pass_=value.get("status") in stage["accepted_statuses"],
                  result_json=stage["result_json"], observed_status=value.get("status"))
    if "checks_expected" in stage:
        checks, key = value.get("checks", []), stage["check_key"]
        result.update(checks_run=len(checks), checks_passed=sum(row.get(key) is True for row in checks))
        result["pass_"] &= len(checks) == stage["checks_expected"] and all(row.get(key) is True for row in checks)
    if stage["name"] == "fixed-renewal-audit":
        result["pass_"] &= value.get("unit_methods_run") == 6 and value.get("unit_errors") == 0 and value.get("unit_failures") == 0 and value.get("source_unchanged") is True
    if stage["name"] == "resolution-s81-fixed":
        selected = value.get("smallest_eligible_configuration") or {}
        result.update(rows_measured=len(value.get("rows", [])), configuration=selected,
                      all_configuration_failures_retained=True, model_selection_changed=False)
        result["pass_"] &= (len(value.get("rows", [])) == 12 and value.get("source_unchanged") is True
            and value.get("task_dataset_reads") == 0 and value.get("task_optimizer_updates") == 0
            and value.get("thresholds") == dict(common_bin_state_l1=.02, cumulative_hit_relative=.03, reference_crosscheck_abs=2e-8)
            and selected.get("active_cells") == 64 and selected.get("phase_cells") == 16 and selected.get("eligible") is True)
    if stage["name"] == "mechanism-nontask-budget-cuda":
        result.update(optimizer_updates_completed=value.get("optimizer_updates_completed"), wall_seconds=value.get("wall_seconds"))
        wall = value.get("wall_seconds")
        result["pass_"] &= (value.get("optimizer_updates_completed") == 400 and value.get("formal_training_fits") == 0
            and value.get("task_datasets_read") is False and value.get("within_480_second_probe_window") is True
            and type(wall) in (int, float) and math.isfinite(wall) and 0 <= wall < 450)
    return result


def run_stage(stage, source, out, env, scope):
    start, gpu0, cpu0 = time.monotonic(), energy(), resource.getrusage(resource.RUSAGE_CHILDREN)
    row = dict(name=stage["name"], argv=[sys.executable, "-B", *stage["args"]], started_utc=stamp(),
        timeout_seconds=stage["timeout_seconds"], returncode=None, timeout=False, skipped=False,
        semantic_gate_pass=False, child_execution_stopped=False)
    stdout, stderr = out / (stage["name"] + ".stdout.log"), out / (stage["name"] + ".stderr.log")
    process = None
    try:
        _, existing = scope.snapshot()
        require(not existing, "PREEXISTING_CONTROLLER_DESCENDANTS")
        with stdout.open("xb") as a, stderr.open("xb") as b:
            process = subprocess.Popen(row["argv"], cwd=source, env=env, stdout=a, stderr=b, start_new_session=True)
            try:
                process.wait(timeout=stage["timeout_seconds"])
            except subprocess.TimeoutExpired:
                row["timeout"] = True
            proof = scope.finish(process, timed_out=row["timeout"])
            row.update(returncode=proof["returncode"], child_execution_stopped=proof["child_execution_stopped"],
                       stop_proof=proof)
        if row["returncode"] == 0 and not row["timeout"] and row["child_execution_stopped"] and not proof["unexpected_live_descendant_after_main_exit"]:
            row["semantic_observation"] = semantic_check(stage, source)
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
        children_peak_rss_kib=cpu1.ru_maxrss, gpu_device_intervals=delta(gpu0, energy()))
    if "unit_methods_expected" in stage:
        log = regular_bytes(stderr).decode() if stderr.exists() else ""
        matches = re.findall(r"Ran (\d+) tests? in", log)
        counts = {key: int(re.search(key + r"=(\d+)", log).group(1)) if re.search(key + r"=(\d+)", log) else 0 for key in ("failures", "errors", "skipped")}
        row["unit_observation"] = dict(methods_run=int(matches[-1]) if matches else None, **counts)
        row["semantic_gate_pass"] &= row["unit_observation"]["methods_run"] == stage["unit_methods_expected"] and not any(counts.values())
    return row


def run_qualification():
    outer_start, work = time.monotonic(), Path.cwd()
    source = Path(__file__).absolute().parents[3]
    contract_raw = regular_bytes(source / "qualification-contract.json")
    require(sha(contract_raw) == CONTRACT_SHA256, "COMMAND_CONTRACT_CHANGED")
    contract = json.loads(contract_raw)
    config = json.loads(regular_bytes(source / "qualification-config.json"))
    require(config["request_id"] == contract["request_id"] == REQUEST_ID
            and config["study_id"] == contract["study_id"] == STUDY_ID, "QUALIFICATION_IDENTITY")
    original42, controls = config["original42_source_pins"], config["control_source_files"]
    manifest = contract["source_files"]
    require(len(original42) == 42 and len(manifest) == 35 and len(controls) == 5, "SOURCE_ROSTER_COUNT")
    require(sha(canonical(manifest)) == contract["source_set_sha256"] == SOURCE35_SHA256, "SOURCE35_IDENTITY")
    def all_source_unchanged():
        return (all(sha(regular_bytes(source / name)) == expected for name, expected in original42.items())
            and all(dict(bytes=len(raw := regular_bytes(source / name)), sha256=sha(raw)) == item for name, item in controls.items())
            and all(original42[name] == item["sha256"] and len(regular_bytes(source / name)) == item["bytes"] for name, item in manifest.items()))
    require(all_source_unchanged(), "SOURCE_BEFORE_EXECUTION_CHANGED")
    commands = contract["commands"]
    require(len(commands) == 12 and sum(row["timeout_seconds"] for row in commands) == 2700, "STAGE_BUDGET_CHANGED")
    inputs = source / "inputs/prior-qualified-bundle"
    fixed = contract["fixed_input"]
    def fixed_unchanged():
        return all(dict(bytes=len(raw := regular_bytes(inputs / item["output_name"])), sha256=sha(raw))
                   == {key: item[key] for key in ("bytes", "sha256")} for item in fixed["members"].values())
    require(fixed_unchanged(), "FIXED_INPUT_CHANGED")
    out = source / "evidence"
    out.mkdir(mode=0o700, exist_ok=False)
    settings = dict(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                    CUBLAS_WORKSPACE_CONFIG=":4096:8", PYTHONDONTWRITEBYTECODE="1")
    env = dict(os.environ, **settings)
    source_report = dict(files=manifest, source_set_sha256=SOURCE35_SHA256, subset_identities=contract["subset_identities"],
                        original42_source_pins=original42, control_source_files=controls)
    dump(work / "source-manifest.json", source_report)
    start, cpu0, gpu0 = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN), energy()
    report = dict(schema="hcsn-s81-colab-v3-qualification-execution-v1", request_id=REQUEST_ID, study_id=STUDY_ID,
        **source_report, source_files=manifest, commands=commands, fixed_input=fixed, started_utc=stamp(),
        python=platform.python_version(), stages=[], status="running", provider_timeout_seconds=3000,
        stage_wall_budget_seconds=2700, formal_training_fits=0, formal_task_dataset_reads=0,
        independent_nontask_budget_updates_registered=400, external_task_gain_established=False,
        worker_children_stopped=False, production_activation=False, full_physical_energy_joules=None,
        monetary_cost=None, stage_environment=settings, gpu_energy_start=gpu0,
        gpu_counter_scope="Actual device interval, including idle/unattributed activity; not full physical energy.",
        bootstrap_elapsed_seconds=start - outer_start, actual_native_producer_binding="External authoritative Colab ledger and native evidence only.",
        old_v1_formal_study_completion_credit=0, original_170_campaign_completion_credit=0)
    scope = None
    dump(work / "execution.json", report)
    try:
        scope = ChildScope()
        for stage in commands:
            if any(row["returncode"] != 0 or not row["semantic_gate_pass"] or not row.get("child_execution_stopped") for row in report["stages"]):
                report["stages"].append(dict(name=stage["name"], returncode=None, skipped=True, timeout=False,
                    semantic_gate_pass=False, child_execution_stopped=None, timeout_seconds=stage["timeout_seconds"],
                    wall_seconds=0., reason="Failed prerequisite; not executed."))
                dump(work / "execution.json", report)
                continue
            print(json.dumps(dict(event="stage_started", name=stage["name"])), flush=True)
            row = run_stage(stage, source, out, env, scope)
            if "unit_observation" in row:
                observation = dict(schema="hcsn-unit-observation-v1", request_id=REQUEST_ID,
                    status="pass" if row["returncode"] == 0 and row["semantic_gate_pass"] else "failed",
                    source_pins={name: item["sha256"] for name, item in manifest.items()},
                    stdout_sha256=row["stdout_sha256"], stderr_sha256=row["stderr_sha256"], **row["unit_observation"])
                dump(out / (stage["name"] + ".unit-observation.json"), observation)
                if stage["name"] == "mechanism-unit":
                    dump(out / "mechanism-unit-result.json", dict(observation, schema="hcsn-mechanism-unit-result-v1",
                        derived_from_observation="evidence/mechanism-unit.unit-observation.json",
                        observation_sha256=sha(regular_bytes(out / "mechanism-unit.unit-observation.json")),
                        command=row["argv"], formal_training_fits=0,
                        native_producer_binding="External authoritative Colab ledger and verified fetch receipts."))
            report["stages"].append(row)
            dump(work / "execution.json", report)
            print(json.dumps({key: row[key] for key in ("name", "returncode", "timeout", "wall_seconds", "semantic_gate_pass", "child_execution_stopped")}), flush=True)
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
        report["worker_children_stopped"] = stopped and all(
            row.get("child_execution_stopped") is True for row in report["stages"] if not row.get("skipped"))
        cpu1, gpu1 = resource.getrusage(resource.RUSAGE_CHILDREN), energy()
        report.update(finished_utc=stamp(), wall_seconds=time.monotonic() - start, gpu_energy_end=gpu1,
            gpu_device_intervals=delta(gpu0, gpu1), children_user_cpu_seconds=cpu1.ru_utime - cpu0.ru_utime,
            children_system_cpu_seconds=cpu1.ru_stime - cpu0.ru_stime, children_peak_rss_kib=cpu1.ru_maxrss,
            source_unchanged=all_source_unchanged(), fixed_input_unchanged=fixed_unchanged())
        passed = "orchestration_error_class" not in report and len(report["stages"]) == 12 and report["source_unchanged"] and report["fixed_input_unchanged"] and report["worker_children_stopped"] and all(
            row["returncode"] == 0 and row["semantic_gate_pass"] and not row["timeout"] and not row["skipped"] for row in report["stages"])
        report["status"] = "pass" if passed else "failed"
        report["exit_zero_scope"] = "Evidence export only; actual qualification requires all fresh gates and external native proof."
        dump(work / "execution.json", report)
        with zipfile.ZipFile(work / "suite-artifacts.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in ("execution.json", "source-manifest.json", "asset-materialization.json"):
                archive.write(work / name, name)
            for root in (out, inputs):
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(source).as_posix())
        dump(work / "outer-timing.json", dict(schema="hcsn-qualification-outer-timing-v3", request_id=REQUEST_ID,
            wall_seconds=time.monotonic() - outer_start, scope="Materialization excluded; source checks, all stages and ZIP assembly included; final timing write excluded.",
            full_physical_energy_joules=None, monetary_cost=None))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", action="store_true")
    parser.add_argument("--request-id")
    parser.add_argument("--output")
    args = parser.parse_args()
    return capability(args.request_id, args.output) if args.capability else run_qualification()


if __name__ == "__main__":
    raise SystemExit(main())
