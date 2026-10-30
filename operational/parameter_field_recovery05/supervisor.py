"""Execution05: explicit A17 inheritance, serial admission and durable ACKs.

CONTEXT_RECONSTRUCTION. This new operational adapter preserves the execution04
scientific loop and archive protocol. Import validation invokes frozen metadata
helpers only; this supervisor never performs science itself or uploads.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


BASE = Path("/workspace/scratch/178ced6a501f")
SOURCE = BASE / "fullstudy_recovery05_git"
OPS = BASE / "fullstudy_execution05_ops"
RAW = BASE / "fullstudy_execution05_durable_raw"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery04 import durable_archive as archive
from operational.parameter_field_recovery05.owned_children import proc_identity

EPISODE = "execution05_backpressure_20261030"
RECONSTRUCTION = "CONTEXT_RECONSTRUCTION"
PREFIX = "experiments.parameter_field_fullstudy_20261029."
ORDER = ["A-17", "A-29", "A-43", "C", "B-17", "B-29", "B-43", "W",
         "R-17", "R-29", "R-43", "A_endpoint", "B_endpoint", "C_endpoint"]
RAM_GATE, DISK_GATE = 1879048192, 2415919104
MiB, GiB = 1024 ** 2, 1024 ** 3
require, read, desc, write = archive.require, archive.read, archive.descriptor, archive.write_json


def process_identity(pid):
    text = Path(f"/proc/{pid}/stat").read_text()
    parts = text[text.rfind(")") + 2:].split()
    return {"pid": pid, "start_ticks": parts[19], "process_group": int(parts[2]),
            "session": int(parts[3]), "state": parts[0]}


def require_matching_proc_namespace():
    text = Path("/proc/self/stat").read_text()
    fields = text[text.rfind(")") + 2:].split()
    require(int(text.split(" ", 1)[0]) == os.getpid()
            and int(fields[2]) == os.getpgid(0) and int(fields[3]) == os.getsid(0),
            "PID namespace and /proc mount differ; use the authorized host executor, not this default sandbox")


def capacity(path):
    root = Path("/sys/fs/cgroup")
    values = {}
    for name in ("memory.stat", "memory.events"):
        values.update({k: int(v) for k, v in (line.split() for line in (root / name).read_text().splitlines())})
    current, limit = int((root / "memory.current").read_text()), (root / "memory.max").read_text().strip()
    require(limit != "max", "A finite cgroup memory limit is required")
    clean = max(0, values.get("inactive_file", 0) - values.get("file_dirty", 0) - values.get("file_writeback", 0))
    space = os.statvfs(path)
    return {"unix": time.time(), "memory_current": current, "memory_limit": int(limit),
            "clean_inactive_file": clean, "effective_available": int(limit) - max(0, current - clean),
            "oom": values.get("oom", 0), "oom_kill": values.get("oom_kill", 0),
            "disk_available": space.f_bavail * space.f_frsize, "available_inodes": space.f_favail}


def args_map(argv):
    result, index = {}, 3
    while index < len(argv):
        flag = argv[index]
        require(flag.startswith("--") and flag not in result, "Invalid or duplicate worker flag")
        if flag == "--execute":
            result[flag], index = True, index + 1
        else:
            result[flag], index = argv[index + 1], index + 2
    return result


def canonical_queue(value, expected_count):
    require(value.get("schema") == "hepta.fullstudy.queue.2" and value.get("attempt_id") == "attempt02",
            "Canonical queue schema/legacy attempt differs")
    jobs = value.get("jobs", [])
    require([job["id"] for job in jobs] == ORDER[:expected_count], "Canonical job order differs")
    for index, job in enumerate(jobs):
        deps = job.get("requires", [])
        require(set(deps) <= set(ORDER[:index]) and (index == 0 or ORDER[index - 1] in deps),
                "Canonical queue does not retain a serial predecessor")
    return value


def activated_prefix(canonical, count, previous=None, finalize=False):
    require(1 <= count <= len(canonical["jobs"]), "Invalid activation prefix")
    require(not finalize or count == 14, "Only the complete grid can finalize")
    value = {**canonical, "jobs": canonical["jobs"][:count], "finalize": finalize}
    if previous is not None:
        require(value["jobs"][:len(previous["jobs"])] == previous["jobs"],
                "Previously accepted job definition changed")
        require(count in (len(previous["jobs"]), len(previous["jobs"]) + 1),
                "Activation must append at most one job")
    return value


def require_durable_predecessor(count, done, acks, finalize=False):
    completed = 14 if finalize else count - 1
    require(done == ORDER[:completed], "Next activation requires the exact completed prefix")
    if completed:
        require(bool(acks) and acks[-1].get("binding", {}).get("label") == ORDER[completed - 1]
                and acks[-1]["binding"].get("completed_jobs") == done,
                "Next activation requires the immediately preceding job's verified durable ACK")


def load_config(path, expected):
    config_desc = desc(path)
    require(config_desc["sha256"] == expected, "Pipeline config SHA differs")
    config = read(path)
    require(config.get("schema") == "hepta.fullstudy.execution05.configuration.1", "Wrong config schema")
    require(config.get("execution_episode") == "execution05_backpressure_20261030", "Wrong execution episode")
    for key, fixed in (("source_root", SOURCE), ("ops_root", OPS), ("raw_root", RAW),
                       ("cas_root", RAW.with_name(RAW.name + "_cas"))):
        require(Path(config[key]).is_absolute() and Path(config[key]).resolve() == fixed,
                "Execution05 fixed path differs: " + key)
    require(re.fullmatch(r"[0-9a-f]{40}", config["source_commit"]) is not None, "Invalid registration commit")
    require(config.get("job_order") == ORDER, "Fixed job order differs")
    python = Path(config["python"])
    require(str(python) == str(BASE / "runtime_recovery_20261030/venv/bin/python")
            and python.is_file() and (python.parent.parent / "pyvenv.cfg").is_file(), "Wrong recovered venv")
    require(sys.version_info[:3] == (3, 12, 14), "Supervisor requires the verified Python 3.12.14")
    empty = Path(config["empty_cwd"])
    require(empty.is_absolute() and empty.is_dir() and not any(empty.iterdir()), "Worker cwd must be empty")
    queue = Path(config["active_queue"])
    require(queue.is_absolute() and queue.resolve().is_relative_to(OPS)
            and not queue.is_relative_to(RAW), "Active queue must be an OPS artifact")
    pins = config["descriptors"]
    required = {"amendment", "initial_queue", "controller_freeze", "cwd_runner", "cwd_policy",
                "registration_driver", "registration_config", "runtime_receipt", "own_supervisor", "durable_archive",
                "wait4_launcher", "producer_config", "import_receipt", "producer_map"}
    require(required <= set(pins), "Missing required input descriptor")
    for value in list(pins.values()) + config.get("initial_metadata", []):
        archive.verify_descriptor(value)
    require(pins["own_supervisor"]["path"] == str(Path(__file__).resolve())
            and pins["durable_archive"]["path"] == str(Path(archive.__file__).resolve()), "Adapter pin differs")
    amendment = read(pins["amendment"]["path"])
    require(amendment.get("attempt_id") == "attempt02" and amendment.get("status") == "REGISTERED_PRE_ENDPOINT"
            and amendment.get("execution_ready") is True and Path(amendment["raw_root"]).resolve() == RAW,
            "Operational amendment is not ready for the new raw root")
    contract, concurrency = amendment["proposed_resource_contract"], amendment["concurrency"]
    require((contract["global_raw_logical_bytes"], contract["minimum_private_allocatable_bytes"],
             contract["C_training_evidence_bytes"], concurrency["max_workers"],
             concurrency["memory_margin_bytes"], concurrency["worker_reservation_bytes"])
            == (2 * GiB, 256 * MiB, 350 * MiB, 2, GiB, 768 * MiB), "Original resource gates changed")
    initial = canonical_queue(read(pins["initial_queue"]["path"]), 4)
    require(initial.get("finalize") is False, "Initial canonical queue must not finalize")
    producer = read(pins["producer_config"]["path"])
    require(producer.get("schema") == "hepta.execution05.producer-config.1"
            and producer.get("execution_episode") == EPISODE
            and producer.get("producer_map") == pins["producer_map"]
            and producer.get("import_receipt") == pins["import_receipt"], "Producer configuration bindings differ")
    fresh = producer["fresh_registration"]
    require(fresh.get("execution_episode") == EPISODE and fresh.get("raw_root") == str(RAW)
            and fresh.get("source_root") == str(SOURCE) and fresh.get("registered_commit") == config["source_commit"]
            and fresh.get("profile") == pins["amendment"], "Fresh producer registration differs")
    imported = load_imported_core(pins["import_receipt"])
    require(initial["jobs"][0] == imported.imported_job, "Initial A17 differs from its sole verified import")
    for name in ("own_supervisor", "durable_archive", "cwd_runner", "registration_driver", "wait4_launcher"):
        target = Path(pins[name]["path"]).resolve()
        require(target.is_relative_to(SOURCE), "Operational source must be in the registered Git tree")
        blob = subprocess.run(["git", "show", config["source_commit"] + ":" + target.relative_to(SOURCE).as_posix()],
                              cwd=SOURCE, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        require(hashlib.sha256(blob).hexdigest() == pins[name]["sha256"], "Committed adapter source differs")
    for name in ("controller.py", "owned_children.py", "producer_adapter.py", "ancestry.py", "resource_backpressure.py"):
        target = Path(__file__).resolve().with_name(name)
        blob = subprocess.run(["git", "show", config["source_commit"] + ":" + target.relative_to(SOURCE).as_posix()],
                              cwd=SOURCE, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        require(hashlib.sha256(blob).hexdigest() == archive.sha256(target), "Committed recovery helper differs: " + name)
    return config, config_desc, initial


def load_imported_core(descriptor):
    from operational.parameter_field_recovery05.controller import ControllerCore
    return ControllerCore(descriptor)


class OwnedChild:
    """One new session, exact wait4 accounting, and bounded identity-safe stop."""

    def __init__(self, directory, name, argv, cwd, env):
        require_matching_proc_namespace()
        self.directory, self.name = Path(directory), name
        self.started, self.result = time.monotonic(), None
        self.argv = argv
        write(self.directory / (name + ".INTENT.json"), {"argv": argv, "cwd": str(cwd), "start_new_session": True})
        self.output = self.directory / (name + ".stdout.log")
        self.error = self.directory / (name + ".stderr.log")
        self.process, self.identity = None, None
        try:
            with self.output.open("xb") as out, self.error.open("xb") as err:
                self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
            self.identity = process_identity(self.process.pid)
            require(self.identity["process_group"] == self.process.pid == self.identity["session"], "New child session differs")
            write(self.directory / (name + ".START.json"), {"argv": argv, "cwd": str(cwd),
                  "identity": self.identity, "started_unix": time.time()})
        except BaseException as error:
            cleanup = self.failed_construction_cleanup()
            record = {"error_type": type(error).__name__, "message": str(error), "argv": argv,
                      "identity": self.identity, "cleanup": cleanup, "automatic_retry": False}
            try:
                write(self.directory / (name + ".SPAWN_FAILED.json"), record)
            except (OSError, ValueError):
                print(json.dumps({"spawn_failed": record}), file=sys.stderr, flush=True)
            raise

    def failed_construction_cleanup(self):
        if self.process is None:
            return {"popen_returned": False}
        # This exact Popen child has never been reaped, so its PID cannot have
        # been recycled even when proc metadata/START publication failed.
        pid, observed, errors = self.process.pid, None, []
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if observed is not None:
                break
            try:
                if os.getpgid(pid) == pid == os.getsid(pid):
                    os.killpg(pid, sig)
                else:
                    os.kill(pid, sig)
            except ProcessLookupError:
                pass
            except OSError as error:
                errors.append(str(error))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                child, status, usage = os.wait4(pid, os.WNOHANG)
                if child:
                    self.process.returncode = os.waitstatus_to_exitcode(status)
                    observed = {"exit_code": self.process.returncode, "wait_status": status,
                                "cpu_seconds_inclusive": usage.ru_utime + usage.ru_stime,
                                "peak_rss_bytes": usage.ru_maxrss * 1024}
                    self.result = {**observed, "total_cpu_seconds": observed["cpu_seconds_inclusive"]}
                    self.exit_ticks = int(time.clock_gettime(time.CLOCK_BOOTTIME) * os.sysconf("SC_CLK_TCK")) + 1
                    break
                time.sleep(.05)
        if self.identity is not None and self.result is not None:
            try:
                if self.group_members():
                    os.killpg(pid, signal.SIGKILL)
            except (OSError, ValueError) as error:
                errors.append(str(error))
        return {"popen_returned": True, "pid": pid, "wait4": observed, "cleanup_errors": errors,
                "unwaited_descendant_costs_unknown": True}

    def poll(self):
        if self.result is None:
            pid, status, usage = os.wait4(self.process.pid, os.WNOHANG)
            if pid:
                code = os.waitstatus_to_exitcode(status)
                self.process.returncode = code  # Popen must not reap a second time.
                self.result = {"exit_code": code, "wait_status": status, "identity": self.identity,
                               "wall_seconds": time.monotonic() - self.started,
                               "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
                               "total_cpu_seconds": usage.ru_utime + usage.ru_stime,
                               "peak_rss_bytes": usage.ru_maxrss * 1024,
                               "scope": "this child and descendants it waited for; includes nested phase/driver costs",
                               "unwaited_orphan_costs_unknown_if_failure": code != 0}
                self.exit_ticks = int(time.clock_gettime(time.CLOCK_BOOTTIME) * os.sysconf("SC_CLK_TCK")) + 1
                write(self.directory / (self.name + ".EXIT.json"), self.result)
        return None if self.result is None else self.result["exit_code"]

    def group_members(self):
        rows = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                row = process_identity(int(entry.name))
            except (OSError, ValueError, IndexError):
                continue
            if row["process_group"] == self.process.pid:
                require(row["session"] == self.identity["session"]
                        and int(row["start_ticks"]) >= int(self.identity["start_ticks"]), "Owned process-group identity differs")
                if row["pid"] == self.process.pid:
                    require(row["start_ticks"] == self.identity["start_ticks"], "Child PID was reused")
                if self.result is not None:
                    require(int(row["start_ticks"]) <= self.exit_ticks, "Cannot establish ownership after leader exit")
                rows.append(row)
        return rows

    def stop(self):
        """Never signal a finished successful child or a reused PID/group."""
        if self.result is not None and self.result["exit_code"] == 0:
            return {"already_exited_successfully": True, "signals_sent": 0}
        rows = self.group_members()
        if rows:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 5
            while self.poll() is None and time.monotonic() < deadline:
                time.sleep(.1)
            if self.group_members():
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.result is None:
            deadline = time.monotonic() + 5
            while self.poll() is None and time.monotonic() < deadline:
                time.sleep(.1)
        return {"members_observed": rows, "child_reaped": self.result is not None,
                "unwaited_descendant_costs_remain_unknown": True}


class Supervisor:
    def __init__(self, config, config_desc, initial):
        self.config, self.config_desc, self.canonical = config, config_desc, initial
        self.pins, self.started, self.started_cpu = config["descriptors"], time.monotonic(), time.process_time()
        self.deadline = self.started + 12 * 3600
        self.run_dir, self.queue_path = OPS / "supervisor_run", Path(config["active_queue"])
        self.children, self.done, self.acks, self.coverage, self.registrations = [], [], [], {}, {}
        self.controller, self.phase, self.last_status, self.last_health = None, "initial_capacity_admission", 0., 0.
        self.last_capacity, self.baseline = None, capacity(OPS)
        self.active, self.pending_request = None, None
        self.import_core, self.start_policy = None, None

    def prepare_imported_layout(self):
        """Only the exact materialized A17 import may precede this fresh run."""
        require(RAW.is_dir() and not RAW.is_symlink(), "Materialized A17 RAW is missing or linked")
        self.import_core = load_imported_core(self.pins["import_receipt"])
        receipt = read(self.pins["import_receipt"]["path"])
        require(Path(receipt["fresh_raw"]).resolve() == RAW
                and self.canonical["jobs"][0] == self.import_core.imported_job, "A17 import target/job differs")
        expected = {row["relative"] for row in receipt["materialize"]}
        expected |= {"imports/execution04/A-17/IMPORT_STARTED.json", "imports/execution04/A-17/IMPORT_RECEIPT.json"}
        actual = {path.relative_to(RAW).as_posix() for path in archive.regular_tree(RAW)}
        require(actual == expected, "Initial RAW differs from exact materialized A17 files")
        allowed_dirs = {"."}
        for relative in expected:
            allowed_dirs.update(parent.as_posix() for parent in Path(relative).parents)
        for base, directories, unused in os.walk(RAW, followlinks=False):
            for name in directories:
                require((Path(base) / name).relative_to(RAW).as_posix() in allowed_dirs,
                        "Unregistered initial RAW directory")
        started = read(RAW / "imports/execution04/A-17/IMPORT_STARTED.json")
        require(started.get("source_episode") == "execution04_durable_20261030"
                and started.get("target_episode") == EPISODE and started.get("pins") == receipt["pins"]
                and started.get("method") == receipt["method"] and started.get("scientific_workers_started") == 0,
                "Original materialization start receipt differs")
        cas = RAW.with_name(RAW.name + "_cas")
        require(not cas.is_symlink(), "New CAS cannot be linked")
        cas.mkdir(exist_ok=True)
        require(not any(cas.iterdir()), "New episode CAS must start empty")

    def write_start_policy(self):
        identity = proc_identity(os.getpid())
        require(all(type(value) is int for value in identity.values()), "Supervisor identity must use integer fields")
        value = {"schema": "hepta.execution05.supervisor-start-policy.1", "execution_episode": EPISODE,
                 "source_root": str(SOURCE), "raw_root": str(RAW), "ops_root": str(OPS),
                 "cwd_policy": self.pins["cwd_policy"], "supervisor_identity": identity,
                 "started_monotonic": self.started, "deadline_monotonic": self.deadline,
                 "oom_baseline": {key: self.baseline[key] for key in ("oom", "oom_kill")}}
        self.start_policy = write(self.run_dir / "START_POLICY.json", value)
        return self.start_policy

    def require_imported_result(self, job, result):
        require(self.import_core is not None, "A17 import was not validated at initial admission")
        archive.verify_descriptor(self.pins["import_receipt"])
        require(job == self.import_core.imported_job and result == self.import_core.imported_result,
                "A17 imported job/result differs from verified origin")
        require(read(RAW / "controller/A-17.IMPORT.json") == self.import_core.import_record,
                "A17 import record differs from verified origin")
        require(not (RAW / "controller/A-17.START.json").exists()
                and not (RAW / "controller/A-17.log").exists()
                and not (RAW / "operations/A-seed-17.START.json").exists(),
                "Imported A17 must have no fabricated new START, PID or log")

    def closed_wrapper_paths(self):
        """The finalizer has exited before all new operational journals close."""
        expected = {"CONTROLLER", "ANALYSIS_PARENT", "ANALYSIS", "FINALIZER-verification05", *ORDER[1:]}
        wrappers = OPS / "wrapper_runs"
        require(wrappers.is_dir() and {path.name for path in wrappers.iterdir()} == expected,
                "Final wrapper population differs")
        paths = {}
        for token in sorted(expected):
            runs = list((wrappers / token).iterdir())
            require(len(runs) == 1 and runs[0].is_dir() and not runs[0].is_symlink(), "Wrapper must have one actual process identity")
            run = runs[0]
            require((run / "START.json").is_file() and (run / "COMPLETE.json").is_file()
                    and not (run / "FAILED.json").exists(), "Operational wrapper is not closed")
            if token in ("CONTROLLER", "ANALYSIS_PARENT"):
                ownership = read(run / "owned_children/CLOSURE.json")
                require(ownership.get("all_returned_direct_children_reaped") is True
                        and ownership.get("accounting_complete_for_attempted_direct_workers") is True,
                        "Owned worker accounting did not close")
        for directory in (wrappers, OPS / "resource_backpressure"):
            require(directory.is_dir(), "Missing operational resource journal tree")
            for path in archive.regular_tree(directory):
                paths["ops/" + path.relative_to(OPS).as_posix()] = path
        return paths

    def status(self, **extra):
        write(OPS / "STATUS.json", {"schema": "hepta.fullstudy.execution05-status.1",
              "execution_episode": self.config["execution_episode"], "phase": self.phase,
              "pid": os.getpid(), "identity": process_identity(os.getpid()),
              "elapsed_seconds": time.monotonic() - self.started, "completed_jobs": self.done,
              "durable_acks": len(self.acks), "capacity": self.last_capacity,
              "awaiting_durable": self.pending_request,
              "children": [{"name": row.name, "identity": row.identity, "exited": row.result is not None} for row in self.children],
              **extra}, replace=True)
        self.last_status = time.monotonic()

    def heartbeat(self, controller_may_exit=False, archiving=False):
        require(time.monotonic() < self.deadline, "Execution05 outer 12 hour window exhausted")
        if time.monotonic() - self.last_health >= 1:
            self.last_capacity, self.last_health = capacity(OPS), time.monotonic()
            require(all(self.last_capacity[key] <= self.baseline[key] for key in ("oom", "oom_kill")), "New cgroup OOM event")
            if archiving:
                require(self.last_capacity["effective_available"] >= GiB, "Archive would violate original RAM margin")
                require(self.last_capacity["disk_available"] >= 258 * MiB
                        and self.last_capacity["available_inodes"] >= 2000, "Archive would violate physical reserve/inodes")
        if self.controller is not None:
            code = self.controller.poll()
            require(code is None or controller_may_exit and code == 0, "Controller exited before durable full-grid closure")
        if time.monotonic() - self.last_status >= 10:
            self.status()

    def quiescent(self):
        active = RAW / "ACTIVE_WORKERS.json"
        require(not active.exists() or read(active).get("workers") == [], "Archival requires no scientific worker")

    def gate(self):
        good = 0
        while good < 3:
            self.heartbeat(controller_may_exit=self.controller is not None and self.controller.result is not None)
            sample = capacity(OPS)
            good = good + 1 if sample["effective_available"] >= RAM_GATE and sample["disk_available"] >= DISK_GATE else 0
            with (self.run_dir / "ADMISSION.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"phase": self.phase, "consecutive": good, **sample}) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.last_capacity = sample
            self.status(admission_consecutive=good)
            if good < 3:
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    self.heartbeat(controller_may_exit=self.controller is not None and self.controller.result is not None)
                    time.sleep(.25)

    def child(self, name, argv):
        env = {**os.environ, "PYTHONPATH": str(SOURCE), "PYTHONDONTWRITEBYTECODE": "1"}
        child = OwnedChild(self.run_dir / "children", name, argv, self.config["empty_cwd"], env)
        self.children.append(child)
        return child

    def wait_child(self, child):
        while child.poll() is None:
            self.heartbeat(controller_may_exit=self.controller is not None and self.controller.result is not None)
            time.sleep(.25)
        require(child.result["exit_code"] == 0, child.name + " failed; no scientific or upload retry")

    def cwd_command(self, kind, flags):
        return [self.config["python"], "-B", self.pins["cwd_runner"]["path"], "--kind", kind,
                "--policy", self.pins["cwd_policy"]["path"], "--expected-policy-sha256",
                self.pins["cwd_policy"]["sha256"], "--", *flags]

    def activate(self, count, finalize=False):
        require_durable_predecessor(count, self.done, self.acks, finalize)
        if self.done:
            require(len(self.acks) == len(self.done)
                    and self.acks[-1]["binding"].get("execution_episode") == EPISODE
                    and self.acks[-1]["binding"].get("sequence") == len(self.acks),
                    "Activation requires a new execution05 durable ACK; historical ACK cannot be reused")
        value = activated_prefix(self.canonical, count, self.active, finalize)
        if self.active is None and self.queue_path.exists():
            require(read(self.queue_path) == value, "Existing initial active queue differs")
        else:
            write(self.queue_path, value, replace=self.active is not None)
        self.active = value
        write(self.run_dir / "queues" / f"{count:02d}{'_final' if finalize else ''}.json", value)

    def register(self, stage, count):
        self.quiescent()
        self.phase = "register_" + stage
        config = self.pins["registration_config"]
        archive.verify_descriptor(config)
        child = self.child("register_" + stage, [self.config["python"], "-B", self.pins["registration_driver"]["path"],
                           "--config", config["path"], "--expected-config-sha256", config["sha256"], "--stage", stage])
        self.wait_child(child)
        result = read(child.output)
        require(result.get("schema") == "hepta.fullstudy.durable-registration-result.1"
                and result.get("stage") == stage and result.get("queue_activated") is False
                and result.get("workers_started") == 0, "Registration result differs")
        for key in ("bundle", "canonical_queue", "registration_cost", "driver_receipt", "driver_cost"):
            archive.verify_descriptor(result[key])
        for item in result["files"].values():
            archive.verify_descriptor(item)
        new = canonical_queue(read(result["canonical_queue"]["path"]), count)
        require(new["jobs"][:len(self.canonical["jobs"])] == self.canonical["jobs"], "Registered accepted definition changed")
        self.canonical, self.registrations[stage] = new, result
        return result

    def wait_job(self, job):
        self.phase = "science_" + job["id"]
        result_path = RAW / "controller" / (job["id"] + ".RESULT.json")
        while not result_path.exists():
            self.heartbeat()
            time.sleep(.25)
        self.quiescent()
        result = read(result_path)
        require(result.get("complete") is True and result.get("exit_code") == 0, "Scientific job failed")
        seal_desc = desc(RAW / job["completion"])
        require(result.get("completion") == {**seal_desc, "path": job["completion"]}, "Job completion descriptor differs")
        if job["id"] == "A-17":
            self.require_imported_result(job, result)
        seal = read(seal_desc["path"])
        provenance = seal.get("operations", seal)
        expected_profile = (self.import_core.import_record["original_profile"]["sha256"]
                            if job["id"] == "A-17" else self.pins["amendment"]["sha256"])
        require(seal.get("complete") is True and seal.get("phase") == job["phase"]
                and seal.get("source_freeze_sha256") == job["freeze_sha256"]
                and provenance.get("attempt_id") == "attempt02"
                and provenance.get("operational_amendment_sha256") == expected_profile,
                "Scientific completion binding differs")
        self.done.append(job["id"])

    def metadata(self):
        archive.verify_descriptor(self.config_desc)
        for item in list(self.pins.values()) + self.config.get("initial_metadata", []):
            archive.verify_descriptor(item)
        result = {"metadata/PIPELINE_CONFIG.json": Path(self.config_desc["path"])}
        require(self.start_policy is not None, "Missing shared execution start policy")
        archive.verify_descriptor(self.start_policy)
        result["metadata/START_POLICY.json"] = Path(self.start_policy["path"])
        for name, item in self.pins.items():
            if Path(item["path"]).resolve().is_relative_to(SOURCE):
                continue  # Git-backed bytes are recovered from source_commit; config retains their exact descriptors.
            result["metadata/pins/" + name + "/" + Path(item["path"]).name] = Path(item["path"])
        for index, item in enumerate(self.config.get("initial_metadata", [])):
            if Path(item["path"]).resolve().is_relative_to(SOURCE):
                continue
            result[f"metadata/initial/{index:04d}/" + Path(item["path"]).name] = Path(item["path"])
        for stage, value in self.registrations.items():
            for name, item in value["files"].items():
                result["metadata/registrations/" + stage + "/" + archive.safe_relative(name)] = Path(item["path"])
            for name in ("bundle", "registration_cost", "driver_receipt", "driver_cost"):
                item = value[name]
                result["metadata/registrations/" + stage + "/" + Path(item["path"]).name] = Path(item["path"])
        registered = OPS / "registrations"
        if registered.exists():
            for path in archive.regular_tree(registered):
                result["metadata/registrations/" + path.relative_to(registered).as_posix()] = path
        launches = OPS / "cwd_launches"
        if launches.exists():
            for directory in sorted(launches.iterdir()):
                completed_analysis = directory.name == "ANALYSIS" and any(
                    row.name == "analysis" and row.result is not None and row.result["exit_code"] == 0
                    for row in self.children)
                require(directory.name in self.done or completed_analysis, "Cwd launch metadata is not closed")
                require((directory / "REQUEST.json").is_file() and (directory / "STARTED.json").is_file()
                        and not (directory / "SPAWN_FAILED.json").exists(), "Cwd launch is incomplete")
                for path in archive.regular_tree(directory):
                    result["metadata/cwd_launches/" + path.relative_to(launches).as_posix()] = path
        return result

    def closed_job_paths(self, job):
        name, phase, seed = job["id"], job["phase"], job.get("seed")
        if name.endswith("_endpoint"):
            directory = RAW / f"stage_{phase}" / ("endpoint_evaluation" if phase == "C" else "endpoints")
        else:
            directory = RAW / f"stage_{phase}"
            if seed is not None:
                directory /= "seed-" + str(seed)
        paths = {"raw/" + path.relative_to(RAW).as_posix(): path for path in archive.regular_tree(directory)}
        if name in ("B_endpoint", "C_endpoint"):
            for filename in ("ENDPOINT_CHECKPOINTS.json",
                             "QUALIFICATION_ACCESS_FREEZE.json" if phase == "B" else "FINAL_ACCESS_FREEZE.json"):
                path = RAW / f"stage_{phase}" / filename
                require(path.is_file(), "Missing completed endpoint access artifact")
                paths["raw/" + path.relative_to(RAW).as_posix()] = path
        if name == "A-17":
            self.require_imported_result(job, read(RAW / "controller/A-17.RESULT.json"))
            for path in archive.regular_tree(RAW / "imports/execution04/A-17"):
                paths["raw/" + path.relative_to(RAW).as_posix()] = path
        for suffix in (("IMPORT.json", "RESULT.json") if name == "A-17" else ("START.json", "RESULT.json", "log")):
            path = RAW / "controller" / (name + "." + suffix)
            require(path.is_file(), "Missing stable controller job artifact")
            paths["raw/" + path.relative_to(RAW).as_posix()] = path
        if not name.endswith("_endpoint"):
            token = phase + ("-all" if seed is None else "-seed-" + str(seed))
            for suffix in (("COMPLETE.json",) if name == "A-17" else ("START.json", "COMPLETE.json")):
                path = RAW / "operations" / (token + "." + suffix)
                require(path.is_file(), "Missing stable scientific operation receipt")
                paths["raw/" + path.relative_to(RAW).as_posix()] = path
        return paths

    def durable(self, label, paths, controller_closed=False):
        self.quiescent()
        self.phase = "archive_" + label
        sequence = len(self.acks) + 1
        directory = OPS / "durable" / f"{sequence:02d}_{label}"
        binding = {"execution_episode": self.config["execution_episode"], "sequence": sequence, "label": label,
                   "pipeline_config": self.config_desc, "completed_jobs": list(self.done),
                   "previous_ack": self.acks[-1]["ack"] if self.acks else None}
        paths = {**self.metadata(), **paths}
        request = archive.build_archive(directory, paths, binding,
                  lambda: self.heartbeat(controller_may_exit=controller_closed, archiving=True))
        self.phase = "await_durable_ack_" + label
        self.pending_request = {"request": request, "ack_path": str(directory / "ACK.json")}
        self.status(durable_request=request, expected_ack=str(directory / "ACK.json"))
        while not (directory / "ACK.json").exists():
            self.heartbeat(controller_may_exit=controller_closed)
            time.sleep(.5)
        verified = archive.verify_ack(directory / "ACK.json", request,
                   lambda: self.heartbeat(controller_may_exit=controller_closed))
        write(directory / "ACK_VERIFIED.json", verified)
        self.acks.append(verified)
        self.pending_request = None
        manifest = read(read(request["path"])["manifest"]["path"])
        for row in manifest["files"]:
            if row["path"].startswith("raw/"):
                self.coverage[row["path"][4:]] = {"bytes": row["bytes"], "sha256": row["sha256"]}

    def verify_grid(self):
        self.quiescent()
        value = read(RAW / "controller/EXECUTION.json")
        require(value.get("complete") is True and set(value["jobs"]) == set(ORDER), "Original controller did not seal 14 jobs")
        require(value.get("imported_jobs") == ["A-17"] and value.get("scientific_jobs_executed_here") == ORDER[1:]
                and value.get("import_receipt") == self.pins["import_receipt"], "Imported/executed job scope differs")
        for job in self.canonical["jobs"]:
            result = value["jobs"][job["id"]]
            if job["id"] == "A-17":
                self.require_imported_result(job, result)
            expected = desc(RAW / job["completion"])
            require(result.get("complete") is True and result.get("exit_code") == 0
                    and result.get("completion") == {**expected, "path": job["completion"]}, "Final controller job differs")

    def sealed_sources(self, result, name, count):
        item = result["files"][name]
        archive.verify_descriptor(item)
        value = read(item["path"])
        seals = value.get("required_scientific_seals", {})
        require(len(seals) == count, "Original required seal count differs")
        for path, digest in seals.items():
            require(archive.sha256(path) == digest, "Original required seal bytes differ")
        return item, value

    def run_analysis(self):
        result = self.register("analysis", 14)
        frozen, value = self.sealed_sources(result, "ANALYSIS_SOURCE_FREEZE.json", 26)
        inputs = result["files"]["REPORT_INPUTS.json"]
        self.phase = "analysis_capacity_admission"
        self.gate()
        self.phase = "aggregate_analysis"
        amend = self.pins["amendment"]
        output = RAW / value["output_relative"]
        flags = ["--root", str(RAW), "--inputs", inputs["path"], "--expected-sha256", inputs["sha256"],
                 "--output", str(output), "--freeze", frozen["path"], "--freeze-sha256", frozen["sha256"],
                 "--amendment", amend["path"], "--amendment-sha256", amend["sha256"]]
        self.wait_child(self.child("analysis", self.cwd_command("analysis", flags)))
        control = RAW / "analysis_operations" / value["analysis_id"]
        require(read(control / "COMPLETE.json").get("complete") is True, "Analysis lacks completion seal")
        paths = {"raw/" + p.relative_to(RAW).as_posix(): p
                 for directory in (output, control) for p in archive.regular_tree(directory)}
        self.durable("analysis", paths, controller_closed=True)
        return output

    def finalize(self, output):
        result = self.register("finalizer", 14)
        frozen, value = self.sealed_sources(result, "FINALIZER_SOURCE_FREEZE.json", 30)
        self.phase = "finalization_capacity_admission"
        self.gate()
        amend = self.pins["amendment"]
        self.phase = "literal_finalization"
        flags = ["--root", str(RAW), "--amendment", amend["path"], "--amendment-sha256", amend["sha256"],
                 "--freeze", frozen["path"], "--evidence-id", "verification05", "--execute"]
        self.wait_child(self.child("finalizer", self.cwd_command("finalizer", flags)))
        evidence = RAW / "evidence_v2/verification05"
        verified, manifest = read(evidence / "VERIFIED.json"), read(evidence / "MANIFEST.json")
        manifest_desc = desc(evidence / "MANIFEST.json")
        require(verified.get("archive_verification_complete") is True
                and verified.get("manifest") == {**manifest_desc, "path": "evidence_v2/verification05/MANIFEST.json"}
                and verified.get("binding", {}).get("source_freeze_sha256") == frozen["sha256"],
                "Literal verification does not bind the final manifest/freeze")
        require(manifest.get("schema") == "hepta.fullstudy.cas-container-manifest.1"
                and manifest.get("binding") == verified["binding"] and manifest.get("root") == str(RAW)
                and manifest.get("cas_root") == self.config["cas_root"], "Final raw inventory binding differs")
        entries = manifest["logical_paths"]
        require(verified["logical_files_restored"] == manifest["logical_artifact_count"] == len(entries)
                and verified["logical_bytes_restored"] == manifest["logical_artifact_bytes"]
                == sum(row["bytes"] for row in entries.values())
                and set(verified["logical_paths_verified"]) == set(entries)
                and verified.get("temporary_directory_removed_after_success") is True,
                "Literal restored file/byte/path counts do not match")
        paths = {"raw/" + name: RAW / name for name, row in entries.items()
                 if self.coverage.get(name) != {"bytes": row["bytes"], "sha256": row["sha256"]}}
        for path in archive.regular_tree(evidence):
            paths["raw/" + path.relative_to(RAW).as_posix()] = path
        for path in archive.regular_tree(self.run_dir):
            paths["ops/supervisor_run/" + path.relative_to(self.run_dir).as_posix()] = path
        for directory in sorted((OPS / "durable").iterdir()):
            for name in ("REQUEST.json", "ACK.json", "ACK_VERIFIED.json", "MANIFEST.json", "VERIFIED.json", "ARCHIVE_COST.json"):
                path = directory / name
                if path.is_file():
                    paths["ops/durable/" + path.relative_to(OPS / "durable").as_posix()] = path
        paths.update(self.closed_wrapper_paths())
        self.durable("final_closure", paths, controller_closed=True)
        require(all(self.coverage.get(name) == {"bytes": row["bytes"], "sha256": row["sha256"]}
                    for name, row in entries.items()), "Durable archives do not cover every final raw logical artifact")
        return {"verified": desc(evidence / "VERIFIED.json"), "manifest": manifest_desc,
                "aggregate_results": desc(output / "RESULTS.json"), "finalizer_freeze": frozen}, verified

    def execute(self):
        require(not self.run_dir.exists(), "New episode cannot resume or overwrite a prior supervisor run")
        self.prepare_imported_layout()
        for directory in (OPS / "wrapper_runs", OPS / "resource_backpressure", OPS / "cwd_launches", OPS / "durable"):
            require(not directory.exists() or not any(directory.iterdir()), "New operational work directories must start empty")
        self.run_dir.mkdir()
        (self.run_dir / "children").mkdir()
        self.write_start_policy()
        self.status()
        self.gate()
        self.activate(1)
        amend, freeze = self.pins["amendment"], self.pins["controller_freeze"]
        flags = ["--root", str(RAW), "--queue", str(self.queue_path), "--freeze", freeze["path"],
                 "--freeze-sha256", freeze["sha256"], "--amendment", amend["path"],
                 "--amendment-sha256", amend["sha256"]]
        self.controller = self.child("controller", self.cwd_command("controller", flags))
        for index in range(14):
            job = self.canonical["jobs"][index]
            self.wait_job(job)
            self.durable(job["id"], self.closed_job_paths(job))
            if index == 2:
                self.register("followups", 11)
            if index == 10:
                self.register("endpoints", 14)
            if index < 13:
                self.activate(index + 2)
        self.activate(14, finalize=True)
        self.phase = "controller_final_seal"
        while self.controller.poll() is None:
            self.heartbeat(controller_may_exit=True)
            time.sleep(.25)
        require(self.controller.result["exit_code"] == 0, "Controller final exit failed")
        self.verify_grid()
        closed = {"raw/controller/" + p.name: p for p in archive.regular_tree(RAW / "controller")}
        self.durable("controller", closed, controller_closed=True)
        output = self.run_analysis()
        artifacts, verified = self.finalize(output)
        require(len(self.acks) == 17, "Execution05 must retain all seventeen durable barriers")
        self.phase = "COMPLETE"
        child_cpu = sum(row.result["total_cpu_seconds"] for row in self.children)
        complete = {"schema": "hepta.fullstudy.pipeline-completion.4", "complete": True,
                    "execution_episode": self.config["execution_episode"], "pipeline_config": self.config_desc,
                    "artifacts": artifacts, "jobs": list(self.done), "jobs_verified": 14,
                    "imported_jobs": ["A-17"], "jobs_imported": 1, "jobs_executed_here": 13,
                    "scientific_jobs_executed_here": ORDER[1:], "import_receipt": self.pins["import_receipt"],
                    "producer_map": self.pins["producer_map"],
                    "imported_scientific_cost_owner": "execution04_durable_20261030:A-17",
                    "imported_A17_new_scientific_cpu_seconds": 0.0,
                    "required_finalizer_seals_verified": 30,
                    "logical_files_restored": verified["logical_files_restored"],
                    "logical_bytes_restored": verified["logical_bytes_restored"],
                    "durable_stages": self.acks, "durable_raw_logical_files": len(self.coverage),
                    "outer_external_uploads_verified": sum(row["items_verified"] for row in self.acks),
                    "original_raw_external_uploads_zero_is_core_scope_only": True,
                    "costs": {"wall_seconds_since_supervisor_init": time.monotonic() - self.started,
                              "self_cpu_seconds_since_init": time.process_time() - self.started_cpu,
                              "wait4_children_inclusive_cpu_seconds": child_cpu,
                              "cpu_seconds_since_init_inclusive": time.process_time() - self.started_cpu + child_cpu,
                              "archive_and_driver_cpu_already_inclusive_do_not_add_again": True,
                              "scientific_and_historical_ledgers_are_separate_attribution_views": True,
                              "external_upload_and_readback_cpu_not_measured_by_this_process": True,
                              "full_entry_to_exit_wait4_receipt_expected_after_exit": True},
                    "terminal_metadata_not_yet_durable": [str(OPS / "COMPLETE.json"), "outer wait4 completion receipt"],
                    "terminal_metadata_closure_owner": "root, after supervisor exit; no further science"}
        write(OPS / "COMPLETE.json", complete)
        self.status()
        return complete

    def fail(self, error):
        stopped = []
        for child in reversed(self.children):
            try:
                stopped.append({"name": child.name, **child.stop()})
            except BaseException as stop_error:
                stopped.append({"name": child.name, "stop_error": str(stop_error), "unwaited_descendant_costs_unknown": True})
        self.phase = "FAILED"
        construction_receipts, construction_cpu = [], 0.
        if (self.run_dir / "children").is_dir():
            for path in sorted((self.run_dir / "children").glob("*.SPAWN_FAILED.json")):
                record = read(path)
                observed = record.get("cleanup", {}).get("wait4")
                construction_cpu += observed.get("cpu_seconds_inclusive", 0.) if observed else 0.
                construction_receipts.append(desc(path))
        failure = {"schema": "hepta.fullstudy.execution05-failure.1", "complete": False,
                   "execution_episode": self.config["execution_episode"], "pipeline_config": self.config_desc,
                   "error_type": type(error).__name__, "message": str(error), "completed_jobs": self.done,
                   "durable_acks": self.acks, "owned_process_stops": stopped,
                   "all_original_and_partial_evidence_preserved": True, "automatic_scientific_retry": False,
                   "unknown_upload_outcome_must_not_be_retried_automatically": True,
                   "costs": {"self_cpu_seconds_since_init": time.process_time() - self.started_cpu,
                             "wait4_children_inclusive_cpu_seconds": construction_cpu + sum(row.result["total_cpu_seconds"] for row in self.children if row.result),
                             "constructor_cleanup_wait4_receipts_included": construction_receipts,
                             "unwaited_descendant_costs_unknown": True}}
        write(OPS / "FAILED.json", failure)
        self.status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    config, config_desc, initial = load_config(args.config, args.expected_config_sha256)
    if not args.execute:
        print(json.dumps({"status": "CONFIG_AND_COMMITTED_ADAPTER_BYTES_VERIFIED_ONLY", "config": config_desc,
                          "workers_started": 0, "uploads_started": 0}))
        return
    require_matching_proc_namespace()
    OPS.mkdir(exist_ok=True)
    with (OPS / ".execution05-supervisor.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        supervisor = Supervisor(config, config_desc, initial)
        def interrupted(number, frame):
            raise RuntimeError("Supervisor received signal " + str(number))
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            result = supervisor.execute()
        except BaseException as error:
            supervisor.fail(error)
            raise
        print(json.dumps({"complete": True, "completion": desc(OPS / "COMPLETE.json"),
                          "execution_episode": result["execution_episode"]}), flush=True)


if __name__ == "__main__":
    main()
