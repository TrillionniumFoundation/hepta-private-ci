"""Mocked process boundaries with actual journal IO, no children or signals."""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qualification.hcsn_training import joint_lifecycle as lifecycle  # noqa: E402
from qualification.hcsn_training import joint_protocol as wire  # noqa: E402
from qualification.hcsn_training import joint_runner as runner  # noqa: E402
from qualification.hcsn_training import joint_worker_adapter as adapter  # noqa: E402
from qualification.hcsn_training.joint_test_support import BOOT, JournalFixture, RUNNER, WORKER  # noqa: E402


class FinishedChild:
    pid = WORKER["process_id"]

    def __init__(self, code):
        self.returncode = code

    def poll(self):
        return self.returncode

    def wait(self, **_):
        return self.returncode


class RunnerAndAdapterBehavior(JournalFixture):
    def fake_run(self, child):
        stack = ExitStack()
        stack.enter_context(self.clocks())
        stack.enter_context(mock.patch.object(runner, "process_identity",
            side_effect=lambda pid, host: WORKER if pid == child.pid else RUNNER))
        # The production owns/closes this harmless FD. No pidfd or process is contacted.
        opened = os.open(os.devnull, os.O_RDONLY)
        stack.enter_context(mock.patch.object(runner.os, "pidfd_open", return_value=opened))
        stack.enter_context(mock.patch.object(runner.subprocess, "Popen", return_value=child))
        self.addCleanup(stack.close)
        return stack

    def test_nonzero_exit_is_not_rescued_by_complete_outputs(self):
        self.reserve()
        self.unsigned_output_fixture()
        with self.fake_run(FinishedChild(1)), mock.patch.object(runner, "validate_outputs") as output_check:
            runner.run_job(self.root, self.job.name, self.reservation["nonce"], self.sources)
        output_check.assert_not_called()
        terminal = wire.decode(self.job.read("terminal.json"))
        self.assertEqual((terminal["state"], terminal["returncode"], terminal["outputs"]), ("failed", 1, None))
        self.assertEqual(terminal["reason"], "worker_nonzero_exit")

    def test_zero_exit_with_missing_outputs_is_failed(self):
        self.reserve()
        with self.fake_run(FinishedChild(0)), self.assertRaises(FileNotFoundError):
            runner.run_job(self.root, self.job.name, self.reservation["nonce"], self.sources)
        terminal = wire.decode(self.job.read("terminal.json"))
        self.assertEqual((terminal["state"], terminal["returncode"], terminal["outputs"]), ("failed", 0, None))
        self.assertTrue(terminal["termination_confirmed"])

    def test_unique_claim_prevents_second_worker_launch(self):
        self.reserve()
        self.claim()
        raw = self.job.read("claim.json")
        with self.clocks(), mock.patch.object(runner, "process_identity", return_value=RUNNER), \
                mock.patch.object(runner.subprocess, "Popen") as spawn, self.assertRaises(FileExistsError):
            runner.run_job(self.root, self.job.name, self.reservation["nonce"], self.sources)
        spawn.assert_not_called()
        self.assertEqual(self.job.read("claim.json"), raw)

    def test_budget_spent_after_claim_refuses_worker_launch(self):
        self.reserve()
        with self.clocks(), mock.patch.object(runner, "process_identity", return_value=RUNNER), \
                mock.patch.object(runner, "remaining_ns", return_value=0), \
                mock.patch.object(runner.subprocess, "Popen") as spawn, self.assertRaises(ValueError):
            runner.run_job(self.root, self.job.name, self.reservation["nonce"], self.sources)
        spawn.assert_not_called()
        terminal = wire.decode(self.job.read("terminal.json"))
        self.assertEqual((terminal["state"], terminal["returncode"], terminal["process"]), ("failed", None, None))
        self.assertIsNotNone(terminal["claim_sha256"])

    def test_late_zero_result_cannot_commit_success(self):
        self.reserve()
        claim = self.claim()
        self.job.write("worker.json", WORKER)
        with self.clocks(), mock.patch.object(lifecycle, "clock_ns", return_value=claim["deadline_nanoseconds"] + 1), \
                self.assertRaises(ValueError):
            lifecycle.finish(self.root, self.job, self.reservation, "succeeded", WORKER, 0,
                             "worker_exit_zero_and_outputs_closed", claim, dict(synthetic=True), 0)
        self.assertFalse(self.job.exists("terminal.json"))

    def test_orphan_cancel_identity_failure_sends_no_signal(self):
        self.reserve()
        self.claim()
        self.job.write("worker.json", WORKER)
        cancel = self.cancellation()
        with self.clocks(), mock.patch.object(runner, "liveness", return_value="stopped"), \
                mock.patch.object(runner, "verified_pidfd", side_effect=ValueError("incarnation changed")), \
                mock.patch.object(runner, "stop_pidfd") as signal:
            answer = lifecycle.dispatch(self.root, cancel, self.sources)
        signal.assert_not_called()
        self.assertEqual(answer["state"], "unknown")
        self.assertTrue(self.job.exists("cancel.json"))
        self.assertFalse(self.job.exists("terminal.json"))

    def test_orphan_cancel_contact_is_not_repeated_after_unknown_result(self):
        self.reserve()
        self.claim()
        self.job.write("worker.json", WORKER)
        cancel = self.cancellation()

        def harmless_fd(*_):
            return os.open(os.devnull, os.O_RDONLY)

        with self.clocks(), mock.patch.object(runner, "liveness", return_value="stopped"), \
                mock.patch.object(runner, "verified_pidfd", side_effect=harmless_fd), \
                mock.patch.object(runner, "stop_pidfd", return_value=False) as signal:
            lifecycle.dispatch(self.root, cancel, self.sources)
            lifecycle.dispatch(self.root, cancel, self.sources)
        signal.assert_called_once()
        self.assertFalse(self.job.exists("terminal.json"))
        evidence = wire.decode(self.job.read("orphan-stop-" + lifecycle.job_key(cancel["dispatch"]) + ".result.json"))
        self.assertIs(evidence["termination_confirmed"], False)
        self.assertIsNone(evidence["actual_waitpid_returncode"])

    def test_same_pid_adapter_uses_only_original_three_arguments(self):
        self.reserve()
        claim = self.claim()
        called = []
        fake = b"def main():\n    return 0\n"
        snapshots = dict(self.sources.snapshots)
        relative = "scripts/joint_generation_v4_text_worker.py"
        snapshots[relative] = (fake, snapshots[relative][1])
        original_compile = compile

        def recorded_compile(raw, filename, mode):
            self.assertEqual((raw, filename, mode), (fake, str(self.sources.repo / relative), "exec"))
            return original_compile(b"def main():\n    captured.append((os.getpid(), list(sys.argv)))\n    return 0\n", filename, mode)

        original_module = adapter.types.ModuleType

        def context_module(name):
            module = original_module(name)
            module.__dict__.update(captured=called, os=os, sys=sys)
            return module

        actual_worker = dict(WORKER, process_id=os.getpid())
        original_argv = list(sys.argv)
        self.addCleanup(setattr, sys, "argv", original_argv)
        with self.clocks(), mock.patch.object(adapter, "arm_deadline") as arm, \
                mock.patch.object(adapter, "_lower_limit") as limits, \
                mock.patch.object(adapter, "process_identity", side_effect=[RUNNER, actual_worker]), \
                mock.patch.object(self.sources, "snapshots", snapshots), \
                mock.patch.object(self.sources, "check"), \
                mock.patch.object(adapter.types, "ModuleType", side_effect=context_module), \
                mock.patch("builtins.compile", side_effect=recorded_compile), \
                mock.patch.object(runner.subprocess, "Popen") as spawn:
            code = adapter.run_worker(self.root, self.job.name, self.reservation["nonce"],
                                      self.sources, claim["deadline_nanoseconds"], BOOT)
        self.assertEqual(code, 0)
        spawn.assert_not_called()
        arm.assert_called_once_with(claim["deadline_nanoseconds"], BOOT)
        self.assertEqual(limits.call_count, 3)
        self.assertEqual(len(called), 1)
        pid, argv = called[0]
        self.assertEqual(pid, os.getpid())
        self.assertEqual(argv[1::2], ["--request", "--predecessor", "--output"])
        self.assertEqual(len(argv), 7)
        self.assertEqual(wire.decode(self.job.read("worker.json")), actual_worker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
