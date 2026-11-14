"""Record the unchanged unittest workload; the parent independently admits it."""

import json
from pathlib import Path
import sys
import unittest


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started, self.completed, self.outcomes = [], [], []
        self.current = {}

    def startTest(self, test):
        self.started.append(test.id())
        self.current[test.id()] = "incomplete"
        super().startTest(test)

    def stopTest(self, test):
        self.completed.append(test.id())
        self.outcomes.append({"id": test.id(), "status": self.current[test.id()]})
        super().stopTest(test)

    def addSuccess(self, test):
        self.current[test.id()] = "success"
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.current[test.id()] = "failure"
        super().addFailure(test, err)

    def addError(self, test, err):
        self.current[test.id()] = "error"
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.current[test.id()] = "skip"
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.current[test.id()] = "expected_failure"
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.current[test.id()] = "unexpected_success"
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.current[test.id()] = "subtest_failure"
        super().addSubTest(test, subtest, err)


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def main():
    implementation, tests, output = map(Path, sys.argv[1:])
    sys.path.insert(0, str(implementation))
    suite = unittest.defaultTestLoader.discover(str(tests))
    discovered = list(test_ids(suite))
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    report = {
        "discovered": discovered,
        "started": result.started,
        "completed": result.completed,
        "outcomes": result.outcomes,
        "tests_run": result.testsRun,
        "unittest_success": result.wasSuccessful(),
    }
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
