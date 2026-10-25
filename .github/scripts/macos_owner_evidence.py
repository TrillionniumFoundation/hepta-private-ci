#!/usr/bin/env python3
"""Bounded native macOS qualification of 278 exact owner tests, not full CI."""

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import selectors
import signal
import subprocess
import sys
import time
import threading
import traceback
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PROFILE = "macos-owner"
BASE = "f403a36fad9ec59c74a4429ef62cdb568eafdd21"
PHASES = ("memory", "supervisor-owning", "supervisor-integration")
OWNER = (
    "restart_budget::tests::budget_is_durable_bounded_and_pending_is_idempotent",
    "restart_policy::tests::restart_schedule_is_exponential_and_stops_after_three_attempts",
    "restart_policy::tests::restart_schedule_resets_after_recovery_window",
    "restart_journal::tests::restart_journal_round_trips_and_rejects_clock_rollback_with_full_budget",
)
INTEGRATION = {
    (
        "codex-hepta-supervisor::restart_budget",
        "unexpected_agent_crashes_back_off_and_stop_after_three_restarts",
    ),
    (
        "codex-hepta-supervisor::restart_budget_recovery",
        "restart_budget_survives_repeated_supervisord_recovery",
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def expected(phase):
    if phase == "memory":
        rows = json.loads((HERE / "macos_owner_cases.json").read_text())["memory"]
        require(
            len(rows) == 279 and len({r["name"] for r in rows}) == 279, "bad inventory"
        )
        require(
            Counter(r["prior"] for r in rows)
            == {"ok": 114, "FAILED": 158, "ignored": 7},
            "bad prior counts",
        )
        return {
            ("codex-hepta-memory", r["name"]) for r in rows if r["prior"] != "ignored"
        }
    if phase == "supervisor-owning":
        return {("codex-hepta-supervisor", name) for name in OWNER}
    require(phase == "supervisor-integration", "unknown phase")
    return INTEGRATION


def selection(phase):
    args = ["--locked", "-p"]
    if phase == "memory":
        args += ["codex-hepta-memory", "--lib"]
    elif phase == "supervisor-owning":
        args += ["codex-hepta-supervisor", "--lib"]
    else:
        args += [
            "codex-hepta-supervisor",
            "--test",
            "restart_budget",
            "--test",
            "restart_budget_recovery",
        ]
    return args + [
        "-E",
        " | ".join(f"test(={name})" for _, name in sorted(expected(phase))),
    ]


def validate_list(path, phase):
    data = json.loads(path.read_text())
    selected = []
    for key, suite in data["rust-suites"].items():
        require(suite["binary-id"] == key, "inconsistent binary identity")
        for name, case in suite["testcases"].items():
            if case["filter-match"]["status"] == "matches":
                require(case["ignored"] is False, "selected ignored test")
                require(suite["status"] == "listed", "suite not listed")
                selected.append((key, name))
    require(
        len(selected) == len(expected(phase)) and set(selected) == expected(phase),
        "wrong selected list identities",
    )
    return sorted(selected)


def validate_report(path, phase):
    root = ET.parse(path).getroot()
    require(root.tag == "testsuites" and root.get("name") == PROFILE, "wrong report")
    require(all(node.tag == "testsuite" for node in root), "unexpected report element")
    cases = root.findall("./testsuite/testcase")
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    require(
        len(identities) == len(expected(phase)) and set(identities) == expected(phase),
        "wrong report identities",
    )
    groups = Counter(classname for classname, _ in identities)
    require(
        Counter(s.get("name") for s in root) == Counter({name: 1 for name in groups}),
        "wrong suites",
    )
    for node in [root, *root]:
        count = len(cases) if node is root else groups[node.get("name")]
        require(int(node.get("tests", "-1")) == count, "wrong count")
        for key in ("failures", "errors", "skipped", "disabled"):
            require(
                int(node.get(key, "-1" if key in {"failures", "errors"} else "0")) == 0,
                f"nonzero/missing {key}",
            )
    for suite in root:
        require(len(suite) == groups[suite.get("name")], "unexpected suite children")
        for case in suite:
            require(
                case.tag == "testcase" and case.get("classname") == suite.get("name"),
                "wrong case suite",
            )
            require(bool(case.get("timestamp")), "missing timestamp")
            require(
                all(c.tag in {"system-out", "system-err"} for c in case),
                "failure/skip/retry/unknown result",
            )
    return sorted(identities)


def snapshot_owned_group(pgid, directory, timeout_seconds=2):
    """One bounded read-only Darwin group snapshot, never a cleanup verdict."""
    snapshot = {
        "stage": "first-eperm-after-term-signal-zero",
        "owned_pgid": pgid,
        "observer_pid": os.getpid(),
        "observer_euid": os.geteuid(),
        "kernel": list(os.uname()),
        "classification": "unverified",
    }
    if platform.system() != "Darwin":
        snapshot["unavailable"] = "Darwin-only diagnostic"
        return snapshot
    require(type(pgid) is int and pgid > 1, "invalid owned group")
    command = [
        "/bin/ps",
        "-g",
        str(pgid),
        "-o",
        "pid=,ppid=,pgid=,sess=,uid=,state=,lstart=",
    ]
    require(0 < timeout_seconds <= 2, "invalid snapshot time bound")
    snapshot.update(argv=command, limit_bytes=16384, timeout_seconds=timeout_seconds)
    process = None
    probe_stop_attempted = False
    output = {"stdout": bytearray(), "stderr": bytearray()}
    started = time.monotonic()
    try:
        snapshot["binary_sha256"] = digest("/bin/ps")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        snapshot["probe_pid"] = process.pid
        with selectors.DefaultSelector() as selector:
            for name, stream in (
                ("stdout", process.stdout),
                ("stderr", process.stderr),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = started + timeout_seconds - time.monotonic()
                if remaining <= 0:
                    snapshot["unavailable"] = "snapshot timeout"
                    break
                ready = selector.select(remaining)
                for key, _ in ready:
                    total = sum(len(value) for value in output.values())
                    chunk = os.read(key.fileobj.fileno(), min(4096, 16385 - total))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output[key.data].extend(chunk)
                if sum(len(value) for value in output.values()) > 16384:
                    snapshot["unavailable"] = "snapshot output exceeds bound"
                    break
        if "unavailable" not in snapshot:
            try:
                snapshot["exit"] = process.wait(
                    timeout=max(0, started + timeout_seconds - time.monotonic())
                )
            except subprocess.TimeoutExpired:
                snapshot["unavailable"] = "snapshot timeout"
        if "unavailable" in snapshot:
            if process.poll() is None:
                # Only this newly created read-only ps process, never the denied group.
                probe_stop_attempted = True
                process.kill()
            snapshot["exit"] = process.wait(timeout=1)
        if snapshot["exit"] != 0:
            snapshot.setdefault("unavailable", "snapshot command failed")
    except Exception as error:
        snapshot.update(unavailable=str(error), error_type=type(error).__name__)
    finally:
        if process is not None:
            if process.poll() is None and not probe_stop_attempted:
                probe_stop_attempted = True
                process.kill()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    snapshot["unavailable"] = "snapshot child reap failed"
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        remaining = 16384
        for name, value in output.items():
            kept = bytes(value[:remaining])
            remaining -= len(kept)
            (directory / f"probe-state.{name}.log").write_bytes(kept)
        snapshot["elapsed_seconds"] = time.monotonic() - started
    return snapshot


def capture_owned_snapshot(process, directory, stage):
    directory.mkdir(parents=True)
    snapshot = snapshot_owned_group(process.pid, directory)
    snapshot["stage"] = stage
    write(directory / "result.json", snapshot)
    return snapshot


def snapshot_rows(snapshot, directory, pgid):
    """Validate a complete read-only receipt, not a signal authorization."""
    require("unavailable" not in snapshot, "unavailable group snapshot")
    require(
        type(snapshot.get("exit")) is int and snapshot["exit"] == 0,
        "unsuccessful group snapshot",
    )
    require(snapshot.get("owned_pgid") == pgid, "snapshot group mismatch")
    require(snapshot.get("observer_pid") == os.getpid(), "snapshot observer mismatch")
    require(snapshot.get("observer_euid") == os.geteuid(), "snapshot uid mismatch")
    require(
        re.fullmatch(r"[0-9a-f]{64}", snapshot.get("binary_sha256", "")) is not None,
        "missing ps binary identity",
    )
    require(
        snapshot.get("argv")
        == [
            "/bin/ps",
            "-g",
            str(pgid),
            "-o",
            "pid=,ppid=,pgid=,sess=,uid=,state=,lstart=",
        ],
        "unexpected snapshot command",
    )
    require(
        snapshot.get("limit_bytes") == 16384
        and isinstance(snapshot.get("timeout_seconds"), (int, float))
        and 0 < snapshot["timeout_seconds"] <= 2,
        "unexpected snapshot bounds",
    )
    stdout = (directory / "probe-state.stdout.log").read_bytes()
    stderr = (directory / "probe-state.stderr.log").read_bytes()
    require(not stderr and len(stdout) <= 16384, "partial or noisy group snapshot")
    rows = []
    for line in stdout.decode("ascii").splitlines():
        parts = line.split()
        require(len(parts) == 11, "malformed process row")
        require(all(parts[i].isdigit() for i in (0, 1, 2, 4)), "malformed process id")
        require(
            re.fullmatch(r"[A-Z][A-Za-z+<>-]*", parts[5]) is not None,
            "malformed process state",
        )
        require(
            re.fullmatch(
                r"(?:Sun|Mon|Tue|Wed|Thu|Fri|Sat) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2} \d{2}:\d{2}:\d{2} \d{4}",
                " ".join(parts[6:]),
            )
            is not None,
            "malformed process start",
        )
        rows.append(
            {
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "pgid": int(parts[2]),
                "uid": int(parts[4]),
                "state": parts[5],
                "start": " ".join(parts[6:]),
            }
        )
    require(bool(rows), "empty group snapshot")
    require(
        all(r["pid"] > 1 and r["ppid"] > 0 for r in rows), "invalid process identity"
    )
    require(len({r["pid"] for r in rows}) == len(rows), "duplicate process row")
    require(
        all(r["pgid"] == pgid and r["uid"] == os.geteuid() for r in rows),
        "foreign process group member",
    )
    return rows


def require_unreaped_owner(process):
    require(process.returncode is None, "leader already reaped")
    require(
        signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL, "nondefault child reaper"
    )
    require(threading.active_count() == 1, "concurrent child reaper cannot be excluded")


def bind_owned_leader(process, directory):
    require_unreaped_owner(process)
    snapshot = capture_owned_snapshot(process, directory, "startup-owned-identity")
    rows = snapshot_rows(snapshot, directory, process.pid)
    leaders = [r for r in rows if r["pid"] == process.pid]
    require(len(leaders) == 1, "missing owned leader")
    leader = leaders[0]
    require(leader["ppid"] == os.getpid(), "leader is not our direct child")
    require(process.returncode is None, "leader already reaped at binding")
    session = {
        "sid": process.pid,
        "session_proof": "Popen start_new_session plus exact unreaped child PGID snapshot",
    }
    if leader["state"].startswith("Z"):
        require(observe_leader(process) is not None, "zombie leader not waitable")
        session["session_observation"] = "derived: leader already terminal"
    else:
        try:
            sid, pgid = os.getsid(process.pid), os.getpgid(process.pid)
        except ProcessLookupError:
            require(
                observe_leader(process) is not None, "live session identity unavailable"
            )
            session["session_observation"] = "derived: exited during startup read"
        else:
            require(
                sid == process.pid and pgid == process.pid,
                "spawned leader session mismatch",
            )
            session.update(
                session_observation="observed live",
                observed_sid=sid,
                observed_pgid=pgid,
            )
    return {
        **{k: v for k, v in leader.items() if k != "state"},
        "ps_sha256": snapshot["binary_sha256"],
        **session,
    }


def pre_kill_owned_leader(process, identity, directory, snapshot=None):
    """Reap only a sole pinned direct-child zombie; never reinterpret EPERM."""
    require_unreaped_owner(process)
    require(identity is not None, "unverified startup leader identity")
    if snapshot is None:
        snapshot = capture_owned_snapshot(process, directory, "before-final-kill")
    rows = snapshot_rows(snapshot, directory, process.pid)
    require(snapshot["binary_sha256"] == identity["ps_sha256"], "ps identity changed")
    leader = next((r for r in rows if r["pid"] == process.pid), None)
    require(leader is not None, "owned leader missing before final kill")
    require(
        {k: v for k, v in leader.items() if k != "state"}
        == {k: identity[k] for k in ("pid", "ppid", "pgid", "uid", "start")},
        "owned leader identity changed",
    )
    require(leader["ppid"] == os.getpid(), "leader parent changed")
    # A complete live family tree is required to retain the original cleanup.
    known = {process.pid}
    pending = {r["pid"]: r for r in rows if r["pid"] != process.pid}
    while pending:
        children = {pid for pid, row in pending.items() if row["ppid"] in known}
        require(bool(children), "unverified group member ancestry")
        known.update(children)
        for pid in children:
            del pending[pid]
    require_unreaped_owner(process)
    if len(rows) != 1 or not leader["state"].startswith("Z"):
        return {"reaped": False, "ownership": "pinned-direct-child-family"}
    require_unreaped_owner(process)
    # No Popen.wait cached/ECHILD success: require this exact terminal reap.
    pid, status = os.waitpid(process.pid, os.WNOHANG)
    require(pid == process.pid, "owned zombie was not reaped")
    require(os.WIFEXITED(status) or os.WIFSIGNALED(status), "nonterminal wait status")
    process.returncode = os.waitstatus_to_exitcode(status)
    return {
        "reaped": True,
        "pid": pid,
        "wait_status": status,
        "returncode": process.returncode,
        "ownership": "sole-pinned-unreaped-direct-child-zombie",
    }


def require_waitid_contract():
    for name in (
        "waitid",
        "P_PID",
        "WEXITED",
        "WNOWAIT",
        "WNOHANG",
        "CLD_EXITED",
        "CLD_KILLED",
        "CLD_DUMPED",
    ):
        require(hasattr(os, name), f"required non-reaping wait API missing: {name}")


def observe_leader(process):
    """Observe this owned child's terminal result without releasing its PID."""
    require_waitid_contract()
    require_unreaped_owner(process)
    event = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
    if event is None:
        return None
    require(event.si_pid == process.pid, "waitid returned another process")
    require(event.si_signo == signal.SIGCHLD, "unexpected waitid signal")
    # Darwin need not populate si_uid: ownership comes from the pinned snapshot.
    if event.si_code == os.CLD_EXITED:
        require(0 <= event.si_status <= 255, "invalid observed exit code")
        return event.si_status
    require(event.si_code in (os.CLD_KILLED, os.CLD_DUMPED), "nonterminal waitid event")
    require(0 < event.si_status < signal.NSIG, "invalid observed terminating signal")
    return -event.si_status


def observe_command(process, deadline):
    while True:
        result = observe_leader(process)
        if result is not None:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.05, remaining))


def capture_cleanup_snapshot(process, directory, stage, deadline):
    remaining = deadline - time.monotonic()
    require(remaining > 0, "owned cleanup budget exhausted before snapshot")
    directory.mkdir(parents=True)
    snapshot = snapshot_owned_group(
        process.pid, directory, timeout_seconds=min(2, remaining)
    )
    snapshot["stage"] = stage
    write(directory / "result.json", snapshot)
    return snapshot


def owned_session_state(process, identity, snapshot, directory):
    require_unreaped_owner(process)
    require(identity is not None, "unverified startup leader identity")
    rows = snapshot_rows(snapshot, directory, process.pid)
    require(snapshot["binary_sha256"] == identity["ps_sha256"], "ps identity changed")
    leader = next((row for row in rows if row["pid"] == process.pid), None)
    require(leader is not None, "anchored leader missing")
    keys = ("pid", "ppid", "pgid", "uid", "start")
    require(
        {k: leader[k] for k in keys} == {k: identity[k] for k in keys},
        "anchored leader identity changed",
    )
    require(identity.get("sid") == process.pid, "missing owned session anchor")
    observed = observe_leader(process)
    if len(rows) == 1 and leader["state"].startswith("Z") and observed is not None:
        return {"state": "sole-terminal-leader", "observed_exit": observed}
    # A stale live row and a newer terminal event cannot authorize a signal.
    if observed is not None and not leader["state"].startswith("Z"):
        return {"state": "await-fresh-terminal-snapshot"}
    live = [row for row in rows if not row["state"].startswith("Z")]
    if not live:
        # Non-child zombies are never reaped by this wrapper or counted gone.
        return {"state": "await-nonchild-zombie-reaping"}
    for row in live:
        try:
            sid = os.getsid(row["pid"])
            pgid = os.getpgid(row["pid"])
        except ProcessLookupError:
            # Darwin excludes dead processes from these APIs. ESRCH is not absence.
            return {"state": "await-fresh-member-snapshot"}
        require(
            sid == process.pid and pgid == process.pid,
            "foreign session or reused group",
        )
    require_unreaped_owner(process)
    return {"state": "owned-live-session", "live_pids": [row["pid"] for row in live]}


def cleanup_owned_session(process, identity, record, directory, grace, send_signal):
    require(identity is not None, "unverified startup leader identity")
    started = time.monotonic()
    term_end = started + grace
    cleanup_end = term_end + grace
    sent_term = False
    sent_kill = False
    index = 0
    record["cleanup_observations"] = []
    while True:
        stage = (
            "before-term"
            if not sent_term
            else "after-kill"
            if sent_kill
            else "after-term"
        )
        target = directory / f"cleanup-{index:04d}"
        snapshot = capture_cleanup_snapshot(process, target, stage, cleanup_end)
        require(
            time.monotonic() <= cleanup_end,
            "owned cleanup observation exceeded deadline",
        )
        state = owned_session_state(process, identity, snapshot, target)
        record["cleanup_observations"].append({"stage": stage, **state})
        index += 1
        if state["state"] == "sole-terminal-leader":
            require(
                time.monotonic() <= cleanup_end, "owned cleanup proof exceeded deadline"
            )
            lifecycle = pre_kill_owned_leader(
                process, identity, target, snapshot=snapshot
            )
            require(lifecycle["reaped"], "terminal leader was not reaped")
            require(
                lifecycle["returncode"] == state["observed_exit"],
                "observed and reaped exit disagree",
            )
            record["leader_lifecycle"] = lifecycle
            return
        now = time.monotonic()
        require(now < cleanup_end, "owned group cleanup remains unverified at deadline")
        if state["state"] == "owned-live-session":
            if not sent_term:
                send_signal(signal.SIGTERM, "first-eperm-term")
                sent_term = True
            elif now >= term_end and not sent_kill:
                send_signal(signal.SIGKILL, "first-eperm-kill")
                sent_kill = True
        time.sleep(min(0.05, max(0, cleanup_end - time.monotonic())))


def bounded(command, directory, deadline, cwd, grace=10):
    """One new owned process group, raw output, deadline and bounded cleanup."""
    directory.mkdir(parents=True)
    write(directory / "command.json", command)
    started = time.monotonic()
    record = {
        "argv": command,
        "remaining_seconds": max(0, deadline - started),
        "timed_out": False,
    }
    process = None

    def signal_owned_group(sig, stage):
        try:
            os.killpg(process.pid, sig)
        except PermissionError:
            # First denial terminates cleanup; never send another group signal.
            try:
                record["owned_group_snapshot"] = snapshot_owned_group(
                    process.pid, directory
                )
            except Exception as diagnostic_error:
                record["owned_group_snapshot"] = {
                    "unavailable": str(diagnostic_error),
                    "classification": "unverified",
                }
            record["owned_group_snapshot"]["stage"] = stage
            raise

    try:
        require(deadline > started, "total native budget exhausted before command")
        if platform.system() == "Darwin":
            require_waitid_contract()
        with (
            (directory / "stdout.log").open("wb") as stdout,
            (directory / "stderr.log").open("wb") as stderr,
        ):
            process = subprocess.Popen(
                command, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True
            )
            record["owned_pgid"] = process.pid
            identity = None
            if platform.system() == "Darwin":
                try:
                    identity = bind_owned_leader(
                        process, directory / "startup-identity"
                    )
                    record["leader_identity"] = identity
                except Exception as identity_error:
                    record["leader_identity_error"] = str(identity_error)
            if platform.system() == "Darwin":
                require(identity is not None, "unverified startup leader identity")
                observed = observe_command(process, deadline)
                record["timed_out"] = observed is None
                record["exit"] = 124 if observed is None else observed
                cleanup_owned_session(
                    process, identity, record, directory, grace, signal_owned_group
                )
            else:
                try:
                    record["exit"] = process.wait(
                        timeout=max(0, deadline - time.monotonic())
                    )
                except subprocess.TimeoutExpired:
                    record["timed_out"] = True
                    record["exit"] = 124
                finally:
                    # This group was created by us, never an unrelated global PID search.
                    # Clean descendants even if the leader already exited.
                    try:
                        signal_owned_group(signal.SIGTERM, "first-eperm-term")
                    except ProcessLookupError:
                        pass
                    else:
                        group_absent = False
                        end = time.monotonic() + grace
                        while time.monotonic() < end:
                            process.poll()
                            try:
                                signal_owned_group(
                                    0, "first-eperm-after-term-signal-zero"
                                )
                            except ProcessLookupError:
                                group_absent = True
                                break
                            time.sleep(0.05)
                        if not group_absent:
                            try:
                                signal_owned_group(signal.SIGKILL, "first-eperm-kill")
                            except ProcessLookupError:
                                pass
                    try:
                        process.wait(timeout=grace)
                    except subprocess.TimeoutExpired as error:
                        record["cleanup_error_type"] = type(error).__name__
                        record["cleanup_traceback"] = traceback.format_exc()
                        record["cleanup_error"] = "owned leader not reaped"
                        record["exit"] = 125
    except Exception as error:
        record["error"] = str(error)
        record["error_type"] = type(error).__name__
        record["traceback"] = traceback.format_exc()
        record["exit"] = 125
    finally:
        record["elapsed_seconds"] = time.monotonic() - started
        write(directory / "result.json", record)
    return record["exit"]


def python_identity():
    require(
        sys.version_info >= (3, 10),
        "Python >= 3.10 required for cross-process macOS monotonic clock",
    )
    executable = Path(sys.executable).resolve()
    return {
        "path": str(executable),
        "version": sys.version,
        "sha256": digest(executable),
    }


def shared_deadline(out):
    budget = json.loads((out / "budget.json").read_text())
    require(budget["python"] == python_identity(), "budget interpreter changed")
    start = budget["start_monotonic"]
    deadline = budget["deadline_monotonic"]
    require(
        type(start) in {int, float} and type(deadline) in {int, float},
        "invalid deadline type",
    )
    require(math.isfinite(start) and math.isfinite(deadline), "nonfinite deadline")
    require(
        budget["seconds"] == 4500 and budget["clock"] == "monotonic", "wrong budget"
    )
    require(
        deadline == start + 4500 and 0 <= start <= time.monotonic(),
        "invalid shared deadline",
    )
    require(budget["head"] == os.environ["CANDIDATE_SHA"], "wrong budget head")
    return deadline


def bind(out):
    require(shared_deadline(out) > time.monotonic(), "setup exhausted shared budget")
    pins = json.loads((HERE / "macos_owner_pins.json").read_text())
    head = git("rev-parse", "HEAD")
    require(
        head == os.environ["CANDIDATE_SHA"] == os.environ["WORKFLOW_SHA"],
        "head/workflow mismatch",
    )
    require(git("rev-parse", "HEAD^") == BASE, "wrong direct parent")
    require(git("rev-parse", BASE + "^{tree}") == pins["base_tree"], "wrong base tree")
    require(not git("status", "--porcelain=v1"), "dirty source")
    require(
        set(git("diff", "--name-only", "--no-renames", BASE, head).splitlines())
        == set(pins["changed_paths"]),
        "unexpected changes",
    )
    require(
        git("rev-parse", "HEAD:codex-rs/Cargo.lock") == pins["lock_blob"], "lock drift"
    )
    for path, sha in pins["source_sha256"].items():
        require(digest(path) == sha, f"source pin mismatch: {path}")
    source = {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}"),
        "base": BASE,
        "base_tree": pins["base_tree"],
        "workflow_sha": os.environ["WORKFLOW_SHA"],
        "lock_blob": pins["lock_blob"],
        "budget_sha256": digest(out / "budget.json"),
    }
    paths = sorted(
        set(pins["changed_paths"])
        | set(pins["support_paths"])
        | set(pins["source_sha256"])
    )
    source["files"] = {
        p: {"sha256": digest(p), "blob": git("rev-parse", f"HEAD:{p}")} for p in paths
    }
    write(out / "source.json", source)
    (out / "candidate.patch").write_bytes(
        subprocess.check_output(["git", "diff", "--binary", "--full-index", BASE, head])
    )
    (out / "tree.txt").write_bytes(
        subprocess.check_output(["git", "ls-tree", "-r", "HEAD"])
    )
    with (out / "source.tar").open("wb") as artifact:
        subprocess.run(
            [
                "git",
                "archive",
                "HEAD",
                "codex-rs/hepta-memory",
                "codex-rs/hepta-supervisor",
                *paths,
            ],
            stdout=artifact,
            check=True,
        )


