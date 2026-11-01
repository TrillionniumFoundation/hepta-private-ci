"""Fail-closed checks using an explicitly synthetic temporary Git fixture."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import restore_check


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hcsn-recovery-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "synthetic-fixture"
        self.repo.mkdir()
        self.git("init", "-q")
        (self.repo / "source.txt").write_text("synthetic source; not v6\n")
        self.git("add", "source.txt")
        self.git("commit", "-q", "-m", "synthetic fixture parent")
        parent = self.git("rev-parse", "HEAD").strip()
        (self.repo / "input.txt").write_text("synthetic input; not an AV recording\n")
        self.protocol = self.repo / restore_check.V6_ROOT / "configs/frontend/CONFIRMATION_PROTOCOL.json"
        self.protocol.parent.mkdir(parents=True)
        self.document = {
            "sources": {"source.txt": restore_check.digest(self.repo / "source.txt")},
            "inputs": {"input.txt": restore_check.digest(self.repo / "input.txt")},
        }
        self.protocol.write_text(json.dumps(self.document))
        self.git("add", ".")
        self.git("commit", "-q", "-m", "synthetic fixture child")
        child = self.git("rev-parse", "HEAD").strip()
        guard = patch.multiple(restore_check, V5_COMMIT=parent, V6_COMMIT=child,
                               PROTOCOL_SHA256=restore_check.digest(self.protocol))
        guard.start()
        self.addCleanup(guard.stop)

    def git(self, *arguments):
        command = ["git", "-c", "user.name=Recovery Test Fixture",
                   "-c", "user.email=recovery-fixture@example.invalid",
                   "-c", "commit.gpgsign=false", "-C", str(self.repo), *arguments]
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=10).stdout

    def test_intact_synthetic_baseline_only_authorizes_development(self):
        result = restore_check.inspect(self.repo, {})
        self.assertTrue(result["ready_for_v7_development"])
        self.assertFalse(result["new_confirmation_executed"])
        self.assertFalse(result["confirmation_authorized_by_this_check"])

    def test_missing_repository_and_supplied_bad_bundle_block(self):
        damaged = self.root / "not-a-real-v6.bundle"
        damaged.write_bytes(b"not a bundle")
        result = restore_check.inspect(self.repo, {"v6": damaged})
        self.assertFalse(result["ready_for_v7_development"])
        self.assertFalse(result["bundles"]["v6"]["identity_matches"])
        result = restore_check.inspect(self.root / "absent", {})
        self.assertEqual(result["status"], "blocked_on_v6_assets")

    def test_changed_source_or_missing_input_cannot_pass(self):
        (self.repo / "source.txt").write_text("changed bytes\n")
        (self.repo / "input.txt").unlink()
        result = restore_check.inspect(self.repo, {})
        self.assertFalse(result["ready_for_v7_development"])
        self.assertEqual(result["source_and_input_inventory"]["sources"]["verified"], 0)
        self.assertEqual(result["source_and_input_inventory"]["inputs"]["verified"], 0)

    def test_protocol_change_and_outside_manifest_path_block(self):
        self.protocol.write_text("{}")
        self.assertFalse(restore_check.inspect(self.repo, {})["ready_for_v7_development"])
        outside = self.root / "external.txt"
        outside.write_text("must not be counted as repository content\n")
        self.document["inputs"] = {"../external.txt": restore_check.digest(outside)}
        self.protocol.write_text(json.dumps(self.document))
        with patch.object(restore_check, "PROTOCOL_SHA256", restore_check.digest(self.protocol)):
            result = restore_check.inspect(self.repo, {})
        self.assertFalse(result["ready_for_v7_development"])
        self.assertEqual(result["source_and_input_inventory"]["inputs"]["failures"][0]["reason"],
                         "path escapes repository")


if __name__ == "__main__":
    unittest.main(verbosity=2)
