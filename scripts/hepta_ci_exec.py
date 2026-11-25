"""Run one real CI command and retain its exact Git identity and exit status.

This is an execution record, not a release/learning qualification. An absent,
running, rejected or failed record must never be interpreted as a passing test.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import hashlib
import math
import selectors
import signal
import uuid
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def identity() -> dict:
    metadata = git("cat-file", "-p", "HEAD").split("\n\n", 1)[0].splitlines()
    return {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "parents": [line[7:] for line in metadata if line.startswith("parent ")],
        "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
    }


def observed_test_counts(text: str) -> tuple[int, int]:
    """Parse terminal runner summaries, never compile messages or ignored tests.

    Output is diagnostic evidence of the named command, not authentication of an
    arbitrary command's claims. A nextest summary supersedes nested libtest text.
    """
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    nextest = re.findall(r"Summary[^\n]*?\d+ tests? run: ([^\n]+)", text)
    if nextest:
        summary = nextest[-1]
        passed = re.search(r"(\d+) passed", summary)
        failed = sum(
            int(value)
            for value in re.findall(r"(\d+) (?:failed|timed out|leaked)", summary)
        )
        return int(passed[1]) if passed else 0, failed
    passed = failed = 0
    for match in re.finditer(
        r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed;", text
    ):
        passed += int(match[1])
        failed += int(match[2])
    for match in re.finditer(
        r"Ran (\d+) tests? in [^\n]+\n\s*\n?(OK|FAILED)(?: \(([^\n]*)\))?(?:\n|$)", text
    ):
        total = int(match[1])
        fields = dict(
            (key.strip(), int(value))
            for key, value in re.findall(r"([a-z ]+)=(\d+)", match[3] or "")
        )
        failures = sum(
            fields.get(key, 0) for key in ("failures", "errors", "unexpected successes")
        )
        failed += failures or (1 if match[2] == "FAILED" else 0)
        excluded = failures + sum(
            fields.get(key, 0) for key in ("skipped", "expected failures")
        )
        passed += max(0, total - excluded)
    return passed, failed


def _leader_has_exited(process) -> bool:
    """Observe our direct child while retaining its PID and process-group ID."""
    if process.returncode is not None:
        raise ChildProcessError("CI command leader was already reaped")
    while True:
        try:
            status = os.waitid(
                os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
            )
            break
        except InterruptedError:
            continue
    if status is None:
        return False
    if status.si_pid != process.pid or status.si_code not in (
        os.CLD_EXITED,
        os.CLD_KILLED,
        os.CLD_DUMPED,
    ):
        raise RuntimeError("Unexpected CI command wait status")
    return True


def _darwin_exited_leader_only(process) -> bool:
    """Distinguish macOS's zombie-only EPERM from a live permission failure.

    Darwin's group signal can ignore zombies and report EPERM for our reserved
    leader. The system libproc census includes live and zombie group members.
    Exactly our one PID in a two-PID buffer proves a complete singleton census;
    zero, overflow, foreign PIDs, errors, or a live leader never waive EPERM.
    No discovered PID is signalled, and no dependency or permission is added.
    """
    if sys.platform != "darwin":
        return False
    try:
        if not _leader_has_exited(process):
            return False
        import ctypes

        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        census = library.proc_listpids
        census.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        census.restype = ctypes.c_int
        members = (ctypes.c_int * 2)()
        ctypes.set_errno(0)
        size = census(2, process.pid, members, ctypes.sizeof(members))
        return (
            size == ctypes.sizeof(ctypes.c_int)
            and members[0] == process.pid
            and ctypes.get_errno() == 0
        )
    except (OSError, AttributeError, ValueError):
        return False


def execute_logged(
    command: list[str],
    log: Path,
    *,
    maximum_bytes: int = 64 * 1024 * 1024,
    timeout_seconds: float = 3600,
) -> dict:
    """Bound a POSIX command group, retain raw output, and reap its direct child.

    EOF is not process completion; parent exit is not pipe completion. The caller
    must be the sole reaper. WNOWAIT reserves the leader until the last group
    signal on success and failure. Escaped sessions require an external sandbox
    and are not claimed to be terminated. The final reap has one extra second;
    refusal or a missing terminal status remains failed, without a signal retry.
    OS spawn, signal and filesystem operations are not hard real time.
    """
    if (
        not command
        or type(maximum_bytes) is not int
        or maximum_bytes <= 0
        or type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError(
            "command output and deadline bounds must be positive and finite"
        )
    if os.name != "posix" or not all(
        hasattr(os, name)
        for name in (
            "waitid",
            "P_PID",
            "WEXITED",
            "WNOHANG",
            "WNOWAIT",
            "CLD_EXITED",
            "CLD_KILLED",
            "CLD_DUMPED",
            "killpg",
        )
    ):
        raise ValueError("bounded CI execution requires POSIX waitid/WNOWAIT ownership")
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise ValueError("CI command owner requires the original SIGCHLD wait status")
    timed_out = exceeded = False
    data = bytearray()
    started = time.monotonic()
    with log.open("xb") as stream:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        assert process.stdout is not None
        descriptor = process.stdout.fileno()
        try:
            os.set_blocking(descriptor, False)
            with selectors.DefaultSelector() as selector:
                selector.register(descriptor, selectors.EVENT_READ)
                eof = False
                while True:
                    exited = _leader_has_exited(process)
                    if eof and exited:
                        break
                    if time.monotonic() - started >= timeout_seconds:
                        timed_out = True
                        break
                    ready = (
                        selector.select(
                            min(
                                0.05,
                                max(0, timeout_seconds - (time.monotonic() - started)),
                            )
                        )
                        if not eof
                        else []
                    )
                    if eof:
                        time.sleep(0.01)
                    for _, _ in ready:
                        chunk = os.read(descriptor, 65536)
                        if not chunk:
                            eof = True
                            selector.unregister(descriptor)
                            break
                        remaining = maximum_bytes - len(data)
                        kept = chunk[:remaining]
                        stream.write(kept)
                        data.extend(kept)
                        print(
                            kept.decode("utf-8", errors="replace"), end="", flush=True
                        )
                        if len(chunk) > remaining:
                            exceeded = True
                            break
                    if exceeded:
                        break
        finally:
            owned = False
            cleanup_refusal = None
            try:
                # This check fails closed if another waiter consumed the child.
                # A successful leader may still have silent group descendants.
                _leader_has_exited(process)
                owned = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError as error:
                    if not _darwin_exited_leader_only(process):
                        cleanup_refusal = error
                        raise
                except OSError as error:
                    cleanup_refusal = error
                    raise
            finally:
                try:
                    if owned:
                        # The only reap is after the LAST group signal. There
                        # must never be a later signal using this numeric ID.
                        try:
                            process.wait(timeout=1)
                        except subprocess.TimeoutExpired as error:
                            cause = (
                                f"{type(cleanup_refusal).__name__}: {cleanup_refusal}"
                                if cleanup_refusal is not None
                                else "final group signal did not yield a terminal child"
                            )
                            raise ValueError(
                                "CI command cleanup unresolved after the one-second reap limit; "
                                + cause
                            ) from error
                finally:
                    process.stdout.close()
                    stream.flush()
                    os.fsync(stream.fileno())
    passed, failed = observed_test_counts(data.decode("utf-8", errors="replace"))
    return {
        "returncode": process.returncode,
        "timed_out": timed_out,
        "output_limit_exceeded": exceeded,
        "log_bytes": len(data),
        "log_sha256": hashlib.sha256(data).hexdigest(),
        "observed_passed_tests": passed,
        "observed_failed_tests": failed,
    }


def run(
    output: Path,
    command: list[str],
    *,
    minimum_tests: int = 0,
    timeout_seconds: float = 3600,
) -> int:
    if not command or type(minimum_tests) is not int or minimum_tests < 0:
        raise ValueError("a command and nonnegative minimum test count are required")
    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if not output.is_absolute() or output.resolve().is_relative_to(root):
        raise ValueError("execution records must be outside the source checkout")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents an old result or another invocation being
    # silently replaced. Abrupt runner death leaves 'running', never 'passed'.
    with output.open("x", encoding="utf-8") as stream:
        record = {
            "schema_version": 1,
            "source_sha": os.environ.get("SOURCE_SHA", ""),
            "base_sha": os.environ.get("BASE_SHA", ""),
            "tested_sha": os.environ.get("TESTED_SHA", ""),
            "lane": os.environ.get("HEPTA_CI_LANE", ""),
            "command": command,
            "working_directory": str(Path.cwd().resolve()),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "command_exit_code": None,
        }
        json.dump(record, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    started = time.monotonic()
    exit_code = 2
    try:
        before = identity()
        record["before"] = before
        for field in ("source_sha", "tested_sha"):
            if re.fullmatch(r"[0-9a-f]{40}", record[field]) is None:
                raise ValueError(f"invalid {field}")
        if before["dirty"] or before["commit"] != record["tested_sha"]:
            raise ValueError("checkout does not match the clean tested identity")
        if record["lane"] == "source-head":
            if record["tested_sha"] != record["source_sha"]:
                raise ValueError("source lane does not test the source SHA")
        elif record["lane"] == "base-merge":
            if re.fullmatch(r"[0-9a-f]{40}", record["base_sha"]) is None:
                raise ValueError("invalid base_sha")
            if before["parents"] != [record["base_sha"], record["source_sha"]]:
                raise ValueError("merge lane has different base/source parents")
            # Parent identities alone do not prove what was merged. Recompute
            # the candidate tree before dispatch, independently of other jobs.
            # Conflicts or unavailable history reject, never certify a fallback.
            expected_tree = git(
                "merge-tree", "--write-tree", record["base_sha"], record["source_sha"]
            )
            if before["tree"] != expected_tree:
                raise ValueError(
                    "merge lane tree differs from the recomputed base/source merge"
                )
            record["recomputed_merge_tree"] = expected_tree
        else:
            raise ValueError("an explicit source-head or base-merge lane is required")
        log = output.with_name(output.name + "." + uuid.uuid4().hex + ".log")
        record["log_file"] = log.name
        execution = execute_logged(command, log, timeout_seconds=timeout_seconds)
        record.update(execution)
        record["log_file"] = log.name
        record["minimum_tests"] = minimum_tests
        record["command_exit_code"] = execution["returncode"]
        after = identity()
        record["after"] = after
        exit_code = (
            execution["returncode"]
            if execution["returncode"] >= 0
            else 128 - execution["returncode"]
        )
        if execution["timed_out"]:
            exit_code = 124
        elif execution["output_limit_exceeded"]:
            exit_code = exit_code or 1
        elif (
            execution["observed_failed_tests"]
            or execution["observed_passed_tests"] < minimum_tests
        ):
            record["error"] = "required tests were not observed passing"
            exit_code = exit_code or 1
        if after != before:
            record["error"] = "source identity or bytes changed during execution"
            exit_code = exit_code or 1
        record["status"] = "passed" if exit_code == 0 else "failed"
    except KeyboardInterrupt:
        record["status"] = "interrupted"
        exit_code = 130
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        record["status"] = "failed" if record.get("log_file") else "rejected"
        record["error"] = str(error)
    finally:
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - started
        record["exit_code"] = exit_code
        # Atomic replacement of the result owned by this invocation only.
        with tempfile.NamedTemporaryFile(
            "w", dir=output.parent, delete=False, encoding="utf-8"
        ) as stream:
            pending = Path(stream.name)
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            pending.replace(output)
        finally:
            pending.unlink(missing_ok=True)
        print(json.dumps(record, sort_keys=True), flush=True)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-tests", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=3600)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        return run(
            args.output,
            command,
            minimum_tests=args.minimum_tests,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"CI command not dispatched: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
