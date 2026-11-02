#!/usr/bin/env python3
"""Run the unchanged registered command plans with an owned process-group guard.

This is operational scheduling only. Child launchers retain CPU authority;
wrapper/worker/actor elapsed times can include pauses and are not additive or
isolated latency benchmarks. Visible free-space checks cannot detect all quota
or filesystem-layer failures. No scientific modules are imported here.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

if __package__:
    from . import continue_registered_run as primary
    from . import continue_addendum_v3 as addendum
else:
    import continue_registered_run as primary
    import continue_addendum_v3 as addendum


SOURCE = Path(__file__).resolve()
REPO = SOURCE.parents[3]
GIB = 1024 ** 3
RECORDS = {"primary": "operational_continuation_guarded_01",
           "addendum": "operational_addendum_guarded_01"}
WALL_NOTE = ("Operational elapsed wall includes waiting and group pauses. Child launcher, worker and actor raw wall may also include these pauses; "
             "none is an isolated latency benchmark. Do not subtract or add wrapper wall to worker totals. Child wait4 receipts retain CPU authority.")
TARGETS = {
    "training_index": ("TRAINING_INDEX.json",),
    "recovery_prepare": ("recovery",),
    "recovery_fit": ("receipts/recovery_fit", "recovery/fits"),
    "recovery_freeze": ("recovery/POLICY_FREEZE.json",),
    "main_evaluate": ("receipts/evaluate", "evaluation"),
    "main_index": ("EVALUATION_INDEX.json", "ABLATION_INDEX.json", "COST_INDEX.json"),
    "online_confirm": ("receipts/full_online_confirmation", "full_online_confirmation/groups"),
    "online_index": ("FULL_ONLINE_CONFIRMATION_INDEX.json", "FULL_ONLINE_CONFIRMATION_SUMMARY.json"),
    "recovery_confirm": ("receipts/recovery_confirm", "recovery/confirmation"),
    "recovery_aggregate": ("recovery/CONFIRMATION_INDEX.json", "recovery/ACTUAL_EXECUTION_INDEX.json"),
    "independent_audit": ("INDEPENDENT_AUDIT.json",),
    "frozen_summary": ("SUMMARY.json",),
    "cross_launch": ("receipts/train_execution_cross", "train_execution_cross/groups"),
    "cross_index": ("TRAIN_EXECUTION_CROSS_INDEX.json", "TRAIN_EXECUTION_CROSS_SUMMARY.json"),
    "runtime_ledger": ("RUNTIME_LEDGER_V3.json",),
    "report": ("report",),
    "figures": ("report/figures",),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def atomic_json(path, value):
    """Publish once, atomically and without replacing any existing evidence."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix="pending_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Events:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=False)
        self.sequence = 0

    def __call__(self, event, **fields):
        row = {"utc": utc(), "event": event, **fields}
        print(json.dumps(row, sort_keys=True, allow_nan=False), flush=True)
        self.sequence += 1
        atomic_json(self.directory / f"{self.sequence:06d}_{event}.json", row)
        return row


def plan(phase, output, source_commit):
    return primary.commands(output) if phase == "primary" else addendum.commands(output, source_commit)


def check_identity(output):
    primary.check_freeze(output)
    parent_sha = digest(output / "SOURCE_FREEZE.json")
    for name, source in (("full_online_confirmation", "online_confirm.py"),
                         ("train_execution_cross", "train_execution_cross.py")):
        registration_path = output / name / "SELF_REGISTRATION.json"
        row = read(registration_path)
        require(row["parent_source_freeze_sha256"] == parent_sha, "Supplement parent freeze changed")
        require(digest(SOURCE.parent.parent / source) == row["source_sha256"], "Supplement source changed")
        require(digest(registration_path.parent / row["source_snapshot"]) == row["source_sha256"], "Supplement snapshot changed")


def no_existing_targets(output, commands):
    found = [str(output / name) for stage, _ in commands for name in TARGETS[stage]
             if (output / name).exists()]
    require(not found, "Refusing to rerun or overwrite stage outputs: " + ", ".join(found))


