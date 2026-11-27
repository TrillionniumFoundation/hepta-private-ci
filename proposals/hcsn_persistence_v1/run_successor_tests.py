"""Run all 28 inherited non-terminal tests with the new journal fixture.

Only ReportingTests' TerminalResultTests fixture reference is adapted. Business
functions, original test methods and archived source bytes are unchanged. The
separate test_successor_terminal CLI runs its 15 tests; they are not counted here.
"""

import argparse
import importlib
import json
from pathlib import Path
import sys
import time
import traceback
import unittest

from .atomic_io import identity, publish_json
from .test_successor_terminal import successor_suite


CLASSES = (
    ("test_c2_execution", "ExecutionTests", 11),
    ("test_c2_execution", "ProtocolTests", 8),
    ("test_c2_reporting", "ReportingTests", 4),
    ("test_c2_trace_coverage", "TraceCoverageTests", 5),
)


def run(successor):
    started = time.perf_counter()
    source = Path(successor).resolve()
    # This creates, but does not execute, the separately counted terminal suite.
    terminal_fixture = type(next(iter(successor_suite(source))))
    modules = {}
    for name, _, _ in CLASSES:
        if name not in modules:
            modules[name] = importlib.import_module(name)
    modules["test_c2_reporting"].TerminalResultTests = terminal_fixture
    names = tuple(modules) + (
        "test_c2_terminal_result",
        "c2_io",
        "c2_runner",
        "c2_controller",
        "c2_boundary",
        "c2_recording",
        "hcsn_persistence_v1.atomic_io",
        "hcsn_persistence_v1.journal",
    )
    before = {}
    for name in names:
        module = sys.modules[name]
        path = source / (name.replace(".", "/") + ".py")
        if Path(module.__file__).resolve() != path:
            raise RuntimeError("test dependency imported outside successor: " + name)
        before[str(path.relative_to(source))] = identity(path)
    suite, counts = unittest.TestSuite(), {}
    for module_name, class_name, expected in CLASSES:
        case = getattr(modules[module_name], class_name)
        selected = unittest.defaultTestLoader.loadTestsFromTestCase(case)
        if selected.countTestCases() != expected:
            raise ValueError("inherited test count differs: " + class_name)
        counts[class_name] = expected
        suite.addTests(selected)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    after = {}
    for name in before:
        try:
            after[name] = identity(source / name)
        except OSError as error:
            after[name] = {"error": str(error)}
    unchanged = before == after
    passed = (
        result.wasSuccessful()
        and not result.skipped
        and result.testsRun == sum(counts.values())
        and unchanged
    )
    return {
        "schema": "hcsn-successor-inherited-tests-v1",
        "successor": str(source),
        "class_counts": counts,
        "tests_run": result.testsRun,
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "skipped": [
            {"test": test.id(), "reason": reason} for test, reason in result.skipped
        ],
        "passed": passed,
        "source_before": before,
        "source_after": after,
        "source_unchanged": unchanged,
        "terminal_suite_run_here": False,
        "fixture_adaptation": "ReportingTests references the same extended terminal fixture; all original methods execute unchanged",
        "wrapper_elapsed_seconds": time.perf_counter() - started,
        "scope": "synthetic software fixtures only; no original C2 terminal reconstruction, training adequacy or scientific benefit",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--successor", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("preserve earlier reports; choose a new output path")
    try:
        report = run(args.successor)
    except Exception:
        report = {
            "schema": "hcsn-successor-inherited-tests-v1",
            "passed": False,
            "tests_run": 0,
            "failures": [],
            "skipped": [],
            "errors": [traceback.format_exc()],
            "terminal_suite_run_here": False,
            "scope": "suite loading failed; no tests executed",
        }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        publish_json(args.output, report)
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)
