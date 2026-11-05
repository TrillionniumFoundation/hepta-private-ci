"""Regression controls for independent historical and current source identities."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import verify_receipts as verifier


class SourceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "v15"
        self.root.mkdir()
        original = verifier.ROOT.parent
        for source in original.glob("*.py"):
            shutil.copyfile(source, self.root / source.name)
        for name in ("checks.json", "checks.log"):
            target = self.root / "evidence" / name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(original / "evidence" / name, target)
        shutil.copytree(original / "evidence/ci_41950367467", self.root / "evidence/ci_41950367467")
        shutil.copytree(verifier.ROOT, self.root / "device_qualification", ignore=shutil.ignore_patterns("__pycache__"))
        self.device = self.root / "device_qualification"
        self.patch = patch.object(verifier, "ROOT", self.device)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def reject(self, message):
        with self.assertRaisesRegex(ValueError, message):
            verifier.verify()

    def test_new_current_source_checks_keep_old_run_identity(self):
        authority = self.root / "authority.py"
        authority.write_bytes(authority.read_bytes() + b"\n# Fresh source identity for the provenance regression.\n")
        checked = subprocess.run([sys.executable, str(self.root / "verify.py")],
                                 capture_output=True, text=True, timeout=120)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        result = verifier.verify()
        self.assertTrue(result["passed"])
        self.assertNotEqual(result["authority_sha256"],
                            result["current_protocol_source_files_sha256"]["authority.py"])
        self.assertFalse(result["historical_receipt_qualifies_current_device_code"])
        self.assertEqual(result["evidence_sha256"], verifier.sha((self.device / "receipts.json").read_bytes()))

    def test_current_source_change_after_checks_is_rejected(self):
        source = self.root / "authority.py"
        source.write_bytes(source.read_bytes() + b"\n# unqualified edit\n")
        self.reject("currently qualified Python source changed")

    def test_current_source_inventory_cannot_omit_new_code(self):
        (self.root / "unchecked.py").write_text("unqualified = True\n")
        self.reject("current source inventory differs")

    def test_unsuccessful_current_checks_are_rejected(self):
        path = self.root / "evidence/checks.json"
        value = json.loads(path.read_bytes())
        value["passed"] = False
        path.write_text(json.dumps(value))
        self.reject("current source checks did not pass")

    def test_historical_archive_tamper_is_rejected(self):
        path = self.device / "history/sources.zip"
        path.write_bytes(path.read_bytes() + b"tamper")
        self.reject("historical source archive identity mismatch")

    def test_historical_manifest_cannot_rebind_changed_source(self):
        path = self.device / "history/manifest.json"
        value = json.loads(path.read_bytes())
        value["files"]["authority.py"]["sha256"] = verifier.sha((self.root / "authority.py").read_bytes())
        path.write_text(json.dumps(value))
        self.reject("historical source manifest identity mismatch")

    def test_historical_check_receipt_tamper_is_rejected(self):
        path = self.root / "evidence/ci_41950367467/checks.json"
        path.write_bytes(path.read_bytes() + b"\n")
        self.reject("historical check receipt identity mismatch")

    def test_recorded_run_cannot_be_relabelled_as_current_source(self):
        path = self.device / "receipts.json"
        value = json.loads(path.read_bytes())
        value["authority_sha256"] = verifier.sha((self.root / "authority.py").read_bytes())
        path.write_text(json.dumps(value))
        self.reject("historical receipt identity mismatch")

    def test_worker_edit_does_not_change_historical_worker_identity(self):
        path = self.device / "host_worker.py"
        path.write_bytes(path.read_bytes() + b"\n# Current worker is not a historical execution.\n")
        result = verifier.verify()
        self.assertTrue(result["passed"])
        self.assertNotEqual(result["worker_sha256"], verifier.sha(path.read_bytes()))
        self.assertFalse(result["historical_receipt_qualifies_current_device_code"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
