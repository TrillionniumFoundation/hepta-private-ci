"""Mutation controls for the consumed original readback; no dynamics are run."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from qualification.hcsn_consolidated_readback import readback


class ConsumedReadbackControls(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        self.snapshot = Path(self.directory.name) / "snapshot"
        self.snapshot.mkdir()
        manifest = readback.load_manifest(readback.ROOT)
        sources = {row["source"] for row in manifest["files"]}
        sources.update(readback.CURRENT_WORKFLOWS)
        sources.add(readback.CURRENT_REQUEST)
        sources.add("qualification/hcsn_consolidated_readback/SNAPSHOT.json")
        for relative in sources:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(readback.ROOT / relative, target)

    def reject_changed_bytes(self, relative):
        target = self.root / relative
        raw = bytearray(target.read_bytes())
        self.assertTrue(raw)
        raw[len(raw) // 2] ^= 1
        target.write_bytes(raw)
        with self.assertRaises(ValueError):
            readback.prepare_snapshot(self.root, self.snapshot)

    def test_exact_snapshot_keeps_live_successor_and_originals_separate(self):
        before = (self.root / readback.CURRENT_REQUEST).read_bytes()
        manifest = readback.prepare_snapshot(self.root, self.snapshot)
        readback.verify_unchanged_snapshot(self.snapshot, manifest)
        self.assertEqual((self.root / readback.CURRENT_REQUEST).read_bytes(), before)
        self.assertEqual(readback.digest(before), readback.CURRENT_REQUEST_SHA256)
        self.assertEqual(
            readback.digest((self.snapshot / readback.CURRENT_REQUEST).read_bytes()),
            "0db12c26ccf722406f62542e35d34982122986f077dc5a3f0806b2e89e10d23b",
        )
        for relative in readback.CURRENT_WORKFLOWS:
            self.assertNotEqual(
                (self.root / relative).read_bytes(),
                (self.snapshot / relative).read_bytes(),
            )

    def test_consumed_admission_changed_key_rejects(self):
        self.reject_changed_bytes(
            "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/evidence/attempt001-20261119/originals/ADMISSION.json"
        )

    def test_original_red_cannot_be_promoted(self):
        path = (
            self.root
            / "qualification/hcsn_currentstate_n256_warm1_sparse/evidence/attempt001-20261119/originals/TERMINAL.json"
        )
        record = json.loads(path.read_text())
        self.assertEqual(record["original_bitwise_gate"], "RED")
        record["original_bitwise_gate"] = "PASS"
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            readback.prepare_snapshot(self.root, self.snapshot)

    def test_result_archive_corruption_rejects(self):
        self.reject_changed_bytes(
            "qualification/hcsn_currentstate_n256_warm1_sparse/evidence/attempt001-20261119/artifact-14501927547.zip"
        )

    def test_current_request_cannot_roll_back_to_original(self):
        archived = (
            self.root
            / "qualification/hcsn_consolidated_readback/originals/terminal-publication-REQUEST.json"
        )
        shutil.copyfile(archived, self.root / readback.CURRENT_REQUEST)
        with self.assertRaisesRegex(
            ValueError, "current coupling repair request drift"
        ):
            readback.prepare_snapshot(self.root, self.snapshot)

    def test_original_workflow_bytes_cannot_be_rebased(self):
        self.reject_changed_bytes(
            "qualification/hcsn_consolidated_readback/originals/hcsn-currentstate-n256-warm1-sparse.yml"
        )

    def test_current_workflow_cannot_reenable_launcher(self):
        path = (
            self.root
            / ".github/workflows/hcsn-currentstate-n256-firststep-dense-oracle-hosted.yml"
        )
        with path.open("a") as output:
            output.write(
                "\n      - run: python -m qualification.hcsn_currentstate_n256_firststep_dense_oracle_hosted.launcher\n"
            )
        with self.assertRaisesRegex(ValueError, "current readback workflow drift"):
            readback.prepare_snapshot(self.root, self.snapshot)

    def test_original_source_freeze_drift_rejects(self):
        self.reject_changed_bytes(
            "qualification/hcsn_currentstate_n256_warm1_sparse/FREEZE.json"
        )

    def test_recorded_source_head_drift_rejects(self):
        self.reject_changed_bytes(
            "qualification/hcsn_currentstate_n256_warm1_sparse/evidence/attempt001-20261119/HOSTED_IDENTITY.json"
        )

    def test_new_manifest_cannot_bless_changed_bytes(self):
        self.reject_changed_bytes(
            "qualification/hcsn_consolidated_readback/SNAPSHOT.json"
        )

    def test_source_link_rejects(self):
        path = self.root / readback.CURRENT_REQUEST
        raw = path.read_bytes()
        external = Path(self.directory.name) / "external.json"
        external.write_bytes(raw)
        path.unlink()
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "source link"):
            readback.prepare_snapshot(self.root, self.snapshot)

    def test_relaunched_output_rejects(self):
        manifest = readback.prepare_snapshot(self.root, self.snapshot)
        (self.snapshot / "RUN_OUTPUT").mkdir()
        with self.assertRaisesRegex(ValueError, "consumed execution was relaunched"):
            readback.verify_unchanged_snapshot(self.snapshot, manifest)


if __name__ == "__main__":
    unittest.main()
