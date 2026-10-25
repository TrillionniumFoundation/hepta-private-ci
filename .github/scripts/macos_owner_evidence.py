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
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PROFILE = "macos-owner"
BASE = "c6784f0e4259cf4fce301691c890caf359961517"
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
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                else:
                    end = time.monotonic() + grace
                    while time.monotonic() < end:
                        process.poll()
                        try:
                            os.killpg(process.pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.05)
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    record["cleanup_error"] = "owned leader not reaped"
                    record["exit"] = 125
    except Exception as error:
        record["error"] = str(error)
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
        deadline - start == 4500 and 0 <= start <= time.monotonic(),
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
    paths = sorted(set(pins["changed_paths"]) | set(pins["support_paths"]))
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
        try:
            verify(out)
        finally:
            write(
                out / "artifact-hashes.json",
                {
                    str(p.relative_to(out)): digest(p)
                    for p in sorted(out.rglob("*"))
                    if p.is_file() and p.name != "artifact-hashes.json"
                },
            )
    else:
        raise ValueError("unknown action")


if __name__ == "__main__":
    main()
