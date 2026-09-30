from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/channel_matrix_source_provenance.py"
SPEC = importlib.util.spec_from_file_location("channel_matrix_source_provenance", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SourceProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init"], cwd=self.root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/channel-matrix-preserve-unknown.yml").write_text(
            "name: test\n", encoding="utf-8"
        )
        (self.root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.root, check=True, stdout=subprocess.DEVNULL)
        self.head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, check=True, text=True, stdout=subprocess.PIPE
        ).stdout.strip()
        self.tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=self.root, check=True, text=True, stdout=subprocess.PIPE
        ).stdout.strip()
        payload = (self.root / "tracked.txt").read_bytes()
        blob = subprocess.run(
            ["git", "rev-parse", "HEAD:tracked.txt"], cwd=self.root, check=True, text=True, stdout=subprocess.PIPE
        ).stdout.strip()
        import hashlib

        self.snapshot = Path(self.temp.name) / "source.json"
        self.snapshot.write_text(
            json.dumps(
                {
                    "schema": "hepta.channel-matrix-source-snapshot.v1",
                    "lane": "source-head",
                    "sourceSha": self.head,
                    "baseSha": self.head,
                    "testedSha": self.head,
                    "testedTree": self.tree,
                    "files": [
                        {
                            "path": "tracked.txt",
                            "gitBlob": blob,
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "bytes": len(payload),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.old_run = os.environ.get("GITHUB_RUN_ID")
        self.old_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
        os.environ["GITHUB_RUN_ID"] = "123"
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"

    def tearDown(self) -> None:
        if self.old_run is None:
            os.environ.pop("GITHUB_RUN_ID", None)
        else:
            os.environ["GITHUB_RUN_ID"] = self.old_run
        if self.old_attempt is None:
            os.environ.pop("GITHUB_RUN_ATTEMPT", None)
        else:
            os.environ["GITHUB_RUN_ATTEMPT"] = self.old_attempt
        self.temp.cleanup()

    def test_reports_only_tracked_exact_git_objects(self) -> None:
        row = MODULE.build_provenance(self.root, self.snapshot, self.head, "checkout")
        self.assertEqual(row["checkoutSha"], self.head)
        self.assertEqual(row["treeSha"], self.tree)
        self.assertTrue(row["scan"]["filesystemWalkUsed"] is False)
        self.assertEqual(row["execution"]["workflowRunId"], "123")
        self.assertEqual(row["execution"]["attemptId"], "2")
        self.assertEqual(len(row["files"]), 1)
        item = row["files"][0]
        self.assertEqual(item["repoRelativePath"], "tracked.txt")
        self.assertTrue(item["tracked"])
        self.assertTrue(item["gitLsFilesErrorUnmatch"])
        self.assertFalse(item["fromGeneratedDirectory"])
        self.assertFalse(item["fromCache"])
        self.assertFalse(item["fromArtifactDownload"])

    def test_rejects_untracked_path_in_source_snapshot(self) -> None:
        row = json.loads(self.snapshot.read_text(encoding="utf-8"))
        row["files"].append(
            {"path": "untracked.txt", "gitBlob": "0" * 40, "sha256": "0" * 64, "bytes": 11}
        )
        self.snapshot.write_text(json.dumps(row), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-tracked"):
            MODULE.build_provenance(self.root, self.snapshot, self.head, "checkout")

    def test_rejects_dirty_tracked_checkout(self) -> None:
        (self.root / "tracked.txt").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not clean"):
            MODULE.build_provenance(self.root, self.snapshot, self.head, "checkout")


if __name__ == "__main__":
    unittest.main()
