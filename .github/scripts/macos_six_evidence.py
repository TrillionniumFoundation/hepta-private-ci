#!/usr/bin/env python3
"""Bounded Intel macOS six-fixture diagnostics with exact owning-suite inventories."""

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
PROFILE = "macos-six"
BASE = "a2ca5c5517d0c766631faaeae4f2d147b725ca26"
SOURCE_SHA = "253d1b6d3b9c2fb4fc250886d0b8457a107842e9"
SOURCE_TREE = "429aa6b7d0027d1f92aabad14e716083ccf86c78"
SOURCE_BASE = "e4ee552d37040a62e8cee6ef4172aae8b6680204"
MANIFEST = json.loads((HERE / "macos_six_cases.json").read_text())
PHASES = tuple(MANIFEST["phases"])
PROFILE_APPENDIX = '\n# Diagnostic profile only; all original defaults and overrides remain above.\n[profile.macos-six]\nretries = 0\n\n[profile.macos-six.junit]\npath = "junit.xml"\nreport-name = "macos-six"\n'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_root():
    raw = Path(os.environ["SOURCE_ROOT"])
    require(raw.is_absolute() and raw == raw.resolve(), "source root alias")
    control = HERE.parent.parent.resolve()
    require(
        raw != control and raw not in control.parents and control not in raw.parents,
        "source/control roots overlap",
    )
    return raw


def git(*args):
    return subprocess.check_output(["git", *args], cwd=source_root(), text=True).strip()


def control_git(*args):
    return subprocess.check_output(
        ["git", *args], cwd=HERE.parent.parent, text=True
    ).strip()


