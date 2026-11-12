#!/usr/bin/env python3
"""One scoped read-only diagnostic; original full gates are not invoked."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["GIT_OPTIONAL_LOCKS"] = "0"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    records = Path(__file__).resolve().parent
    config = json.loads((records / "input.json").read_bytes())
    original_driver = records / "original-driver-v2.py"
    if digest(original_driver.read_bytes()) != config["original_driver_sha256"]:
        raise RuntimeError("original inventory/execution driver differs")
    spec = importlib.util.spec_from_file_location("original_gate_driver", original_driver)
    driver = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = driver
    spec.loader.exec_module(driver)
    source = Path(config["source_root"]).resolve(strict=True)
    if records.is_relative_to(source) or source.is_relative_to(records):
        raise RuntimeError("source and external records must be disjoint")
    cfg = {"source_sha": config["source_sha"], "source_tree": config["source_tree"],
           "run_identity": config["run_identity"]}
    gate = "training-readback-scoped"
    directory = records / gate
    command = [sys.executable, "-B", str(records / "diagnostic.py"),
               "--source-root", str(source), "--overlay-json", str(records / "overlay.json"),
               "--callers", str(records / "CALLERS.toml"),
               "--callers-sha256", config["callers_sha256"],
               "--output", str(directory / "diagnostic-result.json")]
    start = {"schema": "hepta.utility.training-readback-overlay-run.v1",
             "run_identity": config["run_identity"], "started_at": driver.now(),
             "source_sha": config["source_sha"], "source_tree": config["source_tree"],
             "full_source_tree": None, "full_gate_status": "not_run", "cargo_tests": "not_run",
             "actual_A_B_C_qualification": False, "command": command,
             "timeout_seconds": config["timeout_seconds"], "entrypoint_started": False}
    driver.save(records / "run-start.json", start)
    driver.event("scoped_diagnostic_preparing", run_identity=config["run_identity"])
    summary = None
    package = None
    wrapper_error = None
    report = None
    report_error = None
    source_lock = None
    with (records / "SOURCE_DIAGNOSTIC.lock").open("xb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            # Shared lock only; never write or chmod the old source/records.
            source_lock = Path(config["source_lock"]).open("rb")
            fcntl.flock(source_lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            baseline = Path(config["baseline_inventory"]).read_bytes()
            if (len(baseline) != config["baseline_inventory_bytes"]
                    or digest(baseline) != config["baseline_inventory_sha256"]):
                raise RuntimeError("previous exact source inventory differs")
            driver.require_inventory(baseline, cfg)
            for name, expected in config["input_sha256"].items():
                if digest((records / name).read_bytes()) != expected:
                    raise RuntimeError("frozen diagnostic input differs: " + name)
            os.chdir(source)
            runner = driver.load_runner(source, config["hepta_ci_exec_sha256"])
            driver.save(records / "diagnostic-attempt.json", {
                "at": driver.now(), "status": "attempted", "command": command,
                "timeout_seconds": config["timeout_seconds"],
                "note": "Scoped collector diagnostic only; no original full gate entrypoint invoked."})
            summary, package = driver.run_gate(
                source, records, cfg, baseline, runner, gate,
                config["timeout_seconds"], command,
            )
        except Exception as error:
            wrapper_error = {"type": type(error).__name__, "message": str(error),
                             "traceback": traceback.format_exc()}
            driver.save(records / "wrapper-error.json", wrapper_error)
        finally:
            if source_lock is not None:
                source_lock.close()
        report_path = directory / "diagnostic-result.json"
        if report_path.exists():
            try:
                report = json.loads(report_path.read_bytes())
            except Exception as error:
                report_error = {"type": type(error).__name__, "message": str(error)}
        frozen_inputs_unchanged = None
        try:
            frozen_inputs_unchanged = all(
                digest((records / name).read_bytes()) == expected
                for name, expected in config["input_sha256"].items()
            )
        except Exception as error:
            report_error = {"type": type(error).__name__, "message": str(error)}
        attempts = (records / "diagnostic-attempt.json").is_file()
        dispatched = (directory / "execution-start.json").is_file()
        terminal = (directory / "execution-terminal.json").is_file()
        passed = (
            summary is not None and summary.get("status") == "passed"
            and report is not None and report.get("status") == "passed_scoped_diagnostic"
            and len(report.get("boundaries", [])) == 4
            and all(row.get("status") == "passed" for row in report["boundaries"])
            and len(report.get("protected", [])) == 5
            and all(row.get("status") == "passed" for row in report["protected"])
            and report.get("all_original_rust_and_verifier_inputs_unchanged") is True
            and report.get("external_frozen_inputs_unchanged") is True
            and frozen_inputs_unchanged is True
            and wrapper_error is None and report_error is None
        )
        status = "passed_scoped_diagnostic" if passed else "unknown_scoped_diagnostic"
        if frozen_inputs_unchanged is False:
            status = "failed_frozen_input_changed"
        elif summary is not None and summary.get("source_changed"):
            status = "failed_source_changed"
        elif report is not None and report.get("status") == "failed_scoped_diagnostic":
            status = "failed_scoped_diagnostic"
        elif summary is not None and summary.get("status") == "failed":
            status = "failed_execution_or_source_check"
        result = {**start, "finished_at": driver.now(), "status": status,
                  "attempted": attempts, "entrypoint_started": dispatched,
                  "execution_terminal_observed": terminal,
                  "not_run": [] if dispatched else [gate],
                  "gate_summary": summary, "gate_package": package,
                  "frozen_diagnostic_inputs_unchanged": frozen_inputs_unchanged,
                  "report_status": None if report is None else report.get("status"),
                  "wrapper_error": wrapper_error, "report_read_error": report_error,
                  "package_state": "pending"}
        driver.save(records / "run-result-prepackage.json", result)
        try:
            root_package = driver.retain_package(records)
            result["root_package"] = root_package
            result["package_state"] = "completed"
        except Exception as error:
            result["package_state"] = "failed"
            result["package_error"] = {"type": type(error).__name__, "message": str(error),
                                       "traceback": traceback.format_exc()}
            if status == "passed_scoped_diagnostic":
                result["status"] = "unknown_package_failed"
        driver.save(records / "run-result.json", result)
        driver.event("scoped_diagnostic_completed", **result)
        return 0 if result["status"] == "passed_scoped_diagnostic" else 1


if __name__ == "__main__":
    raise SystemExit(main())