def validate_version(tool, raw, prefix):
    headline = raw.decode().splitlines()[0]
    require(
        headline == prefix if tool == "just" else headline.startswith(prefix),
        f"wrong {tool} version",
    )


def tool_receipt(out):
    require(
        platform.system() == "Darwin" and platform.machine() == "x86_64",
        "not native Intel macOS",
    )
    versions = {
        "rustc": "rustc 1.95.0 ",
        "cargo": "cargo 1.95.0 ",
        "just": "just 1.59.0",
        "cargo-nextest": "cargo-nextest 0.9.103 ",
    }
    receipt = {
        "platform": platform.platform(),
        "python": python_identity(),
        "tools": {},
    }
    require(
        receipt["python"] == json.loads((out / "budget.json").read_text())["python"],
        "setup interpreter changed",
    )
    for tool, prefix in versions.items():
        raw = subprocess.check_output([tool, "--version"])
        (out / f"{tool}-version.txt").write_bytes(raw)
        validate_version(tool, raw, prefix)
        path = shutil.which(tool)
        if tool in {"rustc", "cargo"}:
            path = subprocess.check_output(
                ["rustup", "which", "--toolchain", "1.95.0", tool], text=True
            ).strip()
        receipt["tools"][tool] = {
            "path": path,
            "sha256": digest(path),
            "version": raw.decode(),
        }
    rust = subprocess.check_output(["rustc", "-vV"])
    require(b"host: x86_64-apple-darwin" in rust, "wrong Rust host")
    (out / "rustc-verbose.txt").write_bytes(rust)
    write(out / "tools.json", receipt)


