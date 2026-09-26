import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "channel_matrix_evidence.py"
SPEC = importlib.util.spec_from_file_location("matrix_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


class CandidateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.root.mkdir()
        self.artifacts = Path(self.temp.name) / "artifacts"
        self.artifacts.mkdir()
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

    def prepare(self):
        source = self.capture()
        for name in ("source.json", "source-after.json"):
            evidence.write_json(self.artifacts / name, source)
        evidence.write_json(self.artifacts / "candidate.json", {
            "schema": "hepta.channel-matrix-candidate-receipt.v1",
            "status": "PASS_CHANNEL_MATRIX_CANDIDATE_BINDING",
            "candidate": {"commit": self.head, "tree": source["testedTree"]},
        })

    def successful_commands(self):
        self.prepare()
        # Launch real tiny Python processes instead of pretending Cargo exists.
        # The fixed command mapping is replaced only inside this test fixture.
        commands = {label: [sys.executable, "-c", "print('fixture command')"]
                    for label in evidence.COMMANDS}
        patch = mock.patch.dict(evidence.COMMANDS, commands, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        for label in commands:
            self.assertEqual(evidence.run_command(self.root, self.artifacts, label), 0)

    def rewrite(self, name, change):
        path = self.artifacts / name
        row = json.loads(path.read_text())
        change(row)
        evidence.write_json(path, row)

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
        (self.artifacts / "focused-tests.log").write_text("compile failed\n")
        result = evidence.manifest(self.artifacts, "failure")
        self.assertEqual(result["runnerReportedStatus"], "failure")
        self.assertFalse(result["claims"]["focusedCommandsPassed"])
        self.assertFalse(result["claims"]["homeserverQualified"])
        self.assertEqual(len(result["files"]), 1)

    def test_success_requires_all_logs_and_matching_snapshots(self):
        self.successful_commands()
        before = evidence.manifest(self.artifacts, "success")
        self.assertTrue(before["claims"]["focusedCommandsPassed"])
        self.assertFalse(before["claims"]["activation"])
        self.assertFalse(before["claims"]["homeserverQualified"])
        (self.artifacts / "source-after.json").write_text("different\n")
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_plain_text_placeholders_cannot_pose_as_success(self):
        for name in ("source.json", "source-after.json", "candidate.json", "focused-tests.log", "clippy.log"):
            (self.artifacts / name).write_text("fixture\n")
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_manifest_cannot_read_through_symlinks(self):
        (self.artifacts / "link.log").symlink_to(self.source)
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "failure")

    def test_real_nonzero_exit_is_retained(self):
        self.prepare()
        with mock.patch.dict(evidence.COMMANDS, {"focused-tests": [sys.executable, "-c", "raise SystemExit(7)"]}):
            self.assertEqual(evidence.run_command(self.root, self.artifacts, "focused-tests"), 1)
        row = json.loads((self.artifacts / "focused-tests.command.json").read_text())
        self.assertEqual(row["exitCode"], 7)
        self.assertTrue(row["completed"])
        self.assertFalse(evidence.manifest(self.artifacts, "failure")["claims"]["focusedCommandsPassed"])

    def test_launch_failure_is_not_a_completed_command(self):
        self.prepare()
        with mock.patch.dict(evidence.COMMANDS, {"focused-tests": [str(self.root / "nonexistent")] }):
            self.assertEqual(evidence.run_command(self.root, self.artifacts, "focused-tests"), 1)
        row = json.loads((self.artifacts / "focused-tests.command.json").read_text())
        self.assertIsNone(row["exitCode"])
        self.assertFalse(row["completed"])
        self.assertEqual(row["launchError"], "FileNotFoundError")

    def test_zero_exit_with_source_mutation_fails(self):
        self.prepare()
        code = f"from pathlib import Path; Path({str(self.source)!r}).write_text('changed')"
        with mock.patch.dict(evidence.COMMANDS, {"focused-tests": [sys.executable, "-c", code]}):
            self.assertEqual(evidence.run_command(self.root, self.artifacts, "focused-tests"), 1)
        row = json.loads((self.artifacts / "focused-tests.command.json").read_text())
        self.assertEqual(row["exitCode"], 0)
        self.assertFalse(row["sourceUnchanged"])

    def test_duplicate_command_cannot_overwrite_prior_evidence(self):
        self.successful_commands()
        before = (self.artifacts / "focused-tests.command.json").read_bytes()
        with self.assertRaises(ValueError):
            evidence.run_command(self.root, self.artifacts, "focused-tests")
        self.assertEqual((self.artifacts / "focused-tests.command.json").read_bytes(), before)

    def test_log_tampering_fails_success(self):
        self.successful_commands()
        (self.artifacts / "focused-tests.log").write_text("replacement\n")
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_missing_command_receipt_fails_success(self):
        self.successful_commands()
        (self.artifacts / "format.command.json").unlink()
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_boolean_exit_code_is_not_integer_zero(self):
        self.successful_commands()
        self.rewrite("focused-tests.command.json", lambda row: row.update(exitCode=False))
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_wrong_command_arguments_fail(self):
        self.successful_commands()
        self.rewrite("clippy.command.json", lambda row: row.update(arguments=["true"]))
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_wrong_command_candidate_fails(self):
        self.successful_commands()
        self.rewrite("clippy.command.json", lambda row: row.update(testedSha="0" * 40))
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_wrong_source_digest_fails(self):
        self.successful_commands()
        self.rewrite("clippy.command.json", lambda row: row.update(sourceSnapshotSha256="0" * 64))
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_candidate_tree_mismatch_fails(self):
        self.successful_commands()
        self.rewrite("candidate.json", lambda row: row["candidate"].update(tree="0" * 40))
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_incomplete_command_fails(self):
        self.successful_commands()
        self.rewrite("format.command.json", lambda row: row.update(completed=False))
        with self.assertRaises(ValueError):
            evidence.manifest(self.artifacts, "success")

    def test_duplicate_json_fields_are_rejected(self):
        (self.artifacts / "source.json").write_text('{"testedSha":"a","testedSha":"b"}')
        with self.assertRaises(ValueError):
            evidence.read_object(self.artifacts / "source.json")

    def test_cancelled_run_is_never_promoted(self):
        self.successful_commands()
        self.assertFalse(evidence.manifest(self.artifacts, "cancelled")["claims"]["focusedCommandsPassed"])


if __name__ == "__main__":
    unittest.main()