def validate_training(output):
    protocol = read(output / "PROTOCOL.json")
    expected = {(task, seed, mode): f"{task}_s{seed}_{mode}"
                for task, seed, mode in itertools.product(protocol["tasks"], protocol["seeds"], protocol["modes"])}
    require(len(expected) == 32, "Expected the registered 32 training groups")
    total = read(output / "receipts/train/TOTAL.json")
    require(total["stage"] == "train" and total["jobs"] == 32 and total["failed"] == 0,
            "Training TOTAL does not contain 32 successful workers")
    names = set(expected.values())
    require({p.parent.name for p in output.glob("fits/*/SUMMARY.json")} == names, "Incomplete or unexpected completed fit matrix")
    require({p.stem for p in (output / "receipts/train").glob("*.json") if p.name != "TOTAL.json"} == names,
            "Incomplete or unexpected canonical train receipts")
    cpu = []
    for identity, name in expected.items():
        receipt = read(output / "receipts/train" / (name + ".json"))
        summary = read(output / "fits" / name / "SUMMARY.json")
        require(tuple(receipt[k] for k in ("task", "seed", "train_mode")) == identity and receipt["exit_code"] == 0,
                "Failed or misidentified training worker: " + name)
        require(tuple(summary[k] for k in ("task", "seed", "train_mode")) == identity
                and summary["updates"] == protocol["updates"] and summary["development"] is False,
                "Training summary profile differs: " + name)
        for filename, key in (("selected.pt", "checkpoint_sha256"), ("final.pt", "final_checkpoint_sha256")):
            require(digest(output / "fits" / name / filename) == summary[key], "Incomplete training checkpoint: " + name)
        values = [receipt[k] for k in ("cpu_user_seconds", "cpu_system_seconds")]
        require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values), "Invalid training CPU receipt")
        cpu.extend(values)
    require(math.isclose(math.fsum(cpu), total["process_cpu_seconds"], rel_tol=1e-10, abs_tol=1e-6), "Training TOTAL differs from worker receipts")
    return dict(groups=32, all_exit_zero=True, total_sha256=digest(output / "receipts/train/TOTAL.json"))


def group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


