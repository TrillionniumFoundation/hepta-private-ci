#!/usr/bin/env python3
"""Draft: one new CI measurement; refuses every unfrozen contract."""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time

SCHEMA = "hepta.cargo_deny.new_measurement.supervisor.v2"
PROPS = ("ActiveState", "SubState", "Result", "ExecMainCode", "ExecMainStatus",
         "ControlGroup", "CPUUsageNSec", "CPUQuotaPerSecUSec", "CPUQuotaPeriodUSec",
         "RuntimeMaxUSec", "MemoryMax", "TasksMax", "KillMode", "MemoryPeak")
CONTROL_LIMIT = 10

def duration_usec(value):
    parts = re.findall(r"([0-9]+(?:\.[0-9]+)?)(us|ms|s|min|h)", value)
    if not parts or "".join(x + y for x, y in parts) != value.replace(" ", ""):
        raise RuntimeError("UNRECOGNIZED_SYSTEMD_DURATION")
    scales = {"us": 1, "ms": 1000, "s": 1000000, "min": 60000000, "h": 3600000000}
    return round(sum(float(x) * scales[y] for x, y in parts))

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()

def write_once(path, value):
    path = Path(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 1024 ** 2:
        raise RuntimeError("SUPERVISOR_RECEIPT_SIZE_LIMIT")
    temp = path.with_name(path.name + ".tmp")
    with temp.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.link(temp, path)
    temp.unlink()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--run-root", required=True)
    ap.add_argument("--job-start", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--run-attempt", required=True)
    args = ap.parse_args()
    started_cpu = time.process_time()
    started_wall = time.monotonic()
    repo = Path(args.repo).resolve(strict=True)
    root = Path(args.run_root).resolve()
    start = json.loads(Path(args.job_start).read_text())
    contract_path = Path(args.contract).resolve(strict=True)
    contract = json.loads(contract_path.read_text())
    if contract.get("status") != "ROOT_FROZEN_ADMITTED_ONCE":
        raise RuntimeError("CONTRACT_NOT_FROZEN")
    if datetime.datetime.now(datetime.timezone.utc) >= datetime.datetime.fromisoformat(
            contract["not_after_utc"].replace("Z", "+00:00")):
        raise RuntimeError("CONTRACT_EXPIRED")
    if args.run_attempt != "1" or not args.run_id.isdigit():
        raise RuntimeError("ONLY_INITIAL_RUN_ATTEMPT")
    if os.geteuid() != 0 or sys.version_info[:2] != (3, 12):
        raise RuntimeError("ROOT_SYSTEMD_PYTHON312_REQUIRED")
    if not re.fullmatch(r"[0-9a-f]{40}", args.head):
        raise RuntimeError("HEAD_FORMAT")
    if start["head"] != args.head or start["run_id"] != args.run_id:
        raise RuntimeError("JOB_START_IDENTITY")
    first_clock = float(start["monotonic_seconds"])
    if not math.isfinite(first_clock) or not 0 <= started_wall-first_clock < 600:
        raise RuntimeError("JOB_START_CLOCK_INVALID")
    job_deadline = first_clock + 600
    measurement_deadline = first_clock + 540
    if (Path(args.repo).absolute() != repo
        or repo != Path("/home/runner/work/hepta-private-ci/hepta-private-ci")
        or start["workspace"] != str(repo)
        or not isinstance(start["caller_uid"], int) or start["caller_uid"] <= 0
        or not isinstance(start["caller_gid"], int) or start["caller_gid"] < 0
        or start["workspace_uid"] != start["caller_uid"]
        or repo.stat().st_uid != start["caller_uid"]
        or (repo/".git").is_symlink() or not (repo/".git").is_dir()
        or (repo/".git").stat().st_uid != start["caller_uid"]):
        raise RuntimeError("CHECKOUT_OWNER_OR_LOCATION_INVALID")
    checkout_owner = {"workspace": str(repo), "uid": start["caller_uid"],
                      "gid": start["caller_gid"],
                      "workspace_gid": repo.stat().st_gid,
                      "git_directory_gid": (repo/".git").stat().st_gid}
    resource.setrlimit(resource.RLIMIT_CPU, (5, 10))
    if root.exists():
        raise RuntimeError("CREATE_ONLY_RUN_ROOT_EXISTS")
    root.mkdir(mode=0o755, parents=True)
    out = root / "out"
    out.mkdir()
    work = root / "work"
    work.mkdir()
    unit = "hepta-cargo-deny-new-" + args.run_id + "-001.service"
    receipt = {"schema": SCHEMA, "status": "PREFLIGHT", "unit": unit,
               "subject_head": contract["subject_head"], "ci_head": args.head,
               "run_id": args.run_id, "run_attempt": 1,
               "contract_sha256": sha(contract_path), "controls": [],
               "first_step_record": start, "first_step_record_sha256": sha(args.job_start),
               "old_ci_equivalence_claimed": False,
               "old_log_accesses": 0, "whole_job_cpu_seconds": None,
               "host_and_network_service_cpu_seconds": None,
               "absolute_deadlines": {"first_step_monotonic": first_clock,
                   "measurement_and_cleanup_monotonic": measurement_deadline,
                   "job_monotonic": job_deadline},
               "checkout_owner_precondition": checkout_owner}
    started_unit = False
    unit_props = {}
    unit_cpu = None
    control_cpu = 0.0
    control_cpu_complete = True
    observed_all_children_cpu = None
    stopped = False
    unit_cpu_complete = False
    def limited_control(argv):
        nonlocal control_cpu, control_cpu_complete
        if len(receipt["controls"]) >= CONTROL_LIMIT:
            raise RuntimeError("CONTROL_CALL_LIMIT")
        n = len(receipt["controls"]) + 1
        stdout = out / ("control-%02d.stdout" % n)
        stderr = out / ("control-%02d.stderr" % n)
        entry = {"argv": argv, "started": False, "returncode": None}
        receipt["controls"].append(entry)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        now = time.monotonic()
        def limits():
            resource.setrlimit(resource.RLIMIT_CPU, (1, 2))
            resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        p = None
        code = None
        try:
            with stdout.open("xb") as fo, stderr.open("xb") as fe:
                p = subprocess.Popen(argv, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL,
                                     env={"PATH": "/usr/bin:/bin", "SYSTEMD_PAGER": "",
                                          "SYSTEMD_COLORS": "0"},
                                     start_new_session=True, preexec_fn=limits)
                entry["started"] = True
                entry["pid"] = p.pid
                remaining_job = job_deadline-time.monotonic()
                if remaining_job <= 0:
                    raise subprocess.TimeoutExpired(argv, 0)
                code = p.wait(timeout=min(8, remaining_job))
        except BaseException as error:
            control_cpu_complete = False
            entry["error"] = type(error).__name__ + ": " + str(error)
            if p is not None:
                entry["killed"] = True
                try:
                    os.killpg(p.pid, 9)
                except ProcessLookupError:
                    pass
                try:
                    code = p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    entry["reaped"] = False
            raise
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            used = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
            control_cpu += used
            entry.update({"returncode": code, "reaped_cpu_seconds": used,
                          "wall_seconds": time.monotonic() - now})
            entry.setdefault("reaped", code is not None)
            for path, key in ((stdout, "stdout"), (stderr, "stderr")):
                if path.exists():
                    entry[key + "_sha256"] = sha(path)
                    entry[key + "_bytes"] = path.stat().st_size
        if code:
            control_cpu_complete = False
            raise RuntimeError("CONTROL_FAILED_" + str(n))
        return stdout.read_text()
    def show():
        raw = limited_control(["/usr/bin/systemctl", "show", unit,
                               "--property=" + ",".join(PROPS)])
        return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    try:
        pins = contract["publication_file_pins"]
        for rel, expected in pins.items():
            if sha(repo / rel) != expected:
                raise RuntimeError("PUBLICATION_PIN_MISMATCH_" + rel)
        launch_clock = time.monotonic()
        # Reserve ten seconds for unit-start latency/stop grace, and sixty job
        # seconds for final receipts/upload. Every phase shares this deadline.
        remaining = min(530, int(measurement_deadline-launch_clock)-10)
        if remaining < 120:
            raise RuntimeError("INSUFFICIENT_JOB_WALL_REMAINDER")
        worker_deadline = launch_clock + remaining
        receipt["worker_absolute_deadline_monotonic"] = worker_deadline
        worker = repo / contract["worker_path"]
        argv = ["/usr/bin/systemd-run", "--quiet", "--unit=" + unit,
                "--property=Type=exec", "--property=RemainAfterExit=yes",
                "--property=KillMode=control-group", "--property=TimeoutStopSec=5s",
                "--property=RuntimeMaxSec=" + str(remaining) + "s",
                "--property=CPUAccounting=yes", "--property=CPUQuota=25%",
                "--property=CPUQuotaPeriodSec=100ms", "--property=MemoryAccounting=yes",
                "--property=MemoryMax=4G", "--property=TasksMax=64",
                "--property=UMask=0022",
                "--property=StandardOutput=null", "--property=StandardError=null",
                "/usr/bin/python3", "-I", "-B", str(worker), "--repo", str(repo),
                "--contract", str(contract_path), "--root", str(root),
                "--head", args.head, "--unit", unit]
        started_unit = True
        limited_control(argv)
        unit_props = show()
        cg = Path("/sys/fs/cgroup") / unit_props["ControlGroup"].lstrip("/")
        if not str(cg.resolve()).startswith("/sys/fs/cgroup/") or unit not in cg.name:
            raise RuntimeError("UNEXPECTED_CONTROL_GROUP")
        if (cg / "cpu.max").read_text().split() != ["25000", "100000"]:
            raise RuntimeError("CPU_QUOTA_NOT_INSTALLED")
        if (cg / "cpu.max.burst").exists() and (cg / "cpu.max.burst").read_text().strip() != "0":
            raise RuntimeError("CPU_BURST_NOT_ZERO")
        if int((cg / "memory.max").read_text()) != 4294967296:
            raise RuntimeError("MEMORY_LIMIT_NOT_INSTALLED")
        if (cg / "pids.max").read_text().strip() != "64":
            raise RuntimeError("TASK_LIMIT_NOT_INSTALLED")
        if unit_props["KillMode"] != "control-group":
            raise RuntimeError("CONTROL_GROUP_KILL_REQUIRED")
        if duration_usec(unit_props["RuntimeMaxUSec"]) != remaining * 1000000:
            raise RuntimeError("KERNEL_WALL_TIMER_NOT_INSTALLED")
        write_once(root / "RESOURCE_ADMITTED.json",
                   {"unit": unit, "cgroup": str(cg), "properties": unit_props,
                    "worker_wall_limit_seconds": remaining,
                    "worker_absolute_deadline_monotonic": worker_deadline,
                    "absolute_deadlines": receipt["absolute_deadlines"],
                    "checkout_owner_precondition": checkout_owner,
                    "child_cpu_soft_seconds": 150, "child_cpu_hard_acceptance_seconds": 180,
                    "kernel_quota": "25000/100000", "kernel_burst": 0})
        receipt["resource_admission_sha256"] = sha(root/"RESOURCE_ADMITTED.json")
        deadline = worker_deadline
        while time.monotonic() < deadline:
            stat = dict(x.split() for x in (cg / "cpu.stat").read_text().splitlines())
            unit_cpu = int(stat["usage_usec"]) / 1000000
            observed_all_children_cpu = unit_cpu + control_cpu
            events = dict(x.split() for x in (cg / "cgroup.events").read_text().splitlines())
            if observed_all_children_cpu >= 150:
                stopped = True
                break
            if events["populated"] == "0":
                break
            time.sleep(0.2)
        else:
            stopped = True
        if stopped:
            limited_control(["/usr/bin/systemctl", "stop", unit])
        unit_props = show()
        receipt["unit_properties"] = unit_props
        if unit_props.get("CPUUsageNSec", "") not in ("", "[not set]"):
            unit_cpu = int(unit_props["CPUUsageNSec"]) / 1000000000
        populated = (cg / "cgroup.events").read_text() if cg.exists() else None
        receipt["unit_cgroup_events_at_end"] = populated
        unit_cpu_complete = (populated is not None and
                             dict(x.split() for x in populated.splitlines())["populated"] == "0" and
                             unit_props.get("CPUUsageNSec", "") not in ("", "[not set]"))
        child = out / "RESULT.json"
        if child.exists():
            value = json.loads(child.read_text())
            if value.get("contract_sha256") != receipt["contract_sha256"]:
                raise RuntimeError("WORKER_CONTRACT_MISMATCH")
            if value.get("ci_head") != args.head or value.get("unit") != unit:
                raise RuntimeError("WORKER_IDENTITY_MISMATCH")
            if value.get("resource_admission_sha256") != receipt["resource_admission_sha256"]:
                raise RuntimeError("WORKER_RESOURCE_ADMISSION_MISMATCH")
            receipt["worker_result_sha256"] = sha(child)
            receipt["worker_status"] = value.get("status")
            if (value.get("schema") != "hepta.cargo_deny.new_measurement.v2"
                or value.get("status") not in ("CHECK_PASSED_NEW_MEASUREMENT_ONLY",
                                                "CHECK_FAILED_NEW_DIAGNOSTIC")
                or any(value.get(key) != 1 for key in (
                    "metadata_attempts", "metadata_invocations",
                    "policy_check_attempts", "policy_check_invocations"))
                or value.get("cleanup") != "RESEARCH_WORK_REMOVED"
                or value.get("frozen_inputs_unchanged") is not True):
                raise RuntimeError("WORKER_DID_NOT_PRODUCE_VALID_MEASUREMENT")
        else:
            raise RuntimeError("WORKER_RESULT_MISSING")
        if stopped:
            raise RuntimeError("RESOURCE_LIMIT_STOP")
        if unit_props.get("ExecMainStatus") not in ("0", "1"):
            raise RuntimeError("WORKER_ABNORMAL_EXIT")
        receipt["status"] = "NEW_MEASUREMENT_RECEIVED"
    except BaseException as e:
        receipt["status"] = "STOP"
        receipt["error"] = type(e).__name__ + ": " + str(e)
    finally:
        if started_unit:
            try:
                final = show()
                if final.get("CPUUsageNSec", "") not in ("", "[not set]"):
                    unit_cpu = int(final["CPUUsageNSec"]) / 1000000000
                receipt["final_unit_properties"] = final
                limited_control(["/usr/bin/systemctl", "stop", unit])
            except BaseException as e:
                receipt["control_cleanup_error"] = type(e).__name__ + ": " + str(e)
                receipt["status"] = "STOP"
                unit_cpu_complete = False
        receipt["unit_cpu_sample_lower_bound_seconds"] = unit_cpu
        receipt["unit_cpu_seconds"] = unit_cpu if unit_cpu_complete else None
        receipt["control_reaped_cpu_seconds"] = control_cpu
        receipt["control_cpu_complete"] = control_cpu_complete
        receipt["child_cpu_seconds"] = (unit_cpu + control_cpu
                                         if unit_cpu is not None and unit_cpu_complete
                                         and control_cpu_complete else None)
        receipt["parent_cpu_before_main_entry_seconds"] = started_cpu
        receipt["parent_cpu_seconds_through_receipt"] = time.process_time()
        receipt["parent_wall_seconds_through_receipt"] = time.monotonic() - started_wall
        receipt["job_wall_seconds_through_receipt"] = time.monotonic() - start["monotonic_seconds"]
        receipt["host_checkout_upload_teardown_cpu_seconds"] = None
        receipt["whole_job_cost_complete"] = False
        receipt["network_bytes_total"] = None
        receipt["ephemeral_runner_teardown_cost_unknown"] = True
        receipt["output_bytes_before_supervisor_receipt"] = sum(
            path.stat().st_size for path in out.iterdir() if path.is_file())
        receipt["output_acceptance_cap_bytes"] = 128 * 1024 ** 2
        if receipt["output_bytes_before_supervisor_receipt"] > 127 * 1024 ** 2:
            receipt["status"] = "STOP"
            receipt["output_error"] = "OUTPUT_TOTAL_LIMIT"
        if time.monotonic() >= job_deadline:
            receipt["status"] = "STOP"
            receipt["deadline_error"] = "JOB_ABSOLUTE_DEADLINE_NOT_MET"
        if receipt["child_cpu_seconds"] is None or receipt["child_cpu_seconds"] > 180:
            receipt["status"] = "STOP"
        write_once(out / "SUPERVISOR.json", receipt)
    return 0 if receipt["status"] == "NEW_MEASUREMENT_RECEIVED" else 2

if __name__ == "__main__":
    sys.exit(main())