def full_worktree_identity(root):
    """Check EVERY tracked working-tree byte/mode against immutable Git blobs."""
    raw = subprocess.check_output(["git", "ls-tree", "-rz", "HEAD"], cwd=root)
    inventory = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        path = os.fsdecode(name)
        require(
            kind == "blob" and mode in {"100644", "100755", "120000"},
            "unsupported source tree entry",
        )
        target = root / path
        require(target.parent.resolve().is_relative_to(root), "source path escape")
        if mode == "120000":
            require(target.is_symlink(), "symlink mode drift")
            data = os.fsencode(os.readlink(target))
        else:
            require(target.is_file() and not target.is_symlink(), "source type drift")
            require(
                bool(target.stat().st_mode & 0o111) == (mode == "100755"),
                "source executable mode drift",
            )
            data = target.read_bytes()
        actual = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        require(actual == blob, f"working source blob drift: {path}")
        inventory[path] = {
            "blob": blob,
            "mode": mode,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    require(bool(inventory), "empty source tree")
    return inventory


def validate_roots(pins):
    require(os.environ["SOURCE_SHA"] == SOURCE_SHA, "wrong immutable source input")
    source = source_root()
    control = HERE.parent.parent.resolve()
    require(Path.cwd().resolve() == source, "controller not launched from source root")
    require(git("rev-parse", "HEAD") == SOURCE_SHA, "wrong source head")
    require(git("rev-parse", "HEAD^{tree}") == SOURCE_TREE, "wrong source tree")
    require(
        not git("status", "--porcelain=v1", "--untracked-files=all"), "dirty source"
    )
    require(
        control_git("rev-parse", "HEAD")
        == os.environ["CANDIDATE_SHA"]
        == os.environ["WORKFLOW_SHA"],
        "wrong control head",
    )
    require(control_git("rev-parse", "HEAD^") == BASE, "wrong control parent")
    require(
        control_git("rev-parse", BASE + "^{tree}") == pins["base_tree"],
        "wrong control parent tree",
    )
    require(
        not control_git("status", "--porcelain=v1", "--untracked-files=all"),
        "dirty control",
    )
    require(
        set(
            control_git(
                "diff", "--name-only", "--no-renames", BASE, "HEAD"
            ).splitlines()
        )
        == set(pins["changed_paths"]),
        "unexpected control delta",
    )
    require(
        set(
            git("diff", "--name-only", "--no-renames", SOURCE_BASE, "HEAD").splitlines()
        )
        == set(pins["source_changed_paths"]),
        "unexpected source delta",
    )
    chain = git("rev-list", "--first-parent", SOURCE_BASE + "..HEAD").splitlines()
    require(chain == pins["source_chain"], "wrong source ancestry")
    require(
        git("rev-parse", SOURCE_BASE + "^{tree}") == pins["source_base_tree"],
        "wrong source base tree",
    )
    for path, sha in pins["control_sha256"].items():
        require(digest(control / path) == sha, f"control pin mismatch: {path}")
    for path, blob in pins["lock_blobs"].items():
        require(git("rev-parse", f"HEAD:{path}") == blob, "lock drift")
    require(
        (HERE / "macos_six_nextest.toml").read_text()
        == (source / "codex-rs/.config/nextest.toml").read_text() + PROFILE_APPENDIX,
        "inherited nextest policy drift",
    )
    return {
        "source": full_worktree_identity(source),
        "control": full_worktree_identity(control),
        "source_root": str(source),
        "control_root": str(control),
        "control_head": control_git("rev-parse", "HEAD"),
        "control_tree": control_git("rev-parse", "HEAD^{tree}"),
        "source_tree": SOURCE_TREE,
    }


def expected(phase):
    record = MANIFEST["phases"][phase]
    if phase == "supervisor-integration":
        pairs = [(row["binary"], row["case"]) for row in record["cases"]]
        require(len(pairs) == 2 and len(set(pairs)) == 2, "bad integration inventory")
        return set(pairs)
    names = record["cases"]
    require(names and len(names) == len(set(names)), "bad fixed inventory")
    return {(record["package"], name) for name in names}


def selection(phase):
    record = MANIFEST["phases"][phase]
    expression = (
        " | ".join(f"test(={name})" for _, name in sorted(expected(phase)))
        if phase.startswith("original-")
        or phase in {"fleet-owning", "supervisor-owning", "supervisor-integration"}
        else f"test({record['module']}::)"
    )
    if phase == "evidence-outbox":
        expression += " & !test(=authbus_outbox_tests::crash_delivery_child)"
    return [
        "--color",
        "never",
        "--locked",
        "-p",
        record["package"],
        *(["--tests"] if phase == "supervisor-integration" else ["--lib"]),
        "--config-file",
        str(HERE / "macos_six_nextest.toml"),
        "-E",
        expression,
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


def snapshot_owned_group(pgid, directory, timeout_seconds=2, capture_limit_bytes=16384):
    """One bounded read-only Darwin group snapshot, never a cleanup verdict."""
    require(
        type(capture_limit_bytes) is int and 0 < capture_limit_bytes <= 16384,
        "invalid snapshot capture bound",
    )
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
    snapshot["capture_limit_bytes"] = capture_limit_bytes
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
                    chunk = os.read(
                        key.fileobj.fileno(), min(4096, capture_limit_bytes + 1 - total)
                    )
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output[key.data].extend(chunk)
                if sum(len(value) for value in output.values()) > capture_limit_bytes:
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
        remaining = capture_limit_bytes
        for name, value in output.items():
            kept = bytes(value[:remaining])
            remaining -= len(kept)
            (directory / f"probe-state.{name}.log").write_bytes(kept)
        snapshot["elapsed_seconds"] = time.monotonic() - started
    return snapshot


def capture_owned_snapshot(
    process, directory, stage, timeout_seconds=2, capture_limit_bytes=16384
):
    directory.mkdir(parents=True)
    snapshot = snapshot_owned_group(
        process.pid,
        directory,
        timeout_seconds=timeout_seconds,
        capture_limit_bytes=capture_limit_bytes,
    )
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


def startup_snapshot_rows(snapshot, directory, pgid):
    """Startup syntax only: unknown child tokens NEVER authorize signals or reaping."""
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
            (
                re.fullmatch(r"[A-Z][A-Za-z+<>-]*", parts[5]) is not None
                or parts[5] in {"?<", "?<E"}
            ),
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
        require(
            re.fullmatch(r"[0-9a-fA-F]+", parts[3]) is not None,
            "malformed session display",
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


def startup_owned_observation(process, directory, deadline):
    """Bounded read-only startup triage; '?' is never an ownership verdict."""
    started = time.monotonic()
    end = min(started + 2, deadline) if deadline is not None else started + 2
    require(
        math.isfinite(end) and end > started, "startup observation budget exhausted"
    )
    directory.mkdir(parents=True)
    receipt = {
        "start_monotonic": started,
        "deadline_monotonic": end,
        "max_observations": 3,
        "cumulative_limit_bytes": 16384,
        "attempts": [],
    }
    used = 0
    anchor = None
    seen = {}
    previous_pids = set()
    departed = set()
    try:
        for index in range(3):
            require_unreaped_owner(process)
            remaining = end - time.monotonic()
            require(
                remaining > 0 and used < 16384, "startup observation budget exhausted"
            )
            if anchor is not None:
                require(
                    os.getsid(process.pid) == process.pid
                    and os.getpgid(process.pid) == process.pid,
                    "startup session anchor changed",
                )
            remaining = end - time.monotonic()
            require(remaining > 0, "startup anchor check exhausted deadline")
            target = directory / f"attempt-{index:04d}"
            attempt = {
                "index": index,
                "remaining_seconds": remaining,
                "capture_limit_bytes": 16384 - used,
                "directory": target.name,
                "classification": "unverified",
            }
            receipt["attempts"].append(attempt)
            snapshot = capture_owned_snapshot(
                process,
                target,
                "startup-owned-identity",
                timeout_seconds=min(2, remaining),
                capture_limit_bytes=16384 - used,
            )
            require_unreaped_owner(process)
            require(time.monotonic() <= end, "startup observation exceeded deadline")
            count = sum(
                (target / f"probe-state.{name}.log").stat().st_size
                for name in ("stdout", "stderr")
            )
            used += count
            attempt.update(bytes=count, cumulative_bytes=used)
            require(used <= 16384, "startup cumulative output exceeds bound")
            rows = startup_snapshot_rows(snapshot, target, process.pid)
            leaders = [r for r in rows if r["pid"] == process.pid]
            require(len(leaders) == 1, "missing owned startup leader")
            leader = leaders[0]
            require(
                leader["ppid"] == os.getpid(), "startup leader not our direct child"
            )
            require(not leader["state"].startswith("?"), "unknown startup leader state")
            unknown = [r["pid"] for r in rows if r["state"].startswith("?")]
            if not unknown and anchor is None:
                # Preserve the original clean-snapshot binding path. The extra
                # ancestry/session gate applies only to unknown-state triage.
                snapshot_rows(snapshot, target, process.pid)
                attempt["classification"] = "strict-snapshot-verified"
                receipt["selected_attempt"] = index
                return snapshot, target, end
            known = {process.pid}
            pending = {r["pid"]: r for r in rows if r["pid"] != process.pid}
            while pending:
                children = {pid for pid, row in pending.items() if row["ppid"] in known}
                require(bool(children), "unverified startup ancestry")
                known.update(children)
                for pid in children:
                    del pending[pid]
            stable = {k: leader[k] for k in ("pid", "ppid", "pgid", "uid", "start")}
            stable["ps_sha256"] = snapshot["binary_sha256"]
            if anchor is not None:
                require(stable == anchor, "startup leader identity changed")
            current_pids = {r["pid"] for r in rows}
            require(not current_pids & departed, "startup process identity reappeared")
            for row in rows:
                identity = {k: row[k] for k in ("pid", "ppid", "pgid", "uid", "start")}
                require(
                    row["pid"] not in seen or seen[row["pid"]] == identity,
                    "startup process identity changed",
                )
                seen[row["pid"]] = identity
            departed.update(previous_pids - current_pids)
            previous_pids = current_pids
            unknown = [r["pid"] for r in rows if r["state"].startswith("?")]
            if unknown or anchor is not None:
                require(
                    all(
                        r["state"] in {"?<", "?<E"}
                        or re.fullmatch(r"[RUSITHZ](?:<|N)?X?E?V?L?s?\+?", r["state"])
                        is not None
                        for r in rows
                    ),
                    "unsupported startup state syntax",
                )
                # sess is a display field, not the POSIX numeric SID. A real
                # lookup failure is terminal here: no retry/fallback after it.
                sid, pgid = os.getsid(process.pid), os.getpgid(process.pid)
                require(
                    sid == process.pid and pgid == process.pid,
                    "startup session anchor mismatch",
                )
                require_unreaped_owner(process)
                attempt.update(observed_sid=sid, observed_pgid=pgid, leader=stable)
                anchor = stable
            require(time.monotonic() <= end, "startup identity proof exceeded deadline")
            if not unknown:
                snapshot_rows(snapshot, target, process.pid)
                attempt["classification"] = "strict-snapshot-verified"
                receipt["selected_attempt"] = index
                return snapshot, target, end
            attempt.update(classification="unknown-child-state", unknown_pids=unknown)
            require(index < 2, "startup unknown state persisted")
            remaining = end - time.monotonic()
            require(remaining > 0, "startup observation budget exhausted")
            time.sleep(min(0.05, remaining))
        raise ValueError("startup observation exhausted")
    except Exception as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        receipt.update(
            elapsed_seconds=time.monotonic() - started, cumulative_bytes=used
        )
        write(directory / "startup-observations.json", receipt)


def bind_owned_leader(process, directory, deadline=None):
    snapshot, observation_directory, startup_deadline = startup_owned_observation(
        process, directory, deadline
    )
    rows = snapshot_rows(snapshot, observation_directory, process.pid)
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
    require(time.monotonic() <= startup_deadline, "startup binding exceeded deadline")
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
        "cwd": str(Path(cwd).resolve()),
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
                        process, directory / "startup-identity", deadline
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
    pins = json.loads((HERE / "macos_six_pins.json").read_text())
    require(git("rev-parse", "HEAD") == SOURCE_SHA, "head/workflow mismatch")
    roots = validate_roots(pins)
    source = {
        "head": SOURCE_SHA,
        "tree": SOURCE_TREE,
        "roots": roots,
        "budget_sha256": digest(out / "budget.json"),
    }
    write(out / "source.json", source)
    source_paths = sorted(
        set(pins["source_support_paths"])
        | set(pins["source_changed_paths"])
        | {
            f"codex-rs/{name}"
            for name in (
                "rollout",
                "sandboxing",
                "state",
                "hepta-evidence",
                "hepta-bao-adapter",
                "hepta-automation",
                "hepta-authbus",
                "hepta-fleet",
                "hepta-supervisor",
            )
        }
    )
    for name, root, paths in (
        ("source", source_root(), source_paths),
        ("control", HERE.parent.parent, pins["control_paths"]),
    ):
        (out / f"{name}-tree.txt").write_bytes(
            subprocess.check_output(["git", "ls-tree", "-r", "HEAD"], cwd=root)
        )
        with (out / f"{name}.tar").open("wb") as artifact:
            subprocess.run(
                ["git", "archive", "HEAD", *paths],
                cwd=root,
                stdout=artifact,
                check=True,
            )
    (out / "candidate.patch").write_bytes(
        subprocess.check_output(
            ["git", "diff", "--binary", "--full-index", SOURCE_BASE, SOURCE_SHA],
            cwd=source_root(),
        )
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
    require(
        validate_roots(json.loads((HERE / "macos_six_pins.json").read_text()))
        == source["roots"],
        "pre-execution roots drift",
    )
    deadline = shared_deadline(out)
    cwd = source_root() / "codex-rs"
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
                    "--success-output",
                    "final",
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


def validate_native_receipt(record):
    require(
        record["exit"] == 0 and record["timed_out"] is False, "native command failed"
    )
    require(record["cwd"] == str(source_root() / "codex-rs"), "wrong native cwd")
    identity, life = record["leader_identity"], record["leader_lifecycle"]
    require(
        life["reaped"] is True
        and life["pid"]
        == identity["pid"]
        == identity["pgid"]
        == identity["sid"]
        == record["owned_pgid"],
        "unverified exact native leader reap",
    )
    require(
        life["ownership"] == "sole-pinned-unreaped-direct-child-zombie"
        and life["returncode"] == 0 == os.waitstatus_to_exitcode(life["wait_status"]),
        "wrong native reap result",
    )
    require(
        record["cleanup_observations"][-1]["state"] == "sole-terminal-leader",
        "native descendants remain unverified",
    )


def verify(out):
    before = json.loads((out / "source.json").read_text())
    require(before["head"] == git("rev-parse", "HEAD") == SOURCE_SHA, "head drift")
    require(not git("status", "--porcelain=v1"), "dirty after run")
    require(
        validate_roots(json.loads((HERE / "macos_six_pins.json").read_text()))
        == before["roots"],
        "source/control drift after run",
    )
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
    validate_native_receipt(metadata)
    require(metadata["exit"] == 0 and not metadata["timed_out"], "metadata failed")
    require(metadata["cwd"] == str(source_root() / "codex-rs"), "wrong metadata cwd")
    require(
        metadata["argv"] == ["cargo", "metadata", "--locked", "--format-version=1"],
        "wrong metadata command",
    )
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
                "--success-output",
                "final",
            ],
        }
        for mode in ("list", "run"):
            record = json.loads((directory / mode / "result.json").read_text())
            validate_native_receipt(record)
            require(
                record["cwd"] == str(source_root() / "codex-rs"), "wrong native cwd"
            )
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
        out / "native-outcomes.json",
        {
            "head": before["head"],
            "selected_passes": results,
            "ignored_child_not_a_pass": MANIFEST["ignored_child_not_a_pass"],
            "qualified": False,
            "remaining": [
                "checkpoint-path negative coverage",
                "six full Bazel targets and broader matrix",
            ],
            "full_suite": False,
        },
    )
    validate_stages(out)
    write(
        out / "stage-outcomes.json",
        {
            "head": before["head"],
            "stage_plan_sha256": digest(HERE / "macos_six_stages.json"),
            "scoped_stage_verified": True,
            "full_suite": False,
            "production_qualified": False,
        },
    )


def validate_stages(out):
    stage_plan = json.loads((HERE / "macos_six_stages.json").read_text())
    require(
        not stage_plan["unresolved"], "stage evidence plan unresolved; no qualification"
    )
    required = stage_plan["required"]
    require(
        bool(required) and set(required) <= set(PHASES),
        "missing or unknown stage phases",
    )
    for phase, cases in required.items():
        text = (
            (out / phase / "run/stdout.log").read_text()
            + "\n"
            + (out / phase / "run/stderr.log").read_text()
        )
        require("not_exercised" not in text, "native stage was not exercised")
        require(bool(cases), "empty stage requirements")
        case_names = {token.split("|")[1] for token in cases if token.count("|") == 2}
        selected_names = {name for _, name in expected(phase)}
        require(bool(case_names), "empty stage cases")
        for name in case_names:
            require(
                f"seatbelt::tests::{name}" in selected_names,
                "stage receipt case not selected",
            )
            prefix = f"HEPTA_SEATBELT_STAGE|{name}|"
            require(
                cases.get(prefix + "begin") == 1
                and cases.get(prefix + "complete") == 1,
                "missing case boundary contract",
            )
        observed = []
        for line in text.splitlines():
            if "HEPTA_SEATBELT_STAGE|" not in line:
                continue
            match = re.fullmatch(
                r"\s*(HEPTA_SEATBELT_STAGE\|[^\s|]+\|[^\s|]+)\s*", line
            )
            require(match is not None, "malformed stage receipt")
            observed.append(match.group(1))
        for token, count in cases.items():
            require(
                re.fullmatch(r"HEPTA_SEATBELT_STAGE\|[^\s|]+\|[^\s|]+", token)
                is not None
                and type(count) is int
                and count > 0,
                "invalid stage contract",
            )
        require(
            Counter(observed) == Counter(cases),
            "missing/duplicate/unknown stage receipts",
        )
        for token in cases:
            if "|ancestor_rename_denied:" in token:
                startup = token.replace(
                    "|ancestor_rename_denied:", "|restricted_policy_started:"
                )
                unchanged = token.replace(
                    "|ancestor_rename_denied:", "|protected_bytes_unchanged:"
                )
                require(
                    startup in cases and unchanged in cases,
                    "incomplete ancestor stage contract",
                )
                require(
                    observed.index(startup)
                    < observed.index(token)
                    < observed.index(unchanged),
                    "ancestor denial must follow same-policy startup and precede byte verification",
                )
            if token.endswith("|begin"):
                prefix = token.removesuffix("begin")
                sequence = [item for item in observed if item.startswith(prefix)]
                require(
                    sequence[0] == token and sequence[-1] == prefix + "complete",
                    "stage case did not begin and complete in order",
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
