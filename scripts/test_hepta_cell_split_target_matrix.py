from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).with_name("hepta-cell-split-target-matrix.py")
SPEC = importlib.util.spec_from_file_location("cell_split_matrix", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_matrix_is_exactly_sixteen_cases_with_unique_factor_tuples() -> None:
    cases = MODULE.matrix_cases()
    assert len(cases) == 16
    assert len({case["caseId"] for case in cases}) == 16
    assert len({tuple(case[name] for name, _ in MODULE.FACTORS) for case in cases}) == 16


def test_measurement_receipt_requires_all_metrics_and_monotonic_quantiles() -> None:
    metrics = {
        "p50Micros": 10,
        "p95Micros": 20,
        "p99Micros": 30,
        "throughputPerSecond": 100.0,
        "cpuMicros": 100,
        "rssBytes": 200,
        "communicationBytes": 300,
        "fsyncCount": 1,
        "lockWaitMicros": 2,
        "recoveryMicros": 3,
        "negativeMigrationQ32": 0,
    }
    assert MODULE.validate_metrics(metrics) == metrics
    try:
        MODULE.validate_metrics({**metrics, "p95Micros": 40})
    except ValueError as error:
        assert "quantiles" in str(error)
    else:
        raise AssertionError("non-monotonic quantiles were accepted")


def test_dry_run_is_blocked_until_workload_and_observer_receipts_exist(tmp_path: Path) -> None:
    output = tmp_path / "matrix.json"
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=output,
        host_id="test-host",
    )
    assert report["status"] == "blocked"
    assert len(report["cases"]) == 16
    assert "independent-observer" in report["blockingCases"]
    MODULE.validate_report(json.loads(output.read_text(encoding="utf-8")))
