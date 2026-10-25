#!/usr/bin/env python3
"""Bounded native macOS qualification of 278 exact owner tests, not full CI."""

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import selectors
import signal
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PROFILE = "macos-owner"
BASE = "e56ede6cc9e338ed78d2e1ac76a12c7eb0ca26ed"
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


def snapshot_owned_group(pgid, directory):
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
    snapshot.update(argv=command, limit_bytes=16384, timeout_seconds=2)
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
                remaining = started + 2 - time.monotonic()
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
                    timeout=max(0, started + 2 - time.monotonic())
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
        with (
            (directory / "stdout.log").open("wb") as stdout,
            (directory / "stderr.log").open("wb") as stderr,
        ):
            process = subprocess.Popen(
                command, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True
            )
            record["owned_pgid"] = process.pid
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
                    end = time.monotonic() + grace
                    while time.monotonic() < end:
                        process.poll()
                        try:
                            signal_owned_group(0, "first-eperm-after-term-signal-zero")
                        except ProcessLookupError:
                            break
                        time.sleep(0.05)
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
