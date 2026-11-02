"""Actual POSIX child-process controls; never samples a scientific world."""

import argparse
from contextlib import redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

from . import process_guard


def verify():
    with tempfile.TemporaryDirectory(prefix="hcsn_r20_guard_") as directory:
        root = Path(directory)
        tracked, real_popen = [], subprocess.Popen
        def launch(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            tracked.append(child)
            return child
        captured = io.StringIO()
        with redirect_stdout(captured), patch.object(process_guard.subprocess, "Popen", side_effect=launch):
            normal, errors = process_guard.workers(__spec__.name, ["a", "b"], root / "normal")
        assert not errors and len(normal) == 2 and all(v["exit_code"] == 0 for v in normal.values())
        count = 0
        def partial(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError(errno.ENOSPC, "Injected second-child launch failure")
            return launch(*args, **kwargs)
        with redirect_stdout(captured), patch.object(process_guard.subprocess, "Popen", side_effect=partial):
            partial_result, partial_errors = process_guard.workers(__spec__.name, ["a", "b"], root / "partial")
        assert partial_errors and len(partial_result) == 1 and partial_result["a"]["exit_code"] == 0
        reaped = 0
        for child in tracked:
            try:
                os.waitpid(child.pid, os.WNOHANG)
            except ChildProcessError:
                reaped += 1
        assert reaped == 3
        with redirect_stdout(captured):
            missing_status = process_guard.outer(__spec__.name, root / "missing_workers_receipt.json", root / "absent.json")
            failed_write_status = process_guard.outer(__spec__.name, root / "absent" / "receipt.json", root / "absent.json")
        receipt = json.loads((root / "missing_workers_receipt.json").read_text())
        assert missing_status != 0 and failed_write_status != 0
        assert receipt["child_cpu_seconds"] > 0 and receipt["parallel_worker_cpu_sum"] is None
        assert receipt["worker_receipts_read_error"] and not (root / "absent" / "receipt.json").exists()
        records = [json.loads(line) for line in captured.getvalue().splitlines()]
        saved = [r["record"] for r in records if "record" in r and "child_cpu_seconds" in r["record"]]
        assert len(saved) == 2 and all(r["child_cpu_seconds"] > 0 for r in saved)
        assert any("record_write_failed" in r for r in records)
        return dict(passed=True, actual_child_processes=5, known_workers_reaped=3,
            normal_launch=True, partial_launch_error_waited=True, missing_worker_ledger_cpu_preserved=True,
            missing_receipt_directory_stdout_cost_preserved=True, world_generator_called=False,
            retained_child_receipts=saved)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.worker or args.child:
        start = time.process_time()
        while time.process_time() - start < .02:
            pass
        raise SystemExit(7 if args.child else 0)
    print(json.dumps(verify(), sort_keys=True))


if __name__ == "__main__":
    main()
