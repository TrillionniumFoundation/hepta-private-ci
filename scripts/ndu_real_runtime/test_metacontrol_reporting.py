"""Manufactured reporting regressions; no independent policy evidence."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from . import metacontrol_study as study
from .metacontrol import _digest
from .test_metacontrol import CRITIC
from .test_metacontrol_study import fixture_rows


class MetacontrolReportingTests(unittest.TestCase):
    def run_fixture(self, future):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            options = {
                "expected_source_sha256": _digest(study.source_manifest()),
                "context": CRITIC,
                "latency_weight": 0.0,
                "allow_fixtures": True,
                "output": root / "report",
            }
            for phase in ("train", "calibration", "future"):
                rows = future if phase == "future" else fixture_rows(phase)
                raw = b"".join(
                    (json.dumps(row, separators=(",", ":")) + "\n").encode()
                    for row in rows
                )
                path = root / f"{phase}.jsonl"
                path.write_bytes(raw)
                options[phase] = path
                options[phase + "_sha256"] = hashlib.sha256(raw).hexdigest()
            return study.run_study(**options)

    def test_missing_contexts_cannot_report_positive_subset_as_cohort_gain(self):
        # Retain positive WRITE_TEXT comparisons, but omit the negative ones.
        # Every source is still represented; source count alone is insufficient.
        future = [
            row
            for row in fixture_rows("future")
            if not (
                row["observation"]["action"] == "WRITE_TEXT"
                and row["observation"]["state"]["features"] == (-1.0,)
            )
        ]
        report = self.run_fixture(future)
        self.assertEqual(report["incomplete_table_count"], 10)
        self.assertIsNone(
            report["summaries"]["conditional"]["source_balanced_net_gain"]
        )
        for summary in report["summaries"].values():
            self.assertIsNone(summary["source_balanced_net_gain"])
            self.assertFalse(summary["cohort_complete"])
            self.assertEqual(
                (summary["contexts"], summary["observed_contexts"]), (20, 10)
            )
            self.assertEqual(summary["observed_source_groups"], 10)
        subset = report["summaries"]["conditional"]["observed_subset"]
        self.assertEqual((subset["contexts"], subset["source_groups"]), (10, 10))
        self.assertAlmostEqual(subset["source_balanced_net_gain"], 0.18)
        for contrast in report["contrasts"].values():
            self.assertIsNone(contrast["mean"])
            self.assertIsNone(contrast["interval"])
            self.assertEqual(
                (contrast["cohort_contexts"], contrast["unpaired_contexts"]),
                (20, 10),
            )
        self.assertAlmostEqual(
            report["contrasts"]["STOP"]["observed_subset"]["mean"], 0.18
        )
        self.assertEqual(report["decision"], "HOLD_NO_GO")

    def test_unsupported_policy_preserves_its_own_pairing_denominator(self):
        future = fixture_rows("future")
        for row in future:
            if row["observation"]["source_group"] == "future/0":
                row["observation"]["state"]["features"] = (2.0,)
                row["evidence"]["state_sha256"] = _digest(row["observation"]["state"])
        report = self.run_fixture(future)
        self.assertEqual(report["incomplete_table_count"], 0)
        self.assertIsNone(
            report["summaries"]["conditional"]["source_balanced_net_gain"]
        )
        self.assertEqual(report["summaries"]["STOP"]["source_balanced_net_gain"], 0.0)
        self.assertTrue(report["summaries"]["STOP"]["cohort_complete"])
        contrast = report["contrasts"]["STOP"]
        self.assertIsNone(contrast["mean"])
        self.assertEqual(
            (
                contrast["cohort_source_groups"],
                contrast["paired_source_groups"],
                contrast["cohort_contexts"],
                contrast["paired_contexts"],
                contrast["unpaired_contexts"],
            ),
            (10, 9, 20, 18, 2),
        )
        self.assertEqual(contrast["observed_subset"]["source_groups"], 9)

    def test_complete_and_partial_contrasts_preserve_source_equal_weighting(self):
        rows = [
            {
                "source_group": source,
                "policies": {
                    "candidate": {"net_gain_after_planning": gain},
                    "baseline": {"net_gain_after_planning": 0.0},
                },
            }
            for source, gain in (("A", 1.0), ("A", 1.0), ("A", 1.0), ("B", 0.0))
        ]
        complete = study._contrast(rows, "candidate", "baseline")
        self.assertEqual(complete["mean"], 0.5)
        rows[0]["policies"]["baseline"]["net_gain_after_planning"] = None
        partial = study._contrast(rows, "candidate", "baseline")
        self.assertIsNone(partial["mean"])
        self.assertIsNone(partial["interval"])
        self.assertFalse(partial["cohort_complete"])
        self.assertEqual(partial["paired_source_groups"], 2)
        self.assertEqual(partial["observed_subset"]["mean"], 0.5)
        self.assertEqual(partial["unpaired_contexts"], 1)
        self.assertTrue(complete["cohort_complete"])
        self.assertEqual(complete["mean"], complete["observed_subset"]["mean"])
        self.assertEqual(complete["interval"], complete["observed_subset"]["interval"])


if __name__ == "__main__":
    unittest.main()
