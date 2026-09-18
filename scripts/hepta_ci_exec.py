"""Run one real CI command and retain its exact Git identity and exit status.

This is an execution record, not a release/learning qualification. An absent,
running, rejected or failed record must never be interpreted as a passing test.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

MAX_OUTPUT_BYTES = 64 * 1024 * 1024
LIBTEST_SUMMARY = re.compile(
    rb"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;.*"
)


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


def _kill_command(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def execute_logged(command: list[str], log: Path, maximum_bytes: int = MAX_OUTPUT_BYTES) -> dict:
    """Keep bounded merged stdout/stderr, including failures before test startup.

    Test counts recognize libtest summaries, not compilation or process success.
    This parser is not an independent evaluator of adversarial candidate code.
    """
    if maximum_bytes <= 0:
        raise ValueError("output bound must be positive")
    digest = hashlib.sha256()
    count = passed = failed = 0
    pending = b""
    exceeded = False
    # Never overwrite an earlier invocation's diagnostic output.
    with log.open("xb") as stream:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        try:
            assert process.stdout is not None
            while chunk := process.stdout.read(16384):
                available = maximum_bytes - count
                kept = chunk[:available]
                stream.write(kept)
                digest.update(kept)
                count += len(kept)
                # Buffer only a bounded partial line; the retained file has the
                # original bytes even when a command emits a very long line.
                lines = (pending + kept).split(b"\n")
                pending = lines.pop()[-4096:]
                for line in lines:
                    match = LIBTEST_SUMMARY.fullmatch(line.strip())
                    if match:
                        passed += int(match[2])
                        failed += int(match[3])
                if hasattr(sys.stdout, "buffer"):
                    sys.stdout.buffer.write(kept)
                    sys.stdout.buffer.flush()
                else:
                    sys.stdout.write(kept.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
                if len(chunk) > len(kept):
                    exceeded = True
                    _kill_command(process)
                    break
            if match := LIBTEST_SUMMARY.fullmatch(pending.strip()):
                passed += int(match[2])
                failed += int(match[3])
            returncode = process.wait()
        except BaseException:
            _kill_command(process)
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()
            stream.flush()
            os.fsync(stream.fileno())
    return {
        "returncode": returncode, "log_file": log.name,
        "log_bytes": count, "log_sha256": digest.hexdigest(),
        "output_limit_exceeded": exceeded,
        "observed_passed_tests": passed, "observed_failed_tests": failed,
    }


def run(output: Path, command: list[str], minimum_tests: int = 0) -> int:
    if not command:
        raise ValueError("a command is required")
    if minimum_tests < 0:
        raise ValueError("minimum_tests must not be negative")
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
            "minimum_tests": minimum_tests,
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
            expected_tree = git("merge-tree", "--write-tree", record["base_sha"], record["source_sha"])
            if before["tree"] != expected_tree:
                raise ValueError("merge lane tree differs from the recomputed base/source merge")
            record["recomputed_merge_tree"] = expected_tree
        else:
            raise ValueError("an explicit source-head or base-merge lane is required")
        log = output.with_name(f"{output.name}.{uuid.uuid4().hex}.log")
        observed = execute_logged(command, log)
        returncode = observed.pop("returncode")
        record.update(observed)
        record["command_exit_code"] = returncode
        after = identity()
        record["after"] = after
        exit_code = returncode if returncode >= 0 else 128 - returncode
        if after != before:
            record["error"] = "source identity or bytes changed during execution"
            exit_code = exit_code or 1
        if record["output_limit_exceeded"]:
            record["error"] = "command output exceeded the retained-output bound"
            exit_code = exit_code or 1
        if minimum_tests and (
            record["observed_passed_tests"] < minimum_tests
            or record["observed_failed_tests"] != 0
        ):
            record["error"] = "required tests did not execute successfully; zero/ignored is not pass"
            exit_code = exit_code or 1
        record["status"] = "passed" if exit_code == 0 else "failed"
    except KeyboardInterrupt:
        record["status"] = "interrupted"
        exit_code = 130
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        record["status"] = "rejected" if record["command_exit_code"] is None else "failed"
        record["error"] = str(error)
    finally:
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - started
        record["exit_code"] = exit_code
        with tempfile.NamedTemporaryFile("w", dir=output.parent, delete=False, encoding="utf-8") as stream:
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
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        return run(args.output, command, args.minimum_tests)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"CI command not dispatched: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
