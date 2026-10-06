"""Opt-in Linux compiled-cache mechanics; this file does not activate a CI lane.

Cache readiness never changes the native command result. No cache entry is
removed or rewritten here. Native source identity is checked by hepta_ci_exec.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import platform
import signal
import stat
import sys
import threading
import time

import hepta_ci_exec

CACHE_LIMIT = 2 * 1024**3
FREE_RESERVE = 6 * 1024**3
BUILD_SECONDS = 45 * 60
USABLE_JOB_SECONDS = 55 * 60
MAX_SCAN_ENTRIES = 100_000
QUIESCE_SECONDS = 120
COMPATIBILITY_FILES = (
    ".bazelversion", ".bazelrc", "MODULE.bazel", "MODULE.bazel.lock", "defs.bzl",
    "codex-rs/rust-toolchain.toml", ".github/scripts/run_bazel_with_buildbuddy.py",
    ".github/actions/setup-bazel-ci/action.yml",
    ".github/actions/prepare-bazel-ci/action.yml", ".github/actions/setup-ci/action.yml",
)


def free_bytes(path: Path) -> int:
    fs = os.statvfs(path)
    return fs.f_bavail * fs.f_frsize


class UnsafePath(ValueError):
    pass


DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def relative_directory(base_fd: int, parts: tuple[str, ...]):
    descriptor = os.dup(base_fd)
    try:
        for part in parts:
            if part in ("", ".", "..") or "/" in part:
                raise UnsafePath("unsafe relative directory component")
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def absolute_directory(path: Path):
    if not path.is_absolute():
        raise ValueError("directory must be absolute")
    root_fd = os.open("/", DIRECTORY_FLAGS)
    try:
        with relative_directory(root_fd, path.parts[1:]) as descriptor:
            yield descriptor
    finally:
        os.close(root_fd)


def regular_entries(base_fd: int, *, deadline_seconds: float,
                    maximum_entries: int, reject_special: bool = True):
    """No-follow, per-entry traversal rooted in a retained directory descriptor."""
    deadline = time.monotonic() + deadline_seconds
    pending = [()]
    entries = 0
    while pending:
        current = pending.pop()
        if len(current) > 64:
            raise ValueError("directory depth limit exceeded")
        with relative_directory(base_fd, current) as directory_fd:
            with os.scandir(directory_fd) as iterator:
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError("directory measurement deadline exceeded")
                    try:
                        entry = next(iterator)
                    except StopIteration:
                        break
                    entries += 1
                    if entries > maximum_entries:
                        raise ValueError("directory entry limit exceeded")
                    info = entry.stat(follow_symlinks=False)
                    if time.monotonic() >= deadline:
                        raise ValueError("directory measurement deadline exceeded")
                    relative = (*current, entry.name)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(relative)
                    elif stat.S_ISREG(info.st_mode):
                        yield relative, info
                    elif reject_special:
                        raise UnsafePath("directory contains a link or nonregular entry")


def regular_files(path: Path, *, deadline_seconds: float, maximum_entries: int,
                  reject_special: bool = True):
    if path.is_symlink():
        raise UnsafePath("root is not an ordinary directory")
    with absolute_directory(path) as descriptor:
        for parts, info in regular_entries(
            descriptor, deadline_seconds=deadline_seconds,
            maximum_entries=maximum_entries, reject_special=reject_special,
        ):
            yield path.joinpath(*parts), info


def cache_size(path: Path, *, deadline_seconds: float = 10) -> int:
    total = 0
    for _, info in regular_files(path, deadline_seconds=deadline_seconds,
                                 maximum_entries=MAX_SCAN_ENTRIES):
        total += info.st_size
        if total > CACHE_LIMIT:
            raise ValueError("cache exceeds persisted size cap")
    return total


def group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def wait_for_quiescence(pgid: int, *, seconds: float = QUIESCE_SECONDS) -> bool:
    if type(pgid) is not int or pgid <= 0:
        return False
    deadline = time.monotonic() + seconds
    while group_exists(pgid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def prepare(root: Path, directory: Path, env: dict[str, str]) -> dict:
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise ValueError("pilot is fixed to Linux x86_64")
    if env.get("BUILDBUDDY_API_KEY"):
        raise ValueError("pilot is endpoint-free only")
    image = env.get("ImageVersion")
    if not image:
        raise ValueError("runner image identity is required")
    try:
        started = float(env["HEPTA_PILOT_JOB_STARTED"])
    except (KeyError, ValueError) as error:
        raise ValueError("first-step job time anchor is required") from error
    now = time.monotonic()
    if not math.isfinite(started) or started > now or now >= started + BUILD_SECONDS:
        raise ValueError("job budget expired or time anchor is invalid")
    root = root.resolve()
    directory = directory.resolve()
    if directory.is_relative_to(root):
        raise ValueError("pilot outputs must be outside source")
    if directory.exists():
        raise ValueError("pilot directory must be fresh for this attempt")
    if free_bytes(directory.parent) < FREE_RESERVE:
        raise ValueError("insufficient initial free-space reserve")
    identity = hepta_ci_exec.identity()
    if identity["dirty"]:
        raise ValueError("pilot requires clean reviewed source")
    digest = hashlib.sha256(image.encode())
    for relative in COMPATIBILITY_FILES:
        digest.update(relative.encode() + b"\0" + (root / relative).read_bytes() + b"\0")
    prefix = "hepta-bazel-supervisor-measure-v1-linux-x64-" + digest.hexdigest() + "-"
    directory.mkdir()
    (directory / "cache").mkdir()
    return {
        "schema_version": 1, "directory": str(directory), "source_identity": identity,
        "job_started": started, "deadline": started + BUILD_SECONDS,
        "outer_deadline": started + USABLE_JOB_SECONDS,
        "cache_key": prefix + identity["tree"], "restore_prefix": prefix,
        "cache_limit_bytes": CACHE_LIMIT, "free_reserve_bytes": FREE_RESERVE,
    }


def native_command(root: Path, directory: Path) -> list[str]:
    return [
        "python3", str(root / ".github/scripts/run_bazel_with_buildbuddy.py"),
        "--batch", f"--output_user_root={directory / 'user-root'}",
        f"--output_base={directory / 'output'}", "test", "--config=ci-linux",
        f"--disk_cache={directory / 'cache'}", "--nocache_test_results",
        f"--build_event_json_file={directory / 'build-events.json'}",
        f"--execution_log_compact_file={directory / 'execution-log.bin'}",
        f"--profile={directory / 'profile.gz'}",
        "--test_tag_filters=-argument-comment-lint", "--test_verbose_timeout_warnings",
        f"--build_metadata=COMMIT_SHA={os.environ.get('TESTED_SHA', '')}",
        "--", "//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test",
    ]


def save_readiness(directory: Path, *, quiescent: bool, remaining_seconds: float) -> dict:
    result = {"save_ready": False, "quiescent": quiescent}
    if not quiescent:
        return {**result, "reason": "writer lifetime is uncertain"}
    if remaining_seconds < 8 * 60:
        return {**result, "reason": "insufficient reserved save time"}
    if free_bytes(directory) < FREE_RESERVE:
        return {**result, "reason": "insufficient free-space reserve"}
    try:
        size = cache_size(directory / "cache")
    except (OSError, ValueError) as error:
        return {**result, "reason": str(error)}
    if size == 0:
        return {**result, "reason": "empty cache"}
    return {**result, "save_ready": True, "cache_bytes": size, "reason": "bounded cache ready"}


def retain_diagnostics(directory: Path) -> dict:
    """Read bounded logs through no-follow dirfds; never restart/query Bazel."""
    report = {"files": [], "limited": False, "unsafe": False, "errors": []}
    try:
        with absolute_directory(directory) as root_fd:
            # A pre-existing destination is ambiguous; never follow/reuse it.
            os.mkdir("diagnostics", mode=0o700, dir_fd=root_fd)
            with relative_directory(root_fd, ("diagnostics",)) as destination_fd:
                def write(name: str, data: bytes):
                    descriptor = os.open(
                        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                        0o600, dir_fd=destination_fd,
                    )
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(data)

                def capture(parts: tuple[str, ...], name: str, limit: int, *, tail: bool):
                    try:
                        with relative_directory(root_fd, parts[:-1]) as parent_fd:
                            descriptor = os.open(
                                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=parent_fd,
                            )
                        with os.fdopen(descriptor, "rb") as source:
                            info = os.fstat(source.fileno())
                            if not stat.S_ISREG(info.st_mode):
                                raise UnsafePath("diagnostic is not a regular file")
                            if not tail and info.st_size > limit:
                                report["limited"] = True
                                report["errors"].append(f"{name}: exceeds binary capture bound")
                                return
                            if tail and info.st_size > limit:
                                source.seek(-limit, os.SEEK_END)
                            data = source.read(limit)
                        write(name, data)
                        report["files"].append({
                            "source": "/".join(parts), "captured": name,
                            "original_bytes": info.st_size, "captured_bytes": len(data),
                            "tail_truncated": tail and info.st_size > limit,
                            "captured_sha256": hashlib.sha256(data).hexdigest(),
                        })
                    except (OSError, ValueError) as error:
                        report["errors"].append(f"{name}: {error}")
                        if not isinstance(error, FileNotFoundError):
                            report["unsafe"] = True

                capture(("build-events.json",), "build-events.tail.jsonl", 2 * 1024**2, tail=True)
                capture(("execution-log.bin",), "execution-log.bin", 8 * 1024**2, tail=False)
                capture(("profile.gz",), "profile.gz", 2 * 1024**2, tail=False)
                newest = []
                scan_deadline = time.monotonic() + 20
                prefix = ("output", "execroot", "_main", "bazel-out")
                try:
                    with relative_directory(root_fd, prefix) as bazel_out_fd:
                        with os.scandir(bazel_out_fd) as configurations:
                            for count, configuration in enumerate(configurations):
                                if count >= 32 or time.monotonic() >= scan_deadline:
                                    raise ValueError("diagnostic configuration scan bound exceeded")
                                if configuration.is_symlink():
                                    raise UnsafePath("symlinked Bazel configuration directory")
                                if not configuration.is_dir(follow_symlinks=False):
                                    continue
                                relative_root = (*prefix, configuration.name, "testlogs")
                                try:
                                    with relative_directory(root_fd, relative_root) as logs_fd:
                                        for relative, info in regular_entries(
                                            logs_fd, deadline_seconds=max(0, scan_deadline - time.monotonic()),
                                            maximum_entries=MAX_SCAN_ENTRIES,
                                        ):
                                            if relative[-1] != "test.log" and not (
                                                "test_attempts" in relative and relative[-1].endswith(".log")
                                            ):
                                                continue
                                            item = (info.st_mtime_ns, (*relative_root, *relative))
                                            if len(newest) < 64:
                                                heapq.heappush(newest, item)
                                            else:
                                                heapq.heappushpop(newest, item)
                                                report["limited"] = True
                                except FileNotFoundError:
                                    continue
                except (OSError, ValueError) as error:
                    report["limited"] = True
                    report["errors"].append(str(error))
                    if isinstance(error, OSError) and error.errno in (errno.ELOOP, errno.ENOTDIR):
                        report["unsafe"] = True
                    if isinstance(error, UnsafePath):
                        report["unsafe"] = True
                for index, (_, parts) in enumerate(sorted(newest, reverse=True)):
                    capture(parts, f"test-attempt-{index:02d}.tail.log", 64 * 1024, tail=True)
                write("index.json", (json.dumps(report, sort_keys=True) + "\n").encode())
    except (OSError, ValueError) as error:
        report["unsafe"] = True
        report["limited"] = True
        report["errors"].append(f"diagnostic directory rejected: {error}")
    return report


def run_native(root: Path, state: dict) -> tuple[int, dict]:
    """Return the original recorder result; readiness cannot turn failure green."""
    if hepta_ci_exec.identity() != state["source_identity"]:
        return 2, {"save_ready": False, "reason": "prepared source identity changed"}
    directory = Path(state["directory"])
    output = directory / "native.json"
    remaining = state["deadline"] - time.monotonic()
    initial_free = free_bytes(directory)
    if remaining <= 0 or initial_free < FREE_RESERVE:
        return 2, {"save_ready": False, "reason": "build deadline or free-space admission failed"}
    try:
        cache_size(directory / "cache")
    except (OSError, ValueError) as error:
        return 2, {"save_ready": False, "reason": f"restored cache rejected: {error}"}
    remaining = state["deadline"] - time.monotonic()
    if remaining <= 0 or free_bytes(directory) < FREE_RESERVE:
        return 2, {"save_ready": False, "reason": "budget expired during restored-cache validation"}
    cancellation = hepta_ci_exec.CommandCancellation()
    stop = threading.Event()
    low_space = threading.Event()
    minimum_free = [initial_free]

    def monitor():
        while not stop.wait(1):
            try:
                available = free_bytes(directory)
                minimum_free[0] = min(minimum_free[0], available)
                enough = available >= FREE_RESERVE
            except OSError:
                enough = False
            if not enough:
                low_space.set()
                cancellation.request(signal.SIGTERM, None)
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        code = hepta_ci_exec.run(
            output, native_command(root, directory), timeout_seconds=remaining,
            cancellation=cancellation, retain_process_group=True,
            deadline_monotonic=state["deadline"],
        )
    finally:
        stop.set()
        watcher.join()
    record = json.loads(output.read_text())
    quiescent = wait_for_quiescence(record.get("process_group_id", 0))
    diagnostics = retain_diagnostics(directory)
    # First-step55-minute usable window leaves five minutes outside our budget.
    ready = save_readiness(
        directory, quiescent=quiescent,
        remaining_seconds=state["outer_deadline"] - time.monotonic(),
    )
    if diagnostics["unsafe"]:
        ready = {"save_ready": False, "reason": "unsafe diagnostic path rejected", "quiescent": quiescent}
    if low_space.is_set():
        ready = {"save_ready": False, "reason": "free-space guard interrupted native work", "quiescent": quiescent}
    if record.get("before") != state["source_identity"] or record.get("after") != state["source_identity"]:
        ready = {"save_ready": False, "reason": "source identity changed or was not verified", "quiescent": quiescent}
    ready.update(
        native_exit_code=code, low_space_stop=low_space.is_set(),
        initial_free_bytes=initial_free, minimum_observed_free_bytes=minimum_free[0],
        diagnostic_files=len(diagnostics["files"]), diagnostics_limited=diagnostics["limited"],
    )
    ready["measured_save_eligibility"] = ready["save_ready"]
    ready["save_ready"] = False
    ready["measurement_only"] = True
    return code, ready


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "run"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    root = Path(hepta_ci_exec.git("rev-parse", "--show-toplevel")).resolve()
    state_file = args.directory / "pilot-state.json"
    result = {"save_ready": False}
    code = 2
    try:
        if args.phase == "prepare":
            result = prepare(root, args.directory, dict(os.environ))
            with state_file.open("x") as stream:
                json.dump(result, stream, sort_keys=True)
            result["cache_path"] = str(Path(result["directory"]) / "cache")
            code = 0
        else:
            state = json.loads(state_file.read_text())
            if Path(state["directory"]).resolve() != args.directory.resolve():
                raise ValueError("state directory mismatch")
            code, result = run_native(root, state)
            with (args.directory / "cache-readiness.json").open("x") as stream:
                json.dump(result, stream, sort_keys=True)
    except (OSError, ValueError, KeyError) as error:
        result = {"save_ready": False, "reason": str(error)}
    if args.github_output is not None:
        with args.github_output.open("a") as stream:
            for key in ("cache_key", "restore_prefix", "cache_path", "save_ready"):
                if key in result:
                    value = str(result[key]).lower() if isinstance(result[key], bool) else str(result[key])
                    if "\n" in value or "\r" in value:
                        raise ValueError("invalid GitHub output value")
                    stream.write(f"{key}={value}\n")
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
