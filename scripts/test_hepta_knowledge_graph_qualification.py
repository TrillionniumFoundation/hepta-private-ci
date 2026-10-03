"""Exercise the real exact-source recorder and KG qualification fan-in offline."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import hepta_knowledge_graph_qualification as kg

ROOT = Path(__file__).resolve().parents[1]


class KnowledgeGraphQualificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="kg-evidence-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in [
            ("init", "-q"),
            ("config", "user.name", "kg-test"),
            ("config", "user.email", "kg@example.invalid"),
        ]:
            self.git(*args)
        (self.repo / "source").write_text("source\n")
        self.git("add", ".")
        self.git("commit", "-qm", "source")
        source = self.git("rev-parse", "HEAD")
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.repo)
        env = patch.dict(
            os.environ,
            SOURCE_SHA=source,
            TESTED_SHA=source,
            BASE_SHA=source,
            HEPTA_CI_LANE="source-head",
        )
        env.start()
        self.addCleanup(env.stop)
        self.identity = kg.executor.identity()
        self.directory = self.root / "records"

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def command(self, passed=1, status=0):
        return [
            sys.executable,
            "-c",
            f"print('test result: ok. {passed} passed; 0 failed;'); raise SystemExit({status})",
        ]

    def record(self):
        path = self.root / "record.json"
        command = self.command()
        self.assertEqual(kg.executor.run(path, command, minimum_tests=1), 0)
        return path, command

    def test_success_binds_every_log_and_keeps_external_claims_false(self):
        with patch.object(
            kg, "commands", return_value=[("real", self.command(), 1, 5)]
        ):
            self.assertEqual(kg.run_suite(self.directory, "source-head"), 0)
        summary = json.loads((self.directory / "summary.json").read_text())
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["required_commands"], ["real"])
        for field in [
            "production_qualification",
            "independent_acceptance",
            "activation",
            "release",
        ]:
            self.assertIs(summary[field], False)
        for line in (self.directory / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(
                kg.hashlib.sha256((self.directory / name).read_bytes()).hexdigest(),
                digest,
            )

    def test_empty_selector_and_failed_command_do_not_hide_later_evidence(self):
        inventory = [
            ("empty", self.command(0), 1, 5),
            ("failed", self.command(1, 23), 1, 5),
            ("later", self.command(), 1, 5),
        ]
        with patch.object(kg, "commands", return_value=inventory):
            self.assertEqual(kg.run_suite(self.directory, "source-head"), 1)
        result = json.loads((self.directory / "summary.json").read_text())
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["problems"]), 2)
        self.assertEqual(
            [r["record"] for r in result["verified_commands"]], ["later.json"]
        )
        self.assertEqual(len(list(self.directory.glob("*.log"))), 3)

    def test_missing_and_modified_log_fail_verification(self):
        path, command = self.record()
        record = json.loads(path.read_text())
        log = path.with_name(record["log_file"])
        original = log.read_bytes()
        log.write_bytes(original + b"tamper")
        with self.assertRaisesRegex(ValueError, "log identity"):
            kg.verify_record(path, command, 1, self.identity)
        log.unlink()
        with self.assertRaises(FileNotFoundError):
            kg.verify_record(path, command, 1, self.identity)

    def test_record_relabeling_and_forged_counts_fail(self):
        path, command = self.record()
        original = json.loads(path.read_text())
        for field, value in [
            ("command", ["different"]),
            ("source_sha", "f" * 40),
            ("tested_sha", "f" * 40),
            ("run_id", "different-run"),
            ("run_attempt", "99"),
            ("lane", "base-merge"),
            ("minimum_tests", 0),
            ("observed_passed_tests", 4),
            ("log_file", "../outside"),
        ]:
            record = copy.deepcopy(original)
            record[field] = value
            path.write_text(json.dumps(record))
            with self.subTest(field=field), self.assertRaises(ValueError):
                kg.verify_record(path, command, 1, self.identity)
        for side in ["before", "after"]:
            record = copy.deepcopy(original)
            record[side]["tree"] = "f" * 40
            path.write_text(json.dumps(record))
            with self.subTest(side=side), self.assertRaises(ValueError):
                kg.verify_record(path, command, 1, self.identity)

    def test_existing_results_and_in_tree_evidence_are_rejected(self):
        self.directory.mkdir()
        with self.assertRaises(FileExistsError):
            kg.run_suite(self.directory, "source-head")
        with self.assertRaisesRegex(ValueError, "outside"):
            kg.run_suite(self.repo / "evidence", "source-head")

    def test_required_named_ignored_cases_select_exact_existing_rust_symbols(self):
        source, merge = kg.commands("source-head"), kg.commands("base-merge")
        for lane in [source, merge]:
            for name, command, minimum, _ in lane:
                if command[:2] == ["just", "test"]:
                    self.assertGreater(minimum, 0)
                    self.assertEqual(command[command.index("--no-tests") + 1], "fail")
        self.assertEqual([r for r in source if r[0] != "kg-capacity"], merge)
        for name, symbol, file in [
            ("kg-crash-reopen", kg.CRASH, "cognitive_store_tests.rs"),
            ("kg-capacity", kg.CAPACITY, "cognitive_kg_benchmark_tests.rs"),
        ]:
            command = next(command for label, command, _, _ in source if label == name)
            self.assertEqual(command[command.index("-E") + 1], f"test(={symbol})")
            self.assertEqual(command[command.index("--run-ignored") + 1], "only")
            rust = (ROOT / "codex-rs/hepta-memory/src" / file).read_text()
            self.assertIn("async fn " + symbol.split("::")[-1] + "(", rust)
            self.assertIn('#[ignore = "qualification:', rust)
        profile = tomllib.loads(
            (ROOT / "qualification/knowledge-graph/nextest.toml").read_text()
        )
        self.assertLessEqual(
            profile["profile"]["kg-capacity"]["slow-timeout"]["terminate-after"], 35
        )
        with self.assertRaises(ValueError):
            kg.commands("unknown")

    def test_changed_private_owners_each_have_a_nonempty_recorded_group(self):
        inventory = {
            label: (argv, minimum)
            for label, argv, minimum, _ in kg.commands("source-head")
        }
        for label, selector in {
            "agentd-browser": "browser_servo::tests::",
            "agentd-context": "cognitive_context::tests::",
            "agentd-learning-sink": "cognitive_retrieval_learning::tests::",
            "agentd-effect-host": "automation_effect_host::tests::",
            "agentd-effect-snapshot": "state::control::effect_snapshot_tests::",
        }.items():
            with self.subTest(label=label):
                argv, minimum = inventory[label]
                self.assertEqual(argv[argv.index("-E") + 1], f"test({selector})")
                self.assertIn("--lib", argv)
                self.assertGreater(minimum, 0)
        control = (ROOT / "codex-rs/hepta-agentd/src/state_control.rs").read_text()
        self.assertIn('#[path = "state_effect_snapshot_tests.rs"]', control)
        self.assertIn("mod effect_snapshot_tests;", control)
        browser = (ROOT / "codex-rs/hepta-agentd/src/browser_servo.rs").read_text()
        self.assertIn(
            "fn rejected_sequence_keeps_the_next_expected_frame_unchanged(", browser
        )

    def test_workflow_reaches_suite_and_retains_failures_without_permission_expansion(
        self,
    ):
        workflow = (
            ROOT / ".github/workflows/hepta-knowledge-graph-qualification.yml"
        ).read_text()
        self.assertIn("  pull_request:\n    paths:", workflow)
        self.assertIn("permissions:\n  contents: read\n", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("source-head", workflow)
        self.assertIn("base-merge", workflow)
        self.assertIn(".github/actions/hepta-synthetic-merge", workflow)
        run = workflow.split("      - name: Execute required KG commands", 1)[1].split(
            "      - name:", 1
        )[0]
        self.assertNotIn("continue-on-error", run)
        self.assertIn(
            'hepta_knowledge_graph_qualification.py --records "$RECORDS_DIR/commands"',
            run,
        )
        upload = workflow.split(
            "      - name: Retain exact source and merge outcomes", 1
        )[1]
        self.assertIn("if: always()", upload)
        self.assertIn("if-no-files-found: error", upload)


if __name__ == "__main__":
    unittest.main()
