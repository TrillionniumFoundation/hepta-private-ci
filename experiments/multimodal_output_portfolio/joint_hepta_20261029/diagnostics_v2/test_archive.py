"""Real emitted bytes, traversal rejection, and preservation of failed evidence."""

import gzip
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import torch

from .archive import archive_run, audit_trajectory, file_identity
from ..checkpoint import save_checkpoint
from ..mechanism_data import batch
from ..media import utility
from ..model import JointGenerator
from ..runtime import execute, make_profile


class CompactArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "meter"
        self.root.mkdir()
        (self.root / "process.log").write_bytes(b"explicit unit-test fixture log\n")
        process = {"process_log_sha256": file_identity(self.root / "process.log")["sha256"],
                   "exit_code": 0, "timed_out": False, "child_reaped": True}
        (self.root / "PROCESS_RECEIPT.json").write_text(json.dumps(process))
        files = {"unit_fixture.py": "a" * 64}
        snapshot = {"files": files, "sha256": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        (self.root / "SOURCE_RECEIPT.json").write_text(json.dumps({"before": snapshot, "after": snapshot, "source_bytes_unchanged": True}))
        torch.set_num_threads(1)
        torch.manual_seed(17)
        self.model = JointGenerator(width=8)
        self.public, target = batch([0], "archive-unit")
        self.profile = make_profile()
        self.trajectory = "run/arm/development/source-0/TRAJECTORY.json"
        execute(self.model, self.public, lambda sample: utility(sample, target).item(),
                self.root / Path(self.trajectory).parent, seed=17, context_id="archive-unit.0",
                source_id="synthetic.archive-unit.0", profile=self.profile)

    def tearDown(self):
        self.temporary.cleanup()

    def test_original_bytes_roundtrip_and_deterministic_compact_output(self):
        (self.root / "run/RESULT.json").write_bytes(b'{"unit_fixture": true}\n')
        model_path = self.root / "run/arm/MODEL.pt"
        save_checkpoint(model_path, self.model, self.model.encode(self.public),
                        torch.Generator().manual_seed(17), self.profile, self.public)
        first = archive_run(self.root, self.directory / "compact1")
        second = archive_run(self.root, self.directory / "compact2")
        self.assertTrue(first["audit"]["integrity_passed"])
        self.assertEqual(first, second)
        self.assertEqual(first["audit"]["actual_output_files_verified"], 4)
        self.assertEqual(first["audit"]["receipt_checks"]["checkpoint_files_verified"], 1)
        compact = self.directory / "compact1"
        self.assertEqual(gzip.decompress((compact / "original/run/RESULT.json.gz").read_bytes()),
                         (self.root / "run/RESULT.json").read_bytes())
        self.assertEqual((compact / "original/run/arm/MODEL.pt").read_bytes(), model_path.read_bytes())
        with tarfile.open(compact / "TRAJECTORIES.tar.gz", "r:gz") as archived:
            self.assertEqual(archived.extractfile(self.trajectory).read(),
                             (self.root / self.trajectory).read_bytes())
        self.assertFalse(list(compact.rglob("image.png")))

    def test_tampered_real_media_fails_audit_but_preserves_original_record(self):
        image = self.root / Path(self.trajectory).parent / "outputs/image.png"
        image.write_bytes(image.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "output bytes"):
            audit_trajectory(self.root, self.trajectory)
        report = archive_run(self.root, self.directory / "tampered-compact")
        self.assertFalse(report["audit"]["integrity_passed"])
        self.assertEqual(report["audit"]["trajectory_chains_verified"], 0)
        self.assertTrue((self.directory / "tampered-compact/TRAJECTORIES.tar.gz").is_file())

    def test_symlink_and_parent_traversal_never_read_outside_content(self):
        secret = self.directory / "outside.bin"
        secret.write_bytes(b"EXTERNAL_CONTENT_MUST_NOT_BE_COPIED")
        image = self.root / Path(self.trajectory).parent / "outputs/image.png"
        image.unlink()
        image.symlink_to(secret)
        with self.assertRaises(ValueError):
            audit_trajectory(self.root, "../outside.bin")
        report = archive_run(self.root, self.directory / "unsafe-compact")
        self.assertFalse(report["audit"]["integrity_passed"])
        self.assertTrue(any("symlink" in item["error"].lower() for item in report["audit"]["errors"]))
        with gzip.open(self.directory / "unsafe-compact/INPUT_MANIFEST.json.gz") as handle:
            inventory = json.load(handle)
        self.assertNotIn(str(image.relative_to(self.root)), inventory["files"])

    def test_invalid_state_chain_and_partial_process_are_retained(self):
        trajectory = self.root / self.trajectory
        raw = json.loads(trajectory.read_bytes())
        raw["state_chain"][-1]["remaining_budget"] -= 1
        trajectory.write_text(json.dumps(raw))
        receipt = self.root / "PROCESS_RECEIPT.json"
        process = json.loads(receipt.read_bytes())
        process.update(exit_code=-15, timed_out=True)
        receipt.write_text(json.dumps(process))
        (self.root / "run/RESULTS.partial.json").write_bytes(b'{"status":"partial"}\n')
        report = archive_run(self.root, self.directory / "partial-compact")
        self.assertFalse(report["audit"]["integrity_passed"])
        self.assertFalse(report["audit"]["process_completed_successfully"])
        preserved = {item["source_path"] for item in report["preserved_originals"]}
        self.assertIn("run/RESULTS.partial.json", preserved)
        self.assertIn(self.trajectory, preserved)


if __name__ == "__main__":
    unittest.main()
