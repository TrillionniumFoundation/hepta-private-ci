"""Original timed reader stage must merge across independent CPU hosts."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from canonical_model_stage import IDENTITY, REVISION, normalize, sha, verify


def original_stage(root, seconds):
    inventory = {"inventory_digest": IDENTITY}
    publisher = {
        "repository": "Qwen/Qwen2.5-3B-Instruct",
        "revision": REVISION,
    }
    for filename, value in (
        ("inventory.json", inventory),
        ("publisher.json", publisher),
    ):
        (root / filename).write_text(json.dumps(value) + "\n")
    stage = {
        "tier": "qwen-3b",
        "repository": "Qwen/Qwen2.5-3B-Instruct",
        "revision": REVISION,
        "inventory_sha256": sha((root / "inventory.json").read_bytes()),
        "publisher_sha256": sha((root / "publisher.json").read_bytes()),
        "seconds": seconds,
        "model_file_bytes": 6183463389,
        "research_only": True,
        "production_accepted": False,
    }
    (root / "stage.json").write_text(json.dumps(stage, indent=2) + "\n")


class FrozenShardedStageTests(unittest.TestCase):
    def test_real_time_varies_but_canonical_stage_sha_is_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = [Path(tmp) / name for name in ("first", "second")]
            for root, elapsed in zip(roots, (45.50915949, 93.753)):
                root.mkdir()
                original_stage(root, elapsed)
            a, b = (normalize(root) for root in roots)
            self.assertEqual(a["canonical_stage_sha256"], b["canonical_stage_sha256"])
            self.assertNotEqual(a["original_stage_sha256"], b["original_stage_sha256"])
            self.assertNotEqual(a["staging_seconds"], b["staging_seconds"])
            for root in roots:
                self.assertNotIn(
                    "seconds", json.loads((root / "stage.json").read_text())
                )
                self.assertTrue((root / "stage-observation.json").is_file())

    def test_tampered_inventory_and_nonfinite_time_fail_closed(self):
        for corrupt in ("inventory", "nan", "negative"):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                original_stage(root, 2.0)
                old_stage = (root / "stage.json").read_bytes()
                if corrupt == "inventory":
                    (root / "inventory.json").write_text("{}")
                else:
                    stage = json.loads(old_stage)
                    stage["seconds"] = float("nan") if corrupt == "nan" else -1
                    (root / "stage.json").write_text(json.dumps(stage))
                    old_stage = (root / "stage.json").read_bytes()
                with self.assertRaises(ValueError):
                    normalize(root)
                self.assertEqual((root / "stage.json").read_bytes(), old_stage)

    def test_duplicate_staging_refuses_double_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_stage(root, 45.0)
            normalize(root)
            with self.assertRaises(ValueError):
                normalize(root)

    def test_exact_32_shard_costs_and_frozen_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage_sha = None
            for phase in ("calibration", "evaluation"):
                for case in range(8):
                    for part in range(2):
                        folder = (
                            root / "shards" / phase / f"memory-{phase}-{case}-{part}"
                        )
                        folder.mkdir(parents=True)
                        original_stage(folder, 40.0 + case / 10 + part / 100)
                        normalize(folder)
                        digest = sha((folder / "stage.json").read_bytes())
                        if stage_sha is None:
                            stage_sha = digest
                        (folder / "sha-pins.json").write_text(
                            json.dumps({"stage.json": digest})
                        )
            (root / "calibration").mkdir()
            (root / "calibration/frozen-policy.json").write_text(
                json.dumps({"stage_sha256": stage_sha})
            )
            report = verify(root)
            self.assertEqual(report["canonical_stage_sha256"], stage_sha)
            self.assertEqual(report["phases"]["calibration"]["hosts"], 16)
            self.assertEqual(report["phases"]["evaluation"]["hosts"], 16)
            self.assertEqual(len(report["staging_observation_sha256"]), 32)
            self.assertFalse(report["production_accepted"])
            broken = (
                root / "shards/evaluation/memory-evaluation-0-0/stage-observation.json"
            )
            broken.write_text("{}")
            with self.assertRaises(ValueError):
                verify(root)


if __name__ == "__main__":
    unittest.main()
