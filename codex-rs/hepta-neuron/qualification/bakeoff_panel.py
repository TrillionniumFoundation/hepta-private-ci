"""Bounded batch execution for the existing DecisionCell qualification CLI.

A fresh panel directory prevents a failed attempt from reusing an older receipt.
Exit codes describe execution, not model quality, selection or activation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence


def _stop(child: subprocess.Popen) -> None:
    """Reap only this panel's private child; never act on unrelated processes."""
    if os.name == "posix":
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        child.kill()
    child.wait(timeout=10)


def run_panel(*, script: Path, output_dir: Path, model_root: Path,
              models: Sequence[str], device: str, source: dict[str, Any],
              timeout_seconds: float = 900) -> tuple[Path, dict[str, Any]]:
    """Attempt every backend once and retain failures without declaring a winner.

    Cancellation interrupts the panel; ordinary backend failure does not. Each
    invocation gets an exclusive output directory and each child its own log.
    The caller must run the existing receipt verifier before comparing quality.
    """
    models = tuple(models)
    if (not models or len(models) != len(set(models)) or
            any(not isinstance(name, str) or
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name) is None
                for name in models)):
        raise ValueError("backend names must be unique bounded identifiers")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or
            not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600):
        raise ValueError("backend timeout must be finite and in (0, 3600] seconds")
    script = script.resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    panel = Path(tempfile.mkdtemp(prefix="panel-", dir=output_dir))
    report: dict[str, Any] = {
        "schema": "hepta.decision-cell-panel-execution.v1",
        "source": source,
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "requested_models": list(models), "device": device,
        "timeout_seconds": timeout_seconds, "attempts": [],
        "complete": False, "all_executed_successfully": False,
        "production_activation": False, "artifact_selection": False,
    }
    events = panel / "execution-events.jsonl"
    interrupted = False
    try:
        for model in models:
            command = [sys.executable, str(script), "--output-dir", str(panel),
                       "--model-root", str(model_root), "--device", device,
                       "run", "--model", model]
            log_path = panel / (model + ".log")
            row = {"model": model, "command": command, "log": log_path.name,
                   "exit_code": None, "status": "launching"}
            started = time.monotonic()
            with events.open("a", encoding="utf-8") as journal:
                journal.write(json.dumps({"event": "started", "model": model}) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
            try:
                with log_path.open("xb") as log:
                    child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                             start_new_session=os.name == "posix")
                    try:
                        row["exit_code"] = child.wait(timeout=timeout_seconds)
                        row["status"] = "completed" if row["exit_code"] == 0 else "failed"
                    except subprocess.TimeoutExpired:
                        _stop(child)
                        row.update(status="timed_out", exit_code=124)
                    except BaseException:
                        _stop(child)
                        raise
            except OSError as error:
                row.update(status="launch_failed", error_type=type(error).__name__)
            except BaseException:
                interrupted = True
                row["status"] = "interrupted"
                raise
            finally:
                row["elapsed_seconds"] = time.monotonic() - started
                if log_path.is_file():
                    digest = hashlib.sha256()
                    with log_path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    row["log_sha256"] = digest.hexdigest()
                report["attempts"].append(row)
                with events.open("a", encoding="utf-8") as journal:
                    journal.write(json.dumps({"event": "finished", **row}, sort_keys=True) + "\n")
                    journal.flush()
                    os.fsync(journal.fileno())
                print(json.dumps({"panel": str(panel), **row}, sort_keys=True), flush=True)
    finally:
        report["complete"] = not interrupted and len(report["attempts"]) == len(models)
        report["all_executed_successfully"] = report["complete"] and all(
            row["status"] == "completed" for row in report["attempts"])
        report["status"] = ("model_runs_completed" if report["all_executed_successfully"]
                            else "incomplete_or_failed_panel")
        with (panel / "execution.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return panel, report
