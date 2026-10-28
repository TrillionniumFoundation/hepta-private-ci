"""Finite reader controls; synthetic fixtures never qualify a model study."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hepta_neural_evidence_v1 as evidence


class EvidenceReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.environment = {
            "SOURCE_SHA": "a" * 40,
            "TESTED_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_JOB": "fixture",
        }
        self.patcher = patch.dict(os.environ, self.environment)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def command_record(self):
        raw = b"Ran 2 tests in 0.010s\n\nOK\n"
        (self.root / "command.log").write_bytes(raw)
        identity = {"commit": "a" * 40, "tree": "b" * 40, "parents": [], "dirty": False}
        record = {
            "status": "passed",
            "command_exit_code": 0,
            "exit_code": 0,
            "timed_out": False,
            "output_limit_exceeded": False,
            "source_sha": "a" * 40,
            "tested_sha": "a" * 40,
            "lane": "source-head",
            "run_id": "123",
            "run_attempt": "1",
            "job": "fixture",
            "before": identity,
            "after": identity,
            "minimum_tests": 2,
            "log_file": "command.log",
            "log_bytes": len(raw),
            "log_sha256": hashlib.sha256(raw).hexdigest(),
            "observed_passed_tests": 2,
            "observed_failed_tests": 0,
            "command": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-infer-worker-host",
                "--lib",
                "--profile",
                "hepta-public-initial-v2",
                "-E",
                "test(real_selected_initial_serves_ordinary_context_then_refuses_revocation) | "
                "test(real_public_initial_reopens_same_ordinary_owners)",
                "--run-ignored",
                "only",
                "--no-capture",
            ],
        }
        (self.root / "ordinary-native.json").write_text(json.dumps(record))
        return record

    def test_ansi_names_require_each_original_pidfd_control(self):
        record = self.command_record()
        names = list(evidence.NAMESPACE_TESTS) + [
            "pidfd_reaper::tests::" + name for name in evidence.PIDFD_TESTS
        ]

        def install(selected):
            raw = (
                "\n".join(
                    "\x1b[32mPASS\x1b[0m [0.001s] fixture " + name for name in selected
                )
                + "\nSummary [0.01s] 14 tests run: 14 passed, 0 skipped\n"
            ).encode()
            (self.root / "command.log").write_bytes(raw)
            record.update(
                minimum_tests=14,
                observed_passed_tests=14,
                log_bytes=len(raw),
                log_sha256=hashlib.sha256(raw).hexdigest(),
            )
            (self.root / "namespace-and-pidfd.json").write_text(json.dumps(record))

        install(names)
        self.assertEqual(
            evidence.Evidence(self.root).command("namespace-and-pidfd", 14)["passed"],
            14,
        )
        install(names[:-1] + [names[-2]])
        with self.assertRaises(ValueError):
            evidence.Evidence(self.root).command("namespace-and-pidfd", 14)
        install(names[:-1] + [names[-1] + "_impostor"])
        with self.assertRaises(ValueError):
            evidence.Evidence(self.root).command("namespace-and-pidfd", 14)

    def test_actual_terminal_log_is_required_despite_success_status(self):
        self.command_record()
        reader = evidence.Evidence(self.root)
        self.assertEqual(reader.command("ordinary-native", 2)["passed"], 2)
        (self.root / "command.log").write_text("all good\n")
        with self.assertRaises(ValueError):
            reader.command("ordinary-native", 2)

    def test_another_run_cannot_supply_passing_receipt(self):
        record = self.command_record()
        record["run_id"] = "122"
        (self.root / "ordinary-native.json").write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            evidence.Evidence(self.root).command("ordinary-native", 2)

    def test_arbitrary_passing_command_cannot_impersonate_model_gate(self):
        record = self.command_record()
        record["command"] = ["python3", "unrelated-passing-test.py"]
        (self.root / "ordinary-native.json").write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            evidence.Evidence(self.root).command("ordinary-native", 2)

    def test_all_declared_success_without_real_loop_still_fails(self):
        with patch.dict(os.environ, dict.fromkeys(evidence.REQUIRED, "success")):
            self.assertEqual(evidence.assess(self.root), 1)
        report = evidence.read(self.root / "qualification-summary.json")
        self.assertTrue(report["checks"]["declared_outcomes"]["passed"])
        self.assertFalse(report["checks"]["actual_positive_loop"]["passed"])
        self.assertFalse(report["passed"])

    def test_skipped_declared_gate_is_not_success(self):
        with patch.dict(
            os.environ,
            {**dict.fromkeys(evidence.REQUIRED, "success"), "LINT": "skipped"},
        ):
            self.assertEqual(evidence.assess(self.root), 1)
        self.assertFalse(
            evidence.read(self.root / "qualification-summary.json")["checks"][
                "declared_outcomes"
            ]["passed"]
        )

    def test_pin_rejects_changed_or_other_run_bytes(self):
        path = self.root / "pin.json"
        path.write_bytes(b'{"value":1}')
        pin = {"path": str(path), "sha256": evidence.regular(path)["sha256"]}
        reader = evidence.Evidence(self.root)
        self.assertEqual(reader.pin(pin), {"value": 1})
        path.write_bytes(b'{"value":2}')
        with self.assertRaises(ValueError):
            reader.pin(pin)
        with self.assertRaises(ValueError):
            reader.path(self.root.parent / "other-run.json")

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        for raw in (
            b'{"passed":false,"passed":true}',
            b'{"count":NaN}',
            b'{"count":Infinity}',
        ):
            with self.assertRaises(ValueError):
                evidence.decode(raw)

    def test_unchanged_cleanup_limit_and_actual_reaping_are_required(self):
        value = {
            "outcome": "success",
            "exit_code": 0,
            "stop_reason": None,
            "waited_child_reaped": True,
            "owned_child_reap_resolved": True,
            "owned_child_echild_observed": False,
            "waited_child_observation_error": None,
            "budget": {"wall_seconds": 600, "rss_bytes": 8 * 1024**3},
            "exit_observation_profile": {"maximum_drain_ns": 100000000},
        }
        reader = evidence.Evidence(self.root)
        reader.supervisor(value, 600, 8 * 1024**3)
        for altered in (
            {**value, "owned_child_reap_resolved": False},
            {**value, "exit_observation_profile": {"maximum_drain_ns": 101000000}},
        ):
            with self.assertRaises(ValueError):
                reader.supervisor(altered, 600, 8 * 1024**3)

    def test_parent_directory_symlink_is_not_followed(self):
        directory = self.root / "real"
        directory.mkdir()
        (directory / "receipt").write_bytes(b"private fixture")
        (self.root / "alias").symlink_to(directory, target_is_directory=True)
        with self.assertRaises(OSError):
            evidence.regular(self.root / "alias/receipt")

    def test_archive_retains_failure_and_payload_bytes_without_following_links(self):
        source = self.root / "run"
        source.mkdir()
        (source / "failed.json").write_bytes(b'{"passed":false}\n')
        (source / "artifact.safetensors").write_bytes(b"actual fixture payload")
        (source / "link").symlink_to(self.root / "outside")
        output = self.root / "archive"
        with patch.dict(os.environ, {"HEPTA_NEURAL_STUDY_CELL": ""}):
            self.assertEqual(evidence.archive(source, output), 0)
        manifest = evidence.read(output / "archive-manifest.json")
        self.assertTrue(manifest["complete_regular_files"])
        self.assertEqual(len(manifest["files"]), 2)
        self.assertEqual(len(manifest["nonregular_entries"]), 1)
        self.assertEqual(
            (output / "raw/failed.json").read_bytes(),
            (source / "failed.json").read_bytes(),
        )
        self.assertEqual(
            (output / "raw/artifact.safetensors").read_bytes(),
            b"actual fixture payload",
        )

    def test_full_source_rejects_hidden_modified_tracked_bytes(self):
        repository = self.root / "repo"
        repository.mkdir()

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(repository), *args], stderr=subprocess.PIPE, text=True
            ).strip()

        git("init", "-q")
        git("config", "user.name", "Reader test")
        git("config", "user.email", "reader@example.invalid")
        (repository / "source.py").write_text("value = 1\n")
        git("add", "source.py")
        git("commit", "-qm", "fixture")
        head = git("rev-parse", "HEAD")
        self.assertEqual(len(evidence.collect_source(repository, head)["files"]), 1)
        git("update-index", "--assume-unchanged", "source.py")
        (repository / "source.py").write_text("value = 2\n")
        with self.assertRaises(ValueError):
            evidence.collect_source(repository, head)

    def test_archive_rejects_cell_executable_replaced_after_build(self):
        source = self.root / "run"
        source.mkdir()
        binary = self.root / "cell.elf"
        binary.write_bytes(b"\x7fELForiginal")
        (source / "cell-binary.sha256").write_text(
            evidence.regular(binary)["sha256"] + "  " + str(binary) + "\n"
        )
        binary.write_bytes(b"\x7fELFreplaced")
        output = self.root / "archive"
        with patch.dict(os.environ, {"HEPTA_NEURAL_STUDY_CELL": str(binary)}):
            self.assertEqual(evidence.archive(source, output), 1)
        manifest = evidence.read(output / "archive-manifest.json")
        self.assertFalse(manifest["complete_regular_files"])
        self.assertIn("Cell ELF differs", manifest["errors"][0])

    def test_actual_executable_receipt_replaces_early_listing_and_rejects_mutation(
        self,
    ):
        source = self.root / "run"
        study = source / "n/n"
        study.mkdir(parents=True)
        target = self.root / "cargo-target"
        binary = target / "debug/deps/codex_hepta_infer_worker_host-123abc"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x7fELFactual-positive-fixture")
        binary.chmod(0o700)
        (source / "native-input.json").write_text(
            json.dumps({"output": str(source / "n")})
        )
        record = {
            "schema": "hepta-actual-test-executable-v1",
            "pid": os.getpid(),
            "executable": {"path": str(binary), **evidence.regular(binary)},
        }
        (study / "actual-test-executable-before.json").write_text(json.dumps(record))
        # This stale listing intentionally describes a missing, different build.
        (source / "model-target.json").write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "model_tests_present": True,
                            "path": str(target / "old-listed-elf"),
                            "bytes": 99,
                            "sha256": "0" * 64,
                        }
                    ]
                }
            )
        )
        with patch.dict(
            os.environ, {"CARGO_TARGET_DIR": str(target), "HEPTA_NEURAL_STUDY_CELL": ""}
        ):
            reader = evidence.Evidence(source)
            self.assertFalse(
                reader.actual_executable(require_completed=False)["completed"]
            )
            with self.assertRaises(ValueError):
                reader.actual_executable(require_completed=True)
            (study / "actual-test-executable-after.json").write_text(json.dumps(record))
            self.assertTrue(
                reader.actual_executable(require_completed=True)["completed"]
            )
            output = self.root / "actual-archive"
            self.assertEqual(evidence.archive(source, output), 0)
            self.assertEqual(
                (output / "executables/actual-positive-test.elf").read_bytes(),
                binary.read_bytes(),
            )
            self.assertTrue(
                evidence.read(output / "archive-manifest.json")[
                    "actual_positive_executable"
                ]["completed"]
            )
            binary.write_bytes(b"\x7fELFreplaced-positive-fixture")
            with self.assertRaises(ValueError):
                reader.actual_executable(require_completed=True)
            binary.write_bytes(b"\x7fELFactual-positive-fixture")
            original_reader = evidence.Evidence.actual_executable

            def replace_after_validation(instance, *, require_completed):
                actual = original_reader(instance, require_completed=require_completed)
                binary.write_bytes(b"\x7fELFreplaced-between-validation-and-copy")
                return actual

            raced = self.root / "raced-archive"
            with patch.object(
                evidence.Evidence, "actual_executable", replace_after_validation
            ):
                self.assertEqual(evidence.archive(source, raced), 1)
            failure = evidence.read(raced / "archive-manifest.json")
            self.assertFalse(failure["complete_regular_files"])
            self.assertIn(
                "archive source differs from executed pin", failure["errors"][0]
            )


if __name__ == "__main__":
    unittest.main()