class OwnedGroup:
    """Only a fresh session created by this object can receive its signals."""

    def __init__(self, command, out, err, env, cwd, emit):
        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        self.pgid = self.process.pid
        self.emit, self.paused_at, self.pause_seconds = emit, None, 0.
        self.started = time.monotonic()

    def send(self, sig):
        require(self.pgid == self.process.pid and self.pgid != os.getpgrp(), "Refusing to signal a non-owned group")
        try:
            os.killpg(self.pgid, sig)
            return True
        except ProcessLookupError:
            return False

    def update(self, free, low, high):
        if self.paused_at is None and free < low:
            if self.send(signal.SIGSTOP):
                self.paused_at = time.monotonic()
                self.emit("paused", pgid=self.pgid, visible_free_bytes=free)
        elif self.paused_at is not None and free >= high:
            self.send(signal.SIGCONT)
            duration = time.monotonic() - self.paused_at
            self.pause_seconds += duration; self.paused_at = None
            self.emit("resumed", pgid=self.pgid, visible_free_bytes=free, pause_seconds=duration)

    def terminate(self, timeout=10.):
        """Stop the whole owned group even after the original leader exited."""
        self.send(signal.SIGCONT)
        if self.paused_at is not None:
            self.pause_seconds += time.monotonic() - self.paused_at
            self.paused_at = None
        self.send(signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while group_exists(self.pgid) and time.monotonic() < deadline:
            self.process.poll(); time.sleep(.05)
        killed = group_exists(self.pgid)
        if killed:
            self.send(signal.SIGKILL)
        try:
            self.process.wait(timeout=2.)
        except subprocess.TimeoutExpired:
            self.send(signal.SIGKILL); self.process.wait(timeout=2.)
        return dict(pgid=self.pgid, sigkill_sent=killed, leader_exit_code=self.process.returncode,
                    pause_seconds=self.pause_seconds,
                    group_still_present_may_include_unreaped_zombies=group_exists(self.pgid))


def wait_space(free_probe, high, emit, poll):
    waiting = False
    while True:
        free = free_probe()
        if free >= high:
            if waiting:
                emit("start_space_recovered", visible_free_bytes=free)
            return free
        if not waiting:
            emit("waiting_for_start_space", visible_free_bytes=free, required_free_bytes=high)
            waiting = True
        time.sleep(poll)


def execute_stage(directory, name, command, emit, free_probe, low, high, poll=.25, cwd=REPO, cleanup_timeout=10.):
    directory.mkdir(exist_ok=False)
    free = wait_space(free_probe, high, emit, poll)
    intent = dict(stage=name, command=command, utc=utc(), visible_free_bytes=free)
    emit("stage_intent", **intent)
    atomic_json(directory / "INTENT.json", intent)
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    with (directory / "stdout.log").open("x") as out, (directory / "stderr.log").open("x") as err:
        pending, handlers = [], {}
        def defer(signum, frame):
            pending.append(signum)
        # Defer parent interruptions until the new owner is inside its cleanup
        # region. Do not block signal masks: those would survive child exec.
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                handlers[sig] = signal.signal(sig, defer)
            group = OwnedGroup(command, out, err, env, cwd, emit)
        except BaseException:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            raise
        try:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            if pending:
                raise KeyboardInterrupt("Deferred continuation signal " + str(pending))
            started = dict(**intent, pid=group.pgid, pgid=group.pgid, start_new_session=True,
                           started_utc=utc(), wall_scope=WALL_NOTE)
            emit("stage_started", stage=name, pid=group.pgid, command=command)
            atomic_json(directory / "START.json", started)
            while group.process.poll() is None:
                group.update(free_probe(), low, high)
                time.sleep(poll)
            code = group.process.returncode
            if code or group_exists(group.pgid):
                raise RuntimeError(f"Stage {name} exited {code}; surviving owned group={group_exists(group.pgid)}")
            row = dict(**started, finished_utc=utc(), exit_code=code,
                       wall_seconds=time.monotonic()-group.started, pause_seconds=group.pause_seconds,
                       cpu_seconds=None, cpu_accounting="Child receipts authoritative; wrapper timer is not an additional CPU charge")
            emit("stage_complete", **row)
            atomic_json(directory / "COMPLETE.json", row)
            return row
        except BaseException as error:
            shutdown = group.terminate(cleanup_timeout)
            row = dict(stage=name, command=command, utc=utc(), error=repr(error), shutdown=shutdown,
                       wall_seconds=time.monotonic()-group.started, wall_scope=WALL_NOTE, cpu_seconds=None)
            try:
                emit("stage_failed", **row)
                atomic_json(directory / "FAILURE.json", row)
            except (OSError, ValueError):
                pass
            raise


def interrupted(signum, frame):
    raise KeyboardInterrupt("Continuation interrupted by signal " + str(signum))


def run(phase, output, source_commit, low_free_gib=1., high_free_gib=2., poll=.25):
    require(all(math.isfinite(v) for v in (low_free_gib, high_free_gib, poll))
            and 0 < low_free_gib < high_free_gib and poll > 0,
            "Require finite 0 < low < high and positive polling interval")
    commands = plan(phase, output, source_commit)
    check_identity(output)
    no_existing_targets(output, commands)
    record = output / RECORDS[phase]
    record.mkdir(exist_ok=False)
    events = Events(record / "events")
    registration = dict(schema="hcsn.r15.guarded-continuation.v1", utc=utc(), phase=phase, output=str(output),
        source_commit=source_commit, helper_sha256=digest(SOURCE),
        command_provider_sha256={Path(module.__file__).name:digest(module.__file__) for module in (primary, addendum)},
        source_freeze_sha256=digest(output / "SOURCE_FREEZE.json"), commands=commands,
        low_free_bytes=int(low_free_gib*GIB), high_free_bytes=int(high_free_gib*GIB), poll_seconds=poll,
        wall_scope=WALL_NOTE, cpu_seconds=None,
        guard_limit="Visible free space only; no guarantee against independent quotas or filesystem-layer ENOSPC.",
        ownership="Each stage is a fresh session. Registered launchers spawn workers without changing their process group.")
    events("continuation_started", **registration)
    atomic_json(record / "START.json", registration)
    previous = signal.signal(signal.SIGTERM, interrupted)
    start = time.monotonic()
    try:
        prerequisite = (output / "receipts/train/TOTAL.json" if phase == "primary" else
                        output / RECORDS["primary"] / "COMPLETE.json")
        events("waiting_for_prerequisite", path=str(prerequisite))
        while not prerequisite.is_file():
            require(phase != "addendum" or not (prerequisite.parent / "FAILURE.json").exists(), "Guarded primary failed")
            time.sleep(1.)
        check_identity(output)
        qualification = validate_training(output) if phase == "primary" else read(prerequisite)
        require(qualification.get("all_exit_zero") is True, "Prerequisite did not complete successfully")
        events("prerequisite_verified", path=str(prerequisite), sha256=digest(prerequisite))
        atomic_json(record / "PREREQUISITE.json", qualification)
        rows = []
        (record / "stages").mkdir()
        free_probe = lambda: shutil.disk_usage(output).free
        for index, (name, command) in enumerate(commands, 1):
            check_identity(output)
            no_existing_targets(output, [(name, command)])
            rows.append(execute_stage(record / "stages" / f"{index:02d}_{name}", name, command, events,
                                      free_probe, int(low_free_gib*GIB), int(high_free_gib*GIB), poll))
        atomic_json(record / "STAGES.json", rows)
        complete = dict(utc=utc(), phase=phase, stages=len(rows), all_exit_zero=True,
                        elapsed_span_seconds=time.monotonic()-start,
                        stage_pause_seconds=sum(row["pause_seconds"] for row in rows),
                        wall_scope=WALL_NOTE, cpu_seconds=None,
                        note="Successful execution is not a claim of scientific benefit or full cost coverage.")
        events("continuation_complete", **complete)
        atomic_json(record / "COMPLETE.json", complete)
    except BaseException as error:
        failure = dict(utc=utc(), phase=phase, error=repr(error), all_exit_zero=False, wall_scope=WALL_NOTE)
        try:
            events("continuation_failed", **failure)
            atomic_json(record / "FAILURE.json", failure)
        except (OSError, ValueError):
            pass
        raise
    finally:
        signal.signal(signal.SIGTERM, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("primary", "addendum"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--low-free-gib", type=float, default=1.)
    parser.add_argument("--high-free-gib", type=float, default=2.)
    parser.add_argument("--poll-seconds", type=float, default=.25)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if (args.phase == "addendum" and args.source_commit is None) or (args.source_commit is not None and re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is None):
        parser.error("addendum requires --source-commit with a 40-character published Git SHA")
    output = args.output.resolve()
    if args.plan:
        print(json.dumps(plan(args.phase, output, args.source_commit), indent=2))
    else:
        run(args.phase, output, args.source_commit, args.low_free_gib, args.high_free_gib, args.poll_seconds)


if __name__ == "__main__":
    main()
