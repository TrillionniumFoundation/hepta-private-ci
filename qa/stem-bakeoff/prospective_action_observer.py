"""Add uncaught dependency-error visibility without changing the old observer.

This subprocess entry point intentionally supports the pinned CPython 3.8
project runtimes. An import error caught by a successful test remains a pass.
"""

import os
import sys
import time
import unittest

import operational_observer as legacy


_classify = legacy.classify
RESOURCE_ERRNOS = {1, 12, 13, 28, 30}  # EPERM, ENOMEM, EACCES, ENOSPC, EROFS.


def classify(observations, returncode):
    result = _classify(observations, returncode)
    unavailable = sum((o.get("uncaught_import_error") or o.get("exception") in ("ImportError", "ModuleNotFoundError"))
                      and o["status"] == "failed" for o in observations)
    result["uncaught_import_failures"] = unavailable
    resource_errors = sum(o.get("resource_failure_errno") in RESOURCE_ERRNOS
                          and o["status"] == "failed" for o in observations)
    result["uncaught_resource_failures"] = resource_errors
    if unavailable or resource_errors:
        result["outcome"] = "infrastructure_error"
    return result


def observe(runner, args):
    sys.path.insert(0, os.getcwd())
    start = time.perf_counter_ns()
    if runner == "unittest":
        class DependencyResult(legacy.ObservedResult):
            def addError(self, test, error):
                super().addError(test, error)
                self.observations[-1]["uncaught_import_error"] = issubclass(error[0], ImportError)
                if isinstance(error[1], OSError):
                    self.observations[-1]["resource_failure_errno"] = error[1].errno
        class DependencyRunner(legacy.ObservedRunner):
            resultclass = DependencyResult
        program = unittest.TestProgram(module=None, argv=["unittest", *args],
                                       testRunner=DependencyRunner, exit=False)
        observations = program.result.observations
        returncode = 0 if program.result.wasSuccessful() else 1
    else:
        import pytest
        class PhaseObserver(legacy.PytestObserver):
            @pytest.hookimpl(hookwrapper=True)
            def pytest_runtest_makereport(self, item, call):
                report = (yield).get_result()
                if report.failed and call.excinfo is not None:
                    report.hepta_exception = call.excinfo.type.__name__
                    report.hepta_import_error = issubclass(call.excinfo.type, ImportError)
                    report.hepta_resource_errno = call.excinfo.value.errno if isinstance(call.excinfo.value, OSError) else None
                    names = {entry.name for entry in call.excinfo.traceback}
                    if report.when == "call" and names & {"_callSetUp", "setUp"}:
                        report.hepta_phase = "setup"
                    elif report.when == "call" and names & {"_callTearDown", "tearDown"}:
                        report.hepta_phase = "teardown"

            def pytest_runtest_logreport(self, report):
                before = len(self.observations)
                super().pytest_runtest_logreport(report)
                if len(self.observations) > before and hasattr(report, "hepta_exception"):
                    self.observations[-1]["exception"] = report.hepta_exception
                    self.observations[-1]["uncaught_import_error"] = report.hepta_import_error
                    self.observations[-1]["resource_failure_errno"] = report.hepta_resource_errno
        observer = PhaseObserver()
        returncode = int(pytest.main(args, plugins=[observer]))
        observations = observer.observations
    return {"schema": "hepta.prospective-action-phase-observation.v1", "runner": runner, "args": args,
            "python": sys.version, "returncode": returncode, "observations": observations,
            "wall_ns": time.perf_counter_ns() - start, **classify(observations, returncode)}


if __name__ == "__main__":
    legacy.observe = observe
    legacy.main()
