"""One newly reconstructed, exact-source hooks and CLI native observation.

The unavailable old native48 owner is not being represented as recovered.
The original WNOWAIT command owner and JUnit collector are unchanged. The
original command log combines stdout and stderr; no separate stderr original
is claimed. This gate observes exactly 48 (binary ID, test name) instances.
"""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
import os
import platform
from pathlib import Path
import re
import resource
import stat
import subprocess
import time
import xml.etree.ElementTree as ET


SPEC_PATH = "scripts/hepta_chrono_hooks_cli_native_inputs_v2.json"
RUNNER_PATH = "scripts/run_chrono_hooks_cli_native_controls_v2.py"
WORKFLOW_PATH = ".github/workflows/hepta-chrono-hooks-cli-native-controls-v2.yml"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
BASE = "40d15b4bbba331f28e45889ff00846517b08375a"
ROOT_ACCEPTANCE_SHA256 = (
    "952cdc4dd2e63ad2277123f5be0738cb2075b00f6cf834a1f13d6d847587e384"
)
ROSTER_SHA256 = "573a66ecb204d62424187681155d1024e0608a57d22d3301c63b813ab93be09d"
LOCKS = {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}
NATIVE_CAP_SECONDS = 2400
WHOLE_JOB_CAP_SECONDS = 3600
EXACT_TESTS = 48
TOOL_VERSION_CAP_SECONDS = 5
TOOLING = {
    "runner": "ubuntu-24.04-arm",
    "rust": "1.96.0",
    "cargo": "1.96.0",
    "nextest": "0.9.103",
    "just": "1.51.0",
    "test_threads": 1,
    "retries": 0,
    "version_command_cap_seconds": 5,
}
TOOL_VERSION_COMMANDS = [
    {
        "name": "cargo",
        "command": ["cargo", "--version", "--verbose"],
        "prefix": "cargo 1.96.0",
    },
    {
        "name": "rustc",
        "command": ["rustc", "--version", "--verbose"],
        "prefix": "rustc 1.96.0",
    },
    {"name": "just", "command": ["just", "--version"], "prefix": "just 1.51.0"},
    {
        "name": "nextest",
        "command": ["cargo", "nextest", "--version"],
        "prefix": "cargo-nextest 0.9.103",
    },
]
BINARY_IDS = {
    "codex-hooks",
    "codex-cli::bin/codex",
    "codex-cli::bin/hepta",
    "codex-cli::bin/logs_client",
}
DEADLINE_NS = None
JOB_START_NS = None
SOURCE_FILE_LIMIT = 64 * 1024 * 1024
SOURCE_TOTAL_LIMIT = 4 * 1024 * 1024 * 1024
PUBLICATION_REQUIRED = {
    "codex-rs/Cargo.lock",
    "codex-rs/rmcp-client/src/auth_status.rs",
    RUNNER_PATH,
    SPEC_PATH,
    WORKFLOW_PATH,
}
PUBLICATION_OPTIONAL = {".github/workflows/blob-size-policy.yml"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def json_value(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def read_regular(path, maximum=64 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode) and before.st_size <= maximum,
            "input is not a bounded regular file",
        )
        chunks, total = [], 0
        while chunk := os.read(fd, min(64 * 1024, maximum + 1 - total)):
            check_deadline()
            total += len(chunk)
            require(total <= maximum, "input exceeded its bound")
            chunks.append(chunk)
        after = os.fstat(fd)
        stable = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        require(
            stable(before) == stable(after) and total == before.st_size,
            "input changed during the same-descriptor read",
        )
        return b"".join(chunks), before
    finally:
        os.close(fd)


def put(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def git(root, *arguments):
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        timeout=min(10, remaining_seconds()),
        env=dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0"),
    )
    return result.stdout


def original_module(path, name):
    module_spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(value)
    return value


def check_deadline():
    if DEADLINE_NS is not None:
        require(
            time.monotonic_ns() < DEADLINE_NS, "absolute whole-job deadline expired"
        )


def remaining_seconds():
    check_deadline()
    if DEADLINE_NS is None:
        raise ValueError("whole-job deadline has not been established")
    return (DEADLINE_NS - time.monotonic_ns()) / 1_000_000_000


def claim_deadline(evidence):
    global DEADLINE_NS, JOB_START_NS
    raw, _ = read_regular(evidence / "job-start.json", 64 * 1024)
    claim = json_value(raw)
    require(
        claim["schema"] == "hepta.chrono-hooks-cli-native-job-start.v2"
        and claim["source"] == os.environ["SOURCE_SHA"]
        and claim["run_id"] == os.environ["GITHUB_RUN_ID"]
        and claim["run_attempt"] == "1"
        and claim["job"] == os.environ["GITHUB_JOB"]
        and claim["native_command_cap_seconds"] == NATIVE_CAP_SECONDS
        and claim["whole_job_cap_seconds"] == WHOLE_JOB_CAP_SECONDS
        and claim["original_E1_E6_budget_used"] == 0
        and claim["old_lock_scope_reopened"] is False,
        "whole-job claim differs from the original source/run/caps",
    )
    start, deadline = claim["monotonic_start_ns"], claim["monotonic_deadline_ns"]
    require(
        type(start) is int
        and type(deadline) is int
        and 0 < start <= time.monotonic_ns()
        and deadline - start == WHOLE_JOB_CAP_SECONDS * 1_000_000_000,
        "absolute whole-job deadline is invalid",
    )
    JOB_START_NS, DEADLINE_NS = start, deadline
    check_deadline()
    return {"sha256": sha256(raw), "bytes": len(raw), "claim": claim}


def safe_relative(value):
    require(type(value) is str and value, "source path is absent")
    path = Path(value)
    require(
        not path.is_absolute()
        and path.as_posix() == value
        and not any(part in ("", ".", "..") for part in value.split("/"))
        and "\0" not in value,
        "source path is not a canonical relative path",
    )
    return path


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def source_snapshot(root):
    """Read every tracked source blob; no compiler or resolver is invoked here."""
    index = git(root, "ls-files", "--stage", "-z")
    result, total = {}, 0
    checked_directories = {root}
    for item in index.split(b"\0"):
        if not item:
            continue
        check_deadline()
        head, raw_path = item.split(b"\t", 1)
        mode, oid, stage = head.decode("ascii").split()
        path = raw_path.decode("utf-8")
        relative = safe_relative(path)
        require(
            stage == "0"
            and mode in ("100644", "100755", "120000")
            and re.fullmatch(r"[0-9a-f]{40}", oid) is not None
            and path not in result
            and len(result) < 25000,
            "source index is unmerged, duplicated, unsupported, or over bound",
        )
        parent = root
        for part in relative.parts[:-1]:
            parent = parent / part
            if parent not in checked_directories:
                require(
                    stat.S_ISDIR(parent.lstat().st_mode),
                    "source parent is not a real directory",
                )
                checked_directories.add(parent)
        file = root / relative
        if mode == "120000":
            before = file.lstat()
            require(stat.S_ISLNK(before.st_mode), "tracked symbolic link changed type")
            data = os.readlink(file).encode("utf-8")
            after = file.lstat()
            require(
                (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                == (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ),
                "tracked symbolic link changed while reading",
            )
        else:
            data, before = read_regular(file, SOURCE_FILE_LIMIT)
            require(
                bool(before.st_mode & 0o111) == (mode == "100755"),
                "tracked source executable mode changed: " + path,
            )
        total += len(data)
        actual_blob = git_blob(data)
        require(
            total <= SOURCE_TOTAL_LIMIT and actual_blob == oid,
            "tracked source bytes changed: " + path,
        )
        result[path] = {
            "mode": mode,
            "git_blob": actual_blob,
            "bytes": len(data),
            "sha256": sha256(data),
        }
    require(result, "source checkout has no tracked entries")
    return result


def read_root_acceptance(spec):
    raw = spec["root_lock_acceptance_original_json"].encode("utf-8")
    require(
        len(raw) == 6511
        and sha256(raw) == ROOT_ACCEPTANCE_SHA256
        and spec["lock_acceptance_review_sha256"] == ROOT_ACCEPTANCE_SHA256,
        "the original Root lock acceptance is not bound byte-for-byte",
    )
    accepted = json_value(raw)
    require(
        accepted["schema"] == "root-hepta7110-original-generated-lock-acceptance-v1"
        and accepted["status"]
        == "ORIGINAL_GENERATED_LOCKS_ACCEPTED_FOR_NEW_NATIVE_CANDIDATE"
        and accepted["repository"] == REPOSITORY
        and accepted["head"] == BASE
        and accepted["tree"] == "dd412d87f99be786de5fc2cf4e155243fa0d5c71"
        and accepted["run_id"] == 45718835160
        and accepted["run_attempt"] == 1
        and accepted["job_id"] == 139571696076
        and accepted["artifact_id"] == 15071736247
        and accepted["qualification"]["generated_lock_candidate"] is True
        and all(
            value is False
            for name, value in accepted["qualification"].items()
            if name != "generated_lock_candidate"
        )
        and accepted["frozen_E1_E6_training_spent_unchanged"] == 16,
        "Root acceptance has the wrong original scope or qualifications",
    )
    require(set(spec["accepted_locks"]) == LOCKS, "both accepted locks are required")
    for path in LOCKS:
        require(
            all(
                spec["accepted_locks"][path][key] == accepted["locks"][path][key]
                for key in ("bytes", "sha256", "git_blob")
            ),
            "accepted lock differs from the original Root acceptance: " + path,
        )
    return accepted


def expected_command(controls):
    command = ["just", "test", "--locked", "-p", "codex-cli", "-p", "codex-hooks"]
    command.extend(
        [
            "--lib",
            "--bins",
            "--retries",
            "0",
            "--test-threads",
            "1",
            "--status-level",
            "pass",
            "--final-status-level",
            "fail",
            "-E",
            " | ".join(
                f"(binary_id(={row['binary_id']}) & test(={row['name']}))"
                for row in controls
            ),
        ]
    )
    return command


def load_inputs(root):
    check_deadline()
    raw, _ = read_regular(root / SPEC_PATH, 1024 * 1024)
    spec = json_value(raw)
    require(
        spec["schema"] == "hepta.chrono-hooks-cli-native-reconstruction-inputs.v2"
        and spec["activated"] is True
        and spec["activation_blockers"] == [],
        "new native candidate remains inactive until final source publication is admitted",
    )
    require(
        os.environ["GITHUB_REPOSITORY"] == REPOSITORY
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["CHRONO_EVENT_ACTION"] == "opened"
        and os.environ["CHRONO_PR_AUTHOR"] == "ProfHepta"
        and os.environ["CHRONO_PR_DRAFT"] == "true"
        and os.environ["CHRONO_HEAD_REPO"] == REPOSITORY
        and os.environ["CHRONO_HEAD_BRANCH"] == spec["branch"]
        and os.environ["RUNNER_OS"] == "Linux"
        and os.environ["RUNNER_ARCH"] == "ARM64",
        "this is not the one admitted owned Draft opening on the registered native platform",
    )
    release = platform.freedesktop_os_release()
    require(
        spec["tooling"] == TOOLING
        and spec["tool_version_commands"] == TOOL_VERSION_COMMANDS
        and os.environ.get("RUSTUP_TOOLCHAIN") == "1.96.0"
        and platform.system() == "Linux"
        and platform.machine() == "aarch64"
        and release.get("ID") == "ubuntu"
        and release.get("VERSION_ID") == "24.04",
        "registered tooling, fixed rustup toolchain, or actual native platform differs",
    )
    head = os.environ["SOURCE_SHA"]
    require(
        re.fullmatch(r"[0-9a-f]{40}", head) is not None
        and os.environ["TESTED_SHA"] == head
        and os.environ["HEPTA_CI_LANE"] == "source-head"
        and spec["parent"] == BASE
        and spec["lock_generation_source"] == BASE,
        "source head, sole parent, lock origin, or lane changed",
    )
    require(
        git(root, "rev-parse", "HEAD").decode().strip() == head
        and not git(root, "status", "--porcelain=v1", "--untracked-files=all"),
        "native source is not the original clean event head",
    )
    headers = (
        git(root, "cat-file", "-p", head).split(b"\n\n", 1)[0].decode().splitlines()
    )
    require(
        [line[7:] for line in headers if line.startswith("parent ")] == [BASE],
        "native candidate has an unexpected parent",
    )
    tree = next(line[5:] for line in headers if line.startswith("tree "))
    require(re.fullmatch(r"[0-9a-f]{40}", tree) is not None, "source tree is absent")
    require(
        all(
            row.startswith(b"H ")
            for row in git(root, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "native input hides files through index flags",
    )
    publication = spec["publication_paths"]
    require(
        len(publication) == len(set(publication))
        and PUBLICATION_REQUIRED
        <= set(publication)
        <= PUBLICATION_REQUIRED | PUBLICATION_OPTIONAL,
        "publication path set left the reviewed source-only scope",
    )
    actual_paths = {
        value.decode("utf-8")
        for value in git(
            root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            "-z",
            BASE,
            head,
        ).split(b"\0")
        if value
    }
    require(
        actual_paths == set(publication),
        "actual commit changed paths differ from the reviewed publication",
    )
    rows = spec["reviewed_sources"]
    paths = {row["path"] for row in rows}
    require(
        len(rows) == len(paths) and SPEC_PATH not in paths,
        "source pins repeat a path or include a circular spec pin",
    )
    required = {
        "scripts/hepta_ci_exec.py",
        "scripts/hepta_ci_junit.py",
        "scripts/run-nextest.py",
        "scripts/just-shell.py",
        "justfile",
        "codex-rs/.config/nextest.toml",
        "codex-rs/.cargo/config.toml",
        "codex-rs/rust-toolchain.toml",
        "codex-rs/Cargo.toml",
        "codex-rs/cli/Cargo.toml",
        "codex-rs/hooks/Cargo.toml",
        "codex-rs/cli/src/main.rs",
        "codex-rs/cli/src/hepta.rs",
        "codex-rs/cli/src/main_impl.rs",
        "codex-rs/cli/src/doctor.rs",
        "codex-rs/cli/src/doctor/desktop.rs",
        "codex-rs/cli/src/doctor/desktop_tests.rs",
        "codex-rs/cli/src/doctor/desktop_time_tests.rs",
        "codex-rs/cli/src/bin/logs_client.rs",
        "codex-rs/cli/src/logs_client_timestamp_tests.rs",
        "codex-rs/cli/src/timestamp.rs",
        "codex-rs/cli/src/timestamp_tests.rs",
        "codex-rs/hooks/src/lib.rs",
        "codex-rs/hooks/src/types.rs",
        "codex-rs/hooks/src/legacy_notify.rs",
        "codex-rs/hooks/src/engine/command_runner.rs",
        "codex-rs/hooks/src/engine/dispatcher.rs",
        "codex-rs/hooks/src/engine/mcp_runner.rs",
        "codex-rs/core/src/hook_runtime.rs",
        "codex-rs/rmcp-client/src/auth_status.rs",
        ".github/actions/check-clean-worktree/action.yml",
        RUNNER_PATH,
        WORKFLOW_PATH,
    }
    require(
        required <= paths and set(publication) - {SPEC_PATH} <= paths,
        "an original execution/source input or published postimage is not pinned",
    )
    for row in rows:
        relative = safe_relative(row["path"])
        data, observed = read_regular(root / relative)
        require(
            len(data) == row["bytes"]
            and sha256(data) == row["sha256"]
            and git_blob(data) == row["git_blob"]
            and row["mode"] in ("100644", "100755")
            and bool(observed.st_mode & 0o111) == (row["mode"] == "100755"),
            "source differs from its reviewed pin: " + row["path"],
        )
    read_root_acceptance(spec)
    for relative, row in spec["accepted_locks"].items():
        data, _ = read_regular(root / relative)
        require(
            len(data) == row["bytes"]
            and sha256(data) == row["sha256"]
            and git_blob(data) == row["git_blob"],
            "source does not contain the independently accepted original lock: "
            + relative,
        )
    controls = spec["controls"]
    roster = [(row["binary_id"], row["name"]) for row in controls]
    roster_bytes = json.dumps(
        sorted(roster), separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    require(
        len(roster) == len(set(roster)) == EXACT_TESTS
        and sha256(roster_bytes) == ROSTER_SHA256
        and Counter(row["kind"] for row in controls) == {"new": 33, "retained": 15}
        and Counter(row["binary_id"] for row in controls)
        == {key: 12 for key in BINARY_IDS}
        and spec["native_cap_seconds"] == NATIVE_CAP_SECONDS
        and spec["whole_job_cap_seconds"] == WHOLE_JOB_CAP_SECONDS
        and spec["old_native48_original_bytes_recovered"] is False,
        "the fixed reconstructed roster, budgets, or recovery provenance changed",
    )
    for row in controls:
        require(
            row["package"] == row["binary_id"].split("::")[0]
            and row["source_path"] in paths
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_:]*", row["name"]) is not None,
            "a test selector or source provenance is invalid",
        )
    command = expected_command(controls)
    require(
        command == spec["command"],
        "command differs from the fixed binary-ID/name selectors",
    )
    return (
        spec,
        {"head": head, "tree": tree, "parent": BASE, "spec_sha256": sha256(raw)},
        command,
    )


def verify_original_log(evidence, execution_raw, record, controls, identity, command):
    require(
        record["status"] == "passed"
        and record["exit_code"] == 0
        and record["command_exit_code"] == 0
        and record["returncode"] == 0
        and record["timed_out"] is False
        and record["output_limit_exceeded"] is False
        and record["command"] == command
        and record["source_sha"] == identity["head"]
        and record["tested_sha"] == identity["head"]
        and record["lane"] == "source-head"
        and record["run_id"] == os.environ["GITHUB_RUN_ID"]
        and record["run_attempt"] == "1"
        and record["job"] == os.environ["GITHUB_JOB"]
        and record["before"]
        == record["after"]
        == {
            "commit": identity["head"],
            "tree": identity["tree"],
            "parents": [BASE],
            "dirty": False,
        }
        and record["observed_passed_tests"] == EXACT_TESTS
        and record["observed_failed_tests"] == 0
        and record["minimum_tests"] == EXACT_TESTS,
        "the original owner did not bind one clean passing exact command",
    )
    name = record["log_file"]
    require(
        type(name) is str
        and Path(name).name == name
        and name.startswith("controls.json."),
        "original command log path is invalid",
    )
    raw, _ = read_regular(evidence / name)
    require(
        len(raw) == record["log_bytes"] and sha256(raw) == record["log_sha256"],
        "original merged command log bytes changed",
    )
    output = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8"))
    require("\x1b" not in output, "unsupported escape in original command log")
    passes = re.findall(
        r"^\s*PASS\s+\[\s*[0-9.]+s\]\s+(\S+)\s+([A-Za-z_][A-Za-z0-9_:]*)\s*$",
        output,
        re.MULTILINE,
    )
    expected = Counter((row["binary_id"], row["name"]) for row in controls)
    require(
        len(passes) == EXACT_TESTS and Counter(passes) == expected,
        "original merged log does not contain each of the 48 exact PASS pairs once",
    )
    require(
        not re.search(
            r"^\s*(?:SKIP|FAIL|FLAKY|LEAK|TIMEOUT|RETRY|EXECFAIL|ABORT|CANCEL|IGNORED)\b",
            output,
            re.MULTILINE,
        ),
        "original merged log contains a skipped, retried, failed, or incomplete test",
    )
    summaries = re.findall(
        r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+(\d+) tests? run:\s*([^\r\n]+)$",
        output,
        re.MULTILINE,
    )
    require(
        len(summaries) == 1 and int(summaries[0][1]) == EXACT_TESTS,
        "original command lacks exactly one complete 48-test terminal summary",
    )
    summary = re.fullmatch(
        r"48 passed(?: \((\d+) slow\))?, (\d+) skipped", summaries[0][2]
    )
    require(
        summary is not None, "terminal summary reports an unexpected result or retry"
    )
    run_ids = re.findall(
        r"^\s*Nextest run ID ([0-9a-f-]{36}) with nextest profile: local\s*$",
        output,
        re.MULTILINE,
    )
    require(
        len(run_ids) == 1,
        "original log does not identify one local-profile nextest run",
    )
    starts = re.findall(
        r"^\s*Starting (\d+) tests across (\d+) binaries[^\r\n]*$", output, re.MULTILINE
    )
    require(
        len(starts) == 1 and int(starts[0][0]) == EXACT_TESTS,
        "original log did not start exactly the registered 48 instances",
    )
    return {
        "execution_sha256": sha256(execution_raw),
        "original_merged_log_sha256": sha256(raw),
        "original_merged_log_bytes": len(raw),
        "nextest_run_id": run_ids[0],
        "exact_pass_pairs": [
            {"binary_id": key[0], "name": key[1]} for key in sorted(expected)
        ],
        "selected_skipped": 0,
        "duplicate_passes": 0,
        "extra_passes": 0,
        "filter_excluded_unselected_tests": int(summary[2]),
        "slow_selected_tests": int(summary[1] or 0),
        "nextest_summary_seconds": float(summaries[0][0]),
        "listed_binary_count": int(starts[0][1]),
        "stream_provenance": "original WNOWAIT owner merged stdout+stderr; no separate stderr original",
    }


def verify_tool_observation(evidence, identity, case):
    output = evidence / ("version-" + case["name"] + ".json")
    raw, _ = read_regular(output, 1024 * 1024)
    record = json_value(raw)
    require(
        record["status"] == "passed"
        and record["exit_code"] == 0
        and record["command_exit_code"] == 0
        and record["returncode"] == 0
        and record["timed_out"] is False
        and record["output_limit_exceeded"] is False
        and record["command"] == case["command"]
        and record["source_sha"] == identity["head"]
        and record["tested_sha"] == identity["head"]
        and record["lane"] == "source-head"
        and record["run_id"] == os.environ["GITHUB_RUN_ID"]
        and record["run_attempt"] == "1"
        and record["job"] == os.environ["GITHUB_JOB"]
        and record["before"]
        == record["after"]
        == {
            "commit": identity["head"],
            "tree": identity["tree"],
            "parents": [BASE],
            "dirty": False,
        },
        "the original owner rejected a bounded tool-version observation: "
        + case["name"],
    )
    name = record["log_file"]
    require(
        type(name) is str
        and Path(name).name == name
        and name.startswith(output.name + "."),
        "tool-version original log path is invalid",
    )
    log, _ = read_regular(evidence / name, 64 * 1024)
    require(
        len(log) == record["log_bytes"] and sha256(log) == record["log_sha256"],
        "tool-version original merged log changed",
    )
    lines = log.decode("utf-8").splitlines()
    require(
        lines
        and re.fullmatch(re.escape(case["prefix"]) + r"(?: \([^\r\n]*\))?", lines[0])
        is not None,
        "observed executable version does not match the frozen version: "
        + case["name"],
    )
    if case["name"] in ("cargo", "rustc"):
        require(
            lines.count("release: 1.96.0") == 1,
            "verbose release does not match the frozen Rust/Cargo version",
        )
        require(
            lines.count("host: aarch64-unknown-linux-gnu") == 1,
            "Rust/Cargo executable targets a different native host",
        )
    else:
        require(len(lines) == 1, "unexpected extra lines in tool-version observation")
    return {
        "name": case["name"],
        "command": case["command"],
        "first_line": lines[0],
        "execution_file": output.name,
        "execution_sha256": sha256(raw),
        "original_merged_log_file": name,
        "original_merged_log_sha256": sha256(log),
        "original_merged_log_bytes": len(log),
        "exit_code": record["exit_code"],
        "elapsed_seconds": record["elapsed_seconds"],
        "stream_provenance": "original WNOWAIT owner merged stdout+stderr",
    }


def prepare_tools(root, evidence, identity):
    """Observe installed versions only; no build, resolver, update, or test."""
    started = time.monotonic()
    proof = {
        "status": "FAIL",
        "registered_tooling": TOOLING,
        "fixed_rustup_toolchain": os.environ["RUSTUP_TOOLCHAIN"],
        "registered_version_command_cap_seconds": TOOL_VERSION_CAP_SECONDS,
        "commands": TOOL_VERSION_COMMANDS,
        "observations": [],
        "timeouts": {},
        "build_executions": 0,
        "resolver_executions": 0,
        "test_executions": 0,
        "original_command_owner_unchanged": True,
    }
    owner = original_module(
        root / "scripts/hepta_ci_exec.py", "original_hooks_cli_version_command_owner"
    )
    try:
        for case in TOOL_VERSION_COMMANDS:
            cap = min(float(TOOL_VERSION_CAP_SECONDS), remaining_seconds() - 60)
            require(
                cap > 0,
                "no absolute whole-job budget for a bounded version observation",
            )
            proof["timeouts"][case["name"]] = cap
            exit_code = owner.run(
                evidence / ("version-" + case["name"] + ".json"),
                case["command"],
                minimum_tests=0,
                timeout_seconds=cap,
            )
            require(exit_code == 0, "original version command failed: " + case["name"])
            proof["observations"].append(
                verify_tool_observation(evidence, identity, case)
            )
        check_deadline()
        proof["status"] = "ALL_FOUR_FROZEN_TOOL_VERSIONS_OBSERVED"
    except Exception as error:
        proof["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        proof["phase_elapsed_seconds"] = time.monotonic() - started
        proof["whole_elapsed_seconds_at_result"] = (
            time.monotonic_ns() - JOB_START_NS
        ) / 1_000_000_000
        put(evidence / "tool-versions.json", proof)
    raw, _ = read_regular(evidence / "tool-versions.json", 1024 * 1024)
    return {
        "file": "tool-versions.json",
        "sha256": sha256(raw),
        "bytes": len(raw),
        "observations": proof["observations"],
    }


def execute(root, evidence, spec, identity, command, claim):
    junit = root / spec["junit_original_path"]
    require(
        not os.path.lexists(junit),
        "native JUnit must not exist before the original run",
    )
    before = source_snapshot(root)
    put(evidence / "source-before.json", before)
    exit_code = None
    try:
        tools_observed = prepare_tools(root, evidence, identity)
        timeout = min(float(NATIVE_CAP_SECONDS), remaining_seconds() - 60)
        require(
            math.isfinite(timeout) and timeout > 0,
            "whole-job budget has no bounded command/collection window",
        )
        put(
            evidence / "admitted-inputs.json",
            {
                "source": identity,
                "root_acceptance_sha256": ROOT_ACCEPTANCE_SHA256,
                "accepted_locks": spec["accepted_locks"],
                "whole_job_claim": claim,
                "tool_versions": tools_observed,
                "controls": spec["controls"],
                "command": command,
                "effective_native_command_timeout_seconds": timeout,
                "registered_native_command_cap_seconds": NATIVE_CAP_SECONDS,
                "automatic_retry": False,
                "old_scientific_budget_used": 0,
                "old_unpublished_native48_recovered": False,
                "additional_published_source_tests_qualified_by_this_roster": False,
            },
        )
        owner = original_module(
            root / "scripts/hepta_ci_exec.py", "original_hooks_cli_native_command_owner"
        )
        exit_code = owner.run(
            evidence / "controls.json",
            command,
            minimum_tests=EXACT_TESTS,
            timeout_seconds=timeout,
        )
    finally:
        after = source_snapshot(root)
        put(evidence / "source-after.json", after)
        require(
            after == before,
            "full source snapshot changed during the original native command",
        )
    raw, _ = read_regular(evidence / "controls.json", 1024 * 1024)
    record = json_value(raw)
    require(exit_code == 0, "the one original native command failed")
    verified = verify_original_log(
        evidence, raw, record, spec["controls"], identity, command
    )
    put(evidence / "original-log-exact-roster.json", verified)
    return {
        "status": "EXACT_48_COMMAND_OBSERVED_REQUIRES_NATIVE_JUNIT",
        "source": identity,
        "original_log": verified,
        "command_timeout_seconds": timeout,
        "tool_versions": tools_observed,
    }


def collect(root, evidence, spec, identity, command):
    admission_raw, _ = read_regular(evidence / "admitted-inputs.json", 1024 * 1024)
    admission = json_value(admission_raw)
    require(
        admission["source"] == identity
        and admission["command"] == command
        and admission["root_acceptance_sha256"] == ROOT_ACCEPTANCE_SHA256,
        "collection does not belong to this original admission",
    )
    tool_raw, _ = read_regular(evidence / "tool-versions.json", 1024 * 1024)
    tool_proof = json_value(tool_raw)
    require(
        sha256(tool_raw) == admission["tool_versions"]["sha256"]
        and len(tool_raw) == admission["tool_versions"]["bytes"]
        and tool_proof["status"] == "ALL_FOUR_FROZEN_TOOL_VERSIONS_OBSERVED"
        and tool_proof["registered_tooling"] == TOOLING
        and tool_proof["fixed_rustup_toolchain"] == "1.96.0"
        and tool_proof["commands"] == TOOL_VERSION_COMMANDS
        and tool_proof["observations"] == admission["tool_versions"]["observations"]
        and tool_proof["observations"]
        == [
            verify_tool_observation(evidence, identity, case)
            for case in TOOL_VERSION_COMMANDS
        ],
        "collection does not retain the original four fixed tool-version observations",
    )
    current = source_snapshot(root)
    put(evidence / "source-at-collection.json", current)
    before_raw, _ = read_regular(evidence / "source-before.json", 16 * 1024 * 1024)
    after_raw, _ = read_regular(evidence / "source-after.json", 16 * 1024 * 1024)
    require(
        json_value(before_raw) == json_value(after_raw) == current,
        "full source changed between admission, command, and collection",
    )
    execution_raw, _ = read_regular(evidence / "controls.json", 1024 * 1024)
    record = json_value(execution_raw)
    junit_original = root / spec["junit_original_path"]
    original_raw, _ = read_regular(junit_original)
    collector = original_module(
        root / "scripts/hepta_ci_junit.py", "original_hooks_cli_native_junit_owner"
    )
    output = evidence / "controls.junit.xml"
    exit_code = collector.collect(evidence / "controls.json", junit_original, output)
    require(
        exit_code == 0, "the original native JUnit collector rejected this observation"
    )
    raw, _ = read_regular(output)
    fresh_raw, _ = read_regular(junit_original)
    summary_raw, _ = read_regular(output.with_suffix(".summary.json"), 1024 * 1024)
    summary = json_value(summary_raw)
    require(
        raw == original_raw == fresh_raw
        and summary["status"] == "passed"
        and summary["junit_sha256"] == sha256(raw)
        and summary["junit_bytes"] == len(raw)
        and summary["source_sha"] == identity["head"]
        and summary["source_tree"] == identity["tree"]
        and summary["command"] == command
        and summary["execution_sha256"] == sha256(execution_raw)
        and summary["total_testcases"] == EXACT_TESTS
        and summary["failures"] == summary["errors"] == summary["skipped_in_xml"] == 0,
        "retained native JUnit does not match the exact original source execution",
    )
    log = verify_original_log(
        evidence, execution_raw, record, spec["controls"], identity, command
    )
    document = ET.fromstring(
        raw, parser=ET.XMLParser(target=collector.NoDoctypeTreeBuilder())
    )
    require(
        document.tag == "testsuites"
        and document.attrib.get("uuid") == log["nextest_run_id"],
        "JUnit UUID does not match the one original nextest run",
    )
    suites = list(document)
    require(
        len(suites) == 4
        and all(suite.tag == "testsuite" for suite in suites)
        and Counter(suite.attrib.get("name") for suite in suites)
        == Counter(BINARY_IDS),
        "native JUnit does not contain exactly the four registered binary suites",
    )
    cases = list(document.iter("testcase"))
    require(
        not any(
            node.tag
            in (
                "skipped",
                "failure",
                "error",
                "rerunFailure",
                "rerunError",
                "flakyFailure",
                "flakyError",
            )
            for node in document.iter()
        ),
        "native JUnit contains a skipped, retried, failed, or errored control",
    )
    actual = Counter(
        (case.attrib.get("classname"), case.attrib.get("name")) for case in cases
    )
    expected = Counter((row["binary_id"], row["name"]) for row in spec["controls"])
    require(
        len(cases) == EXACT_TESTS and actual == expected,
        "native JUnit does not contain each of the 48 exact binary-ID/name pairs once",
    )
    for suite in suites:
        require(
            len(list(suite.iter("testcase"))) == 12
            and all(
                case.attrib.get("classname") == suite.attrib["name"]
                for case in suite.iter("testcase")
            ),
            "JUnit suite/classname membership is inconsistent",
        )
    check_deadline()
    return {
        "status": "EXACT_48_NATIVE_CONTROLS_PASSED_REQUIRES_ROOT_REVIEW",
        "source": identity,
        "root_lock_acceptance_sha256": ROOT_ACCEPTANCE_SHA256,
        "junit_sha256": sha256(raw),
        "collector_summary_sha256": sha256(summary_raw),
        "original_log": log,
        "new_instance_count": 33,
        "retained_instance_count": 15,
        "tool_versions_sha256": sha256(tool_raw),
        "chrono_advisory_closed": False,
        "ordinary_locked_ci_qualified": False,
        "rmcp_or_fence_qualified_by_native48": False,
        "old_scientific_qualification_transferred": False,
        "adoption_qualified": False,
        "final_use_qualified": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("execute", "collect"))
    mode = parser.parse_args().mode
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    evidence = Path(os.environ["CHRONO_NATIVE_EVIDENCE"]).resolve(strict=True)
    require(
        not evidence.is_relative_to(root) and not root.is_relative_to(evidence),
        "native evidence must remain outside the source checkout",
    )
    started = time.monotonic()
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "schema": "hepta.chrono-hooks-cli-native-result.v2",
        "status": "FAIL",
        "mode": mode,
        "old_scope_reopened": False,
        "automatic_retry": False,
        "explicit_lock_update_executions": 0,
        "old_E1_E6_budget_used": 0,
        "budget_phase_timings_are_nested_not_summed": True,
        "ci_job_completion_and_queue_time_require_original_GitHub_readback": True,
    }
    try:
        claim = claim_deadline(evidence)
        spec, identity, command = load_inputs(root)
        if mode == "execute":
            result.update(execute(root, evidence, spec, identity, command, claim))
        else:
            result.update(collect(root, evidence, spec, identity, command))
        check_deadline()
    except Exception as error:
        result["status"] = "FAIL"
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        cpu_after = resource.getrusage(resource.RUSAGE_SELF)
        children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result["phase_elapsed_seconds"] = time.monotonic() - started
        result["self_cpu_seconds"] = (
            cpu_after.ru_utime
            + cpu_after.ru_stime
            - cpu_before.ru_utime
            - cpu_before.ru_stime
        )
        result["reaped_children_cpu_seconds"] = (
            children_after.ru_utime
            + children_after.ru_stime
            - children_before.ru_utime
            - children_before.ru_stime
        )
        result["whole_elapsed_seconds_at_result"] = (
            None
            if JOB_START_NS is None
            else (time.monotonic_ns() - JOB_START_NS) / 1_000_000_000
        )
        result["absolute_deadline_ns"] = DEADLINE_NS
        put(evidence / (mode + ".RESULT.json"), result)
        print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
