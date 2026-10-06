"""Local mechanics regressions; no Bazel build, cache service, or native proof."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import hepta_bazel_cache_pilot as pilot


class PilotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.cache = self.directory / "cache"
        self.cache.mkdir()
        (self.cache / "entry").write_bytes(b"entry")

    def test_flat_directory_checks_deadline_per_entry(self):
        for index in range(10):
            (self.cache / str(index)).write_bytes(b"x")
        with patch.object(pilot.time, "monotonic", side_effect=[0, 0, 0, 0, 2]):
            with self.assertRaisesRegex(ValueError, "deadline"):
                pilot.cache_size(self.cache, deadline_seconds=1)

    def test_flat_directory_has_an_entry_count_bound(self):
        (self.cache / "second").write_bytes(b"x")
        with patch.object(pilot, "MAX_SCAN_ENTRIES", 1):
            with self.assertRaisesRegex(ValueError, "entry limit"):
                pilot.cache_size(self.cache)

    def test_diagnostics_capture_attempt_tail_without_invoking_bazel(self):
        attempt = self.directory / "output/execroot/_main/bazel-out/linux-fastbuild/testlogs/pkg/target/test_attempts/attempt_1.log"
        attempt.parent.mkdir(parents=True)
        attempt.write_bytes(b"x" * 70000 + b"exact assertion failure")
        with patch.object(pilot.subprocess if hasattr(pilot, "subprocess") else subprocess, "run", side_effect=AssertionError("no diagnostic command invocation")):
            report = pilot.retain_diagnostics(self.directory)
        captured = [item for item in report["files"] if "test-attempt" in item["captured"]]
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0]["tail_truncated"])
        self.assertLessEqual(captured[0]["captured_bytes"], 64 * 1024)
        self.assertTrue((self.directory / "diagnostics" / captured[0]["captured"]).read_bytes().endswith(b"exact assertion failure"))

    def test_named_diagnostic_fifo_is_rejected_without_blocking(self):
        os.mkfifo(self.directory / "build-events.json")
        code = (
            "import json; from pathlib import Path; import hepta_bazel_cache_pilot as p; "
            f"print(json.dumps(p.retain_diagnostics(Path({str(self.directory)!r}))))"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, timeout=3, check=True,
                                cwd=Path(__file__).resolve().parent)
        report = json.loads(result.stdout)
        self.assertTrue(report["unsafe"])
        self.assertFalse(report["files"])

    def test_symlinked_diagnostic_destination_is_never_written(self):
        outside = self.directory / "outside"
        outside.mkdir()
        (self.directory / "diagnostics").symlink_to(outside, target_is_directory=True)
        report = pilot.retain_diagnostics(self.directory)
        self.assertTrue(report["unsafe"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_source_ancestor_is_not_followed(self):
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "test.log").write_text("DO_NOT_COPY")
        (self.directory / "output").symlink_to(outside, target_is_directory=True)
        report = pilot.retain_diagnostics(self.directory)
        self.assertTrue(report["unsafe"])
        self.assertFalse(report["files"])
        self.assertNotIn("DO_NOT_COPY", (self.directory / "diagnostics/index.json").read_text())

    def test_symlinked_pilot_root_is_rejected(self):
        alias = self.directory / "alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        report = pilot.retain_diagnostics(alias)
        self.assertTrue(report["unsafe"])
        self.assertFalse((self.directory / "diagnostics").exists())

    def test_retained_directory_does_not_follow_replaced_name(self):
        owned = self.directory / "owned"
        owned.mkdir()
        (owned / "entry").write_text("owned")
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "entry").write_text("DO_NOT_COPY")
        with pilot.absolute_directory(self.directory) as root_fd:
            with pilot.relative_directory(root_fd, ("owned",)) as owned_fd:
                owned.rename(self.directory / "retained")
                owned.symlink_to(outside, target_is_directory=True)
                descriptor = os.open("entry", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     dir_fd=owned_fd)
                with os.fdopen(descriptor) as stream:
                    self.assertEqual(stream.read(), "owned")

    def test_group_telemetry_is_opt_in_for_existing_recorder(self):
        record = pilot.hepta_ci_exec.execute_logged(
            [sys.executable, "-c", "pass"], self.directory / "default.log",
        )
        self.assertNotIn("process_group_id", record)
        opted = pilot.hepta_ci_exec.execute_logged(
            [sys.executable, "-c", "pass"], self.directory / "opted.log",
            retain_process_group=True,
        )
        self.assertGreater(opted["process_group_id"], 0)

    def test_size_rejects_symlinks(self):
        (self.cache / "link").symlink_to(self.directory / "elsewhere")
        with self.assertRaises(ValueError):
            pilot.cache_size(self.cache)

    def test_size_rejects_nonregular_entry(self):
        os.mkfifo(self.cache / "pipe")
        with self.assertRaises(ValueError):
            pilot.cache_size(self.cache)

    def test_size_rejects_over_limit(self):
        with patch.object(pilot, "CACHE_LIMIT", 4):
            with self.assertRaises(ValueError):
                pilot.cache_size(self.cache)

    def test_readiness_requires_quiescence(self):
        with patch.object(pilot, "free_bytes", return_value=20 * 1024**3):
            self.assertFalse(pilot.save_readiness(self.directory, quiescent=False, remaining_seconds=900)["save_ready"])

    def test_readiness_rejects_low_space(self):
        with patch.object(pilot, "free_bytes", return_value=pilot.FREE_RESERVE - 1):
            self.assertFalse(pilot.save_readiness(self.directory, quiescent=True, remaining_seconds=900)["save_ready"])

    def test_readiness_rejects_short_deadline(self):
        self.assertFalse(pilot.save_readiness(self.directory, quiescent=True, remaining_seconds=299)["save_ready"])

    def test_readiness_rejects_empty_cache(self):
        (self.cache / "entry").unlink()
        with patch.object(pilot, "free_bytes", return_value=20 * 1024**3):
            self.assertFalse(pilot.save_readiness(self.directory, quiescent=True, remaining_seconds=900)["save_ready"])

    def test_bounded_quiescent_cache_is_ready(self):
        with patch.object(pilot, "free_bytes", return_value=20 * 1024**3):
            result = pilot.save_readiness(self.directory, quiescent=True, remaining_seconds=900)
        self.assertTrue(result["save_ready"])
        self.assertEqual(result["cache_bytes"], 5)

    def test_group_probe_uncertainty_never_saves(self):
        with patch.object(pilot, "group_exists", return_value=True):
            self.assertFalse(pilot.wait_for_quiescence(123, seconds=0))
        for value in (0, -1, None, "123"):
            self.assertFalse(pilot.wait_for_quiescence(value, seconds=0))

    def test_command_is_fixed_batch_fresh_test_and_isolated_paths(self):
        command = pilot.native_command(Path("/reviewed"), self.directory)
        self.assertLess(command.index("--batch"), command.index("test"))
        self.assertIn("--nocache_test_results", command)
        self.assertIn("--config=ci-linux", command)
        self.assertIn(f"--disk_cache={self.cache}", command)
        self.assertIn(f"--output_base={self.directory / 'output'}", command)
        self.assertEqual(command[-2:], ["--", "//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test"])


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = self.directory / "repo"
        self.repo.mkdir()
        for relative in pilot.COMPATIBILITY_FILES:
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("pinned input")
        self.identity = {"commit": "1" * 40, "tree": "2" * 40, "dirty": False, "parents": []}

    def prepare(self, name, env=None):
        with patch.object(pilot.hepta_ci_exec, "identity", return_value=self.identity), patch.object(pilot, "free_bytes", return_value=20 * 1024**3):
            actual_env = dict(env or {"ImageVersion": "runner-v1"})
            actual_env.setdefault("HEPTA_PILOT_JOB_STARTED", str(time.monotonic()))
            return pilot.prepare(self.repo, self.directory / name, actual_env)

    def test_delayed_preparation_does_not_restart_job_budget(self):
        started = time.monotonic() - 300
        state = self.prepare("delayed", {"ImageVersion": "runner-v1", "HEPTA_PILOT_JOB_STARTED": str(started)})
        self.assertEqual(state["deadline"], started + pilot.BUILD_SECONDS)
        self.assertEqual(state["outer_deadline"], started + pilot.USABLE_JOB_SECONDS)
        self.assertLess(state["deadline"] - time.monotonic(), 2401)

    def test_expired_or_future_time_anchor_rejected(self):
        for started in (time.monotonic() - 3000, time.monotonic() + 100, float("inf")):
            with self.assertRaises(ValueError):
                self.prepare("invalid-time", {"ImageVersion": "runner-v1", "HEPTA_PILOT_JOB_STARTED": str(started)})

    def test_compatibility_key_changes_for_pin_or_runner_image(self):
        first = self.prepare("first")
        changed_image = self.prepare("second", {"ImageVersion": "runner-v2"})
        self.assertNotEqual(first["restore_prefix"], changed_image["restore_prefix"])
        (self.repo / ".bazelversion").write_text("different pin")
        changed_pin = self.prepare("third")
        self.assertNotEqual(first["restore_prefix"], changed_pin["restore_prefix"])

    def test_source_tree_changes_primary_but_not_compatible_prefix(self):
        first = self.prepare("first")
        self.identity["tree"] = "3" * 40
        second = self.prepare("second")
        self.assertEqual(first["restore_prefix"], second["restore_prefix"])
        self.assertNotEqual(first["cache_key"], second["cache_key"])

    def test_keyed_context_and_missing_image_are_rejected(self):
        for env in ({"ImageVersion": "runner-v1", "BUILDBUDDY_API_KEY": "test-only-sentinel"}, {"OTHER": "value"}):
            with self.assertRaises(ValueError):
                self.prepare("rejected", env)

    def test_preparation_never_reuses_existing_attempt_directory(self):
        self.prepare("once")
        with self.assertRaises(ValueError):
            self.prepare("once")


class RecordedOutcomeTests(unittest.TestCase):
    def setUp(self):
        PilotTests.setUp(self)
        self.repo = self.directory / "repo"
        self.repo.mkdir()
        for args in (("init", "-q"), ("config", "user.name", "Fixture"), ("config", "user.email", "fixture@example.invalid")):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)
        (self.repo / "source").write_text("reviewed source")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)
        self.old_cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.old_cwd)
        identity = pilot.hepta_ci_exec.identity()
        self.state = {"directory": str(self.directory), "deadline": time.monotonic() + 20, "outer_deadline": time.monotonic() + 900, "source_identity": identity}
        env = {"SOURCE_SHA": identity["commit"], "TESTED_SHA": identity["commit"], "BASE_SHA": identity["commit"], "HEPTA_CI_LANE": "source-head"}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, code, deadline=None):
        if deadline is not None:
            self.state["deadline"] = time.monotonic() + deadline
        with patch.object(pilot, "native_command", return_value=[sys.executable, "-c", code]), patch.object(pilot, "free_bytes", return_value=20 * 1024**3):
            return pilot.run_native(self.repo, self.state)

    def test_failed_native_result_survives_ready_cache(self):
        code, ready = self.execute("raise SystemExit(7)")
        self.assertEqual(code, 7)
        self.assertEqual(ready["native_exit_code"], 7)
        self.assertFalse(ready["save_ready"])
        self.assertTrue(ready["measured_save_eligibility"])
        self.assertTrue(ready["measurement_only"])

    def test_timeout_remains_failure(self):
        code, ready = self.execute("import time; time.sleep(10)", deadline=0.1)
        self.assertNotEqual(code, 0)
        self.assertEqual(ready["native_exit_code"], code)
        self.assertTrue(json.loads((self.directory / "native.json").read_text())["timed_out"])

    def test_unconfirmed_writer_prevents_save(self):
        with patch.object(pilot, "wait_for_quiescence", return_value=False):
            code, ready = self.execute("raise SystemExit(0)")
        self.assertEqual(code, 0)
        self.assertFalse(ready["save_ready"])

    def test_source_mutation_during_native_work_prevents_cache_save(self):
        code, ready = self.execute("from pathlib import Path; Path('source').write_text('mutated')")
        self.assertNotEqual(code, 0)
        self.assertFalse(ready["save_ready"])

    def test_restored_symlink_rejected_before_launch(self):
        (self.cache / "link").symlink_to(self.directory / "elsewhere")
        with patch.object(pilot, "free_bytes", return_value=20 * 1024**3), patch.object(pilot, "native_command") as command:
            code, ready = pilot.run_native(self.repo, self.state)
        self.assertEqual(code, 2)
        self.assertFalse(ready["save_ready"])
        command.assert_not_called()

    def test_cache_scan_consumed_budget_prevents_native_launch(self):
        def slow_scan(_):
            self.state["deadline"] = time.monotonic() - 1
            return 5
        with patch.object(pilot, "cache_size", side_effect=slow_scan), patch.object(pilot, "free_bytes", return_value=20 * 1024**3), patch.object(pilot, "native_command") as command:
            code, ready = pilot.run_native(self.repo, self.state)
        self.assertEqual(code, 2)
        self.assertFalse(ready["save_ready"])
        command.assert_not_called()

    def test_recorder_rechecks_deadline_after_source_validation(self):
        original = pilot.hepta_ci_exec.identity
        def delayed_identity():
            time.sleep(0.05)
            return original()
        with patch.object(pilot.hepta_ci_exec, "identity", side_effect=delayed_identity), patch.object(pilot.hepta_ci_exec, "execute_logged") as execute:
            code = pilot.hepta_ci_exec.run(
                self.directory / "delayed.json", [sys.executable, "-c", "pass"],
                deadline_monotonic=time.monotonic() + 0.01,
            )
        self.assertEqual(code, 2)
        execute.assert_not_called()

    def test_changed_source_rejected_before_launch(self):
        (self.repo / "source").write_text("changed source")
        with patch.object(pilot, "native_command") as command:
            code, ready = pilot.run_native(self.repo, self.state)
        self.assertEqual(code, 2)
        self.assertFalse(ready["save_ready"])
        command.assert_not_called()

    def test_runtime_free_space_stop_remains_failed_and_unsaved(self):
        with patch.object(pilot, "native_command", return_value=[sys.executable, "-c", "import time; time.sleep(10)"]), patch.object(pilot, "free_bytes", side_effect=[20 * 1024**3, 20 * 1024**3, 0, 20 * 1024**3]):
            code, ready = pilot.run_native(self.repo, self.state)
        self.assertNotEqual(code, 0)
        self.assertTrue(ready["low_space_stop"])
        self.assertFalse(ready["save_ready"])

    def test_initial_free_space_rejected_before_launch(self):
        with patch.object(pilot, "free_bytes", return_value=0), patch.object(pilot, "native_command") as command:
            code, ready = pilot.run_native(self.repo, self.state)
        self.assertEqual(code, 2)
        self.assertFalse(ready["save_ready"])
        command.assert_not_called()


class WorkflowContractTests(unittest.TestCase):
    def test_opt_in_single_linux_lane_preserves_failure_and_never_uploads_cache(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".github/workflows/bazel.yml").read_text()
        diagnostic = text.split("  fixed-linux-supervisor:", 1)[1].split("  fixed-windows-platform:", 1)[0]
        self.assertIn("inputs.qualification-group == 'linux-supervisor'", diagnostic)
        self.assertNotIn("secrets:", diagnostic)
        self.assertEqual(diagnostic.count("runs-on:"), 1)
        self.assertIn("runs-on: ubuntu-24.04", diagnostic)
        self.assertIn("timeout-minutes: 60", diagnostic)
        native = diagnostic.split("      - name: Run only Supervisor", 1)[1].split("      - name:", 1)[0]
        self.assertNotIn("continue-on-error", native)
        self.assertNotIn("actions/cache/save", diagnostic)
        self.assertNotIn("actions/cache/restore", diagnostic)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", diagnostic)
        self.assertLess(diagnostic.index("Anchor diagnostic budget before checkout"), diagnostic.index("actions/checkout@"))


if __name__ == "__main__":
    unittest.main()
