"""Source-object binding and failure preservation, without experiment sampling."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run as driver


class RunnerEvidenceTests(unittest.TestCase):
    def test_same_filesystem_cannot_count_the_same_free_space_twice(self):
        payload, allowance = 1024, 64 * 1024 * 1024
        estimate = {"uncompressed_payload_estimate_bytes": payload,
                    "required_free_bytes_with_archive_headroom": 2 * (payload + allowance)}
        output = {"directory": "/output", "st_dev": 7, "free_bytes": payload + allowance}
        archive = {"directory": "/different-path", "st_dev": 7, "free_bytes": payload + allowance}
        plan = driver.storage_plan(estimate, output, archive)
        self.assertFalse(plan["passed"])
        self.assertEqual(plan["strategy"], "shared-filesystem")
        self.assertTrue(plan["archive"]["required_is_shared_with_output"])
        self.assertEqual(plan["total_required_unique_filesystem_bytes"], 2 * (payload + allowance))
        self.assertFalse(driver.storage_plan(estimate, output, output)["passed"])
        output["free_bytes"] = archive["free_bytes"] = 2 * (payload + allowance)
        self.assertTrue(driver.storage_plan(estimate, output, archive)["passed"])

    def test_split_devices_preserve_total_and_both_individual_requirements(self):
        payload, allowance = 1024, 64 * 1024 * 1024
        estimate = {"uncompressed_payload_estimate_bytes": payload,
                    "required_free_bytes_with_archive_headroom": 2 * (payload + allowance)}
        output = {"directory": "/output", "st_dev": 7, "free_bytes": payload + allowance}
        archive = {"directory": "/archive", "st_dev": 9, "free_bytes": payload + allowance}
        plan = driver.storage_plan(estimate, output, archive)
        self.assertTrue(plan["passed"])
        self.assertEqual(plan["strategy"], "split-filesystems")
        self.assertFalse(plan["archive"]["required_is_shared_with_output"])
        self.assertEqual(plan["total_required_unique_filesystem_bytes"],
                         estimate["required_free_bytes_with_archive_headroom"])
        self.assertEqual(plan["output"]["required_free_bytes"] + plan["archive"]["required_free_bytes"],
                         estimate["required_free_bytes_with_archive_headroom"])
        for scarce in ("output", "archive"):
            with self.subTest(scarce=scarce):
                records = {"output": dict(output), "archive": dict(archive)}
                records[scarce]["free_bytes"] -= 1
                records["archive" if scarce == "output" else "output"]["free_bytes"] += 1000000
                self.assertFalse(driver.storage_plan(estimate, **records)["passed"])

    def test_archive_argument_must_already_be_a_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            for candidate in (fixture / "missing", fixture / "file"):
                if candidate.name == "file":
                    candidate.write_text("not a directory")
                with self.subTest(path=candidate.name), self.assertRaises((FileNotFoundError, NotADirectoryError)):
                    driver.execute(fixture / "not-started", fixture, fixture / "unused", True, candidate)
                self.assertFalse((fixture / "not-started").exists())

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