def validate_metadata(path):
    metadata = json.loads(path.read_text())
    require(
        isinstance(metadata.get("resolve"), dict), "metadata has no dependency graph"
    )
    require(
        isinstance(metadata["resolve"].get("nodes"), list)
        and bool(metadata["resolve"]["nodes"]),
        "empty dependency graph",
    )
    require(
        bool(metadata.get("workspace_members")) and bool(metadata.get("packages")),
        "incomplete cargo metadata",
    )


def execute(out):
    source = json.loads((out / "source.json").read_text())
    require(
        digest(out / "budget.json") == source["budget_sha256"],
        "shared budget was reset",
    )
    deadline = shared_deadline(out)
    cwd = Path.cwd() / "codex-rs"
    failed = False
    metadata = out / "metadata"
    status = bounded(
        ["cargo", "metadata", "--locked", "--format-version=1"],
        metadata,
        deadline,
        cwd,
    )
    require(status == 0, "metadata failed; original evidence retained")
    validate_metadata(metadata / "stdout.log")
    for phase in PHASES:
        directory = out / phase
        directory.mkdir()
        report = cwd / "target/nextest" / PROFILE / "junit.xml"
        report.unlink(missing_ok=True)
        args = selection(phase) + ["--cargo-metadata", str(metadata / "stdout.log")]
        command = [
            "cargo",
            "nextest",
            "list",
            *args,
            "--profile",
            PROFILE,
            "--message-format",
            "json",
        ]
        status = bounded(command, directory / "list", deadline, cwd)
        try:
            require(status == 0, "list command failed")
            validate_list(directory / "list/stdout.log", phase)
            status = bounded(
                [
                    "just",
                    "test",
                    *args,
                    "--profile",
                    PROFILE,
                    "--retries",
                    "0",
                    "--no-tests",
                    "fail",
                ],
                directory / "run",
                deadline,
                cwd,
            )
            if report.is_file():
                shutil.copyfile(report, directory / "junit.xml")
            require(status == 0, "original just test failed")
            validate_report(directory / "junit.xml", phase)
        except Exception as error:
            failed = True
            (directory / "error.txt").write_text(str(error) + "\n")
    require(not failed, "one or more native phases failed; see original evidence")


