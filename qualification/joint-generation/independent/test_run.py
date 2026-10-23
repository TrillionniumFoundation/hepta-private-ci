import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from independent import run


class FrozenRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.root = self.repo / "qualification/joint-generation"
        self.independent = self.root / "independent"
        self.independent.mkdir(parents=True)
        self.plan = self.independent / "plan.json"
        self.plan.write_text(json.dumps({"fixture": True}))
        (self.root / "model.py").write_text("BOUND = 1\n")
        for argv in (["git", "init", "-q"], ["git", "add", "."],
                     ["git", "-c", "user.name=Qualification fixture", "-c",
                      "user.email=fixture@example.invalid", "commit", "-qm", "fixture"]):
            subprocess.run(argv, cwd=self.repo, check=True, capture_output=True)
        self.marker = self.independent / "efficient-r2-test-opened.json"
        for name, value in (("ROOT", self.root), ("PLAN", self.plan), ("MARKER", self.marker)):
            manager = patch.object(run, name, value)
            manager.start()
            self.addCleanup(manager.stop)

    def test_committed_protocol_freezes_then_source_changes_reject(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        value = run.check_freeze(receipt)
        self.assertFalse(value["test_opened"])
        self.assertEqual(value["sources"], {"model.py": run.sha(self.root / "model.py")})
        (self.root / "model.py").write_text("BOUND = 2\n")
        with self.assertRaisesRegex(ValueError, "source changed"):
            run.check_freeze(receipt)
        self.assertFalse(self.marker.exists())

    def test_uncommitted_protocol_is_not_accepted_as_frozen(self):
        self.plan.write_text(json.dumps({"fixture": False}))
        with self.assertRaisesRegex(ValueError, "commit all protocol"):
            run.freeze(self.independent / "uncommitted.json")
        self.assertFalse((self.independent / "uncommitted.json").exists())

    def test_experiment_opening_blocks_new_freeze_and_training_preflight(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        self.marker.write_text("{}")
        with self.assertRaisesRegex(ValueError, "already opened"):
            run.freeze(self.independent / "another-freeze.json")
        with self.assertRaisesRegex(ValueError, "already opened"):
            run.check_freeze(receipt)
        self.assertFalse((self.independent / "another-freeze.json").exists())

    def test_freeze_receipt_cannot_be_overwritten(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        before = receipt.read_bytes()
        with self.assertRaises(FileExistsError):
            run.freeze(receipt)
        self.assertEqual(receipt.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
