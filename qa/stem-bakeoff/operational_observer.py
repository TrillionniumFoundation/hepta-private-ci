"""Observe real unittest/pytest phases without converting infrastructure errors into labels.

This child entry point intentionally supports CPython 3.8. It executes the exact
upstream test arguments through that framework's public runner entry point.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback
import unittest


def error_phase(test, error):
    if type(test).__name__ == "_FailedTest":
        return "collection"
    frames = {frame.name for frame in traceback.extract_tb(error[2])}
    if "_callSetUp" in frames or "_callTearDown" in frames:
        return "setup" if "_callSetUp" in frames else "teardown"
    method = getattr(test, "_testMethodName", None)
    if "_callTestMethod" in frames or method in frames:
        return "call"
    if "setUp" in frames or "tearDown" in frames:
        return "setup" if "setUp" in frames else "teardown"
    return "unknown"


class ObservedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.observations.append({"id": test.id(), "phase": "call", "status": "passed"})

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.observations.append({"id": test.id(), "phase": error_phase(test, error), "status": "failed", "exception": error[0].__name__})

    def addError(self, test, error):
        super().addError(test, error)
        self.observations.append({"id": test.id(), "phase": error_phase(test, error), "status": "failed", "exception": error[0].__name__})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.observations.append({"id": test.id(), "phase": "call", "status": "skipped", "reason": reason})

    def addExpectedFailure(self, test, error):
        super().addExpectedFailure(test, error)
        self.observations.append({"id": test.id(), "phase": "call", "status": "expected_failure"})

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.observations.append({"id": test.id(), "phase": "call", "status": "unexpected_success"})


class ObservedRunner(unittest.TextTestRunner):
    resultclass = ObservedResult


class PytestObserver:
    def __init__(self):
        self.observations = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed:
            self.observations.append({"id": report.nodeid, "phase": getattr(report, "hepta_phase", report.when),
                "status": report.outcome, "expected_failure": bool(getattr(report, "wasxfail", False))})

    def pytest_collectreport(self, report):
        if report.failed:
            self.observations.append({"id": report.nodeid, "phase": "collection", "status": "failed"})


def classify(observations, returncode):
    invalid = [o for o in observations if o["status"] == "failed" and o["phase"] != "call"]
    calls = [o for o in observations if o["phase"] == "call" and not o.get("expected_failure")]
    passed = sum(o["status"] == "passed" for o in calls)
    failed = sum(o["status"] == "failed" for o in calls)
    if invalid or returncode not in (0, 1):
        outcome = "infrastructure_error"
    elif failed and returncode == 1:
        outcome = "test_failure"
    elif passed and not failed and returncode == 0:
        outcome = "pass"
    else:
        outcome = "uninformative"
    return {"outcome": outcome, "test_call_passes": passed, "test_call_failures": failed,
            "non_call_failures": len(invalid), "observation_count": len(observations)}


def observe(runner, args):
    sys.path.insert(0, os.getcwd())
    start = time.perf_counter_ns()
    if runner == "unittest":
        program = unittest.TestProgram(module=None, argv=["unittest", *args], testRunner=ObservedRunner, exit=False)
        observations = program.result.observations
        returncode = 0 if program.result.wasSuccessful() else 1
    else:
        import pytest
        class PhaseObserver(PytestObserver):
            @pytest.hookimpl(hookwrapper=True)
            def pytest_runtest_makereport(self, item, call):
                outcome = yield
                report = outcome.get_result()
                if report.failed and report.when == "call" and call.excinfo is not None:
                    names = {entry.name for entry in call.excinfo.traceback}
                    if names & {"_callSetUp", "setUp"}:
                        report.hepta_phase = "setup"
                    elif names & {"_callTearDown", "tearDown"}:
                        report.hepta_phase = "teardown"
        observer = PhaseObserver()
        returncode = int(pytest.main(args, plugins=[observer]))
        observations = observer.observations
    return {"schema": "hepta.operational-command-observation.v1", "runner": runner, "args": args,
            "python": sys.version, "returncode": returncode, "observations": observations,
            "wall_ns": time.perf_counter_ns() - start, **classify(observations, returncode)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", choices=("pytest", "unittest"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cpu-seconds", type=int, default=0)
    parser.add_argument("--address-space-bytes", type=int, default=0)
    parser.add_argument("--log-bytes", type=int, default=0)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()
    args = parsed.args[1:] if parsed.args[:1] == ["--"] else parsed.args
    try:
        if parsed.cpu_seconds or parsed.address_space_bytes or parsed.log_bytes:
            import resource
            if min(parsed.cpu_seconds, parsed.address_space_bytes, parsed.log_bytes) <= 0:
                raise ValueError("all explicit local Linux subprocess limits must be positive")
            resource.setrlimit(resource.RLIMIT_CPU, (parsed.cpu_seconds, parsed.cpu_seconds + 1))
            resource.setrlimit(resource.RLIMIT_AS, (parsed.address_space_bytes, parsed.address_space_bytes))
            resource.setrlimit(resource.RLIMIT_FSIZE, (parsed.log_bytes, parsed.log_bytes))
        result = observe(parsed.runner, args)
    except BaseException as error:
        traceback.print_exc()
        result = {"schema": "hepta.operational-command-observation.v1", "runner": parsed.runner,
            "args": args, "python": sys.version, "outcome": "infrastructure_error", "returncode": 3,
            "observer_exception": type(error).__name__, "observer_message": str(error)}
    destination = Path(parsed.output)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(result, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(destination)
    raise SystemExit(result["returncode"])


if __name__ == "__main__":
    main()
