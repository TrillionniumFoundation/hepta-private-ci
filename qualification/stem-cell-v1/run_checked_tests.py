"""Run an explicit unittest selection; skipped, incomplete or empty is not green.

Imports no model framework. Dependency failures remain unittest errors. This is
source-test accounting, not model qualification or proof a test is well designed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import unittest
from pathlib import Path


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


class ObservedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed_ids = []

    def startTest(self, test):
        self.executed_ids.append(test.id())
        super().startTest(test)


def run_checked_suite(suite, *, loader_errors=(), stream=None):
    planned = list(test_ids(suite))
    if not planned or len(planned) != len(set(planned)):
        raise ValueError('nonempty, duplicate-free test inventory required')
    runner = unittest.TextTestRunner(stream=stream or sys.stderr, verbosity=2,
                                    resultclass=ObservedResult)
    result = runner.run(suite)
    complete = sorted(result.executed_ids) == sorted(planned)
    passed = (result.wasSuccessful() and complete and not loader_errors
              and not result.skipped and not result.expectedFailures
              and not result.unexpectedSuccesses)
    return dict(schema='hepta.checked-source-tests.v1', passed=passed,
                planned_ids=planned, executed_ids=result.executed_ids,
                planned=len(planned), executed=result.testsRun,
                complete=complete, errors=len(result.errors),
                failures=len(result.failures), skips=len(result.skipped),
                expected_failures=len(result.expectedFailures),
                unexpected_successes=len(result.unexpectedSuccesses),
                discovery_errors=list(loader_errors), python=platform.python_version(),
                model_qualification=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default=str(Path(__file__).parent))
    parser.add_argument('--pattern', default='test_*.py')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    # Reserve before executing: an existing output never causes a second run.
    with Path(args.output).open('x', encoding='utf-8') as target:
        try:
            loader = unittest.TestLoader()
            suite = loader.discover(args.start, pattern=args.pattern)
            report = run_checked_suite(suite, loader_errors=loader.errors)
            report['source_test_files'] = {
                str(p.relative_to(args.start)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(Path(args.start).rglob(args.pattern)) if p.is_file()}
        except Exception as exc:
            json.dump({'schema': 'hepta.checked-source-tests.v1', 'passed': False,
                       'error_type': type(exc).__name__, 'model_qualification': False}, target)
            target.write('\n')
            raise
        json.dump(report, target, sort_keys=True, indent=2, allow_nan=False)
        target.write('\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
