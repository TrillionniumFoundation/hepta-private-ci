"""Standard-library rejection regressions for signed Cell Split target evidence.

These tests run on exact-source and prospective-merge architecture lanes, with
no model, host access, or production authority. They cannot qualify a target.
"""

from __future__ import annotations

import copy
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "hepta-cell-split-target-matrix.py"
SPEC = importlib.util.spec_from_file_location("hepta_cell_split_target_matrix", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def metrics() -> dict[str, int | float]:
    return {
        "p50Micros": 10, "p95Micros": 20, "p99Micros": 30,
        "throughputPerSecond": 100.0, "cpuMicros": 100, "rssBytes": 200,
        "communicationBytes": 300, "fsyncCount": 1, "lockWaitMicros": 2,
        "recoveryMicros": 3, "negativeMigrationQ32": 0,
    }


def rehash(report: dict) -> None:
    report["reportDigest"] = MODULE.digest({
        key: report[key]
        for key in (
            "schema", "authority", "sourceCommit", "workloadDigest",
            "workloadSourceDigest", "host", "cases", "observer",
        )
    })


class TargetMatrixSignatureRejections(unittest.TestCase):
    def blocked_report(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="hepta-matrix-qualification-") as directory:
            report = MODULE.run_matrix(
                workload_command=None,
                observer_command=None,
                workload_digest="a" * 64,
                source_commit="b" * 40,
                output=Path(directory) / "matrix.json",
                host_id="unprivileged-test-host",
            )
        return report

    def test_dry_run_remains_blocked_and_tampered_digest_is_rejected(self) -> None:
        report = self.blocked_report()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(len(report["cases"]), 16)
        MODULE.validate_report(report)
        report["reportDigest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "report digest mismatch"):
            MODULE.validate_report(report)

    def test_duplicate_matrix_rows_cannot_be_qualified(self) -> None:
        report = self.blocked_report()
        report["cases"].append(copy.deepcopy(report["cases"][0]))
        rehash(report)
        with self.assertRaisesRegex(ValueError, "exactly the sixteen"):
            MODULE.validate_report(report)

    def test_case_factor_drift_is_rejected_even_with_a_matching_hash(self) -> None:
        report = self.blocked_report()
        report["cases"][0]["encoder_topology"] = "replicated"
        rehash(report)
        with self.assertRaisesRegex(ValueError, "matrix factor drift"):
            MODULE.validate_report(report)

    def test_fake_verified_observer_cannot_qualify(self) -> None:
        report = self.blocked_report()
        for case in report["cases"]:
            case["status"] = "measured"
            case.pop("reason", None)
            case["metrics"] = metrics()
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
            "observerId": "self-asserted-observer",
            "verified": True,
            "sourceCommit": report["sourceCommit"],
            "workloadDigest": report["workloadDigest"],
            "reportDigest": MODULE.digest(provisional),
            "metricsDigest": MODULE.digest([
                {"caseId": c["caseId"], "metricsDigest": c["metricsDigest"]}
                for c in report["cases"]
            ]),
            "signatureEd25519": "0" * 128,
        }
        observer["receiptDigest"] = MODULE.digest(observer)
        report["observer"] = observer
        report["status"] = "qualified"
        rehash(report)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "public key"):
                MODULE.validate_report(report)

    def test_trusted_signer_is_required_and_signature_binds_exact_evidence(self) -> None:
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("optional Ed25519 provider absent; unsigned refusal already tested")
            return
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
        pubkey = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        receipt = {
            "observerId": "independent-evaluator-v1",
            "verified": True,
            "sourceCommit": "a" * 40,
            "workloadDigest": "b" * 64,
            "reportDigest": "c" * 64,
            "metricsDigest": "d" * 64,
        }
        receipt["signatureEd25519"] = key.sign(
            MODULE.observer_signing_payload(receipt)
        ).hex()
        kwargs = {
            "source_commit": receipt["sourceCommit"],
            "workload_digest": receipt["workloadDigest"],
            "report_digest": receipt["reportDigest"],
            "metrics_digest": receipt["metricsDigest"],
        }
        with patch.dict(os.environ, {MODULE.TRUSTED_OBSERVER_PUBKEY_ENV: pubkey}):
            MODULE.verify_signed_observer_receipt(receipt, **kwargs)
            changed = {**receipt, "metricsDigest": "e" * 64}
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                MODULE.verify_signed_observer_receipt(changed, **kwargs)
            changed = {**receipt, "signatureEd25519": "0" * 128}
            with self.assertRaisesRegex(ValueError, "signature verification failed"):
                MODULE.verify_signed_observer_receipt(changed, **kwargs)


if __name__ == "__main__":
    unittest.main()
