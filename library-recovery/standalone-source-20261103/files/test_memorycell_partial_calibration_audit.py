"""Actual-archive tamper/regression tests for two already-completed Qwen shards."""

from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
import json

from memorycell_partial_calibration_audit import (
    LABELS, PREP, SHARDS, SOURCE_COMMIT, MODEL, audit, parse, sha,
)

SOURCE = Path(__file__).resolve().parent


class ArchivedCalibrationTest(unittest.TestCase):
    def test_real_answer_and_support_census_is_anchored(self):
        report = audit(SOURCE)
        self.assertEqual(report['source_commit'], SOURCE_COMMIT)
        self.assertEqual(report['model_identity'], MODEL)
        self.assertEqual(report['observed_model_calls'], 5)
        self.assertEqual(report['preregistered_calibration_calls'], 40)
        self.assertEqual(report['strict_success'], 0)
        self.assertEqual(report['required_sources_in_context'], 4)
        self.assertEqual(report['annotation_support_in_citations'], 1)
        self.assertEqual(sum(x['input_tokens'] for x in report['observations']), 5679)
        self.assertFalse(report['qualifying_result'])
        self.assertFalse(report['complete_calibration'])
        self.assertFalse(report['production_accepted'])
        self.assertEqual(len(report['observations']), 5)
        self.assertEqual({x['case_index'] for x in report['observations']}, {0, 2})

    def test_cross_host_stage_requires_canonicalization(self):
        report = audit(SOURCE)
        self.assertTrue(report['raw_host_stage_pins_differ'])
        self.assertEqual(len(report['distinct_original_stage_hashes']), 2)
        self.assertEqual(
            report['canonical_model_stage_sha256'],
            '3c67750e9b39ed11dc78a449861cabfd0ecabe8abc6a24891bd90971dd791bd2',
        )
        self.assertTrue(report['source_inventory_pins_agree'])

    def _clone(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        for name in (PREP[0], LABELS[0], *(t[0] for t in SHARDS)):
            shutil.copyfile(SOURCE / name, root / name)
        self.addCleanup(tmp.cleanup)
        return root

    def test_changed_original_model_answer_is_rejected(self):
        root = self._clone()
        path = root / SHARDS[0][0]
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, 'outer SHA'):
            audit(root)

    def test_changed_plan_before_calibration_is_rejected(self):
        root = self._clone()
        path = root / PREP[0]
        with open(path, 'ab') as target:
            target.write(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'outer SHA'):
            audit(root)

    def test_missing_shard_cannot_be_called_completed_calibration(self):
        root = self._clone()
        (root / SHARDS[1][0]).unlink()
        with self.assertRaises(ValueError):
            audit(root)

    def test_untrusted_json_duplicate_keys_and_nonfinite_reject(self):
        for payload in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse(payload)

    def test_published_shard_zips_have_distinct_outer_hashes(self):
        for name, digest, *rest in SHARDS:
            with self.subTest(name=name):
                self.assertEqual(sha((SOURCE / name).read_bytes()), digest)


if __name__ == '__main__':
    unittest.main()
