"""Measured parent for the fixed execution04 supervisor; never uploads or retries."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import durable_archive as archive

BASE = Path("/workspace/scratch/178ced6a501f")
OPS = BASE / "fullstudy_execution04_ops"


def identity(pid):
    value = Path(f"/proc/{pid}/stat").read_text()
    fields = value[value.rfind(")") + 2:].split()
    return {"pid": pid, "start_ticks": fields[19], "process_group": int(fields[2]), "session": int(fields[3])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    config_desc = archive.descriptor(args.config)
    archive.require(config_desc["sha256"] == args.expected_config_sha256, "Config SHA differs")
    config = archive.read(args.config)
    archive.require(config.get("schema") == "hepta.fullstudy.execution04.configuration.1"
                    and config.get("execution_episode") == "execution04_durable_20261030"
                    and Path(config["ops_root"]).resolve() == OPS, "Wrong measured execution")
    python = str(BASE / "runtime_recovery_20261030/venv/bin/python")
    archive.require(config["python"] == python and sys.version_info[:3] == (3, 12, 14), "Wrong verified interpreter")
    supervisor = config["descriptors"]["own_supervisor"]
    archive.verify_descriptor(supervisor)
    archive.verify_descriptor(config["descriptors"]["durable_archive"])
    pinned = config["descriptors"]["wait4_launcher"]
    archive.require(pinned["path"] == str(Path(__file__).resolve()), "Wrong measured launcher pin")
    archive.verify_descriptor(pinned)
    argv = [python, "-B", supervisor["path"], "--config", config_desc["path"],
            "--expected-config-sha256", config_desc["sha256"], "--execute"]
    if not args.execute:
        print(json.dumps({"status": "MEASURED_LAUNCH_PREPARED_ONLY", "argv": argv, "workers_started": 0}))
        return
    current = Path("/proc/self/stat").read_text()
    fields = current[current.rfind(")") + 2:].split()
    archive.require(int(current.split(" ", 1)[0]) == os.getpid()
                    and int(fields[2]) == os.getpgid(0) and int(fields[3]) == os.getsid(0),
                    "PID namespace and /proc mount differ; actual launch requires the authorized host executor")
    with (OPS / ".execution04-launcher.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        directory = OPS / "wait4_launcher"
        directory.mkdir(exist_ok=False)
        archive.write_json(directory / "INTENT.json", {"config": config_desc, "argv": argv,
                           "cwd": config["empty_cwd"], "start_new_session": True,
                           "caller_must_detach_this_measuring_parent_if_needed": True})
        started, cpu = time.monotonic(), time.process_time()
        with (directory / "supervisor.stdout.log").open("xb") as out, (directory / "supervisor.stderr.log").open("xb") as err:
            child = subprocess.Popen(argv, cwd=config["empty_cwd"], stdout=out, stderr=err,
                    env={**os.environ, "PYTHONPATH": config["source_root"], "PYTHONDONTWRITEBYTECODE": "1"},
                    start_new_session=True)
        # A START publication error must not orphan the just-created child.
        try:
            observed = identity(child.pid)
            archive.write_json(directory / "START.json", {"config": config_desc, "argv": argv,
                               "child_identity": observed, "parent_identity": identity(os.getpid()),
                               "started_unix": time.time()})
        except BaseException:
            # The unreaped direct child cannot have a recycled PID. Its own
            # supervisor signal handler stops any already-started owned group.
            try:
                child.terminate()
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            raise
        pid, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        result = {"schema": "hepta.fullstudy.execution04-outer-wait4.1", "config": config_desc,
                  "argv": argv, "child_identity": observed, "waited_pid": pid,
                  "exit_code": child.returncode, "wait_status": status,
                  "wall_seconds": time.monotonic() - started,
                  "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
                  "total_cpu_seconds_inclusive": usage.ru_utime + usage.ru_stime,
                  "peak_rss_bytes": usage.ru_maxrss * 1024,
                  "launcher_cpu_seconds_separate": time.process_time() - cpu,
                  "measurement_scope": "full supervisor entry-to-exit plus descendants it waited for; excludes external root upload/readback processes",
                  "do_not_add_nested_science_driver_archive_or_supervisor_ledgers": True,
                  "unwaited_orphan_costs_unknown_if_failure": child.returncode != 0,
                  "pending_root_durable_closure": True}
        if child.returncode == 0:
            complete = archive.read(OPS / "COMPLETE.json")
            archive.require(complete.get("schema") == "hepta.fullstudy.pipeline-completion.4"
                            and complete.get("complete") is True, "Zero exit lacks primary completion")
            result["primary_complete"] = archive.descriptor(OPS / "COMPLETE.json")
        archive.write_json(directory / "WAIT4_COMPLETE.json", result)
        print(json.dumps(result), flush=True)
        raise SystemExit(child.returncode if child.returncode >= 0 else 128 - child.returncode)


if __name__ == "__main__":
    main()
