"""A partial tool failure must remain inspectable and never produce a pass."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from file_family import FileDestination
from qualify_families import qualify


class FamilyQualificationTests(unittest.TestCase):
    archive = None

    def test_duplicate_family_rejected_before_any_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result"
            with self.assertRaisesRegex(ValueError, "invalid family panel"):
                qualify(self.archive, output, ["filesystem", "filesystem"], None)
            self.assertFalse(output.exists())

    def test_changed_replay_checkpoint_is_rejected_before_any_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "models"
            directory.mkdir()
            contents = {"FROZEN_MANIFEST.json": b"{}", "RESULT.json": b"{}"}
            contents.update(
                {
                    f"{order}-seed-{seed}.npz": (
                        self.archive / f"B4_gru-seed-{seed}.npz"
                    ).read_bytes()
                    for seed in range(700, 708)
                    for order in ("ordered", "shuffled")
                }
            )
            for name, data in contents.items():
                (directory / name).write_bytes(data)
            (directory / "SHA256SUMS.json").write_text(
                json.dumps(
                    {
                        name: hashlib.sha256(data).hexdigest()
                        for name, data in contents.items()
                    }
                )
            )
            (directory / "shuffled-seed-707.npz").write_bytes(b"changed checkpoint")
            output = Path(folder) / "result"
            with patch("qualify_families.FileDestination") as primitive:
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    qualify(self.archive, output, ["filesystem"], None, directory)
                primitive.assert_not_called()
            self.assertFalse((output / "RESULT.json").exists())

    def test_error_after_real_effect_retains_physical_bytes_without_success(self):
        def interrupted(task, arm, model, path, browser):
            destination = FileDestination(path, task)
            destination.inspect()
            destination.ensure()
            raise RuntimeError("injected interruption after physical publication")

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result"
            with patch("qualify_families.episode", interrupted):
                with self.assertRaisesRegex(RuntimeError, "physical publication"):
                    qualify(self.archive, output, ["filesystem"], None)
            failure = json.loads((output / "FAILURE.json").read_text())
            self.assertEqual(
                (
                    failure["status"],
                    failure["recorded_episodes"],
                    failure["production_adoption"],
                ),
                ("ENGINEERING_FAIL", 0, False),
            )
            self.assertFalse((output / "RESULT.json").exists())
            with tarfile.open(
                output / "destination-bytes.partial.tar.xz", "r:xz"
            ) as retained:
                effects = [m for m in retained if m.name.endswith("/intent.json")]
                self.assertEqual(len(effects), 1)
                intent = json.loads(retained.extractfile(effects[0]).read())
                value = (
                    retained.extractfile(
                        effects[0].name.removesuffix("intent.json") + "value"
                    )
                    .read()
                    .decode()
                )
                self.assertEqual(value, intent["goal"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    FamilyQualificationTests.archive = args.archive.resolve()
    unittest.main(argv=[__file__, *remaining])
