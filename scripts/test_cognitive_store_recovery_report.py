#!/usr/bin/env python3
"""Synthetic report validator regressions; no benchmark or target-host claim."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import cognitive_store_recovery_report as gate


def fixture():
    return {"schema": "hepta.cognitive-store-recovery-perf.v1", "sourceCommit": "a" * 40,
            "testedCommit": "b" * 40, "testedTree": "c" * 40, "debugAssertions": False,
            "records": 256, "repetitions": 3, "initialAnchorAcquisitionUs": 1,
            "initialAnchorHeldTransactionUs": 2, "samplingIntervalMs": 5, "sampleCount": 4,
            "rssPeakSampledBytes": 1024, "rootBaselineBytes": 100,
            "rootPeakSampledBytes": 500, "additionalDiskPeakSampledBytes": 400,
            "fixtureAuthorityVerificationUs": [0] * 6, "claimBoundary": dict(gate.BOUNDARY),
            "runs": [{"iteration": index, "descriptorRecoveryUs": 4, "anchorAcquisitionUs": 0,
                      "anchorHeldTransactionUs": 3, "pageUs": [2], "retainedRecords": 256,
                      "rootBytesIncludingRetainedGenerations": 300 + index * 200,
                      "activeDatabaseBytes": 100, "exactCutPreserved": True} for index in range(3)]}


class RecoveryReportTests(unittest.TestCase):
    def setUp(self):
        self.report = fixture()

    def validate(self, **kwargs):
        return gate.validate(self.report, source_commit="a" * 40, tested_commit="b" * 40,
                             tested_tree="c" * 40, records=256, **kwargs)

    def test_complete_fixture_is_not_host_or_slo_acceptance(self):
        result = self.validate(require_rss=True)
        self.assertEqual(result["result"], "valid_measurement")
        self.assertFalse(result["targetHostQualified"])
        self.assertFalse(result["sloAccepted"])

    def test_each_candidate_identity_is_required(self):
        for key in ("sourceCommit", "testedCommit", "testedTree"):
            with self.subTest(key=key):
                self.report = fixture()
                self.report[key] = "f" * 40
                with self.assertRaises(ValueError): self.validate()

    def test_debug_build_rejected(self):
        self.report["debugAssertions"] = True
        with self.assertRaises(ValueError): self.validate()

    def test_wrong_record_profile_rejected(self):
        self.report["records"] = 128
        with self.assertRaises(ValueError): self.validate()

    def test_repetition_floor_not_weakened(self):
        with self.assertRaises(ValueError): self.validate(minimum_repetitions=1)

    def test_truncated_runs_rejected(self):
        self.report["runs"].pop()
        with self.assertRaises(ValueError): self.validate()

    def test_duplicate_or_reordered_iterations_rejected(self):
        self.report["runs"][1]["iteration"] = 0
        with self.assertRaises(ValueError): self.validate()

    def test_lost_records_rejected(self):
        self.report["runs"][1]["retainedRecords"] = 255
        with self.assertRaises(ValueError): self.validate()

    def test_changed_cut_rejected(self):
        self.report["runs"][1]["exactCutPreserved"] = False
        with self.assertRaises(ValueError): self.validate()

    def test_missing_page_measurement_rejected(self):
        self.report["runs"][1]["pageUs"] = []
        with self.assertRaises(ValueError): self.validate()

    def test_claim_escalations_rejected(self):
        for key in gate.BOUNDARY:
            with self.subTest(key=key):
                self.report = fixture()
                self.report["claimBoundary"][key] = not gate.BOUNDARY[key]
                with self.assertRaises(ValueError): self.validate()

    def test_bool_is_not_measurement_integer(self):
        self.report["runs"][0]["anchorAcquisitionUs"] = False
        with self.assertRaises(ValueError): self.validate()

    def test_negative_or_saturated_latency_rejected(self):
        for value in (-1, (1 << 64) - 1):
            with self.subTest(value=value):
                self.report["runs"][0]["descriptorRecoveryUs"] = value
                with self.assertRaises(ValueError): self.validate()

    def test_resource_samples_required(self):
        self.report["sampleCount"] = 0
        with self.assertRaises(ValueError): self.validate()

    def test_disk_growth_accounting_checked(self):
        self.report["additionalDiskPeakSampledBytes"] = 401
        with self.assertRaises(ValueError): self.validate()

    def test_sampled_peak_is_not_misrepresented_as_absolute_peak(self):
        self.assertLess(self.report["rootPeakSampledBytes"], self.report["runs"][-1]["rootBytesIncludingRetainedGenerations"])
        self.validate()

    def test_rss_absence_is_explicit_and_profile_dependent(self):
        self.report["rssPeakSampledBytes"] = None
        self.validate()
        with self.assertRaises(ValueError): self.validate(require_rss=True)

    def test_final_use_verifier_coverage_required(self):
        self.report["fixtureAuthorityVerificationUs"] = [1] * 3
        with self.assertRaises(ValueError): self.validate()

    def test_unknown_and_missing_fields_rejected(self):
        self.report["new"] = 0
        with self.assertRaises(ValueError): self.validate()
        self.report = fixture()
        del self.report["initialAnchorHeldTransactionUs"]
        with self.assertRaises(ValueError): self.validate()

    def test_bounded_loader_rejects_duplicate_float_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            for content in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":1.1}', b'x' * (gate.MAX_REPORT_BYTES + 1)):
                path.write_bytes(content)
                with self.assertRaises(ValueError): gate.load_report(path)

    def test_report_loader_binds_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            path.write_text(json.dumps(self.report))
            result, digest = gate.load_report(path)
            self.assertEqual(result, self.report)
            self.assertEqual(len(digest), 64)
            link = path.with_name("link")
            link.symlink_to(path)
            with self.assertRaises(OSError): gate.load_report(link)


if __name__ == "__main__":
    unittest.main()
