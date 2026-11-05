"""Run scoped protocol checks and preserve their exact executed source identity."""

import hashlib
import io
import json
import os
from pathlib import Path
import platform
import resource
import sqlite3
import sys
import time
import unittest

import cryptography
import cloudpickle


ROOT = Path(__file__).resolve().parent


def source_inventory():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob("*.py"))}


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = []

    def startTest(self, test):
        self.executed.append(test.id())
        super().startTest(test)


def main():
    source_before = source_inventory()
    began = time.perf_counter()
    before_self, before_child = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern="*tests.py")
    result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=RecordedResult).run(suite)
    after_self, after_child = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    source_after = source_inventory()
    output = ROOT / "evidence"
    output.mkdir(exist_ok=True)
    raw_log = log.getvalue()
    (output / "checks.log").write_text(raw_log)
    report = {
        "schema": "hepta.memory.v15.protocol-checks.v1",
        "passed": result.wasSuccessful() and result.testsRun > 0 and not result.skipped and source_before == source_after,
        "tests_run": result.testsRun, "test_ids": result.executed,
        "failures": [t.id() for t, _ in result.failures], "errors": [t.id() for t, _ in result.errors],
        "skipped": [(t.id(), reason) for t, reason in result.skipped],
        "source_files_sha256": source_before, "source_unchanged_during_execution": source_before == source_after,
        "git_source_commit_if_ci": os.getenv("GITHUB_SHA"), "python": sys.version,
        "cryptography": cryptography.__version__, "cloudpickle": cloudpickle.__version__,
        "python_optimize": sys.flags.optimize, "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(), "wall_seconds": time.perf_counter() - began,
        "self_cpu_seconds": (after_self.ru_utime + after_self.ru_stime) - (before_self.ru_utime + before_self.ru_stime),
        "child_cpu_seconds": (after_child.ru_utime + after_child.ru_stime) - (before_child.ru_utime + before_child.ru_stime),
        "self_process_high_water_rss_bytes": after_self.ru_maxrss * 1024 if sys.platform.startswith("linux") else None,
        "energy_joules": None, "cloud_bill_usd": None,
        "log_sha256": hashlib.sha256(raw_log.encode()).hexdigest(),
        "scope": "Synthetic finite-model and control-plane checks; includes real same-host processes and process kills. No new language training, physical multi-node run or product efficacy measurement.",
        "cost_scope": "This verification process and waited children only; excludes interpreter startup, package setup, research, and deployment. Peak RSS is the parent lifetime high-water mark.",
        "production_activation_allowed": False,
    }
    (output / "checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(raw_log, end="")
    print(json.dumps({k: report[k] for k in ("passed", "tests_run", "failures", "errors", "wall_seconds")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
