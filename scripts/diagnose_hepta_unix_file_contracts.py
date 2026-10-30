#!/usr/bin/env python3
"""Observe Unix file-sync and inherited-lock behavior using private fixtures.

This is a diagnostic observer, not a functional acceptance gate. It never opens
production state. Filesystem errno values are observations, not suppressed test
failures. The original Fleet and holdout tests must still run separately.
"""

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import signal
import stat
import sys
import tempfile
import time


class SetupFailed(Exception):
    pass


class Observer:
    def __init__(self):
        self.operations = []

    def call(self, operation, function, path=None):
        started = time.monotonic()
        record = {"operation": operation}
        if path is not None:
            record["path"] = str(path)
        try:
            value = function()
            record.update({"status": "ok", "result": value})
            return True, value
        except OSError as error:
            record.update({
                "status": "error", "error_type": type(error).__name__,
                "errno": error.errno, "message": str(error),
            })
            return False, None
        finally:
            record["seconds"] = time.monotonic() - started
            self.operations.append(record)

    def required(self, operation, function, path=None):
        ok, value = self.call(operation, function, path)
        if not ok:
            raise SetupFailed(operation)
        return value


def fd_state(fd):
    import fcntl

    info = os.fstat(fd)
    return {
        "device": info.st_dev, "inode": info.st_ino,
        "mode": oct(stat.S_IMODE(info.st_mode)), "size": info.st_size,
        "open_flags": fcntl.fcntl(fd, fcntl.F_GETFL),
        "close_on_exec": not os.get_inheritable(fd),
    }


def sync_observations(observer, label, fd, path):
    import fcntl

    observer.call(label + ": descriptor state", lambda: fd_state(fd), path)
    if sys.platform == "darwin" and hasattr(fcntl, "F_FULLFSYNC"):
        observer.call(
            label + ": F_FULLFSYNC", lambda: fcntl.fcntl(fd, fcntl.F_FULLFSYNC), path
        )
    else:
        observer.operations.append({
            "operation": label + ": F_FULLFSYNC", "path": str(path),
            "status": "not_applicable",
            "reason": "Requires Darwin and its Python fcntl.F_FULLFSYNC constant",
        })
    # This comparison is explicitly additional to the Rust1.96 Apple operation.
    # It is never used as a fallback to turn an F_FULLFSYNC error into success.
    observer.call(label + ": ordinary fsync comparison", lambda: os.fsync(fd), path)


