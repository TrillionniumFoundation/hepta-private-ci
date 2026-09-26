import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "channel_matrix_evidence.py"
SPEC = importlib.util.spec_from_file_location("matrix_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


class CandidateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.command("init", "-q")
        self.command("config", "user.name", "fixture")
        self.command("config", "user.email", "fixture@example.test")
        self.source = self.root / "codex-rs/hepta-matrix-sdk/src/lib.rs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("pub fn example() {}\n")
        self.command("add", ".")
        self.command("commit", "-qm", "source fixture")
        self.head = self.command("rev-parse", "HEAD").strip()

    def command(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True,
                              text=True).stdout

    def capture(self):
        return evidence.snapshot(self.root, self.head, self.head, self.head, "source-head")

    def test_exact_clean_bytes_are_bound_without_execution_claim(self):
        result = self.capture()
        self.assertEqual(result["testedSha"], self.head)
        self.assertFalse(result["claims"]["testsPassed"])
        self.assertEqual(result["files"][0]["gitBlob"],
                         self.command("rev-parse", "HEAD:codex-rs/hepta-matrix-sdk/src/lib.rs").strip())

    def test_snapshot_is_stable(self):
        self.assertEqual(self.capture(), self.capture())

    def test_dirty_source_rejected(self):
        self.source.write_text("pub fn changed() {}\n")
        with self.assertRaises(subprocess.CalledProcessError):
            self.capture()

    def test_staged_source_rejected(self):
        self.source.write_text("pub fn staged() {}\n")
        self.command("add", ".")
        with self.assertRaises(subprocess.CalledProcessError):
            self.capture()

    def test_untracked_source_rejected(self):
        self.source.with_name("hidden.rs").write_text("untracked")
        with self.assertRaises(ValueError):
            self.capture()

    def test_ignored_source_rejected(self):
        (self.root / ".git/info/exclude").write_text("hidden.rs\n")
        self.source.with_name("hidden.rs").write_text("ignored")
        with self.assertRaises(ValueError):
            self.capture()

    def test_abbreviated_expected_sha_rejected(self):
        with self.assertRaises(ValueError):
            evidence.snapshot(self.root, self.head[:10], self.head, self.head, "source-head")

    def test_wrong_head_rejected(self):
        self.source.write_text("pub fn another() {}\n")
        self.command("commit", "-qam", "another")
        with self.assertRaises(ValueError):
            self.capture()

    def test_source_commit_cannot_pose_as_merge(self):
        with self.assertRaises(ValueError):
            evidence.snapshot(self.root, self.head, self.head, self.head, "base-merge")

    def test_real_merge_tree_and_parents_are_verified(self):
        base = self.head
        self.source.write_text("pub fn source() {}\n")
        self.command("commit", "-qam", "source")
        source = self.command("rev-parse", "HEAD").strip()
        tree = self.command("merge-tree", "--write-tree", base, source).strip()
        merge = subprocess.run(["git", "commit-tree", tree, "-p", base, "-p", source],
                               cwd=self.root, input="fixture merge\n", text=True,
                               check=True, capture_output=True).stdout.strip()
        self.command("checkout", "-q", "--detach", merge)
        result = evidence.snapshot(self.root, merge, source, base, "base-merge")
        self.assertEqual(result["testedTree"], tree)

    def test_manifest_does_not_promote_failed_commands(self):
        directory = self.root / "artifacts"
        directory.mkdir()
        (directory / "focused-tests.log").write_text("compile failed\n")
        result = evidence.manifest(directory, "failure")
        self.assertEqual(result["runnerReportedStatus"], "failure")
        self.assertFalse(result["claims"]["homeserverQualified"])
        self.assertEqual(len(result["files"]), 1)

    def test_success_requires_all_logs_and_matching_snapshots(self):
        directory = self.root / "artifacts"
        directory.mkdir()
        with self.assertRaises(ValueError):
            evidence.manifest(directory, "success")
        for name in ("source.json", "source-after.json", "candidate.json", "focused-tests.log", "clippy.log"):
            (directory / name).write_text("fixture\n")
        before = evidence.manifest(directory, "success")
        self.assertFalse(before["claims"]["activation"])
        (directory / "source-after.json").write_text("different\n")
        with self.assertRaises(ValueError):
            evidence.manifest(directory, "success")
        (directory / "source-after.json").write_text("fixture\n")
        (directory / "clippy.log").write_text("changed\n")
        after = evidence.manifest(directory, "success")
        self.assertNotEqual(before["artifactSetSha256"], after["artifactSetSha256"])

    def test_manifest_cannot_read_through_symlinks(self):
        directory = self.root / "artifacts"
        directory.mkdir()
        (directory / "link.log").symlink_to(self.source)
        with self.assertRaises(ValueError):
            evidence.manifest(directory, "failure")


if __name__ == "__main__":
    unittest.main()
