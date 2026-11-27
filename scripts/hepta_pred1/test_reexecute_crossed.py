"""New-execution wrapper fixtures use unrelated tiny train/dev seeds only."""

from hashlib import sha256
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from . import reexecute_crossed as R
from .test_crossed_training_fit import config


@unittest.skipUnless(
    sys.platform.startswith("linux"), "Linux research execution wrapper"
)
class ReexecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        cfg = config()
        cfg.update(variants=["single_step"], train_episodes=8, dev_episodes=4, epochs=1)
        encoded = (json.dumps(cfg, sort_keys=True, indent=2) + "\n").encode()
        (self.root / "registered_config.json").write_bytes(encoded)
        self.plan = {
            "schema": "pred1-crossed-reexecution-registration-v1",
            "execution_id": "tiny-unrelated-fixture-v1",
            "new_execution_only": True,
            "original_artifacts_status": "ORIGINAL_ARTIFACTS_NOT_LOCATED",
            "config_file": "registered_config.json",
            "config_sha256": sha256(encoded).hexdigest(),
            "source_sha256": {n: sha256(v).hexdigest() for n, v in R._source().items()},
            "runner_sha256": sha256(Path(R.__file__).read_bytes()).hexdigest(),
            "timeout_seconds": 60,
            "design_registration_commit": "d" * 40,
            "execution_source_commit": "e" * 40,
        }
        self.registration = self.root / "REGISTRATION.json"
        self.write_registration(self.plan)

    def write_registration(self, plan):
        self.registration.write_bytes(
            (json.dumps(plan, sort_keys=True, indent=2) + "\n").encode()
        )

    def test_actual_eight_fit_run_retains_exact_identity_bytes_and_create_only_output(
        self,
    ):
        out = self.root / "new-run"
        receipt = R.run(self.registration, "f" * 40, out)
        self.assertEqual(
            (receipt["status"], receipt["exit_code"], receipt["checkpoint_count"]),
            ("EXITED", 0, 8),
        )
        self.assertEqual(receipt["execution_id"], "tiny-unrelated-fixture-v1")
        self.assertEqual(receipt["registration_commit"], "d" * 40)
        self.assertEqual(receipt["execution_source_commit"], "e" * 40)
        self.assertEqual(receipt["execution_registration_commit"], "f" * 40)
        self.assertFalse(receipt["original_execution_recovered"])
        self.assertFalse(receipt["fit_outcomes_parsed"])
        self.assertTrue(receipt["source_closure_unchanged"])
        self.assertEqual(
            receipt["result_sha256"], R._sha(out / "campaign" / "RESULT.json")
        )
        for entry in receipt["checkpoint_inventory"]:
            path = out / "campaign" / "fits" / entry["filename"]
            self.assertEqual(
                (entry["bytes"], entry["sha256"]), (path.stat().st_size, R._sha(path))
            )
        attempt = json.loads((out / "campaign" / "attempt.json").read_text())
        self.assertEqual(
            attempt["environment"]["thread_environment"], dict.fromkeys(R.THREADS, "1")
        )
        self.assertFalse(attempt["confirmation_data_read"])
        started = json.loads((out / "EXECUTION_STARTED.json").read_text())
        self.assertEqual(started["argv"], receipt["argv"])
        before = (out / "EXECUTION_RECEIPT.json").read_bytes()
        with self.assertRaises(FileExistsError):
            R.run(self.registration, "f" * 40, out)
        self.assertEqual((out / "EXECUTION_RECEIPT.json").read_bytes(), before)

    def test_mismatched_registration_refuses_before_output_or_child_launch(self):
        for key, value in (
            ("config_sha256", "0" * 64),
            ("runner_sha256", "0" * 64),
            ("source_sha256", {}),
            ("config_file", "../other.json"),
        ):
            out = self.root / key
            self.write_registration({**self.plan, key: value})
            with self.subTest(key=key), patch.object(R.subprocess, "Popen") as launch:
                with self.assertRaises(ValueError):
                    R.run(self.registration, "f" * 40, out)
                launch.assert_not_called()
                self.assertFalse(out.exists())
        self.write_registration(self.plan)
        with self.assertRaises(ValueError):
            R.run(self.registration, "abbreviated", self.root / "bad-sha")
        self.assertFalse((self.root / "bad-sha").exists())

    def test_launch_failure_is_retained_without_retry_or_fake_result(self):
        out = self.root / "failed"
        with patch.object(
            R.subprocess,
            "Popen",
            side_effect=FileNotFoundError("fixture launch failure"),
        ) as launch:
            receipt = R.run(self.registration, "f" * 40, out)
        launch.assert_called_once()
        self.assertEqual(receipt["status"], "LAUNCH_FAILED")
        self.assertEqual(receipt["exit_code"], 1)
        self.assertIsNone(receipt["child_exit_code"])
        self.assertFalse(receipt["result_present"])
        self.assertEqual(receipt["checkpoint_inventory"], [])
        self.assertTrue((out / "EXECUTION_STARTED.json").is_file())
        self.assertTrue((out / "EXECUTION_RECEIPT.json").is_file())
        self.assertEqual(set(receipt["logs"]), {"stdout.log", "stderr.log"})

    def test_timeout_terminates_only_the_child_owned_session_and_retains_receipt(self):
        child = MagicMock(pid=999999)
        child.wait.side_effect = [subprocess.TimeoutExpired("fixture", 60), -15]
        with (
            patch.object(R.subprocess, "Popen", return_value=child),
            patch.object(R.os, "killpg") as kill,
        ):
            receipt = R.run(self.registration, "f" * 40, self.root / "timeout")
        kill.assert_called_once_with(child.pid, signal.SIGTERM)
        self.assertEqual(
            (receipt["status"], receipt["exit_code"], receipt["child_exit_code"]),
            ("TIMED_OUT", 1, -15),
        )
        self.assertFalse(receipt["result_present"])

    def test_successful_child_cannot_make_changed_or_unreadable_source_replayable(self):
        original = R._source()
        changed = {**original, "__init__.py": original["__init__.py"] + b"\n"}
        for name, after in (
            ("changed", changed),
            ("unreadable", FileNotFoundError("fixture source absent")),
        ):
            out = self.root / name
            with (
                self.subTest(case=name),
                patch.object(R, "_source", side_effect=[original, after]),
            ):
                receipt = R.run(self.registration, "f" * 40, out)
            self.assertEqual(
                (receipt["child_exit_code"], receipt["status"], receipt["exit_code"]),
                (0, "SOURCE_CHANGED", 1),
            )
            self.assertFalse(receipt["source_closure_unchanged"])
            self.assertTrue(receipt["result_present"])
            self.assertEqual(receipt["checkpoint_count"], 8)
            self.assertEqual(set(receipt["logs"]), {"stdout.log", "stderr.log"})
            self.assertEqual(bool(receipt["source_read_errors"]), name == "unreadable")
            self.assertEqual(
                json.loads((out / "EXECUTION_RECEIPT.json").read_text())["exit_code"], 1
            )

    def test_escalated_timeout_exit_race_still_writes_terminal_receipt(self):
        child = MagicMock(pid=999999)
        child.wait.side_effect = [
            subprocess.TimeoutExpired("fixture", 60),
            subprocess.TimeoutExpired("fixture", 10),
            -9,
        ]
        with (
            patch.object(R.subprocess, "Popen", return_value=child),
            patch.object(
                R.os, "killpg", side_effect=[None, ProcessLookupError()]
            ) as kill,
        ):
            receipt = R.run(self.registration, "f" * 40, self.root / "kill-race")
        self.assertEqual(
            [call.args for call in kill.call_args_list],
            [(child.pid, signal.SIGTERM), (child.pid, signal.SIGKILL)],
        )
        self.assertEqual(
            (receipt["status"], receipt["exit_code"], receipt["child_exit_code"]),
            ("TIMED_OUT", 1, -9),
        )
        self.assertTrue((self.root / "kill-race" / "EXECUTION_RECEIPT.json").is_file())


if __name__ == "__main__":
    unittest.main()
