#!/usr/bin/env python3
"""Bind one synthetic Root refusal test to its new source and compiled binary.

Preparation runs without Root. The Root phase accepts no command or state path:
it runs one fixed libtest name in a new private /run directory on the ephemeral
GitHub runner. No production registration, material or credential is supplied.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hepta_ci_exec import _leader_has_exited
from hepta_ci_exec import execute_logged
from hepta_ci_exec import identity

TEST = "deployment_issuer::paired::tests::paired_actual_root_service_refuses_configured_policy_without_minting"
SCHEMA = "hepta-paired-root-isolated-engineering-v1"
ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "scripts/hepta_ci_paired_root.py",
    "scripts/hepta_ci_exec.py",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/hepta-agentd/src/deployment_paired_tests.rs",
)
MAX_BINARY = 1024 * 1024 * 1024
TOTAL_SECONDS = 300


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path, bound):
    digest = hashlib.sha256()
    count = 0
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    )
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= bound,
            "bounded regular hash input required",
        )
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            require(count <= bound, "bounded evidence input exceeded")
            digest.update(chunk)
    return digest.hexdigest()


def read_bounded(path, bound, *, directory_fd=None, owner_uid=None, mode=None):
    """Authenticate and read one opened original, never re-resolve its path."""
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=directory_fd,
    )
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= bound,
            "bounded regular evidence file required",
        )
        if owner_uid is not None:
            require(before.st_uid == owner_uid, "original evidence owner required")
        if mode is not None:
            require(
                stat.S_IMODE(before.st_mode) == mode, "original evidence mode required"
            )
        raw = stream.read(bound + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) == before.st_size and len(raw) <= bound, "evidence size changed")
    fields = (
        "st_dev",
        "st_ino",
        "st_uid",
        "st_mode",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    require(
        all(getattr(before, name) == getattr(after, name) for name in fields),
        "opened evidence changed during read",
    )
    return raw


def write_raw(path, raw, *, directory_fd=None, mode=0o600):
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory_fd,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        # This changes only the inode this invocation just created, even when
        # the unprivileged evidence directory concurrently renames its entry.
        os.fchmod(stream.fileno(), mode)
        os.fsync(stream.fileno())


def write_json(path, value, *, directory_fd=None, mode=0o600):
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    write_raw(path, raw, directory_fd=directory_fd, mode=mode)


def context(environment):
    require(sys.platform == "linux", "Linux pidfd ownership is required")
    require(environment.get("GITHUB_ACTIONS") == "true", "GitHub job required")
    require(
        environment.get("RUNNER_ENVIRONMENT") == "github-hosted",
        "ephemeral hosted runner required",
    )
    require(environment.get("RUNNER_OS") == "Linux", "Linux hosted runner required")
    require(environment.get("HEPTA_CI_LANE") == "source-head", "source-head gate only")
    source = environment.get("SOURCE_SHA", "")
    require(re.fullmatch(r"[0-9a-f]{40}", source), "exact source SHA required")
    require(environment.get("TESTED_SHA") == source, "tested/source mismatch")
    run_id, attempt = (
        environment.get("GITHUB_RUN_ID", ""),
        environment.get("GITHUB_RUN_ATTEMPT", ""),
    )
    require(re.fullmatch(r"[1-9][0-9]{0,19}", run_id), "exact run ID required")
    require(re.fullmatch(r"[1-9][0-9]{0,5}", attempt), "exact attempt required")
    return {"source": source, "run_id": run_id, "attempt": attempt}


def remaining(deadline_ns, reserve_seconds=0):
    seconds = (deadline_ns - time.monotonic_ns()) / 1_000_000_000 - reserve_seconds
    require(seconds > 0, "shared absolute engineering deadline expired")
    return seconds


def capture(command, path, deadline_ns, environment, rows, bound=16 * 1024 * 1024):
    """Keep exact stdout separate from the enclosing command's raw stderr.

    The existing outer CI owner holds this preparation process group. This
    function only signals its own unreaped direct child, never a numeric group.
    """
    started = time.monotonic_ns()
    row = {"command": command, "stdout": path.name, "status": "running"}
    rows.append(row)
    child = subprocess.Popen(
        command, cwd=ROOT / "codex-rs", env=environment, stdout=subprocess.PIPE
    )
    assert child.stdout is not None
    count = 0
    digest = hashlib.sha256()
    complete = False
    try:
        os.set_blocking(child.stdout.fileno(), False)
        with path.open("xb") as output, selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            eof = False
            while not (eof and _leader_has_exited(child)):
                duration = remaining(deadline_ns, 45)
                for _, _ in selector.select(min(0.05, duration)):
                    chunk = os.read(child.stdout.fileno(), 65536)
                    if not chunk:
                        eof = True
                        selector.unregister(child.stdout)
                        break
                    require(count + len(chunk) <= bound, "build stdout bound exceeded")
                    output.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
            output.flush()
            os.fsync(output.fileno())
            complete = True
    finally:
        _leader_has_exited(child)
        if not complete:
            child.kill()
        child.stdout.close()
        code = child.wait(timeout=1)
        row.update(
            returncode=code,
            stdout_bytes=count,
            elapsed_ns=time.monotonic_ns() - started,
        )
        row["status"] = "completed" if complete else "failed"
    require(code == 0, "build identity command failed")
    raw = read_bounded(path, bound, owner_uid=os.getuid())
    row["stdout_sha256"] = digest.hexdigest()
    require(
        len(raw) == count and hashlib.sha256(raw).hexdigest() == row["stdout_sha256"],
        "captured build stdout changed",
    )
    return raw


def binary_from_metadata(metadata, cargo, root):
    binaries = metadata.get("rust-binaries", {})
    require(
        set(binaries) == {"codex-hepta-agentd"},
        "exactly the Agentd libtest binary is required",
    )
    binary = binaries["codex-hepta-agentd"]
    packages = [
        p for p in cargo.get("packages", []) if p.get("name") == "codex-hepta-agentd"
    ]
    require(len(packages) == 1, "exact Agentd package identity required")
    package = packages[0]
    require(
        Path(package["manifest_path"]).resolve()
        == root / "codex-rs/hepta-agentd/Cargo.toml",
        "foreign package source",
    )
    require(binary.get("package-id") == package["id"], "binary package mismatch")
    require(
        binary.get("binary-id") == "codex-hepta-agentd"
        and binary.get("binary-name") == "codex_hepta_agentd"
        and binary.get("kind") == "lib",
        "wrong binary kind",
    )
    target = Path(cargo["target_directory"]).resolve()
    path = Path(binary["binary-path"])
    require(
        path.is_absolute() and path.resolve() == path and path.is_relative_to(target),
        "binary outside original target",
    )
    metadata_stat = path.stat()
    require(
        stat.S_ISREG(metadata_stat.st_mode) and 0 < metadata_stat.st_size <= MAX_BINARY,
        "invalid binary file",
    )
    return path


def prepare(output):
    require(os.geteuid() != 0, "compilation must remain non-Root")
    os.chdir(ROOT)
    ctx = context(os.environ)
    before = identity()
    require(
        not before["dirty"] and before["commit"] == ctx["source"],
        "clean exact source required",
    )
    require(
        output.is_absolute()
        and output.resolve() == output
        and not output.is_relative_to(ROOT),
        "evidence must be outside checkout",
    )
    output.mkdir(mode=0o700)
    deadline = time.monotonic_ns() + TOTAL_SECONDS * 1_000_000_000
    rows = []
    record = {
        "schema": SCHEMA,
        "context": ctx,
        "source_identity": before,
        "deadline_monotonic_ns": deadline,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "test": TEST,
        "build_commands": rows,
        "production_authority": False,
    }
    try:
        require(
            tomllib is not None,
            "the Ubuntu 24.04 Root gate requires Python 3.11 or later",
        )
        toolchain = tomllib.loads((ROOT / "codex-rs/rust-toolchain.toml").read_text())
        require(
            toolchain["toolchain"]["channel"] == "1.96.0",
            "reviewed Rust 1.96 source required",
        )
        environment = os.environ.copy()
        require(
            not any(
                environment.get(key)
                for key in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER")
            ),
            "ambient compiler wrappers are not part of this gate",
        )
        environment["RUSTUP_TOOLCHAIN"] = "1.96.0"
        environment["CARGO_NET_OFFLINE"] = "true"
        rustc = Path(
            capture(
                ["rustup", "which", "--toolchain", "1.96.0", "rustc"],
                output / "rustc-path.stdout",
                deadline,
                environment,
                rows,
                4096,
            )
            .decode()
            .strip()
        )
        environment["RUSTC"] = str(rustc)
        version = capture(
            [str(rustc), "--version", "--verbose"],
            output / "rustc-version.stdout",
            deadline,
            environment,
            rows,
            16384,
        ).decode()
        require("\nrelease: 1.96.0\n" in version, "compiler release differs")
        nextest = capture(
            ["cargo", "nextest", "--version"],
            output / "nextest-version.stdout",
            deadline,
            environment,
            rows,
            16384,
        ).decode()
        require(
            nextest.startswith("cargo-nextest 0.9.103 ")
            or nextest.strip() == "cargo-nextest 0.9.103",
            "pinned nextest version required",
        )
        cargo_raw = capture(
            [
                "cargo",
                "metadata",
                "--no-deps",
                "--format-version=1",
                "--locked",
                "--offline",
            ],
            output / "cargo-metadata.json",
            deadline,
            environment,
            rows,
        )
        binaries_raw = capture(
            [
                "cargo",
                "nextest",
                "list",
                "--locked",
                "--offline",
                "-p",
                "codex-hepta-agentd",
                "--lib",
                "--cargo-metadata",
                str(output / "cargo-metadata.json"),
                "--list-type",
                "binaries-only",
                "--message-format",
                "json",
            ],
            output / "binaries-metadata.json",
            deadline,
            environment,
            rows,
        )
        binary = binary_from_metadata(
            json.loads(binaries_raw), json.loads(cargo_raw), ROOT
        )
        record.update(
            binary={
                "path": str(binary),
                "bytes": binary.stat().st_size,
                "sha256": sha256(binary, MAX_BINARY),
            },
            compiler={
                "path": str(rustc),
                "sha256": sha256(rustc, MAX_BINARY),
                "verbose": version,
            },
            files={p: sha256(ROOT / p, 1024 * 1024) for p in SOURCE_FILES},
        )
        require(identity() == before, "source changed during preparation")
        remaining(deadline, 30)
        record.update(status="prepared", runner_uid=os.getuid(), runner_gid=os.getgid())
        write_json(output / "BUILD.json", record)
    finally:
        write_json(output / "BUILD_ATTEMPT.json", record)


def one_test_passed(raw):
    """Require the original libtest name and one terminal, non-ignored result."""
    text = raw.decode("utf-8", errors="strict")
    require(
        re.findall(r"^running (\d+) tests?\s*$", text, re.MULTILINE) == ["1"],
        "exactly one original libtest invocation required",
    )
    named = re.findall(r"^test (\S+) \.\.\. (\S+)\s*$", text, re.MULTILINE)
    summaries = re.findall(
        r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;[^\n]*$",
        text,
        re.MULTILINE,
    )
    require(named == [(TEST, "ok")], "exact named Root control did not pass once")
    require(
        len(summaries) == 1 and summaries[0][:5] == ("ok", "1", "0", "0", "0"),
        "Root control must run once with zero ignored tests",
    )


def copy_binary(source, target, expected, deadline):
    digest = hashlib.sha256()
    count = 0
    descriptor = os.open(
        source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    )
    with os.fdopen(descriptor, "rb") as reader, target.open("xb") as writer:
        info = os.fstat(reader.fileno())
        require(
            stat.S_ISREG(info.st_mode) and info.st_size == expected["bytes"],
            "binary size/type changed",
        )
        while True:
            remaining(deadline, 10)
            chunk = reader.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            require(count <= MAX_BINARY, "binary bound exceeded")
            digest.update(chunk)
            writer.write(chunk)
        writer.flush()
        os.fchmod(writer.fileno(), 0o500)
        os.fsync(writer.fileno())
    require(
        count == expected["bytes"] and digest.hexdigest() == expected["sha256"],
        "compiled binary changed",
    )


def private_identity(path):
    info = path.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) == 0o700,
        "private Root directory required",
    )
    return info.st_dev, info.st_ino


def run_root(args):
    require(
        sys.platform == "linux" and os.getuid() == 0 and os.geteuid() == 0,
        "actual Root Linux process required",
    )
    bundle = args.output
    require(
        bundle.is_absolute()
        and bundle.resolve() == bundle
        and not bundle.is_relative_to(ROOT),
        "original evidence path required",
    )
    directory_fd = os.open(
        bundle, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        info = os.fstat(directory_fd)
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid != 0
            and stat.S_IMODE(info.st_mode) == 0o700,
            "original non-Root evidence directory required",
        )
        return run_root_held(args, directory_fd, info.st_uid)
    finally:
        os.close(directory_fd)


def run_root_held(args, directory_fd, evidence_uid):
    started_ns = time.monotonic_ns()
    build_raw = read_bounded(
        "BUILD.json",
        1024 * 1024,
        directory_fd=directory_fd,
        owner_uid=evidence_uid,
        mode=0o600,
    )
    require(
        hashlib.sha256(build_raw).hexdigest() == args.manifest_sha256,
        "build manifest changed",
    )
    build = json.loads(build_raw)
    require(
        build["schema"] == SCHEMA
        and build["status"] == "prepared"
        and build["test"] == TEST
        and build["production_authority"] is False,
        "wrong prepared gate",
    )
    require(
        build["context"]
        == {"source": args.source, "run_id": args.run_id, "attempt": args.run_attempt},
        "wrong source/run identity",
    )
    require(
        build["source_identity"]["commit"] == args.source
        and build["source_identity"]["dirty"] is False,
        "prepared source identity is not clean/exact",
    )
    require(
        build["boot_id"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "build/runtime host lifetime differs",
    )
    require(
        set(build["files"]) == set(SOURCE_FILES), "unexpected source identity inputs"
    )
    require(
        all(
            sha256(ROOT / p, 1024 * 1024) == value
            for p, value in build["files"].items()
        ),
        "source input changed",
    )
    require(
        build["runner_uid"] == evidence_uid, "original non-Root evidence owner required"
    )
    deadline = build["deadline_monotonic_ns"]
    require(
        type(deadline) is int and 0 < remaining(deadline) <= TOTAL_SECONDS,
        "invalid shared deadline",
    )
    # Narrow the original deadline; never start a fresh additional budget.
    deadline = min(deadline, time.monotonic_ns() + 35_000_000_000)
    run = Path("/run")
    info = run.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == 0
        and not info.st_mode & 0o022
        and run.resolve() == run,
        "protected /run ancestor required",
    )
    root_info = Path("/").stat()
    require(
        root_info.st_uid == 0 and not root_info.st_mode & 0o022,
        "protected filesystem ancestor required",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", args.source)
        and re.fullmatch(r"[1-9][0-9]{0,19}", args.run_id)
        and re.fullmatch(r"[1-9][0-9]{0,5}", args.run_attempt),
        "invalid fixed test identity",
    )
    parent = run / f"hepta-paired-root-ci-{args.run_id}-{args.run_attempt}"
    os.umask(0o077)
    attempt = {
        "schema": SCHEMA,
        "source_identity": build["source_identity"],
        "context": build["context"],
        "test": TEST,
        "parent": str(parent),
        "deadline_monotonic_ns": deadline,
        "original_build_deadline_monotonic_ns": build["deadline_monotonic_ns"],
        "started_monotonic_ns": started_ns,
        "build_manifest_sha256": args.manifest_sha256,
        "binary": build["binary"],
        "status": "running",
        "production_authority": False,
    }
    write_json("ROOT_ATTEMPT.json", attempt, directory_fd=directory_fd, mode=0o644)
    original_parent = None
    created = False
    execution = None
    dispatched = False
    cancellation = []
    record = dict(attempt)
    log = parent / "libtest.stdout"
    raw_log = None

    def cancel_child_wait(signum, _frame):
        # Keep the original owner alive through its <=20s child deadline and
        # final signal/reap. A cancelled gate can never publish success.
        if not cancellation:
            cancellation.append(signum)

    try:
        parent.mkdir(mode=0o700)
        created = True
        original_parent = private_identity(parent)
        binary = parent / "original-libtest"
        copy_binary(Path(build["binary"]["path"]), binary, build["binary"], deadline)
        state = parent / "state"
        state.mkdir(mode=0o700)
        private_identity(state)
        os.environ.clear()
        os.environ.update(
            PATH="/usr/bin:/bin",
            RUST_MIN_STACK="8388608",
            HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=str(state),
        )
        command = [
            str(binary),
            "--exact",
            TEST,
            "--ignored",
            "--nocapture",
            "--test-threads=1",
        ]
        timeout = min(20, remaining(deadline, 10))
        signal.signal(signal.SIGINT, cancel_child_wait)
        signal.signal(signal.SIGTERM, cancel_child_wait)
        record["command"] = command
        record["test_started_monotonic_ns"] = time.monotonic_ns()
        dispatched = True
        execution = execute_logged(
            command, log, maximum_bytes=4 * 1024 * 1024, timeout_seconds=timeout
        )
        record["execution"] = execution
        record["test_finished_monotonic_ns"] = time.monotonic_ns()
        require(not cancellation, "Root control wait was cancelled")
        require(
            execution["returncode"] == 0
            and not execution["timed_out"]
            and not execution["output_limit_exceeded"],
            "Root control failed or exceeded bounds",
        )
        raw_log = read_bounded(log, 4 * 1024 * 1024, owner_uid=0, mode=0o600)
        require(
            len(raw_log) == execution["log_bytes"]
            and hashlib.sha256(raw_log).hexdigest() == execution["log_sha256"],
            "original captured Root stdout changed",
        )
        one_test_passed(raw_log)
        record["private_binary_sha256"] = sha256(binary, MAX_BINARY)
        require(
            record["private_binary_sha256"] == build["binary"]["sha256"],
            "tested binary changed",
        )
        record["actual_tests"] = {
            "names": [TEST],
            "passed": 1,
            "failed": 0,
            "ignored": 0,
        }
        record["status"] = "passed"
    except BaseException as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        signal.signal(signal.SIGINT, cancel_child_wait)
        signal.signal(signal.SIGTERM, cancel_child_wait)
        if execution is not None:
            try:
                if raw_log is None:
                    raw_log = read_bounded(
                        log, 4 * 1024 * 1024, owner_uid=0, mode=0o600
                    )
                require(
                    len(raw_log) == execution["log_bytes"]
                    and hashlib.sha256(raw_log).hexdigest() == execution["log_sha256"],
                    "original captured Root stdout changed",
                )
                write_raw(
                    "root-libtest.stdout",
                    raw_log,
                    directory_fd=directory_fd,
                    mode=0o644,
                )
            except BaseException as error:
                record.update(
                    status="failed", evidence_error=f"{type(error).__name__}: {error}"
                )
        # The existing execution owner has either reaped the exact child or
        # raised with uncertain cleanup. Never remove live/unknown test state.
        try:
            if created:
                require(
                    not dispatched or execution is not None,
                    "test ownership unresolved; private state retained",
                )
                require(
                    private_identity(parent) == original_parent,
                    "Root parent identity changed",
                )
                require(
                    shutil.rmtree.avoids_symlink_attacks,
                    "safe directory cleanup unavailable",
                )
                shutil.rmtree(parent)
                require(not parent.exists(), "Root state remains")
                record["cleanup"] = "terminal_and_removed"
            else:
                record["cleanup"] = "not_created"
        except BaseException as error:
            record.update(
                status="failed",
                cleanup="unknown_or_refused",
                cleanup_error=f"{type(error).__name__}: {error}",
            )
        record["finished_monotonic_ns"] = time.monotonic_ns()
        if cancellation:
            record.update(status="failed", cancelled_by_signal=cancellation[0])
        if record["finished_monotonic_ns"] >= deadline:
            record.update(status="failed", deadline_exceeded=True)
        write_json("ROOT_RESULT.json", record, directory_fd=directory_fd, mode=0o644)
        print(json.dumps(record, sort_keys=True), flush=True)
    return 0 if record["status"] == "passed" and not cancellation else 1


def collect(output):
    """Verify this job's original Root evidence without executing/reprinting it."""
    require(os.geteuid() != 0, "collection must remain non-Root")
    require(
        output.is_absolute()
        and output.resolve() == output
        and not output.is_relative_to(ROOT),
        "original evidence path required",
    )
    directory_fd = os.open(
        output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        info = os.fstat(directory_fd)
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            "original collection directory required",
        )
        return collect_held(directory_fd)
    finally:
        os.close(directory_fd)


