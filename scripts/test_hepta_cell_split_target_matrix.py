from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


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


def test_measurement_rejects_nonfinite_or_unbounded_counters() -> None:
    base = {
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
    for name, bad_value in (
        ("throughputPerSecond", float("nan")),
        ("p95Micros", float("inf")),
        ("negativeMigrationQ32", float("-inf")),
        ("rssBytes", 1 << 128),
    ):
        try:
            MODULE.validate_metrics({**base, name: bad_value})
        except ValueError:
            pass
        else:
            raise AssertionError(f"unbounded metric {name} was accepted")



def _metric_fixture() -> dict[str, int | float]:
    return {
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


def test_observer_self_assertion_cannot_qualify_without_trusted_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MODULE.TRUSTED_OBSERVER_PUBKEY_ENV, raising=False)
    output = tmp_path / "fake-qualified.json"
    report = MODULE.run_matrix(
        workload_command=None,
        observer_command=None,
        workload_digest="a" * 64,
        source_commit="f" * 40,
        output=output,
        host_id="fixture-host",
    )
    for case in report["cases"]:
        case["status"] = "measured"
        case.pop("reason", None)
        case["metrics"] = _metric_fixture()
        case["metricsDigest"] = MODULE.digest(case["metrics"])
    report["blockingCases"] = []
    provisional = {
        field: report[field]
        for field in (
            "schema", "authority", "sourceCommit", "workloadDigest",
            "workloadSourceDigest", "host", "cases",
        )
    }
    observer = {
        "observerId": "attacker",
        "verified": True,
        "sourceCommit": report["sourceCommit"],
        "workloadDigest": report["workloadDigest"],
        "reportDigest": MODULE.digest(provisional),
        "metricsDigest": MODULE.digest([
            {"caseId": case["caseId"], "metricsDigest": case["metricsDigest"]}
            for case in report["cases"]
        ]),
        "signatureEd25519": "0" * 128,
    }
    observer["receiptDigest"] = MODULE.digest(observer)
    report["observer"] = observer
    report["status"] = "qualified"
    report["reportDigest"] = MODULE.digest({**provisional, "observer": observer})
    with pytest.raises(ValueError, match="public key"):
        MODULE.validate_report(report)
    # Metadata cannot hide a signed-report failure by mutating the outer hash.
    report["reportDigest"] = "0" * 64
    with pytest.raises(ValueError, match="report digest mismatch"):
        MODULE.validate_report(report)


def test_signed_observer_receipt_is_exactly_bound_to_pinned_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    trusted = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    monkeypatch.setenv(MODULE.TRUSTED_OBSERVER_PUBKEY_ENV, trusted)
    receipt = {
        "observerId": "independent-evaluator-v1",
        "verified": True,
        "sourceCommit": "a" * 40,
        "workloadDigest": "b" * 64,
        "reportDigest": "c" * 64,
        "metricsDigest": "d" * 64,
    }
    receipt["signatureEd25519"] = private.sign(
        MODULE.observer_signing_payload(receipt)
    ).hex()
    kwargs = {
        "source_commit": receipt["sourceCommit"],
        "workload_digest": receipt["workloadDigest"],
        "report_digest": receipt["reportDigest"],
        "metrics_digest": receipt["metricsDigest"],
    }
    MODULE.verify_signed_observer_receipt(receipt, **kwargs)

    changed = {**receipt, "metricsDigest": "e" * 64}
    with pytest.raises(ValueError, match="binding mismatch"):
        MODULE.verify_signed_observer_receipt(changed, **kwargs)
    changed = {**receipt, "signatureEd25519": "0" * 128}
    with pytest.raises(ValueError, match="signature verification failed"):
        MODULE.verify_signed_observer_receipt(changed, **kwargs)
