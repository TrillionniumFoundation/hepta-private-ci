"""Run a small, CPU-only synthetic mechanism qualification in a new evidence file.

Example, from the candidate root::

    python -m qualification.hcsn_differentiable.run_qualification --output /tmp/new-result.json

This runner does not start a cloud job, consume an old study ledger, or grant
formal-task completion credit. Missing Torch is a blocked result, not a skip
that can be counted as a successful qualification.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
import traceback
import unittest

try:
    import resource
except ImportError:
    resource = None


def _sources(root: Path) -> dict[str, dict[str, str | int]]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".md") and "__pycache__" not in path.parts:
            data = path.read_bytes()
            result[str(path.relative_to(root))] = {
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)
            }
    return result


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": str(value)}
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self._starts = {}

    def startTest(self, test):
        self._starts[test.id()] = time.perf_counter()
        super().startTest(test)

    def _record(self, test, outcome, detail=None):
        row = {"test": test.id(), "outcome": outcome,
               "wall_seconds": time.perf_counter() - self._starts.get(test.id(), time.perf_counter())}
        if detail is not None:
            row["detail"] = detail
        if hasattr(test, "measurements"):
            row["measurements"] = copy.deepcopy(test.measurements)
        if hasattr(test, "numerical_evidence"):
            row["numerical_evidence"] = copy.deepcopy(test.numerical_evidence)
        self.records.append(row)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failure", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skip", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "expected_failure", self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "unexpected_success")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._record(test, "subtest_failure", {"subtest": subtest.id(),
                                                    "traceback": self._exc_info_to_string(err, test)})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new JSON file; existing evidence is never overwritten")
    parser.add_argument("--threads", type=int, default=1, help="bounded local CPU thread count (1..4)")
    args = parser.parse_args(argv)
    if not 1 <= args.threads <= 4:
        parser.error("--threads must be between 1 and 4")
    if args.output.exists():
        parser.error("--output already exists; preserve it and choose a new evidence path")

    root = Path(__file__).resolve().parent
    before = _sources(root)
    started, cpu_started = time.perf_counter(), time.process_time()
    report = {
        "schema": "hcsn-differentiable-cpu-qualification-v1",
        "evidence_class": "synthetic_mechanism_and_gradient_qualification",
        "status": "started", "device": "cpu", "source_before": before,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(),
        "formal_fits_started": 0, "old_s81_completion_credit": 0,
        "physical_energy_joules": None, "provider_charges": None,
        "claim_boundary": "Small CPU mechanism fixtures only; no full-parameter-domain, high-resolution fidelity, large-model, hardware-energy, or formal-study claim.",
    }
    exit_code = 1
    try:
        try:
            import torch
        except ImportError as error:
            report.update(status="blocked", blocking_dependency="torch", detail=str(error), tests_run=0)
            exit_code = 2
        else:
            torch.set_num_threads(args.threads)
            torch.set_num_interop_threads(args.threads)
            torch.use_deterministic_algorithms(True)
            torch.manual_seed(20261108)
            report.update(torch=torch.__version__, cpu_threads=torch.get_num_threads(),
                          cpu_interop_threads=torch.get_num_interop_threads(),
                          deterministic_algorithms=torch.are_deterministic_algorithms_enabled())
            # Adding the repository-like candidate root supports both -m and
            # direct-file invocation without importing any old S81 module.
            candidate_root = str(root.parent.parent)
            if candidate_root not in sys.path:
                sys.path.insert(0, candidate_root)
            suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
            result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
            passed = (result.wasSuccessful() and result.testsRun > 0
                      and not result.skipped and not result.expectedFailures)
            report.update(status="passed" if passed else "failed", tests_run=result.testsRun,
                          failures=len(result.failures), errors=len(result.errors),
                          skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
                          tests=result.records)
            exit_code = 0 if passed else 1
    except Exception:
        report.update(status="runner_error", detail=traceback.format_exc())
        exit_code = 2
    finally:
        after = _sources(root)
        report.update(source_after=after, source_unchanged=before == after,
                      finished_utc=datetime.now(timezone.utc).isoformat(),
                      wall_seconds=time.perf_counter() - started,
                      process_cpu_seconds=time.process_time() - cpu_started,
                      peak_rss_native=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                                       if resource is not None else None),
                      peak_rss_native_unit=("bytes" if sys.platform == "darwin" else "KiB")
                                          if resource is not None else None,
                      peak_rss_scope="Entire qualification process high-water mark; unavailable where Python resource is unsupported.")
        if before != after:
            report["status"] = "source_changed_during_qualification"
            exit_code = 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(_json_safe(report), stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "tests_run": report.get("tests_run", 0), "source_unchanged": report["source_unchanged"]}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
