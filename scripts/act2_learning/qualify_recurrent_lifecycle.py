"""Retain exact-source ACT recovery tests; no production or efficacy qualification."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUITES = (
    "test_skill_lifecycle",
    "test_file_family",
    "test_durable_lifecycle",
    "test_durable_async_owner",
    "test_recurrent_lifecycle",
    "test_recurrent_lifecycle_adversarial",
    "test_async_recurrent_lifecycle",
    "test_async_recurrent_adversarial",
)


def source_identity():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "worktree_status": git("status", "--porcelain", "--untracked-files=all"),
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(HERE.glob("*.py"))
        },
        "model_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(
                (ROOT / "qualification/act2-learning-20261110/run2").glob(
                    "B4_gru-seed-*.npz"
                )
            )
        },
    }


def cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from cases(test)
        else:
            yield test


class RetainedResult(unittest.TextTestResult):
    """Record the actually started test identities, not only an exit code."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = []
        self.passed = []

    def startTest(self, test):
        self.started.append(test.id())
        super().startTest(test)

    def addSuccess(self, test):
        self.passed.append(test.id())
        super().addSuccess(test)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.absolute()
    if out.resolve().is_relative_to(ROOT):
        parser.error("qualification output must be outside the source checkout")
    out.mkdir(parents=True, exist_ok=False)
    before = source_identity()
    manifest = {
        "source_before": before,
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "planned_suites": list(SUITES),
        "scope": "Linux cooperative same-UID same-boot GRU, original filesystem owner, async worker and controller death",
        "production_authority": False,
        "new_boot_recovery_qualified": False,
        "common_rollback_qualified": False,
        "async_retry_qualified": False,
        "new_training_runs": 0,
        "independent_real_tasks": 0,
        "learning_advantage_claimed": False,
        "promotion": False,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if before["worktree_status"] or len(before["model_sha256"]) != 8:
        raise ValueError(
            "exact clean source and all eight retained GRU models required"
        )
    source = out / "source"
    source.mkdir()
    for name in before["source_sha256"]:
        (source / name).write_bytes((HERE / name).read_bytes())
    suite = unittest.TestSuite()
    planned = []
    for name in SUITES:
        tests = unittest.defaultTestLoader.loadTestsFromName(name)
        items = list(cases(tests))
        if not items or any(type(t).__name__ == "_FailedTest" for t in items):
            raise ValueError("missing or unimportable qualification suite: " + name)
        for test in items:
            if hasattr(type(test), "evidence"):
                retained = out / "originals" / name
                retained.mkdir(parents=True, exist_ok=True)
                type(test).evidence = retained
            planned.append(test.id())
        suite.addTests(tests)
    if len(planned) != len(set(planned)):
        raise ValueError("duplicate planned test identity")
    (out / "PLAN.json").write_text(json.dumps(planned, indent=2) + "\n")
    started_ns = time.monotonic_ns()
    with (out / "tests.log").open("w") as log:
        result = unittest.TextTestRunner(
            stream=log, verbosity=2, resultclass=RetainedResult
        ).run(suite)
    after = source_identity()
    passed = (
        result.wasSuccessful()
        and not result.skipped
        and result.testsRun == len(planned)
        and result.started == planned
        and result.passed == planned
        and before == after
    )
    report = {
        "passed": passed,
        "planned": len(planned),
        "executed": result.testsRun,
        "passed_test_ids": result.passed,
        "started_test_ids": result.started,
        "skipped": [(t.id(), reason) for t, reason in result.skipped],
        "failed_test_ids": [t.id() for t, _ in result.failures],
        "error_test_ids": [t.id() for t, _ in result.errors],
        "source_before": before,
        "source_after": after,
        "wall_ns": time.monotonic_ns() - started_ns,
        "log_sha256": hashlib.sha256((out / "tests.log").read_bytes()).hexdigest(),
        "scope": manifest["scope"],
        "production_authority": False,
        "promotion": False,
    }
    (out / "RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    files = {
        str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }
    (out / "SHA256SUMS.json").write_text(json.dumps(files, indent=2) + "\n")
    print(
        json.dumps({"passed": passed, "executed": result.testsRun, "output": str(out)})
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
