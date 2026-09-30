import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("campaign", Path(__file__).parents[1] / "platform_wire_fuzz_campaign.py")
campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(campaign)


class CampaignTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.receipt = self.root / "campaign.json"
        env = patch.dict(os.environ, FUZZ_TOOLCHAIN="nightly-test", CARGO_FUZZ_VERSION="0.13.2",
                         SOURCE_SHA="a" * 40, GITHUB_EVENT_NAME="workflow_dispatch",
                         REQUESTED_SECONDS="60", GITHUB_RUN_ID="12", GITHUB_RUN_ATTEMPT="1",
                         GITHUB_WORKFLOW_REF="repo/workflow@refs/heads/main", GITHUB_WORKFLOW_SHA="c" * 40)
        env.start()
        self.addCleanup(env.stop)
        subject = patch.object(campaign, "subject", return_value={
            "source_sha": "a" * 40, "tested_sha": "a" * 40, "source_tree": "b" * 40,
        })
        subject.start()
        self.addCleanup(subject.stop)

    def passing(self):
        result = campaign.initialize(self.root, self.receipt)
        for target in campaign.TARGETS:
            log = self.root / (target + ".log")
            log.write_text("stat::number_of_executed_units: 5\n")
            result["targets"][target] = {
                "status": "passed", "exit_code": 0, "executed_units": 5,
                "log_sha256": campaign.digest(log), "command": campaign.command(target, 20),
                "cwd": "codex-rs/hepta-wire", "duration_seconds": 20,
                "timeout_seconds": 140, "elapsed_seconds": 20.1,
            }
        campaign.save(self.receipt, result)
        return result

    def test_duration_limits_and_non_shell_inputs(self):
        for value in ("", "0", "59", "1801", "999999", "60; echo bad", "$(id)", "-1"):
            with self.assertRaises(ValueError):
                campaign.seconds("workflow_dispatch", value)
        self.assertEqual(campaign.seconds("workflow_dispatch", "60"), 60)
        self.assertEqual(campaign.seconds("pull_request", "$(id)"), 180)
        self.assertEqual(campaign.seconds("schedule", ""), 900)

    def test_commands_are_allowlisted_and_bounded(self):
        self.assertIn("-print_final_stats=1", campaign.command("managed_records", 20))
        for target, duration in (("evil", 20), ("decode_frames", 0), ("decode_frames", 601), ("decode_frames", True)):
            with self.assertRaises(ValueError):
                campaign.command(target, duration)

    def test_success_text_is_not_execution(self):
        log = self.root / "run.log"
        log.write_text("success\nnot_run\nstat::number_of_executed_units: 0\n")
        self.assertEqual(campaign.executed_units(log), 0)
        log.write_text("stat::number_of_executed_units: 251\n")
        self.assertEqual(campaign.executed_units(log), 251)

    def test_init_failure_retains_not_run_targets(self):
        with patch.dict(os.environ, REQUESTED_SECONDS=""):
            with self.assertRaises(ValueError):
                campaign.initialize(self.root, self.receipt)
        result = json.loads(self.receipt.read_text())
        self.assertEqual(result["status"], "failed")
        self.assertTrue(all(row["status"] == "not_run" for row in result["targets"].values()))

    def test_missing_receipt_fails_closed(self):
        self.assertFalse(campaign.finalize(self.root, self.receipt))
        self.assertEqual(json.loads(self.receipt.read_text())["status"], "failed")

    def test_interrupted_execution_never_passes(self):
        result = self.passing()
        for row in result["targets"].values():
            row["status"] = "running"
        campaign.save(self.receipt, result)
        self.assertFalse(campaign.finalize(self.root, self.receipt))
        self.assertTrue(all(row["status"] == "failed" for row in json.loads(self.receipt.read_text())["targets"].values()))

    def test_valid_logs_and_exact_source_are_required(self):
        original = self.passing()
        self.assertTrue(campaign.finalize(self.root, self.receipt))
        with patch.object(campaign, "subject", return_value={"source_sha": "d" * 40}):
            self.assertFalse(campaign.finalize(self.root, self.receipt))
        campaign.save(self.receipt, original)
        (self.root / "managed_records.log").write_text("changed\n")
        self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_bad_target_does_not_skip_remaining_scenarios(self):
        campaign.initialize(self.root, self.receipt)
        calls = []
        def fake_run(argv, **kwargs):
            calls.append(argv[4])
            kwargs["stdout"].write("stat::number_of_executed_units: 7\n")
            return 1 if len(calls) == 1 else 0
        with patch.object(campaign, "run_bounded", side_effect=fake_run):
            campaign.run(self.root, self.receipt)
        self.assertEqual(calls, list(campaign.TARGETS))
        rows = json.loads(self.receipt.read_text())["targets"]
        self.assertEqual(rows["decode_frames"]["status"], "failed")
        self.assertEqual(rows["policy_admission"]["status"], "passed")

    def test_old_workflow_invocation_and_toolchain_are_rejected(self):
        for field in campaign.CONTEXT:
            with self.subTest(field=field):
                result = self.passing()
                result[field] = "substituted"
                campaign.save(self.receipt, result)
                self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_missing_identity_fields_are_not_inferred(self):
        for field in (*campaign.CONTEXT, "source_sha", "tested_sha", "source_tree", "schema"):
            with self.subTest(field=field):
                result = self.passing()
                del result[field]
                campaign.save(self.receipt, result)
                self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_command_substitution_cannot_borrow_valid_statistics(self):
        for index in range(len(campaign.command("decode_frames", 20))):
            with self.subTest(index=index):
                result = self.passing()
                result["targets"]["decode_frames"]["command"][index] = "substituted"
                campaign.save(self.receipt, result)
                self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_numeric_type_budget_and_context_guards(self):
        for changes in (
            {"exit_code": False}, {"exit_code": 0.0}, {"executed_units": True},
            {"executed_units": 5.0}, {"duration_seconds": 21}, {"duration_seconds": True},
            {"timeout_seconds": 140.0}, {"timeout_seconds": 10},
            {"cwd": "somewhere/else"}, {"elapsed_seconds": 0},
            {"elapsed_seconds": float("nan")}, {"elapsed_seconds": float("inf")},
            {"elapsed_seconds": True},
        ):
            with self.subTest(changes=changes):
                result = self.passing()
                result["targets"]["managed_records"].update(changes)
                campaign.save(self.receipt, result)
                self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_requested_budget_must_equal_initialized_budget(self):
        self.passing()
        with patch.dict(os.environ, REQUESTED_SECONDS="120"):
            self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_engine_and_sanitizer_are_bound(self):
        for field in ("engine", "sanitizer"):
            result = self.passing()
            result[field] = "different"
            campaign.save(self.receipt, result)
            self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_zero_statistics_and_build_logs_cannot_qualify(self):
        for text in ("Finished release profile\n", "stat::number_of_executed_units: 0\n"):
            result = self.passing()
            log = self.root / "policy_admission.log"
            log.write_text(text)
            result["targets"]["policy_admission"]["log_sha256"] = campaign.digest(log)
            campaign.save(self.receipt, result)
            self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_missing_log_is_rejected(self):
        self.passing()
        (self.root / "policy_admission.log").unlink()
        self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_malformed_top_level_is_replaced_with_failure(self):
        for text in ("{", "[]", "null", "1", '"text"'):
            with self.subTest(text=text):
                self.receipt.write_text(text)
                self.assertFalse(campaign.finalize(self.root, self.receipt))
                self.assertEqual(json.loads(self.receipt.read_text())["status"], "failed")

    def test_malformed_targets_fail_closed(self):
        for value in (None, [], "text"):
            result = self.passing()
            result["targets"] = value
            campaign.save(self.receipt, result)
            self.assertFalse(campaign.finalize(self.root, self.receipt))
            result = self.passing()
            result["targets"]["managed_records"] = value
            campaign.save(self.receipt, result)
            self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_missing_one_target_cannot_pass(self):
        result = self.passing()
        del result["targets"]["managed_records"]
        campaign.save(self.receipt, result)
        self.assertFalse(campaign.finalize(self.root, self.receipt))

    def test_execution_does_not_self_attest_acceptance(self):
        self.passing()
        self.assertTrue(campaign.finalize(self.root, self.receipt))
        self.assertTrue(campaign.finalize(self.root, self.receipt))
        result = json.loads(self.receipt.read_text())
        for field in ("production_activation", "independent_acceptance", "real_transport_acceptance"):
            self.assertIs(result[field], False)

    def test_timeouts_retire_previous_passes_and_attempt_every_target(self):
        self.passing()
        with patch.object(campaign, "run_bounded", side_effect=subprocess.TimeoutExpired("cargo", 140)) as runner:
            campaign.run(self.root, self.receipt)
        self.assertEqual(runner.call_count, 3)
        self.assertFalse(campaign.finalize(self.root, self.receipt))
        result = json.loads(self.receipt.read_text())
        self.assertTrue(all(row["status"] == "failed" for row in result["targets"].values()))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process-group lifecycle")
    def test_timeout_kills_actual_descendant(self):
        pid_file = self.root / "child.pid"
        child = "import time; time.sleep(30)"
        parent = (
            "import subprocess,sys,time,pathlib; "
            f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
            f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(30)"
        )
        with (self.root / "process.log").open("w") as output:
            with self.assertRaises(subprocess.TimeoutExpired):
                campaign.run_bounded([sys.executable, "-c", parent], cwd=self.root, stdout=output, timeout=1.0)
        self.assertTrue(pid_file.is_file())
        pid = int(pid_file.read_text())
        def running():
            try:
                stat = Path(f"/proc/{pid}/stat").read_text().split()
                return len(stat) > 2 and stat[2] not in ("Z", "X")
            except (FileNotFoundError, ProcessLookupError, OSError):
                return False
        deadline = time.monotonic() + 2
        while running() and time.monotonic() < deadline:
            time.sleep(0.01)
        if running():
            os.kill(pid, signal.SIGKILL)
            self.fail("fuzz descendant survived process-group timeout")


if __name__ == "__main__":
    unittest.main()
