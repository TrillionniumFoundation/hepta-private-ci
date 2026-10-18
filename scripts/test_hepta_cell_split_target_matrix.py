from __future__ import annotations

import hashlib
import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCRIPT = Path(__file__).with_name("hepta-cell-split-target-matrix.py")
SPEC = importlib.util.spec_from_file_location("cell_split_matrix", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def current_checkout_sha() -> str:
    return subprocess.run(
        ["git", "-C", str(SCRIPT.resolve().parent.parent), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def example_metrics() -> dict[str, object]:
    return {
        "p50Micros": 10,
        "p95Micros": 20,
        "p99Micros": 30,
        "throughputPerSecond": 100.0,
        "cpuMicros": 100,
        "rssBytes": 200,
        "gpuObserved": False,
        "gpuMicros": None,
        "gpuBytes": None,
        "communicationBytes": 300,
        "fsyncCount": 1,
        "walBytes": 400,
        "walFsyncCount": 1,
        "lockWaitMicros": 2,
        "recoveryMicros": 3,
        "negativeMigrationQ32": 0,
    }


def test_default_matrix_is_64_unique_cases_across_four_cell_counts() -> None:
    cases = MODULE.matrix_cases()
    assert len(cases) == 64
    assert [count for count in MODULE.CELL_COUNTS] == [64, 256, 1024, 4096]
    assert len({case["caseId"] for case in cases}) == 64
    assert len(
        {
            (case["cellCount"], *(case[name] for name, _ in MODULE.FACTORS))
            for case in cases
        }
    ) == 64
    for count in MODULE.CELL_COUNTS:
        one = MODULE.matrix_cases(count)
        assert len(one) == 16
        assert all(case["cellCount"] == count for case in one)
    with pytest.raises(ValueError, match="unsupported Cell count"):
        MODULE.matrix_cases(8)


def test_measurement_requires_all_metrics_and_monotonic_quantiles() -> None:
    metrics = example_metrics()
    assert MODULE.validate_metrics(metrics) == metrics
    with pytest.raises(ValueError, match="quantiles"):
        MODULE.validate_metrics({**metrics, "p95Micros": 40})
    for missing in ("walBytes", "walFsyncCount", "gpuObserved", "gpuMicros", "gpuBytes"):
        incomplete = dict(metrics)
        del incomplete[missing]
        with pytest.raises(ValueError, match="missing metrics"):
            MODULE.validate_metrics(incomplete)


def test_missing_gpu_is_explicit_null_not_fake_zero() -> None:
    metrics = example_metrics()
    assert MODULE.validate_metrics(metrics)["gpuObserved"] is False
    with pytest.raises(ValueError, match="unobserved GPU"):
        MODULE.validate_metrics({**metrics, "gpuMicros": 0})
    with pytest.raises(ValueError, match="unobserved GPU"):
        MODULE.validate_metrics({**metrics, "gpuBytes": 0})
    with pytest.raises(ValueError, match="gpuObserved"):
        MODULE.validate_metrics({**metrics, "gpuObserved": 0})
    with pytest.raises(ValueError, match="gpuMicros"):
        MODULE.validate_metrics({**metrics, "gpuObserved": True})
    measured = {**metrics, "gpuObserved": True, "gpuMicros": 12, "gpuBytes": 256}
    assert MODULE.validate_metrics(measured) == measured


def test_measurement_rejects_nonfinite_or_unbounded_counters() -> None:
    base = example_metrics()
    for name, bad_value in (
        ("throughputPerSecond", float("nan")),
        ("p95Micros", float("inf")),
        ("negativeMigrationQ32", float("-inf")),
        ("rssBytes", 1 << 128),
        ("walBytes", -1),
        ("walFsyncCount", 1.5),
    ):
        with pytest.raises(ValueError):
            MODULE.validate_metrics({**base, name: bad_value})


def test_pretty_json_workload_receipt_is_parsed() -> None:
    receipt = {"caseId": "case-1", "metrics": example_metrics()}
    assert MODULE.parse_workload_output(json.dumps(receipt, indent=2)) == receipt


def test_dry_run_is_blocked_until_workload_and_observer_exist(tmp_path: Path) -> None:
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
    assert report["authority"] == "DENY_ALL"
    assert len(report["cases"]) == 64
    assert report["cellCounts"] == list(MODULE.CELL_COUNTS)
    assert "independent-observer" in report["blockingCases"]
    MODULE.validate_report(json.loads(output.read_text(encoding="utf-8")))


def test_single_count_workload_passes_count_and_remains_diagnostic(tmp_path: Path) -> None:
    workload = tmp_path / "frozen-tasks"
    workload.write_bytes(b"fixture only: not a production task corpus")
    frozen_digest = hashlib.sha256(workload.read_bytes()).hexdigest()
    worker = tmp_path / "fixture-worker.py"
    worker.write_text(
        "import json, os, sys\n"
        f"METRICS = {example_metrics()!r}\n"
        "assert sys.argv[1] == os.environ['HEPTA_MATRIX_CELL_COUNT']\n"
        "print(json.dumps({"
        "'caseId': os.environ['HEPTA_MATRIX_CASE_ID'],"
        "'cellCount': int(os.environ['HEPTA_MATRIX_CELL_COUNT']),"
        "'sourceCommit': os.environ['HEPTA_MATRIX_SOURCE_COMMIT'],"
        "'workloadDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'workloadSourceDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'encoder_topology': os.environ['HEPTA_MATRIX_ENCODER_TOPOLOGY'],"
        "'execution': os.environ['HEPTA_MATRIX_EXECUTION'],"
        "'feature_materialization': os.environ['HEPTA_MATRIX_FEATURE_MATERIALIZATION'],"
        "'persistence': os.environ['HEPTA_MATRIX_PERSISTENCE'],"
        "'metrics': METRICS"
        "}))\n",
        encoding="utf-8",
    )
    report = MODULE.run_matrix(
        workload_command=f"{shlex.quote(sys.executable)} {shlex.quote(str(worker))} {{cellCount}}",
        observer_command=None,
        workload_digest=frozen_digest,
        source_commit=current_checkout_sha(),
        output=tmp_path / "matrix.json",
        workload_path=workload,
        host_id="fixture-only",
        cell_count=64,
    )
    assert len(report["cases"]) == 16
    assert all(case["status"] == "measured" for case in report["cases"])
    assert report["status"] == "blocked"
    assert "full-scale-matrix" in report["blockingCases"]
    assert "independent-observer" in report["blockingCases"]
    MODULE.validate_report(report)


def test_live_worker_must_match_actual_source_checkout(tmp_path: Path) -> None:
    workload = tmp_path / "frozen"
    workload.write_bytes(b"fixture only")
    with pytest.raises(ValueError, match="does not match repository HEAD"):
        MODULE.run_matrix(
            workload_command="python --version",
            observer_command=None,
            workload_digest=hashlib.sha256(workload.read_bytes()).hexdigest(),
            source_commit="e" * 40,
            output=tmp_path / "mismatch.json",
            workload_path=workload,
            cell_count=64,
        )


def test_live_worker_must_echo_actual_factor_tuple(tmp_path: Path) -> None:
    workload = tmp_path / "frozen"
    workload.write_bytes(b"fixture only")
    worker = tmp_path / "missing-factor.py"
    worker.write_text(
        "import json, os\n"
        f"metrics = {example_metrics()!r}\n"
        "print(json.dumps({"
        "'caseId': os.environ['HEPTA_MATRIX_CASE_ID'],"
        "'cellCount': int(os.environ['HEPTA_MATRIX_CELL_COUNT']),"
        "'sourceCommit': os.environ['HEPTA_MATRIX_SOURCE_COMMIT'],"
        "'workloadDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'workloadSourceDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'metrics': metrics"
        "}))\n",
        encoding="utf-8",
    )
    report = MODULE.run_matrix(
        workload_command=f"{shlex.quote(sys.executable)} {shlex.quote(str(worker))}",
        observer_command=None,
        workload_digest=hashlib.sha256(workload.read_bytes()).hexdigest(),
        source_commit=current_checkout_sha(),
        output=tmp_path / "missing-factor-report.json",
        workload_path=workload,
        cell_count=64,
    )
    assert report["status"] == "blocked"
    assert all(row["status"] == "blocked" for row in report["cases"])
    assert all("identity does not bind" in row["reason"] for row in report["cases"])
    MODULE.validate_report(report)


def test_live_worker_cannot_mutate_frozen_workload(tmp_path: Path) -> None:
    workload = tmp_path / "frozen"
    workload.write_bytes(b"immutable fixture")
    original_digest = hashlib.sha256(workload.read_bytes()).hexdigest()
    worker = tmp_path / "tamper.py"
    worker.write_text(
        "import json, os\n"
        "with open(os.environ['HEPTA_MATRIX_WORKLOAD_PATH'], 'ab') as out:\n"
        "    out.write(b'tamper')\n"
        f"metrics = {example_metrics()!r}\n"
        "print(json.dumps({"
        "'caseId': os.environ['HEPTA_MATRIX_CASE_ID'],"
        "'cellCount': int(os.environ['HEPTA_MATRIX_CELL_COUNT']),"
        "'sourceCommit': os.environ['HEPTA_MATRIX_SOURCE_COMMIT'],"
        "'workloadDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'workloadSourceDigest': os.environ['HEPTA_MATRIX_WORKLOAD_DIGEST'],"
        "'encoder_topology': os.environ['HEPTA_MATRIX_ENCODER_TOPOLOGY'],"
        "'execution': os.environ['HEPTA_MATRIX_EXECUTION'],"
        "'feature_materialization': os.environ['HEPTA_MATRIX_FEATURE_MATERIALIZATION'],"
        "'persistence': os.environ['HEPTA_MATRIX_PERSISTENCE'],"
        "'metrics': metrics"
        "}))\n",
        encoding="utf-8",
    )
    report = MODULE.run_matrix(
        workload_command=f"{shlex.quote(sys.executable)} {shlex.quote(str(worker))}",
        observer_command=None,
        workload_digest=original_digest,
        source_commit=current_checkout_sha(),
        output=tmp_path / "tamper-report.json",
        workload_path=workload,
        cell_count=64,
    )
    assert report["status"] == "blocked"
    assert all(row["status"] == "blocked" for row in report["cases"])
    assert "changed during" in report["cases"][0]["reason"]
    assert "changed before" in report["cases"][1]["reason"]
    MODULE.validate_report(report)


def test_report_rejects_duplicate_or_swapped_case_factors(tmp_path: Path) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
    )
    duplicated = {**report, "cases": [dict(x) for x in report["cases"]]}
    duplicated["cases"][0] = dict(duplicated["cases"][1])
    with pytest.raises(ValueError, match="unique and complete"):
        MODULE.validate_report(duplicated)
    swapped = {**report, "cases": [dict(x) for x in report["cases"]]}
    swapped["cases"][0]["encoder_topology"] = "incorrect"
    with pytest.raises(ValueError, match="factor or Cell-count"):
        MODULE.validate_report(swapped)
    bad_digest = {**report, "reportDigest": "0" * 64}
    with pytest.raises(ValueError, match="report digest mismatch"):
        MODULE.validate_report(bad_digest)


def test_full_scale_cannot_be_forged_from_one_count(tmp_path: Path) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
        cell_count=256,
    )
    forged = {**report, "status": "qualified", "blockingCases": []}
    with pytest.raises(ValueError, match="full scale"):
        MODULE.validate_report(forged)


def test_signed_observer_requires_out_of_band_trust_root() -> None:
    private = Ed25519PrivateKey.generate()
    trusted_key = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    receipt = {
        "schema": MODULE.OBSERVER_SCHEMA,
        "verified": True,
        "sourceCommit": "a" * 40,
        "workloadDigest": "b" * 64,
        "reportDigest": "c" * 64,
        "metricsDigest": "d" * 64,
        "observerId": "independent-observer",
    }
    receipt["signatureHex"] = private.sign(
        MODULE.observer_signing_bytes(receipt)
    ).hex()
    MODULE.verify_observer_signature(receipt, trusted_key)
    with pytest.raises(ValueError, match="trusted independent"):
        MODULE.verify_observer_signature(receipt, None)
    with pytest.raises(ValueError, match="prime-order"):
        MODULE.verify_observer_signature(receipt, "00" * 32)
    tampered = {**receipt, "metricsDigest": "e" * 64}
    with pytest.raises(ValueError, match="signature invalid"):
        MODULE.verify_observer_signature(tampered, trusted_key)
    with pytest.raises(ValueError, match="missing or malformed"):
        MODULE.verify_observer_signature({**receipt, "signatureHex": None}, trusted_key)


def test_rejects_low_order_and_noncanonical_pinned_ed25519_keys() -> None:
    receipt = {
        "schema": MODULE.OBSERVER_SCHEMA,
        "verified": True,
        "sourceCommit": "a" * 40,
        "workloadDigest": "b" * 64,
        "reportDigest": "c" * 64,
        "metricsDigest": "d" * 64,
        "observerId": "untrusted",
        "signatureHex": "00" * 64,
    }
    for weak_key in (
        "00" * 32,
        "01" + "00" * 31,
        "ec" + "ff" * 30 + "7f",
        "ed" + "ff" * 30 + "7f",
    ):
        with pytest.raises(ValueError, match="not prime-order"):
            MODULE.verify_observer_signature(receipt, weak_key)


def test_forged_verified_observer_cannot_qualify_report_without_signature(tmp_path: Path) -> None:
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=tmp_path / "matrix.json",
    )
    for row in report["cases"]:
        row["status"] = "measured"
        row["metrics"] = example_metrics()
        row["metricsDigest"] = MODULE.digest(row["metrics"])
        row.pop("reason", None)
    provisional = {
        key: report[key]
        for key in (
            "schema", "authority", "cellCounts", "sourceCommit",
            "workloadDigest", "workloadSourceDigest", "host", "cases",
        )
    }
    observer = {
        "schema": MODULE.OBSERVER_SCHEMA,
        "verified": True,
        "sourceCommit": report["sourceCommit"],
        "workloadDigest": report["workloadDigest"],
        "reportDigest": MODULE.digest(provisional),
        "metricsDigest": MODULE.digest([
            {"caseId": row["caseId"], "metricsDigest": row["metricsDigest"]}
            for row in report["cases"]
        ]),
        "observerId": "untrusted",
    }
    observer["signatureHex"] = "00" * 64
    observer["receiptDigest"] = MODULE.digest(observer)
    report["observer"] = observer
    report["blockingCases"] = []
    report["status"] = "qualified"
    report["reportDigest"] = MODULE.digest({**provisional, "observer": observer})
    with pytest.raises(ValueError, match="trusted independent"):
        MODULE.validate_report(report)
    with pytest.raises(ValueError, match="prime-order"):
        MODULE.validate_report(report, trusted_observer_public_key="00" * 32)
