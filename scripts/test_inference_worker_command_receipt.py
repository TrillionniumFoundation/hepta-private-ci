import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    from scripts import inference_worker_command_receipt as receipt
except ImportError:
    import inference_worker_command_receipt as receipt


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "receipt-test")
        self.git("config", "user.email", "receipt@example.invalid")
        (self.repo / "codex-rs").mkdir()
        (self.repo / "codex-rs" / "Cargo.lock").write_text("lock-v1\n")
        (self.repo / "source").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / "source").write_text("source\n")
        self.git("commit", "-qam", "source")
        self.source = self.git("rev-parse", "HEAD")
        self.records = self.root / "records"
        self.records.mkdir()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True
        ).strip()

    def command_record(self, label, *, status="passed", exit_code=0, passed=3, failed=0, skipped=1):
        log = self.records / f"{label}.log"
        log.write_text(
            "test result: ok. "
            f"{passed} passed; {failed} failed; {skipped} ignored; "
            "0 measured; 0 filtered out;\n"
        )
        import hashlib
        record = {
            "schema_version": 1,
            "source_sha": self.source,
            "base_sha": self.base,
            "tested_sha": self.source,
            "lane": "source-head",
            "command": ["cargo", label],
            "working_directory": str(self.repo),
            "status": status,
            "exit_code": exit_code,
            "command_exit_code": exit_code,
            "minimum_tests": 1 if label == "library" else 0,
            "observed_passed_tests": passed,
            "observed_failed_tests": failed,
            "log_file": log.name,
            "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            "before": {
                "commit": self.source,
                "tree": self.git("rev-parse", "HEAD^{tree}"),
                "parents": [self.base],
                "dirty": False,
            },
            "after": {
                "commit": self.source,
                "tree": self.git("rev-parse", "HEAD^{tree}"),
                "parents": [self.base],
                "dirty": False,
            },
        }
        path = self.records / f"{label}.json"
        path.write_text(json.dumps(record))
        return path

    def emit(self, records):
        return receipt.emit_receipt(
            repo=self.repo,
            source_sha=self.source,
            base_sha=self.base,
            tested_sha=self.source,
            lane="source-head",
            package="codex-hepta-infer-core",
            runner_os="Linux",
            runner_arch="X64",
            runner_name="GitHub Actions 1",
            runner_environment="github-hosted",
            records=records,
            expected_labels=["library", "binary", "check", "clippy"],
            generated_at="2026-09-29T00:00:00+00:00",
        )

    def test_success_binds_lock_runner_counts_and_commands(self):
        records = [
            (name, self.command_record(name))
            for name in ["library", "binary", "check", "clippy"]
        ]
        value = self.emit(records)
        self.assertEqual(value["result"], "success")
        self.assertEqual(value["test_counts"], {"passed": 12, "failed": 0, "skipped": 4})
        self.assertEqual(
            value["cargo_lock_blob"],
            self.git("rev-parse", f"{self.source}:codex-rs/Cargo.lock"),
        )
        self.assertEqual(value["runner"]["environment"], "github-hosted")
        self.assertRegex(value["receipt_sha256"], r"^[0-9a-f]{64}$")

    def test_missing_or_failed_command_fails_closed(self):
        records = [
            ("library", self.command_record("library")),
            ("binary", self.command_record("binary", status="failed", exit_code=1, failed=1)),
            ("check", self.command_record("check")),
        ]
        value = self.emit(records)
        self.assertEqual(value["result"], "failed_or_incomplete")
        self.assertTrue(any("missing command" in item for item in value["failures"]))
        self.assertTrue(any("binary" in item for item in value["failures"]))

    def test_log_tamper_rejected(self):
        path = self.command_record("library")
        (self.records / "library.log").write_text("changed")
        value = self.emit([
            ("library", path),
            ("binary", self.command_record("binary")),
            ("check", self.command_record("check")),
            ("clippy", self.command_record("clippy")),
        ])
        self.assertEqual(value["result"], "failed_or_incomplete")
        self.assertTrue(any("digest mismatch" in item for item in value["failures"]))

    def test_aggregate_requires_complete_matrix(self):
        records = [
            (name, self.command_record(name))
            for name in ["library", "binary", "check", "clippy"]
        ]
        value = self.emit(records)
        aggregate = receipt.aggregate_receipts(
            receipts=[value],
            source_sha=self.source,
            base_sha=self.base,
            expected_lanes=["source-head"],
            expected_packages=["codex-hepta-infer-core"],
            generated_at="2026-09-29T00:00:00+00:00",
        )
        self.assertEqual(aggregate["result"], "success")
        missing = receipt.aggregate_receipts(
            receipts=[value],
            source_sha=self.source,
            base_sha=self.base,
            expected_lanes=["source-head", "base-merge"],
            expected_packages=["codex-hepta-infer-core"],
        )
        self.assertEqual(missing["result"], "failed_or_incomplete")
        self.assertTrue(any("missing receipts" in item for item in missing["failures"]))

    def test_nextest_skip_parser_does_not_count_filtered(self):
        text = "Summary [ 1.000s] 7 tests run: 5 passed, 2 skipped, 90 filtered out"
        self.assertEqual(receipt.observed_skipped_tests(text), 2)


if __name__ == "__main__":
    unittest.main()
