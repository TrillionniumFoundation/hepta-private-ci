"""Bind a fresh unchanged calibration audit to current confirmation bytes.

This reporting wrapper does not create samples, fit models, change a gate, or
modify any prior receipt. It records provenance for this invocation now; it
does not claim that the earlier unbound review recorded these hashes.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from ..freeze import REPO, verify


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def object_sha(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def write_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def confirmation_inventory(root):
    directory = root / "calibration_confirmation"
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files or any(path.is_symlink() for path in files):
        raise ValueError("A nonempty regular-file confirmation inventory is required")
    if not (directory / "RESULTS.json").is_file() or not (directory / "INDEX.json").is_file():
        raise ValueError("Complete calibration confirmation results and index are required")
    return {str(path.relative_to(root)): {"sha256": file_sha(path), "bytes": path.stat().st_size}
            for path in files}


def bind(run_dir):
    root = Path(run_dir).resolve()
    frozen = verify(root)
    reviews = root / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    original_path = reviews / "CALIBRATION_CONFIRM_REVIEW.json"
    numeric_path = reviews / "CALIBRATION_CONFIRM_REVIEW_BOUND.json"
    binding_path = reviews / "CALIBRATION_CONFIRM_REVIEW_BINDING.json"
    started_path = reviews / "CALIBRATION_CONFIRM_REVIEW_BINDING_STARTED.json"
    stdout_path = reviews / "CALIBRATION_CONFIRM_REVIEW_BOUND.stdout.log"
    stderr_path = reviews / "CALIBRATION_CONFIRM_REVIEW_BOUND.stderr.log"
    for path in (numeric_path, binding_path, started_path, stdout_path, stderr_path):
        if path.exists():
            raise FileExistsError("Preserve immutable prior attempt: " + str(path))
    original = json.loads(original_path.read_text())
    if original.get("passed") is not True or original.get("phase") != "confirm":
        raise ValueError("The existing completed confirmation review must remain available")
    original_sha = file_sha(original_path)
    reviewer = Path(__file__).with_name("review_calibration.py")
    reviewer_sha = file_sha(reviewer)
    if reviewer_sha != original["reviewer_source_sha256"]:
        raise ValueError("The requested unchanged numerical reviewer has changed")
    prepared_path = root / "calibration_prepared/PREPARED.json"
    prepared_sha = file_sha(prepared_path)
    if original["prepared_sha256"] != prepared_sha:
        raise ValueError("Original review prepared binding differs")
    started_utc = datetime.now(timezone.utc).isoformat()
    started_ns = time.perf_counter_ns()
    before = confirmation_inventory(root)
    command = [sys.executable, "-m", "experiments.analytic_event_neuron.round4.evidence.review_calibration",
               "confirm", "--run-dir", str(root), "--output", str(numeric_path)]
    start = {
        "schema": "hepta.calibration.confirmation-binding-start.v1",
        "started_utc": started_utc, "source_commit": frozen["source_commit"],
        "freeze_sha256": file_sha(root / "FREEZE.json"),
        "confirmation_inventory": before,
        "confirmation_inventory_sha256": object_sha(before),
        "prepared_sha256": prepared_sha, "reviewer_source_sha256": reviewer_sha,
        "original_review_path": str(original_path.relative_to(root)),
        "original_review_sha256": original_sha, "command": command,
        "bound_review_path": str(numeric_path.relative_to(root)),
        "current_time_binding": "Hashes observed before this fresh invocation; not retroactive provenance for the original receipt.",
        "retroactive_original_review_provenance_claimed": False,
    }
    write_new(started_path, start)
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    completed = subprocess.run(command, cwd=REPO, env=environment, capture_output=True, text=True)
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    with stdout_path.open("x") as stream:
        stream.write(completed.stdout)
    with stderr_path.open("x") as stream:
        stream.write(completed.stderr)
    after = confirmation_inventory(root)
    unchanged_inventory = before == after
    source_unchanged = file_sha(reviewer) == reviewer_sha
    original_unchanged = file_sha(original_path) == original_sha
    prepared_unchanged = file_sha(prepared_path) == prepared_sha
    verified_after = verify(root)
    frozen_unchanged = verified_after == frozen
    numeric = json.loads(numeric_path.read_text()) if numeric_path.is_file() else {}
    numeric_passed = (completed.returncode == 0 and numeric.get("passed") is True
                      and numeric.get("phase") == "confirm"
                      and numeric.get("reviewer_source_sha256") == reviewer_sha
                      and numeric.get("prepared_sha256") == prepared_sha)
    passed = (numeric_passed and unchanged_inventory and source_unchanged
              and original_unchanged and prepared_unchanged and frozen_unchanged)
    report = {
        "schema": "hepta.calibration.confirmation-binding.v1",
        "passed": passed, "started_utc": started_utc,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": frozen["source_commit"], "freeze_sha256": file_sha(root / "FREEZE.json"),
        "results_sha256": after["calibration_confirmation/RESULTS.json"]["sha256"],
        "bound_review_path": str(numeric_path.relative_to(root)),
        "bound_review_sha256": file_sha(numeric_path) if numeric_path.is_file() else None,
        "bound_review_passed": numeric_passed,
        "bound_review_checks": numeric.get("checks"),
        "bound_review_scalar_comparisons": numeric.get("scalar_comparisons"),
        "confirmation_files_sha256": {name: item["sha256"] for name, item in after.items()},
        "confirmation_file_bytes": {name: item["bytes"] for name, item in after.items()},
        "confirmation_file_count": len(after), "confirmation_total_file_bytes": sum(item["bytes"] for item in after.values()),
        "before_after_identical": unchanged_inventory,
        "before_confirmation_inventory_sha256": object_sha(before),
        "after_confirmation_inventory_sha256": object_sha(after),
        "started_receipt_path": str(started_path.relative_to(root)),
        "started_receipt_sha256": file_sha(started_path),
        "original_review_path": str(original_path.relative_to(root)),
        "original_review_sha256": original_sha, "original_review_unchanged": original_unchanged,
        "reviewer_source_sha256": reviewer_sha, "reviewer_source_unchanged": source_unchanged,
        "binding_wrapper_sha256": file_sha(__file__), "prepared_sha256": prepared_sha,
        "frozen_sources_and_prepared_artifacts_verified_before_and_after": frozen_unchanged,
        "current_time_binding": "This receipt binds current confirmation bytes observed before and after a fresh unchanged read-only numerical audit. It does not supply previously unrecorded provenance for the original review.",
        "retroactive_original_review_provenance_claimed": False,
        "new_scientific_gate": False, "fitting_performed": False,
        "confirmation_generated_or_filtered": False,
        "scientific_source_modified": False, "prepared_artifacts_modified": False,
        "command": command, "returncode": completed.returncode,
        "stdout_path": str(stdout_path.relative_to(root)), "stderr_path": str(stderr_path.relative_to(root)),
        "numerical_review_child_user_seconds": usage_after.ru_utime - usage_before.ru_utime,
        "numerical_review_child_system_seconds": usage_after.ru_stime - usage_before.ru_stime,
        "wall_ns": time.perf_counter_ns() - started_ns,
        "timers_nested_within_outer_execute_wrapper": True,
    }
    write_new(binding_path, report)
    return report, binding_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    report, path = bind(args.run_dir)
    print(json.dumps({"passed": report["passed"], "binding_path": str(path),
                      "binding_sha256": file_sha(path), "bound_review_path": report["bound_review_path"],
                      "bound_review_sha256": report["bound_review_sha256"],
                      "confirmation_file_count": report["confirmation_file_count"],
                      "results_sha256": report["results_sha256"]}), flush=True)
    raise SystemExit(0 if report["passed"] else 1)