def collect_held(directory_fd):
    result_raw = read_bounded(
        "ROOT_RESULT.json",
        1024 * 1024,
        directory_fd=directory_fd,
        owner_uid=0,
        mode=0o644,
    )
    build_raw = read_bounded(
        "BUILD.json",
        1024 * 1024,
        directory_fd=directory_fd,
        owner_uid=os.getuid(),
        mode=0o600,
    )
    result = json.loads(result_raw)
    build = json.loads(build_raw)
    os.chdir(ROOT)
    current = identity()
    ctx = context(os.environ)
    require(
        current == build["source_identity"] and build["context"] == ctx,
        "source changed after original build",
    )
    require(
        build["boot_id"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "build/collection boot differs",
    )
    remaining(build["deadline_monotonic_ns"])
    require(
        result["schema"] == SCHEMA
        and result["status"] == "passed"
        and result["cleanup"] == "terminal_and_removed"
        and result["production_authority"] is False,
        "original Root test or cleanup did not pass",
    )
    require(
        result["source_identity"] == current
        and result["context"] == ctx
        and result["binary"] == build["binary"],
        "Root execution source/binary differs",
    )
    require(
        result["build_manifest_sha256"] == hashlib.sha256(build_raw).hexdigest(),
        "original prepared manifest changed",
    )
    require(
        result["original_build_deadline_monotonic_ns"]
        == build["deadline_monotonic_ns"],
        "Root used another deadline",
    )
    parent = Path("/run") / f"hepta-paired-root-ci-{ctx['run_id']}-{ctx['attempt']}"
    require(
        result["parent"] == str(parent) and not parent.exists(),
        "original Root state not removed",
    )
    expected_command = [
        str(parent / "original-libtest"),
        "--exact",
        TEST,
        "--ignored",
        "--nocapture",
        "--test-threads=1",
    ]
    require(
        result["command"] == expected_command
        and result["actual_tests"]
        == {"names": [TEST], "passed": 1, "failed": 0, "ignored": 0},
        "wrong original Root test command/count",
    )
    require(
        result["started_monotonic_ns"]
        <= result["test_started_monotonic_ns"]
        <= result["test_finished_monotonic_ns"]
        <= result["finished_monotonic_ns"]
        < result["deadline_monotonic_ns"]
        <= build["deadline_monotonic_ns"],
        "Root timing/deadline identity differs",
    )
    log_raw = read_bounded(
        "root-libtest.stdout",
        4 * 1024 * 1024,
        directory_fd=directory_fd,
        owner_uid=0,
        mode=0o644,
    )
    execution = result["execution"]
    require(
        execution["returncode"] == 0
        and execution["timed_out"] is False
        and execution["output_limit_exceeded"] is False,
        "Root child not successful/terminal",
    )
    require(
        len(log_raw) == execution["log_bytes"]
        and hashlib.sha256(log_raw).hexdigest() == execution["log_sha256"],
        "original Root stdout changed",
    )
    one_test_passed(log_raw)
    require(identity() == current, "source changed during collection")
    remaining(build["deadline_monotonic_ns"])
    receipt = {
        "schema": SCHEMA,
        "phase": "collection_only",
        "status": "verified_original_evidence",
        "source_identity": current,
        "root_result_sha256": hashlib.sha256(result_raw).hexdigest(),
        "root_log_sha256": execution["log_sha256"],
        "new_tests_executed": 0,
        "production_authority": False,
    }
    write_json("COLLECTED.json", receipt, directory_fd=directory_fd)
    # Do not replay the original PASS lines into another execution counter.
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "run-root", "collect"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--source")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt")
    args = parser.parse_args()

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt("Root engineering gate interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        if args.phase == "prepare":
            prepare(args.output)
            return 0
        if args.phase == "collect":
            return collect(args.output)
        return run_root(args)
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as error:
        print(f"paired Root engineering gate refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
