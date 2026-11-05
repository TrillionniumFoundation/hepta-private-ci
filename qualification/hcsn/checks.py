"""Run the HCSN tests and write an exact-source qualification receipt.

``python -m qualification.hcsn.checks --output /tmp/hcsn-tests.json`` runs the
available local checks. CI adds --require-torch: skipped tensor tests cannot
be counted as a green tensor qualification.
"""

import argparse
import hashlib
import importlib.util
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-torch", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    source_files = sorted(root.rglob("*.py")) + sorted((root / "configs").glob("*.json"))
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in source_files}
    software = {}
    for package in ("numpy", "scipy", "torch", "ncps", "mamba-ssm"):
        try:
            software[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            software[package] = None
    report = {"schema_version": 1, "source_commit": os.environ.get("GITHUB_SHA"),
              "source_files_sha256": hashes, "python": sys.version.split()[0],
              "platform": platform.platform(), "software": software,
              "require_torch": args.require_torch}
    has_torch = importlib.util.find_spec("torch") is not None
    if args.require_torch and not has_torch:
        report.update(status="unavailable", reason="PyTorch is required but not installed",
                      passed=0, failed=0, errors=0, skipped=0, tests_run=0)
        code = 2
    else:
        suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root.parent))
        started = time.perf_counter()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        report.update(tests_run=result.testsRun, failed=len(result.failures), errors=len(result.errors),
                      skipped=len(result.skipped), elapsed_seconds=time.perf_counter() - started,
                      skipped_tests=[{"test": str(test), "reason": reason} for test, reason in result.skipped],
                      failures=[{"test": str(test), "traceback": trace} for test, trace in result.failures + result.errors])
        report["passed"] = result.testsRun - report["failed"] - report["errors"] - report["skipped"]
        report["status"] = "failed" if not result.wasSuccessful() else "partial" if result.skipped else "passed"
        code = 1 if not result.wasSuccessful() else 2 if args.require_torch and result.skipped else 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "tests_run", "passed", "failed", "errors", "skipped")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
