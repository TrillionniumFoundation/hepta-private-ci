"""Source-object binding and failure preservation, without experiment sampling."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run as driver


class RunnerEvidenceTests(unittest.TestCase):
    def test_binding_works_without_local_blob_and_detects_changed_or_untracked_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            path = repo / "source.py"
            path.write_text("value = 7\n")
            subprocess.run(["git", "add", "source.py"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "-qm", "isolated source fixture"], cwd=repo, check=True)
            initial = driver.git_bindings(repo, ["source.py"])
            self.assertTrue(initial["all_source_bytes_committed"])
            blob = initial["committed_blob_sha1"]["source.py"]
            (repo / ".git/objects" / blob[:2] / blob[2:]).unlink()
            self.assertEqual(driver.git_bindings(repo, ["source.py"]), initial)
            path.write_text("value = 8\n")
            (repo / "new.py").write_text("new = True\n")
            changed = driver.git_bindings(repo, ["new.py", "source.py"])
            self.assertEqual(changed["development_dirty_files"], ["new.py", "source.py"])
            self.assertFalse(changed["all_source_bytes_committed"])
            self.assertEqual(changed["committed_blob_sha1"], initial["committed_blob_sha1"])

    def test_early_failure_is_receipted_and_attempt_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / "protocol.json").write_text('{"fixture": "deliberate invalid protocol"}\n')
            output = fixture / "failed-attempt"
            with patch.object(driver, "HERE", fixture):
                with self.assertRaisesRegex(RuntimeError, "evidence retained"):
                    driver.execute(output, fixture / "unused", fixture / "unused-binary", development=True)
                receipt_bytes = (output / "run-receipt.json").read_bytes()
                receipt = json.loads(receipt_bytes)
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(receipt["full_actual_linear_macs"], 0)
                self.assertIn("protocol differs", receipt["traceback"])
                artifacts = json.loads((output / "artifacts.json").read_text())
                self.assertEqual(artifacts["protocol.json"]["sha256"], driver.digest(fixture / "protocol.json"))
                self.assertEqual(receipt["artifact_manifest_sha256"], driver.digest(output / "artifacts.json"))
                with self.assertRaises(FileExistsError):
                    driver.execute(output, fixture / "unused", fixture / "unused-binary", development=True)
                self.assertEqual((output / "run-receipt.json").read_bytes(), receipt_bytes)


if __name__ == "__main__":
    unittest.main()
