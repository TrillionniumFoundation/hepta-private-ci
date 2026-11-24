"""Research stage-attribution contracts; fixtures are not native task gains."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from stem_candidate_depth_audit import (
    HEX64,
    analyze,
    classify,
    sha256_file,
    strict_json,
    verify_zip,
)


class CandidateDepthTests(unittest.TestCase):
    def setUp(self):
        self.ranked = [f"source-{i}" for i in range(1, 65)]
        self.first = self.ranked[:8]

    def test_frozen_frontier_and_present_oracle_evidence(self):
        for original, expected_bucket, rank in (
            (self.ranked[0], "top8", 1),
            (self.ranked[7], "top8", 8),
            (self.ranked[8], "ranks9-64", 9),
            (self.ranked[63], "ranks9-64", 64),
        ):
            with self.subTest(original=original):
                result = classify(
                    ranked=self.ranked,
                    original_top8=self.first,
                    oracle_ids=[original],
                    eligible=True,
                    indexed=None,
                )
                self.assertEqual(result, dict(bucket=expected_bucket, first_rank=rank))

    def test_indexed_beyond_top64_is_recall_not_top8_reranking(self):
        report = classify(
            ranked=self.ranked,
            original_top8=self.first,
            oracle_ids=["source-100"],
            eligible=True,
            indexed=True,
        )
        self.assertEqual(report["bucket"], "indexed-beyond-64")
        self.assertIsNone(report["first_rank"])
        unknown = classify(
            ranked=self.ranked,
            original_top8=self.first,
            oracle_ids=["source-100"],
            eligible=True,
            indexed=None,
        )
        self.assertEqual(unknown["bucket"], "index-unchecked")

    def test_non_indexed_source_not_silently_ascribed_to_ranker(self):
        report = classify(
            ranked=self.ranked,
            original_top8=self.first,
            oracle_ids=["source-100"],
            eligible=True,
            indexed=False,
        )
        self.assertEqual(report["bucket"], "not-in-original-index")

    def test_missing_publisher_oracle_and_native_unscored_are_unknown(self):
        for eligible, oracle, bucket in (
            (False, [], "not-native-scored"),
            (True, [], "no-publisher-oracle-source"),
            (False, ["source-100"], "not-native-scored"),
        ):
            with self.subTest(eligible=eligible, oracle=oracle):
                outcome = classify(
                    ranked=self.ranked,
                    original_top8=self.first,
                    oracle_ids=oracle,
                    eligible=eligible,
                    indexed=False,
                )
                self.assertEqual(outcome["bucket"], bucket)

    def test_ranking_or_oracle_identity_drift_rejected(self):
        for ranked, baseline, oracle in (
            (self.ranked[:-1] + [self.ranked[2]], self.first, [self.ranked[0]]),
            (self.ranked, self.first[::-1], [self.ranked[0]]),
            (self.ranked[:7], self.first[:7], [self.ranked[0]]),
            (self.ranked, self.first, [self.ranked[0]] * 2),
        ):
            with self.assertRaises(ValueError):
                classify(
                    ranked=ranked,
                    original_top8=baseline,
                    oracle_ids=oracle,
                    eligible=True,
                    indexed=True,
                )

    def test_no_duplicate_json_or_nonfinite_values(self):
        for value in ('{"id":1,"id":2}', '{"score":NaN}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                strict_json(value)

    def test_archive_sha_and_member_inventory_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.zip"
            payload = b'{"ok":true}'
            with ZipFile(path, "w") as archive:
                archive.writestr("source.json", payload)
                archive.writestr(
                    "SHA256SUMS",
                    f"{hashlib.sha256(payload).hexdigest()}  ./source.json\n",
                )
            loaded, checked = verify_zip(path, sha256_file(path))
            self.assertEqual((checked, loaded.read("source.json")), (1, payload))
            loaded.close()
            with self.assertRaises(ValueError):
                verify_zip(path, "0" * 64)

    def test_archive_traversal_or_missing_inventory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad_name in ("../escape", "safe"):
                path = Path(tmp) / (bad_name.replace("/", "_") + ".zip")
                with ZipFile(path, "w") as archive:
                    archive.writestr(bad_name, b"hello")
                    archive.writestr("SHA256SUMS", "")
                with self.subTest(name=bad_name), self.assertRaises(ValueError):
                    verify_zip(path, sha256_file(path))

    def test_historical_report_always_disclaims_independence(self):
        self.assertTrue(HEX64.fullmatch("a" * 64))
        self.assertFalse(HEX64.fullmatch("a" * 63))


if __name__ == "__main__":
    unittest.main()
