"""Pure synthetic structural tests; never claim authentic model invocation."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import run_prepared_pair as pair
import test_run_prepared_pair as fixtures
import verify_prepared_pair_report as verify


def synthetic_report() -> dict:
    pairs = []
    for cells in pair.SCALES:
        for arm in pair.ARMS:
            originals = {
                mode: fixtures.receipt(mode, arm, cells)
                for mode in pair.MODES
            }
            pairs.append(pair.validate_pair(originals, arm, cells, fixtures.TRACE, 8))
    return {
        "schema": pair.SCHEMA,
        "evidence_kind": "UNVERIFIED_HOST_UNTRAINED_KERNEL_ONLY",
        "source_trace_sha256": fixtures.TRACE,
        "source_binary_sha256_claim": hashlib.sha256(b"binary").hexdigest(),
        "source_binary_independently_attested": False,
        "arms": list(pair.ARMS),
        "scales": list(pair.SCALES),
        "pair_count": 20,
        "native_subprocess_count": 40,
        "hosted_ci_run_id_claim": "",
        "pairs": pairs,
        "private_model_parameter_budgets_matched": False,
        "real_training_or_model_efficacy": False,
        "real_encoder_model_batch_queue_wal_cas_cost": False,
        "target_host_certified": False,
        "ndu_eligible": False,
        "production_qualification": False,
        "decision": "NO_PROMOTION",
        "limitations": ["synthetic only", "not signed", "not trained"],
    }


class IndependentPairedAuditTests(unittest.TestCase):
    def test_all_40_raw_observations_recomputed_not_promoted(self) -> None:
        report = verify.audit(synthetic_report())
        self.assertEqual(report["original_raw_mode_receipts_recomputed"], 40)
        self.assertEqual(report["exact_checkpoint_frontier_pairs_rechecked"], 20)
        self.assertFalse(report["production_qualification"])
        self.assertEqual(report["decision"], "NO_PROMOTION")

    def test_submitted_binary_must_match_content_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "bin"
            binary.write_bytes(b"binary")
            self.assertTrue(
                verify.audit(synthetic_report(), binary=binary)["binary_bytes_checked_against_report"]
            )
            binary.write_bytes(b"other")
            with self.assertRaisesRegex(ValueError, "physical executable SHA"):
                verify.audit(synthetic_report(), binary=binary)

    def test_one_pair_missing_duplicate_or_bad_count_rejected(self) -> None:
        for kind in ("missing", "duplicate", "bad_count", "bad_scale"):
            row = synthetic_report()
            if kind == "missing":
                row["pairs"].pop()
            elif kind == "duplicate":
                row["pairs"][-1] = copy.deepcopy(row["pairs"][0])
            elif kind == "bad_count":
                row["native_subprocess_count"] = 39
            else:
                row["pairs"][0]["cells"] = 257
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    verify.audit(row)

    def test_modified_raw_metric_or_digest_rejected(self) -> None:
        for field in ("p99_tick_nanos", "process_wall_micros", "frontier_digest"):
            row = synthetic_report()
            raw = row["pairs"][0]["raw_mode_receipts"]["prepared"]
            raw[field] = (raw[field] + 1 if isinstance(raw[field], int)
                          else hashlib.sha256(b"tampered").hexdigest())
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    verify.audit(row)

    def test_rewritten_derived_metric_without_raw_evidence_rejected(self) -> None:
        row = synthetic_report()
        row["pairs"][1]["legacy_to_prepared_p99_ratio"] = "9999.000000"
        with self.assertRaisesRegex(ValueError, "not reproducible"):
            verify.audit(row)

    def test_claimed_production_or_host_proof_is_rejected(self) -> None:
        for key in (
            "production_qualification", "ndu_eligible",
            "real_training_or_model_efficacy",
            "source_binary_independently_attested",
            "private_model_parameter_budgets_matched",
        ):
            row = synthetic_report()
            row[key] = True
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    verify.audit(row)

    def test_duplicate_json_and_bad_nan_report_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
                path.write_bytes(raw)
                with self.subTest(raw=raw):
                    with self.assertRaises(ValueError):
                        verify.load_report(path)

    def test_forged_repeated_scale_or_unknown_binary_digest_rejected(self) -> None:
        row = synthetic_report()
        row["source_binary_sha256_claim"] = "a" * 63
        with self.assertRaisesRegex(ValueError, "digest"):
            verify.audit(row)
        row = synthetic_report()
        row["pairs"][0]["events"] = 9
        with self.assertRaises(ValueError):
            verify.audit(row)


if __name__ == "__main__":
    unittest.main()
