import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("campaign", Path(__file__).parents[1] / "platform_wire_fuzz_campaign.py")
campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(campaign)


class CampaignTests(unittest.TestCase):
    def test_duration_limits_and_non_shell_inputs(self):
        for value in ("", "0", "59", "1801", "999999", "60; echo bad", "$(id)", "-1"):
            with self.assertRaises(ValueError):
                campaign.seconds("workflow_dispatch", value)
        self.assertEqual(campaign.seconds("workflow_dispatch", "60"), 60)
        self.assertEqual(campaign.seconds("pull_request", "$(id)"), 180)
        self.assertEqual(campaign.seconds("schedule", ""), 900)

    def test_commands_are_allowlisted_and_bounded(self):
        with patch.dict(os.environ, FUZZ_TOOLCHAIN="nightly-test"):
            self.assertIn("-print_final_stats=1", campaign.command("managed_records", 20))
            for target, duration in (("evil", 20), ("decode_frames", 0), ("decode_frames", 601)):
                with self.assertRaises(ValueError):
                    campaign.command(target, duration)

    def test_success_text_is_not_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            log.write_text("success\nnot_run\nstat::number_of_executed_units: 0\n")
            self.assertEqual(campaign.executed_units(log), 0)
            log.write_text("stat::number_of_executed_units: 251\n")
            self.assertEqual(campaign.executed_units(log), 251)

    def test_init_failure_retains_not_run_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "evidence/campaign.json"
            with patch.dict(os.environ, GITHUB_EVENT_NAME="workflow_dispatch", REQUESTED_SECONDS=""):
                with self.assertRaises(ValueError):
                    campaign.initialize(root, receipt)
            result = json.loads(receipt.read_text())
            self.assertEqual(result["status"], "failed")
            self.assertTrue(all(row["status"] == "not_run" for row in result["targets"].values()))

    def test_missing_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "campaign.json"
            with patch.object(campaign, "subject", return_value={"source_sha": "a" * 40}):
                self.assertFalse(campaign.finalize(root, receipt))
            self.assertEqual(json.loads(receipt.read_text())["status"], "failed")

    def test_interrupted_execution_never_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "campaign.json"
            campaign.save(receipt, {"source_sha": "a" * 40, "targets": {
                target: {"status": "running"} for target in campaign.TARGETS
            }})
            with patch.object(campaign, "subject", return_value={"source_sha": "a" * 40}):
                self.assertFalse(campaign.finalize(root, receipt))
            self.assertTrue(all(row["status"] == "failed" for row in json.loads(receipt.read_text())["targets"].values()))

    def test_valid_logs_and_exact_source_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "campaign.json"
            rows = {}
            for target in campaign.TARGETS:
                log = root / (target + ".log")
                log.write_text("stat::number_of_executed_units: 5\n")
                rows[target] = {"status": "passed", "exit_code": 0, "executed_units": 5,
                                "log_sha256": campaign.digest(log)}
            original = {"source_sha": "a" * 40, "targets": rows}
            campaign.save(receipt, original)
            with patch.object(campaign, "subject", return_value={"source_sha": "a" * 40}):
                self.assertTrue(campaign.finalize(root, receipt))
            with patch.object(campaign, "subject", return_value={"source_sha": "b" * 40}):
                self.assertFalse(campaign.finalize(root, receipt))
            campaign.save(receipt, original)
            (root / "managed_records.log").write_text("changed\n")
            with patch.object(campaign, "subject", return_value={"source_sha": "a" * 40}):
                self.assertFalse(campaign.finalize(root, receipt))

    def test_bad_target_does_not_skip_remaining_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "campaign.json"
            campaign.save(receipt, {"source_sha": "a" * 40, "duration_seconds": 60, "targets": {}})
            calls = []
            def fake_run(argv, **kwargs):
                calls.append(argv[4])
                kwargs["stdout"].write("stat::number_of_executed_units: 7\n")
                return type("Result", (), {"returncode": 1 if len(calls) == 1 else 0})()
            with patch.dict(os.environ, FUZZ_TOOLCHAIN="nightly-test"), \
                 patch.object(campaign, "subject", return_value={"source_sha": "a" * 40}), \
                 patch.object(campaign.subprocess, "run", side_effect=fake_run):
                campaign.run(root, receipt)
            self.assertEqual(calls, list(campaign.TARGETS))
            rows = json.loads(receipt.read_text())["targets"]
            self.assertEqual(rows["decode_frames"]["status"], "failed")
            self.assertEqual(rows["policy_admission"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
