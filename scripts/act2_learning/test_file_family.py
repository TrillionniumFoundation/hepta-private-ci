"""Exercise real publication bytes, invocation binding and uncertain observations."""

import tempfile
import json
import shutil
from pathlib import Path
import unittest

from file_family import FileOwner, FileDestination
from run import macro


class FileFamilyTests(unittest.TestCase):
    def test_foreign_effect_and_metadata_only_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = {
                "id": "source",
                "goals": ["shared-goal"],
                "version": 1,
                "fault": "normal",
            }
            original = FileOwner(Path(tmp) / "original", task)
            original.stage(0, "shared-goal", 1)
            original.apply(0, "shared-goal", "invocation", 1)
            folder = next((original.path / "effects").iterdir())
            other = FileOwner(Path(tmp) / "other", dict(task, id="other-task"))
            shutil.copytree(folder, other.path / "effects" / folder.name)
            with self.assertRaisesRegex(ValueError, "identity changed"):
                other.observe()
            intent = folder / "intent.json"
            record = json.loads(intent.read_text())
            record["invocation"] = "changed-with-identical-value"
            intent.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "identity changed"):
                original.audit()

    def test_file_effects_survive_ack_loss_and_partial_failure(self):
        for version in (1, 2):
            for fault in (
                "normal",
                "lost_reply",
                "partial_failure",
                "opaque_after_apply",
            ):
                with (
                    self.subTest(version=version, fault=fault),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    task = {
                        "id": "file-probe",
                        "goals": ["one", "two", "three"],
                        "version": version,
                        "fault": fault,
                    }
                    d = FileDestination(Path(tmp) / "owner", task)
                    claimed = False
                    for _ in range(d.budget):
                        action = macro(d)
                        if action == "stop":
                            view = d.inspect()
                            claimed = bool(view and view["complete"])
                            break
                        getattr(d, action)()
                    result = d.score(claimed)
                    self.assertEqual(
                        (result["complete"], claimed, result["duplicate_effects"]),
                        (
                            fault != "opaque_after_apply",
                            fault != "opaque_after_apply",
                            0,
                        ),
                    )
                    self.assertEqual(result["lost_replies"], int(fault == "lost_reply"))

    def test_owner_rejects_changed_intent_version_and_tampered_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = {
                "id": "file-probe",
                "goals": ["one", "two"],
                "version": 2,
                "fault": "normal",
            }
            owner = FileOwner(Path(tmp) / "owner", task)
            owner.stage(0, "one", 2)
            owner.apply(0, "one", "operation-1", 2)
            self.assertEqual(
                owner.apply(0, "one", "operation-1", 2)["status"], "deduplicated"
            )
            with self.assertRaisesRegex(ValueError, "different intent"):
                owner.apply(1, "two", "operation-1", 2)
            with self.assertRaisesRegex(ValueError, "version mismatch"):
                owner.apply(0, "one", "operation-1", 1)
            with self.assertRaisesRegex(ValueError, "version mismatch"):
                owner.apply(0, "one", "operation-1", True)
            with self.assertRaisesRegex(ValueError, "second invocation"):
                owner.apply(0, "one", "operation-2", 2)
            next((owner.path / "effects").glob("*/value")).write_text(
                '{"content":"corrupt"}'
            )
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                owner.observe()


if __name__ == "__main__":
    unittest.main()
