"""Evidence view tests; fixture receipts are never native execution claims."""
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

import sys
sys.path.insert(0, str(ROOT / "scripts"))

import channel_matrix_evidence_v2 as policy
import channel_matrix_status as status
from channel_matrix_evidence import file_digest


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.source = {
            "schema": "hepta.channel-matrix-source-snapshot.v1",
            "testedSha": "a" * 40,
            "testedTree": "b" * 40,
            "sourceSha": "a" * 40,
            "baseSha": "c" * 40,
            "lane": "source-head",
            "files": [{"path": "fixture"}],
        }
        self.write("source.json", self.source)
        self.write("source-after.json", self.source)
        self.write(
            "candidate.json",
            {
                "schema": "hepta.channel-matrix-candidate-receipt.v1",
                "candidate": {"commit": "a" * 40, "tree": "b" * 40},
                "status": "PASS_CHANNEL_MATRIX_CANDIDATE_BINDING",
            },
        )

    def write(self, name, row):
        (self.path / name).write_text(json.dumps(row))

    def receipt(self, label="compile", **changes):
        log = self.path / f"{label}.log"
        log.write_text("fixture, not a Rust execution\n")
        row = {
            "schema": "hepta.channel-matrix-command.v1",
            "label": label,
            "arguments": status.COMMANDS[label],
            "workingDirectory": "codex-rs",
            "testedSha": "a" * 40,
            "sourceSnapshotSha256": file_digest(self.path / "source.json"),
            "completed": True,
            "exitCode": 0,
            "launchError": None,
            "sourceUnchanged": True,
            "log": {
                "path": log.name,
                "bytes": log.stat().st_size,
                "sha256": file_digest(log),
                "withinBudget": True,
            },
        }
        row.update(changes)
        self.write(f"{label}.command.json", row)

    def test_status_uses_the_exact_v2_command_policy(self):
        self.assertIs(status.COMMANDS, policy.evidence.COMMANDS)
        self.assertEqual(
            status.COMMANDS["focused-tests"],
            policy.FOCUSED_GATE_COMMAND,
        )
        self.assertEqual(
            status.COMMANDS["compile"],
            policy.COMPILE_COMMAND,
        )

    def test_compilation_does_not_imply_tests_or_target(self):
        self.receipt()
        row = status.summarize(self.path)
        self.assertEqual(row["states"]["compilation"], "passed")
        self.assertEqual(row["states"]["api_compile_fail"], "not_executed")
        self.assertEqual(row["states"]["native_tests"], "not_executed")
        self.assertEqual(row["states"]["clean_tree"], "passed")
        self.assertEqual(row["states"]["target_qualification"], "not_proved")
        self.assertFalse(row["activation"])

    def test_failed_and_interrupted_commands_remain_distinct(self):
        self.receipt(exitCode=7)
        self.assertEqual(
            status.summarize(self.path)["states"]["compilation"],
            "failed",
        )
        self.receipt(completed=False, exitCode=None)
        self.assertEqual(
            status.summarize(self.path)["states"]["compilation"],
            "not_completed",
        )

    def test_boolean_exit_and_stale_candidate_are_rejected(self):
        for update in (
            {"exitCode": False},
            {"testedSha": "d" * 40},
            {"workingDirectory": "."},
        ):
            self.receipt(**update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                status.summarize(self.path)

    def test_tampered_log_is_rejected(self):
        self.receipt()
        (self.path / "compile.log").write_text("tampered")
        with self.assertRaises(ValueError):
            status.summarize(self.path)

    def test_changed_source_cannot_pass(self):
        self.receipt()
        self.write(
            "source-after.json",
            {**self.source, "testedTree": "d" * 40},
        )
        row = status.summarize(self.path)
        self.assertEqual(row["states"]["compilation"], "invalid_evidence")
        self.assertEqual(row["states"]["clean_tree"], "invalid_evidence")

    def test_empty_failed_freeze_has_no_green_state(self):
        for path in self.path.iterdir():
            path.unlink()
        row = status.summarize(self.path)
        self.assertIsNone(row["candidate"])
        self.assertNotIn("passed", row["states"].values())

    def test_duplicate_fields_fail_closed(self):
        (self.path / "source.json").write_text(
            '{"testedSha":"a","testedSha":"b"}'
        )
        with self.assertRaises(ValueError):
            status.summarize(self.path)

    def test_all_local_passes_still_do_not_grant_acceptance(self):
        for label in status.COMMANDS:
            self.receipt(label)
        row = status.summarize(self.path)
        self.assertEqual(row["states"]["api_compile_fail"], "passed")
        self.assertEqual(row["states"]["clean_tree"], "passed")
        self.assertEqual(
            row["states"]["independent_acceptance"],
            "not_proved",
        )
        self.assertFalse(row["release"])
        self.assertIn("not deployment authority", status.markdown(row))
