"""Pinned-source transport tests with a tiny artificial local Git repository."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from experiments.first_passage_adaptive.materialize_owner_sources import materialize


class MaterializationTests(unittest.TestCase):
    def fixture(self, root):
        source = root/"source"
        source.mkdir()
        (source/"scripts").mkdir()
        (source/"scripts/run-nextest.py").write_text("# artificial test runner\n")
        payload = b"original owner source\n"
        (source/"owner.rs").write_bytes(payload)
        for command in (["init", "-q"], ["add", "."], ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "artificial source"]):
            subprocess.run(["git", "-C", str(source), *command], check=True, capture_output=True)
        commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        sha = hashlib.sha1(b"blob "+str(len(payload)).encode()+b"\0"+payload).hexdigest()
        manifest = root/"manifest.json"
        manifest.write_text(json.dumps({"source_commit": commit, "files": [{"path": "owner.rs", "git_blob_sha": sha}]}))
        return source, manifest, payload

    def test_reads_frozen_git_blob_even_when_worktree_differs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest, payload = self.fixture(root)
            (source/"owner.rs").write_text("different current worktree\n")
            result = materialize(source, root/"replay", manifest)
            self.assertEqual((root/"replay/owner.rs").read_bytes(), payload)
            self.assertEqual(len(result["files"]), 2)
            self.assertEqual((source/"owner.rs").read_text(), "different current worktree\n")

    def test_bad_frozen_identity_refuses_materialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest, _ = self.fixture(root)
            data = json.loads(manifest.read_text())
            data["files"][0]["git_blob_sha"] = "0"*40
            manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "frozen identity"):
                materialize(source, root/"rejected", manifest)
            self.assertFalse((root/"rejected").exists())


if __name__ == "__main__":
    unittest.main()