def filesystem_observations(root, observer):
    source = root / "source-program"
    staging = root / "staging"
    bin_root = staging / "bin"
    destination = bin_root / "program"
    manifest = staging / "release.json"
    final = root / "published"
    payload = b"hepta private Unix contract fixture\n"
    open_fds = set()

    def open_fd(path, flags, mode=0o666):
        fd = observer.required("open descriptor", lambda: os.open(path, flags, mode), path)
        open_fds.add(fd)
        return fd

    def close_fd(fd):
        open_fds.remove(fd)
        observer.call("close descriptor", lambda: os.close(fd))

    def copy_bytes(input_fd, output_fd):
        total = 0
        while data := os.read(input_fd, 4096):
            while data:
                written = os.write(output_fd, data)
                if written == 0:
                    raise OSError(errno.EIO, "zero-byte write")
                total += written
                data = data[written:]
        return total

    result = {"status": "started", "continues_after_sync_errors_for_observation": True}
    try:
        observer.required("write owned source", lambda: source.write_bytes(payload), source)
        observer.required("chmod source 0555", lambda: source.chmod(0o555), source)
        observer.required("create staging", lambda: staging.mkdir(), staging)
        observer.required("create bin", lambda: bin_root.mkdir(), bin_root)
        input_fd = open_fd(source, os.O_RDONLY)
        output_fd = open_fd(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        observer.required("copy program bytes", lambda: copy_bytes(input_fd, output_fd), destination)
        observer.call("chmod copied program 0555", lambda: destination.chmod(0o555), destination)
        sync_observations(observer, "copied program retained writer", output_fd, destination)
        close_fd(output_fd)
        close_fd(input_fd)

        readonly_fd = open_fd(destination, os.O_RDONLY)
        sync_observations(observer, "copied program reopened reader comparison", readonly_fd, destination)
        close_fd(readonly_fd)

        manifest_fd = open_fd(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        observer.required("write manifest", lambda: os.write(manifest_fd, b"{}\n"), manifest)
        sync_observations(observer, "manifest retained writer", manifest_fd, manifest)
        close_fd(manifest_fd)
        observer.call("chmod manifest 0444", lambda: manifest.chmod(0o444), manifest)
        observer.call("chmod bin 0555", lambda: bin_root.chmod(0o555), bin_root)
        for label, path in (("readonly bin directory", bin_root), ("writable staging directory", staging)):
            directory_fd = open_fd(path, os.O_RDONLY)
            sync_observations(observer, label, directory_fd, path)
            close_fd(directory_fd)
        observer.call("chmod staging 0555", lambda: staging.chmod(0o555), staging)
        published, _ = observer.call("rename staging within same parent", lambda: os.rename(staging, final), final)
        parent_fd = open_fd(root, os.O_RDONLY)
        sync_observations(observer, "publication parent directory", parent_fd, root)
        close_fd(parent_fd)
        if published:
            observer.call(
                "verify published and source bytes",
                lambda: {
                    "published_matches": (final / "bin/program").read_bytes() == payload,
                    "source_matches": source.read_bytes() == payload,
                },
                final,
            )
        result["status"] = "observations_complete"
    except SetupFailed as error:
        result.update({"status": "setup_unavailable", "operation": str(error)})
    finally:
        for fd in list(open_fds):
            close_fd(fd)
    return result


def wait_child(pid, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            found, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return {"reaped": False, "error": "child status unavailable"}
        if found == pid:
            return {"reaped": True, "exit_code": os.waitstatus_to_exitcode(status)}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.01, remaining))


def lock_attempt(fd):
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        return {
            "outcome": "would_block" if error.errno in (errno.EAGAIN, errno.EACCES) else "error",
            "errno": error.errno, "message": str(error),
        }
    fcntl.flock(fd, fcntl.LOCK_UN)
    return {"outcome": "acquired_and_released"}


def inherited_lock_observations(root, timeout, observer):
    import fcntl

    result = {"status": "started", "timeout_seconds_per_wait": timeout, "cleanup_signals": []}
    path = root / "inherited-lock"
    descriptors = set()
    child = None
    status = None

    def close_fd(fd):
        if fd in descriptors:
            descriptors.remove(fd)
            os.close(fd)

    try:
        owner = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        descriptors.add(owner)
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result["owner_descriptor"] = fd_state(owner)
        ready_read, ready_write = os.pipe()
        release_read, release_write = os.pipe()
        descriptors.update((ready_read, ready_write, release_read, release_write))
        child = os.fork()
        if child == 0:
            # The child has a deadline even if its parent unexpectedly exits.
            code = 125
            try:
                os.close(ready_read)
                os.close(release_write)
                os.fstat(owner)
                os.write(ready_write, b"R")
                readable, _, _ = select.select([release_read], [], [], timeout)
                if readable and os.read(release_read, 1) == b"X":
                    code = 0
                else:
                    code = 124
                os.close(owner)
            except BaseException:
                code = 125
            finally:
                os._exit(code)

        result["child_pid"] = child
        close_fd(ready_write)
        close_fd(release_read)
        readable, _, _ = select.select([ready_read], [], [], timeout)
        result["ready_received"] = bool(readable and os.read(ready_read, 1) == b"R")
        if not result["ready_received"]:
            raise SetupFailed("child readiness")
        close_fd(owner)
        result["parent_owner_closed"] = True
        contender = os.open(path, os.O_RDWR)
        descriptors.add(contender)
        result["while_child_retains_description"] = lock_attempt(contender)
        close_fd(contender)
        os.write(release_write, b"X")
        close_fd(release_write)
        status = wait_child(child, timeout)
        result["status"] = "observations_complete"
    except (OSError, SetupFailed) as error:
        result.update({
            "status": "setup_unavailable", "error_type": type(error).__name__,
            "errno": getattr(error, "errno", None), "message": str(error),
        })
    finally:
        for fd in list(descriptors):
            observer.call("close parent fork descriptor", lambda fd=fd: close_fd(fd))
        if child is not None and child > 0 and status is None:
            status = wait_child(child, 0.5)
            for termination in (signal.SIGTERM, signal.SIGKILL):
                if status is not None:
                    break
                # This PID was created above and has not been reaped elsewhere.
                observer.call("terminate owned diagnostic child", lambda: os.kill(child, termination))
                result["cleanup_signals"].append(termination.name)
                status = wait_child(child, 1.0)
        result["child_status"] = status
        result["child_reaped"] = bool(status and status.get("reaped"))

    result["inherited_lock_observation_valid"] = bool(
        result.get("ready_received") and result.get("parent_owner_closed")
        and status and status.get("reaped") and status.get("exit_code") == 0
        and not result["cleanup_signals"]
    )
    if result["child_reaped"]:
        contender = os.open(path, os.O_RDWR)
        try:
            result["after_child_exit"] = lock_attempt(contender)
        finally:
            os.close(contender)
    return result


def make_fixture_removable(root):
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_symlink():
            path.chmod(0o700 if path.is_dir() else 0o600)
    root.chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; never overwritten")
    parser.add_argument("--work-parent", type=Path, help="Existing directory under which to create a private TempDir")
    parser.add_argument("--timeout-seconds", type=float, default=5.0, help="Each fork handshake/wait, in (0,10]")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if not 0 < args.timeout_seconds <= 10:
        parser.error("--timeout-seconds must be in (0,10]")
    observer = Observer()
    receipt = {
        "schema": "hepta.unix-file-contract-observation.v1",
        "utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv,
        "platform": platform.platform(), "python": platform.python_version(),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "pid": os.getpid(), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "diagnostic_only": True,
        "limits": [
            "Own temporary fixtures only; no production state or permissions changed.",
            "Filesystem errors are recorded individually; subsequent independent observations may continue.",
            "Ordinary fsync is a separately labeled comparison, not a fallback for F_FULLFSYNC.",
            "The fork experiment demonstrates this process's OS contract, not the cause of an earlier Rust test failure.",
            "A runner observation is not a Bazel sandbox observation unless executed in that same context.",
            "Original Fleet/holdout functional gates remain required.",
        ],
    }
    directory = None
    infrastructure_failure = False
    try:
        if os.name != "posix" or not hasattr(os, "fork"):
            receipt["status"] = "unsupported_platform"
        else:
            directory = tempfile.TemporaryDirectory(prefix="hepta-unix-contract-", dir=args.work_parent)
            root = Path(directory.name)
            receipt["fixture_root"] = {"requested": str(root), "canonical": str(root.resolve(strict=True))}
            receipt["filesystem"] = filesystem_observations(root, observer)
            receipt["fork_lock"] = inherited_lock_observations(root, args.timeout_seconds, observer)
            infrastructure_failure = not receipt["fork_lock"]["child_reaped"]
            receipt["status"] = "observations_complete"
    except Exception as error:
        infrastructure_failure = True
        receipt.update({"status": "observer_error", "error_type": type(error).__name__, "message": str(error)})
    finally:
        if directory is not None:
            ok, _ = observer.call("restore owned fixture cleanup modes", lambda: make_fixture_removable(Path(directory.name)))
            cleaned, _ = observer.call("remove owned fixture tree", directory.cleanup)
            infrastructure_failure |= not (ok and cleaned)
        receipt["operations"] = observer.operations
        receipt["infrastructure_failure"] = infrastructure_failure
        with args.output.open("x") as output:
            json.dump(receipt, output, indent=2)
            output.write("\n")
    print(json.dumps({"output": str(args.output), "status": receipt["status"], "infrastructure_failure": infrastructure_failure}))
    raise SystemExit(1 if infrastructure_failure else 0)


if __name__ == "__main__":
    main()
