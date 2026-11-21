"""Synthetic runtime controls: no actual predictor, Git or native children."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fresh_contract as c
import run_fresh as runner
import test_fresh as fixtures


class RuntimeTests(unittest.TestCase):
    setUp = fixtures.FreshTests.setUp
    binding = fixtures.FreshTests.binding
    request = fixtures.FreshTests.request

    def test_failed_callback_cannot_be_reissued_under_another_output_path(self):
        class FailedPredictor:
            calls = 0

            def predict(self, request):
                self.calls += 1
                raise RuntimeError("synthetic interrupted callback; no model exists")

        predictor = FailedPredictor()
        slots, slot = c.Slots(self.selection, self.excluded), (c.MODES[0], "frozen", 0)
        for index in range(2):
            with self.assertRaises((RuntimeError, FileExistsError)):
                runner.run_task({"record_id": "synthetic"}, self.request(), {}, predictor, None,
                                slots, slot, self.root / str(index))
        self.assertEqual(predictor.calls, 1)
        self.assertTrue((self.root / "0/FAILED.json").is_file())
        self.assertEqual(len(list(slots.root.glob("generation--*.json"))), 1)

    def test_venv_external_interpreter_bytes_are_bound(self):
        target, canary = self.root / "synthetic-python", self.root / "canary"
        target.write_bytes(b"not an executable; synthetic inventory only")
        canary.write_bytes(b"synthetic canary")
        root = self.root / "venv"
        (root / "bin").mkdir(parents=True)
        (root / "bin/python").symlink_to(target)
        environment = {"schema": "hepta.readonly-native-environment.v1", "root": str(root),
            "inventory_scope": runner.ENVIRONMENT_SCOPE, "host_mount_closure_complete": False,
            "python_binary_sha256": c.sha(target), "files": [{"path": "bin/python", "symlink_target": str(target),
                "external_target": {"path": str(target), "bytes": target.stat().st_size, "sha256": c.sha(target)}}]}
        deployment = {"native_source": "mocked-not-executed", "ancestor": str(canary), "codec": str(canary),
            "host_canary": str(canary), "native_environment": self.binding("environment.json", environment)}
        with patch.object(runner, "module", return_value=SimpleNamespace()), patch.object(runner, "GATE_SHA", c.sha(canary)), patch.object(runner, "CODEC_SHA", c.sha(canary)):
            runner.native_adapter(deployment)
            target.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "external symlink target"):
                runner.native_adapter(deployment)

    def test_forced_supervisor_stop_blocks_later_arms_even_after_worker_exit(self):
        deployment = {key: self.binding(key + ".json", value) for key, value in
                      (("selection", self.selection), ("weights", self.weights), ("excluded", self.excluded),
                       ("selection_publication", self.publication))}
        binding = self.binding("deployment.json", deployment)
        worker = SimpleNamespace(pid=999999, poll=lambda: None, wait=lambda **kwargs: 0)
        with patch.object(runner.subprocess, "Popen", return_value=worker) as spawn, patch.object(runner.os, "killpg") as kill, patch.object(runner.time, "monotonic", side_effect=[0, 2401, 2401]):
            with self.assertRaisesRegex(ValueError, "bounded worker failed"):
                runner.supervise(binding, c.MODES[0], "frozen")
            self.assertEqual(spawn.call_count, 1)
            self.assertEqual(kill.call_count, 1)
        uncertain = json.loads((Path(self.selection["owner_root"]) / "EXECUTION_UNCERTAIN.json").read_bytes())
        self.assertTrue(uncertain["worker_exit_confirmed"])
        self.assertFalse(uncertain["owned_native_cleanup_confirmed"])
        with patch.object(runner.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "cleanup is unresolved"):
                runner.supervise(binding, c.MODES[0], "retrieval")
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