def verify(out):
    before = json.loads((out / "source.json").read_text())
    require(
        before["head"]
        == git("rev-parse", "HEAD")
        == os.environ["CANDIDATE_SHA"]
        == os.environ["WORKFLOW_SHA"],
        "head drift",
    )
    require(not git("status", "--porcelain=v1"), "dirty after run")
    for path, item in before["files"].items():
        require(digest(path) == item["sha256"], f"source drift {path}")
    require(
        digest(out / "budget.json") == before["budget_sha256"], "shared budget changed"
    )
    validate_metadata(out / "metadata/stdout.log")
    tools = json.loads((out / "tools.json").read_text())
    require(tools["python"] == python_identity(), "tool receipt interpreter changed")
    for tool, receipt in tools["tools"].items():
        require(digest(receipt["path"]) == receipt["sha256"], f"tool changed: {tool}")
        require(
            subprocess.check_output([tool, "--version"]).decode() == receipt["version"],
            f"tool version changed: {tool}",
        )
    metadata = json.loads((out / "metadata/result.json").read_text())
    require(metadata["exit"] == 0 and not metadata["timed_out"], "metadata failed")
    results = {}
    for phase in PHASES:
        directory = out / phase
        expected_commands = {
            "list": [
                "cargo",
                "nextest",
                "list",
                *selection(phase),
                "--cargo-metadata",
                str(out / "metadata/stdout.log"),
                "--profile",
                PROFILE,
                "--message-format",
                "json",
            ],
            "run": [
                "just",
                "test",
                *selection(phase),
                "--cargo-metadata",
                str(out / "metadata/stdout.log"),
                "--profile",
                PROFILE,
                "--retries",
                "0",
                "--no-tests",
                "fail",
            ],
        }
        for mode in ("list", "run"):
            record = json.loads((directory / mode / "result.json").read_text())
            require(record["argv"] == expected_commands[mode], "wrong native command")
            require(
                json.loads((directory / mode / "command.json").read_text())
                == record["argv"],
                "command receipt mismatch",
            )
            require(
                record["exit"] == 0 and not record["timed_out"],
                f"failed {phase}/{mode}",
            )
        require(
            validate_list(directory / "list/stdout.log", phase)
            == validate_report(directory / "junit.xml", phase),
            "list/report mismatch",
        )
        results[phase] = len(expected(phase))
    write(
        out / "qualification.json",
        {
            "head": before["head"],
            "selected_passes": results,
            "excluded_ignored_memory": 7,
            "full_suite": False,
        },
    )


def seal(out):
    """Hash finalized files only after all command/log producers have closed."""
    write(
        out / "artifact-hashes.json",
        {
            str(p.relative_to(out)): digest(p)
            for p in sorted(out.rglob("*"))
            if p.is_file() and p.name != "artifact-hashes.json"
        },
    )


def main():
    action, directory = sys.argv[1:]
    out = Path(directory).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if action == "bind":
        bind(out)
    elif action == "tools":
        tool_receipt(out)
    elif action == "run":
        execute(out)
    elif action == "verify":
        verify(out)
    elif action == "seal":
        seal(out)
    else:
        raise ValueError("unknown action")


if __name__ == "__main__":
    main()
