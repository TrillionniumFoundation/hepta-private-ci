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


class QualificationResult(unittest.TextTestResult):
    """Count method outcomes separately from subtest and fixture records.

    unittest's failures/errors/skipped lists contain individual records, whereas
    testsRun counts started test methods. Public result hooks retain the parent
    method for subtest failures. An error outside any started method is a class
    or module fixture outcome; it never creates a fictitious executed method.
    """

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.method_outcomes = []
        self.fixture_outcomes = []
        self._active_methods = {}

    def startTest(self, test):
        super().startTest(test)
        record = {"test": test.id(), "events": set()}
        self.method_outcomes.append(record)
        self._active_methods[id(test)] = record

    def stopTest(self, test):
        record = self._active_methods.pop(id(test))
        # Error takes precedence when different subtests fail and error inside
        # the same method. The raw record counts and tracebacks remain available.
        precedence = ("error", "failed", "unexpected_success", "skipped",
                      "expected_failure", "passed")
        record["status"] = next((kind for kind in precedence if kind in record["events"]),
                                "unfinished")
        record["events"] = sorted(record["events"])
        super().stopTest(test)

    def _record(self, test, outcome, *, subtest_skip=False):
        record = self._active_methods.get(id(test))
        # addSkip receives the subtest rather than its parent. The standard
        # sequential runner has exactly one active method in that callback;
        # class/module fixture callbacks run outside any active method.
        if record is None and subtest_skip and len(self._active_methods) == 1:
            record = next(iter(self._active_methods.values()))
        if record is None:
            self.fixture_outcomes.append({"test": str(test), "status": outcome})
        else:
            record["events"].add(outcome)

    def addSuccess(self, test):
        self._record(test, "passed")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self._record(test, "failed")
        super().addFailure(test, err)

    def addError(self, test, err):
        self._record(test, "error")
        super().addError(test, err)

    def addSkip(self, test, reason):
        self._record(test, "skipped", subtest_skip=True)
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self._record(test, "expected_failure")
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self._record(test, "unexpected_success")
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            outcome = "failed" if issubclass(err[0], test.failureException) else "error"
            self._record(test, outcome)
        super().addSubTest(test, subtest, err)


def summarize_result(result, *, require_torch):
    """Return mutually exclusive method counts, fixture counts, and gate exit."""
    def count(kind):
        return sum(record["status"] == kind for record in result.method_outcomes)

    def fixture_count(kind):
        return sum(record["status"] == kind for record in result.fixture_outcomes)

    report = {
        "tests_run": result.testsRun,
        "passed": count("passed"), "failed": count("failed"),
        "errors": count("error"), "skipped": count("skipped"),
        "expected_failures": count("expected_failure"),
        "unexpected_successes": count("unexpected_success"),
        "unfinished": count("unfinished"),
        "fixture_failures": fixture_count("failed"),
        "fixture_errors": fixture_count("error"),
        "fixture_skipped": fixture_count("skipped"),
        "failure_records": len(result.failures), "error_records": len(result.errors),
        "skipped_records": len(result.skipped),
        "method_outcomes": result.method_outcomes,
        "fixture_outcomes": result.fixture_outcomes,
        "skipped_tests": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
        "failures": [{"test": str(test), "traceback": trace}
                     for test, trace in result.failures + result.errors],
    }
    if not result.wasSuccessful() or report["unfinished"]:
        report["status"], code = "failed", 1
    elif result.skipped:
        report["status"], code = "partial", 2 if require_torch else 0
    else:
        report["status"], code = "passed", 0
    return report, code


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
        report["tests_discovered"] = suite.countTestCases()
        started = time.perf_counter()
        result = unittest.TextTestRunner(verbosity=2, resultclass=QualificationResult).run(suite)
        outcomes, code = summarize_result(result, require_torch=args.require_torch)
        report.update(outcomes, elapsed_seconds=time.perf_counter() - started)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "tests_run", "passed", "failed", "errors", "skipped")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
