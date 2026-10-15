"""Mock only pretrained original replay to test full six-block artifact custody.

Synthetic archives and mocked underlying original reviewers cannot establish
real Granite97 model execution or independent scientific effectiveness.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from group_feedback_factorial_aggregate import FACTORS, SEEDS, PROFILES
from group_feedback_factorial_raw_replay import JSONS, MODELS, SOURCE_SHA, replay_original_six

RUN = 38738835065


def fixture(root: Path):
    for seed in SEEDS:
        for profile in PROFILES:
            bundle = root / f"hepta-group-2x2-{seed}-{profile}-{RUN}"
            bundle.mkdir()
            summary = dict(authority="DENY_ALL", production_promotion_permitted=False,
                           source_consistent_not_independently_attested=True,
                           seed=seed, profile=profile)
            for basename in ("factorial-independent-review.json", "external-recheck.json"):
                (bundle / basename).write_text(json.dumps(summary), encoding="utf-8")
            for factor in FACTORS:
                arm = bundle / factor
                arm.mkdir()
                for name in JSONS:
                    (arm / (name + ".json")).write_text(
                        json.dumps({"factor": factor, "seed": seed}), encoding="utf-8")
                for model in MODELS:
                    (arm / ("group-" + model + ".safetensors")).write_bytes(
                        b"dummy-known-not-actual-checkpoint")


def replay_mock(roots):
    root = next(iter(roots.values())).parent
    return json.loads((root / "external-recheck.json").read_text())


def audit_mock(paths):
    if len(paths) != 6:
        raise ValueError("not six")
    return {"passed": True, "winner_selected": False, "production_promotion_permitted": False}


class RawReplayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixture(self.root)

    def audit(self):
        with (patch('group_feedback_factorial_raw_replay.review_factorial',
                    side_effect=replay_mock) as p,
              patch('group_feedback_factorial_raw_replay.audit_six',
                    side_effect=audit_mock) as a):
            result = replay_original_six(self.root, run_id=RUN)
            self.assertEqual(p.call_count, 6)
            self.assertEqual(a.call_count, 1)
            return result

    def test_all_six_blocks_24_raw_arms_and_archive_contents(self):
        result = self.audit()
        self.assertEqual(result["original_run_id"], RUN)
        self.assertEqual(result["original_workflow_source_sha"], SOURCE_SHA)
        self.assertFalse(result["production_promotion_permitted"])
        self.assertFalse(result["physical_execution_attested_independently"])
        self.assertEqual(len(result["original_raw_file_sha256_by_block"]), 6)
        for inventory in result["original_raw_file_sha256_by_block"].values():
            self.assertEqual(len(inventory), len(FACTORS) * (len(JSONS) + len(MODELS)) + 2)
            self.assertTrue(all(len(h) == 64 for h in inventory.values()))

    def test_missing_or_extra_artifact_and_wrong_run_id_denied(self):
        for removed in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                fixture(root)
                if removed:
                    import shutil
                    shutil.rmtree(next(iter(root.iterdir())))
                else:
                    (root / "wrong-run-extra-artifact").mkdir()
                with self.assertRaises(ValueError):
                    replay_original_six(root, run_id=RUN)
        with self.assertRaises(ValueError):
            replay_original_six(self.root, run_id=RUN + 1)
        with self.assertRaises(ValueError):
            replay_original_six(self.root, run_id=RUN, source_commit="0" * 40)

    def test_denies_missing_head_checkpoint_and_raw_source(self):
        bundle = self.root / f"hepta-group-2x2-41-sgd_v1-{RUN}"
        for filename in ("group-attention.safetensors", "protocol.json"):
            item = bundle / "guarded_no_verifier" / filename
            value = item.read_bytes()
            item.unlink()
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                replay_original_six(self.root, run_id=RUN)
            item.write_bytes(value)

    def test_denies_symlinked_raw_file_and_bundle(self):
        bundle = self.root / f"hepta-group-2x2-41-sgd_v1-{RUN}"
        item = bundle / "legacy_oracle" / "report.json"
        target = bundle / "legacy_oracle" / "source.json"
        original = item.read_bytes()
        item.unlink()
        target.write_bytes(original)
        item.symlink_to(target)
        with self.assertRaises(ValueError):
            replay_original_six(self.root, run_id=RUN)
        item.unlink()
        item.write_bytes(original)
        self.audit()

    def test_denies_cross_checker_disagreement_and_forged_status(self):
        bundle = self.root / f"hepta-group-2x2-41-sgd_v1-{RUN}"
        target = bundle / "factorial-independent-review.json"
        value = json.loads(target.read_text())
        value["source_consistent_not_independently_attested"] = False
        target.write_text(json.dumps(value))
        with patch("group_feedback_factorial_raw_replay.review_factorial",
                   side_effect=replay_mock):
            with self.assertRaises(ValueError):
                replay_original_six(self.root, run_id=RUN)

    def test_denies_duplicate_json_and_nonfinite_summary(self):
        bundle = self.root / f"hepta-group-2x2-41-sgd_v1-{RUN}"
        target = bundle / "external-recheck.json"
        original = target.read_text()
        try:
            for bad in ('{"x": 1, "x": 2}', '{"score": NaN}'):
                target.write_text(bad)
                with patch("group_feedback_factorial_raw_replay.review_factorial",
                           side_effect=replay_mock):
                    with self.subTest(bad=bad), self.assertRaises(ValueError):
                        replay_original_six(self.root, run_id=RUN)
        finally:
            target.write_text(original)

    def test_denies_missing_original_full_replay_even_with_all_files(self):
        with patch("group_feedback_factorial_raw_replay.review_factorial",
                   side_effect=ValueError("original check failed")):
            with self.assertRaises(ValueError):
                replay_original_six(self.root, run_id=RUN)


if __name__ == "__main__":
    unittest.main()
