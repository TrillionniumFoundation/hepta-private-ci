"""Run only the new CPU reference/control checks, with immutable receipts."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

from qualification.hcsn.checks import QualificationResult, summarize_result


def source_map(root):
    paths = list((root/"qualification/hcsn_causal").rglob("*.py"))
    paths += list((root/"qualification/hcsn_regenerative").rglob("*.py"))
    paths += [root/"qualification/hcsn/reference.py", root/"qualification/hcsn/checks.py",
              root/"qualification/hcsn/population.py"]
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("receipt already exists; retain it and use a new attempt path")
    root = Path(__file__).resolve().parents[2]
    before = source_map(root)
    report = {"schema": "hcsn-regenerative-causal-checks.v1",
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "source_files_sha256": before, "python": sys.version,
              "platform": platform.platform(),
              "software": {name: metadata.version(name) for name in ("numpy", "scipy")},
              "new_training_campaigns": 0, "scientific_gain_established": False}
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    report["checkout_head_before_execution"] = git.stdout.strip() if git.returncode == 0 else None
    suite = unittest.TestSuite()
    for package in ("qualification.hcsn_causal.test_event_stream",
                    "qualification.hcsn_causal.test_comparison",
                    "qualification.hcsn_causal.test_inventory",
                    "qualification.hcsn_regenerative.tests.test_process",
                    "qualification.hcsn_regenerative.tests.test_audit"):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(package))
    report["tests_discovered"] = suite.countTestCases()
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=QualificationResult).run(suite)
    # This inherited flag makes skipped methods non-passing; the new suite is
    # explicitly NumPy/SciPy only and makes no tensor/autodiff claim.
    outcomes, code = summarize_result(result, require_torch=True)
    report.update(outcomes, elapsed_seconds=time.perf_counter()-started)
    report["source_unchanged_during_execution"] = source_map(root) == before
    if not report["source_unchanged_during_execution"]:
        report["status"], code = "source_changed", 1
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "passed", "failed", "errors", "skipped")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
