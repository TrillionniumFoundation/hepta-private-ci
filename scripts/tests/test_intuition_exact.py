"""Local unit tests of evidence mechanics; not Rust/product qualification."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import intuition_qualify_exact as q
import intuition_accept_exact as a

SOURCE = "a" * 40
CONTEXT = {"runId": "123", "runAttempt": "2", "repository": "owner/repo"}


def bundle(path, mode, job):
    path.mkdir()
    commands = q.COMMANDS if mode == "qualification" else q.INDEPENDENT_COMMANDS
    rows = []
    for name, argv in commands:
        log = path / (name + ".log")
        log.write_text("test result: ok. 1 passed; 0 failed;\n")
        rows.append({"name": name, "argv": argv, "cwd": "codex-rs", "status": "passed",
                     "exitCode": 0, "log": log.name, "logSha256": q.sha256(log),
                     "binaries": [{"name": "test-only", "sha256": "0" * 64}]})
    tool = path / "toolchain.txt"
    tool.write_text("fixture - not an actual compiler\n")
    record = {"schema": q.SCHEMA, "sourceSha": SOURCE, "testedSha": SOURCE,
              "testedTree": "b" * 40, "mode": mode, "lane": "source-head",
              **CONTEXT, "jobId": job, "status": "passed", "worktreeUnchanged": True,
              "commands": rows, "cargoLockSha256": "c" * 64,
              "toolchainLogSha256": q.sha256(tool)}
    q.write_json(path / "command-record.json", record)
    q.write_json(path / "IMPLEMENTATION_MAP.json", {"productionImplementation": False})
    (path / "execution-dossier.md").write_text("Unit-test fixture.\n")
    q.seal(path)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.standard = self.root / "standard"
        self.independent = self.root / "independent"
        bundle(self.standard, "qualification", "qualification")
        bundle(self.independent, "independent", "independent")

    def tearDown(self):
        self.temp.cleanup()

    def mutate(self, field, value, directory=None):
        directory = directory or self.independent
        path = directory / "command-record.json"
        record = json.loads(path.read_text())
        record[field] = value
        q.write_json(path, record)
        q.seal(directory)

    def verify(self):
        return a.verify_pair(self.standard, self.independent, SOURCE, CONTEXT)

    def test_matching_distinct_jobs(self):
        self.assertEqual(self.verify()[0]["testedSha"], SOURCE)

    def test_same_job_is_not_independent(self):
        self.mutate("jobId", "qualification")
        with self.assertRaises(ValueError): self.verify()

    def test_different_source_rejected(self):
        self.mutate("sourceSha", "d" * 40)
        with self.assertRaises(ValueError): self.verify()

    def test_different_tree_rejected(self):
        self.mutate("testedTree", "d" * 40)
        with self.assertRaises(ValueError): self.verify()

    def test_different_attempt_rejected(self):
        self.mutate("runAttempt", "1")
        with self.assertRaises(ValueError): self.verify()

    def test_missing_run_id_rejected(self):
        self.mutate("runId", None)
        with self.assertRaises(ValueError): self.verify()

    def test_dirty_worktree_rejected(self):
        self.mutate("worktreeUnchanged", False)
        with self.assertRaises(ValueError): self.verify()

    def test_failed_execution_rejected(self):
        self.mutate("status", "failed")
        with self.assertRaises(ValueError): self.verify()

    def test_missing_command_rejected(self):
        self.mutate("commands", [])
        with self.assertRaises(ValueError): self.verify()

    def test_log_tampering_rejected(self):
        (self.independent / "independent-product.log").write_text("tampered\n")
        with self.assertRaises(ValueError): self.verify()

    def test_substituted_command_rejected_even_after_rehash(self):
        record = json.loads((self.independent / "command-record.json").read_text())
        record["commands"][0]["argv"] = ["true"]
        self.mutate("commands", record["commands"])
        with self.assertRaises(ValueError): self.verify()

    def test_zero_test_execution_rejected_even_after_rehash(self):
        log = self.independent / "independent-product.log"
        log.write_text("test result: ok. 0 passed; 0 failed;\n")
        record = json.loads((self.independent / "command-record.json").read_text())
        for row in record["commands"]:
            if row["name"] == "independent-product": row["logSha256"] = q.sha256(log)
        self.mutate("commands", record["commands"])
        with self.assertRaises(ValueError): self.verify()

    def test_symlink_rejected(self):
        path = self.independent / "execution-dossier.md"
        content = path.read_text()
        path.unlink()
        outside = self.root / "outside"
        outside.write_text(content)
        path.symlink_to(outside)
        with self.assertRaises(ValueError): self.verify()

    def test_stale_output_refused(self):
        with self.assertRaises(ValueError): q.external_directory(self.standard)

    def test_source_output_refused(self):
        with self.assertRaises(ValueError): q.external_directory(q.ROOT / "evidence")

    def test_short_sha_refused(self):
        self.assertIsNotNone(q.identity_error(SOURCE, SOURCE, "aaaaaaa", "", "source-head"))

    def test_source_head_must_match_source(self):
        self.assertIsNotNone(q.identity_error(SOURCE, SOURCE, "d" * 40, "", "source-head"))

    def test_synthetic_parents_bound(self):
        base = "e" * 40
        with mock.patch.object(q, "git", return_value=f"{SOURCE} {base} {'d' * 40}"):
            self.assertIsNotNone(q.identity_error(SOURCE, SOURCE, SOURCE, base, "synthetic-merge"))

    def test_missing_executable_returns_127(self):
        self.assertEqual(q.execute(["/no-such-intuition-executable"], self.root / "missing.log", self.root, 1), 127)

    def test_timeout_returns_124(self):
        self.assertEqual(q.execute([sys.executable, "-c", "import time; time.sleep(5)"], self.root / "timeout.log", self.root, 1), 124)

    def test_log_summary_bounded(self):
        log = self.root / "large.log"
        log.write_text("x" * 100000)
        self.assertLessEqual(len(q.log_summary(log)), 16384)

    def test_log_summary_keeps_early_compiler_errors_and_tail(self):
        log = self.root / "compiler.log"
        failures = [
            f"\x1b[31merror[E{i:04}]: failure {i}\x1b[0m\n"
            f"  --> owner{i}.rs:10:2\n"
            "   | source context\n\n"
            for i in range(15)
        ]
        log.write_text(
            "".join(failures)
            + "Compiling dependency\n" * 10000
            + "final command failed\n"
        )
        summary = q.log_summary(log)
        for i in range(15):
            self.assertIn(f"error[E{i:04}]: failure {i}", summary)
            self.assertIn(f"owner{i}.rs:10:2", summary)
        self.assertIn("final command failed", summary)
        self.assertNotIn("\x1b[", summary)
        self.assertLessEqual(len(summary), 16384)

    def test_log_summary_reports_omitted_diagnostics_and_caps_large_contexts(self):
        log = self.root / "many-errors.log"
        log.write_text(
            "".join(
                f"error: failure {i}\n  --> owner{i}.rs:10:2\n" + "x" * 100000 + "\n"
                for i in range(100)
            )
            + "final failure\n"
        )
        summary = q.log_summary(log)
        self.assertIn("32 of 100", summary)
        self.assertIn("error: failure 0", summary)
        self.assertIn("owner31.rs:10:2", summary)
        self.assertIn("final failure", summary)
        self.assertLessEqual(len(summary), 16384)

    def test_real_git_dirty_source_fails_without_running_gate(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "source").write_text("clean\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        (repo / "source").write_text("dirty\n")
        with mock.patch.object(q, "ROOT", repo), mock.patch.object(q, "execute") as run:
            self.assertEqual(q.main(["--source-commit", sha, "--evidence", str(self.root / "dirty-evidence")]), 1)
            run.assert_not_called()
        self.assertEqual((repo / "source").read_text(), "dirty\n")


if __name__ == "__main__":
    unittest.main()
