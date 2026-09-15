"""Run one real CI command and retain its exact Git identity and exit status.

This is an execution record, not a release/learning qualification. An absent,
running, rejected or failed record must never be interpreted as a passing test.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

MAX_OUTPUT_TAIL_BYTES = 65_536


def execute(command: list[str], record: dict) -> int:
    """Stream ordinary CI output and retain a bounded diagnostic tail.

    The tail is diagnostic only: it never substitutes for the process exit code
    or the before/after source-identity check. No extra checkout files are written.
    """
    tail = bytearray()
    total = 0
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            try:
                while chunk := process.stdout.read1(MAX_OUTPUT_TAIL_BYTES):
                    total += len(chunk)
                    tail.extend(chunk)
                    if len(tail) > MAX_OUTPUT_TAIL_BYTES:
                        del tail[:-MAX_OUTPUT_TAIL_BYTES]
                    binary_stdout = getattr(sys.stdout, "buffer", None)
                    if binary_stdout is None:
                        sys.stdout.write(chunk.decode("utf-8", "replace"))
                        sys.stdout.flush()
                    else:
                        binary_stdout.write(chunk)
                        binary_stdout.flush()
                return process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
    finally:
        record["output_tail"] = tail.decode("utf-8", "replace")
        record["output_bytes"] = total
        record["output_truncated"] = total > MAX_OUTPUT_TAIL_BYTES


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


def run(output: Path, command: list[str]) -> int:
    if not command:
        raise ValueError("a command is required")
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
            expected_tree = git("merge-tree", "--write-tree", record["base_sha"], record["source_sha"])
            if before["tree"] != expected_tree:
                raise ValueError("merge lane tree differs from the recomputed base/source merge")
            record["recomputed_merge_tree"] = expected_tree
        else:
            raise ValueError("an explicit source-head or base-merge lane is required")
        command_exit_code = execute(command, record)
        record["command_exit_code"] = command_exit_code
        after = identity()
        record["after"] = after
        exit_code = command_exit_code if command_exit_code >= 0 else 128 - command_exit_code
        if after != before:
            record["error"] = "source identity or bytes changed during execution"
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
        # Atomic replacement of the result owned by this invocation only.
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
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        return run(args.output, command)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"CI command not dispatched: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
