"""No-model regressions for the original two-Reader paired collector."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stage1_reader_pair import pair, read_json, strict_json, verify_inventory

SOURCE = "a" * 40


def fake_rows(tier):
    rows = {}
    for arm in ("empty", "reviewed_minimal", "ranked4"):
        status = "unavailable" if arm == "reviewed_minimal" else "succeeded"
        row = dict(
            question_id="q-1",
            arm=arm,
            family="old-exposed-family",
            phase="capability",
            status=status,
        )
        if status == "succeeded":
            row.update(
                answer="original generated answer",
                f1=0.25 if tier == "smol-135m" else 0.50,
                receipt={
                    "reader_identity": tier,
                    "delivered_evidence": [
                        {"label": "E1", "excerpt": "unchanged original"}
                    ],
                },
            )
        else:
            row["f1"] = None
        rows[("q-1", arm)] = row
    return (
        rows,
        {
            "inventory_digest": tier,
            "revision": tier,
            "planned": 3,
            "successful": 2,
            "unavailable": 1,
        },
        {
            "cases": [
                {
                    "question": {"identity": "q-1"},
                    "family": "old-exposed-family",
                    "phase": "capability",
                }
            ]
        },
    )


class PairedReaderTests(unittest.TestCase):
    def test_original_unavailable_retained_with_wide_bounds(self):
        with patch(
            "stage1_reader_pair.records_from_run",
            side_effect=lambda _root, *, tier, expected_source: fake_rows(tier),
        ):
            report = pair("/not/needed", SOURCE)
        self.assertEqual(report["planned"], 3)
        self.assertEqual(report["matched_succeeded"], 2)
        self.assertEqual(report["unpaired_or_unavailable"], 1)
        self.assertFalse(report["complete_compatible_execution"])
        self.assertAlmostEqual(report["matched_only_mean_f1_delta"], 0.25)
        self.assertAlmostEqual(report["planned_population_delta_lower_bound"], -1 / 6)
        self.assertAlmostEqual(report["planned_population_delta_upper_bound"], 0.5)
        self.assertFalse(report["reader_capacity_is_memory_gain"])

    def test_different_sources_rejected_without_imputation(self):
        def altered(root, *, tier, expected_source):
            rows, info, plan = fake_rows(tier)
            if tier == "smol-1.7b":
                rows[("q-1", "ranked4")]["receipt"]["delivered_evidence"][0][
                    "excerpt"
                ] = "substituted reference evidence"
            return rows, info, plan

        with patch("stage1_reader_pair.records_from_run", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "delivered evidence"):
                pair("/not/needed", SOURCE)

    def test_identity_reuse_rejected(self):
        def reused(root, *, tier, expected_source):
            rows, info, plan = fake_rows(tier)
            info["inventory_digest"] = "same"
            return rows, info, plan

        with patch("stage1_reader_pair.records_from_run", side_effect=reused):
            with self.assertRaisesRegex(ValueError, "reader revision reused"):
                pair("/not/needed", SOURCE)

    def test_incomplete_matched_population_rejected(self):
        def missing(root, *, tier, expected_source):
            rows, info, plan = fake_rows(tier)
            if tier == "smol-1.7b":
                del rows[("q-1", "ranked4")]
            return rows, info, plan

        with patch("stage1_reader_pair.records_from_run", side_effect=missing):
            with self.assertRaisesRegex(ValueError, "incomplete or different"):
                pair("/not/needed", SOURCE)

    def test_manifest_detects_tampering_and_extra_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"original binary receipt"
            (root / "source.txt").write_bytes(payload)
            (root / "SHA256SUMS").write_text(
                hashlib.sha256(payload).hexdigest() + "  ./source.txt\n"
            )
            self.assertEqual(
                verify_inventory(root)["source.txt"],
                hashlib.sha256(payload).hexdigest(),
            )
            (root / "source.txt").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_inventory(root)
            (root / "source.txt").write_bytes(payload)
            (root / "extra.txt").write_text("unlisted")
            with self.assertRaisesRegex(ValueError, "missing/extra"):
                verify_inventory(root)

    def test_raw_jsonl_line_must_reject_ambiguous_fields(self):
        for payload in (b'{"answer":"yes","answer":"no"}', b'{"f1":NaN}'):
            with self.assertRaises(ValueError):
                strict_json(payload)

    def test_duplicate_and_nonfinite_original_json_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.json"
            for content in ('{"x":1,"x":2}', '{"score":NaN}'):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    read_json(path)


if __name__ == "__main__":
    unittest.main()
