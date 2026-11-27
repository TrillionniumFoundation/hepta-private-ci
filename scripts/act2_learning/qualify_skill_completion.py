"""Freeze an old-TRAIN completion advisory probe; no execution or promotion."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import traceback
import unittest

import numpy as np

from qualify_recurrent_lifecycle import RetainedResult, cases, source_identity
from skill_completion_advisory import run_probe


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUITES = ("test_ensure_transition_loader", "test_skill_completion_advisory")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.absolute()
    if out.resolve().is_relative_to(ROOT):
        parser.error("qualification output must be outside the source checkout")
    out.mkdir(parents=True, exist_ok=False)
    before = source_identity()
    write_json(
        out / "MANIFEST.json",
        {
            "source_before": before,
            "python": sys.version,
            "numpy": np.__version__,
            "platform": platform.platform(),
            "planned_suites": list(SUITES),
            "scope": "old pinned controlled TRAIN, subsequent actor readback prediction only",
            "original_execution_host_contact": False,
            "new_independent_real_tasks": 0,
            "learned_complete_skill_composition_qualified": False,
            "operational_benefit_qualified": False,
            "production_authority": False,
            "promotion": False,
        },
    )
    if before["worktree_status"]:
        raise ValueError("exact clean source required")
    source = out / "source"
    source.mkdir()
    for name in before["source_sha256"]:
        (source / name).write_bytes((HERE / name).read_bytes())
    suite, planned = unittest.TestSuite(), []
    for name in SUITES:
        tests = unittest.defaultTestLoader.loadTestsFromName(name)
        items = list(cases(tests))
        if not items or any(type(t).__name__ == "_FailedTest" for t in items):
            raise ValueError("missing or unimportable qualification suite: " + name)
        planned.extend(test.id() for test in items)
        suite.addTests(tests)
    if len(planned) != len(set(planned)):
        raise ValueError("duplicate planned test identity")
    write_json(out / "TEST_PLAN.json", planned)
    started_ns = time.monotonic_ns()
    with (out / "tests.log").open("w") as log:
        tests = unittest.TextTestRunner(
            stream=log, verbosity=2, resultclass=RetainedResult
        ).run(suite)
    tests_passed = (
        tests.wasSuccessful()
        and not tests.skipped
        and tests.testsRun == len(planned)
        and tests.started == planned
        and tests.passed == planned
    )
    probe, error = None, None
    if tests_passed:
        with (out / "probe.log").open("w") as log:
            try:
                with redirect_stdout(log), redirect_stderr(log):
                    probe = run_probe(
                        ROOT / "qualification/act2-learning-20261110/run2",
                        out / "probe",
                    )
                    if (
                        probe.get("fit_count") != 20
                        or probe.get("optimizer_invocations") != 4000
                        or probe.get("observed") != 80
                        or probe.get("censored") != 16
                        or probe.get("promotion") is not False
                        or probe.get("new_independent_real_tasks") != 0
                    ):
                        raise ValueError("incomplete or out-of-scope advisory probe")
            except Exception as exc:
                error = {"type": type(exc).__name__, "message": str(exc)}
                traceback.print_exc(file=log)
    after = source_identity()
    passed = tests_passed and error is None and probe is not None and before == after
    report = {
        "passed": passed,
        "planned_tests": len(planned),
        "executed_tests": tests.testsRun,
        "started_test_ids": tests.started,
        "passed_test_ids": tests.passed,
        "skipped": [(t.id(), reason) for t, reason in tests.skipped],
        "failed_test_ids": [t.id() for t, _ in tests.failures],
        "error_test_ids": [t.id() for t, _ in tests.errors],
        "probe_error": error,
        "probe_result": probe,
        "source_before": before,
        "source_after": after,
        "wall_ns": time.monotonic_ns() - started_ns,
        "new_independent_real_tasks": 0,
        "operational_benefit_qualified": False,
        "production_authority": False,
        "promotion": False,
    }
    write_json(out / "RESULT.json", report)
    write_json(
        out / "SHA256SUMS.json",
        {
            str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*"))
            if p.is_file() and not p.is_symlink()
        },
    )
    print(
        json.dumps(
            {"passed": passed, "executed_tests": tests.testsRun, "output": str(out)}
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
