"""Real subprocess boundary tests with synthetic bytes, not model efficacy."""
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from laya_wait import observation_supported, observe_owned_exit
from unittest.mock import patch

from hepta_retrieval_wire import MAX_FRAME, decode_reply, encode_request
from laya_binary import OwnerDeadline
from laya_process import (MAX_DIAGNOSTIC_BYTES, ProcessFailure, _exchange,
                          offline_environment, run_pinned)
from laya_retrieval import Rejected
from test_hepta_retrieval_wire import reply_for, request


@unittest.skipUnless(observation_supported(),
                     "non-reaping child observation is unsupported")
class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.marker = Path(self.directory.name) / "entered"
        value = request()
        value["deadline_ms"] = time.time_ns() // 1_000_000 + 10_000
        self.wire = encode_request(value)
        self.reply = reply_for(self.wire)
        self.deadline = OwnerDeadline.start(value["deadline_ms"], maximum_seconds=3)

    def command(self, code):
        return [sys.executable, "-u", "-c", "import os,sys,time\n" + code]

    def execute(self, code, deadline=None, cancel=None):
        return _exchange(self.command(code), self.wire, deadline or self.deadline, cancel)

    def failed(self, code, deadline=None, cancel=None):
        with self.assertRaises(ProcessFailure) as caught:
            self.execute(code, deadline, cancel)
        observation = caught.exception.observation
        self.assertTrue(observation["spawned"])
        self.assertTrue(observation["direct_child_exit_observed"])
        self.assertFalse(observation["eligible_reply"])
        self.assertFalse(observation["retry_allowed"])
        self.assertIsNone(observation["reply_sha256"])
        self.assertIsNone(caught.exception.child)
        return observation

    def test_full_reply_requires_bound_bytes_input_delivery_and_observed_exit(self):
        result = self.execute(f"data=sys.stdin.buffer.read()\nassert data=={self.wire!r}\n"
                              f"sys.stdout.buffer.write({self.reply!r})")
        self.assertEqual(result.wire, self.reply)
        self.assertEqual(decode_reply(result.wire, self.wire), decode_reply(self.reply, self.wire))
        self.assertEqual(result.observation["input_bytes_written"], len(self.wire))
        self.assertEqual(result.observation["returncode"], 0)
        self.assertEqual(result.observation["request_sha256"], hashlib.sha256(self.wire).hexdigest())
        self.assertTrue(result.observation["direct_child_exit_observed"])
        self.assertFalse(result.observation["descendant_exit_verified"])
        self.assertIsNone(result.observation["observed_memory_bytes"])
        self.assertIsNone(result.observation["task_success"])

    def test_partial_invalid_and_wrong_request_replies_never_become_success(self):
        other = request(); other["deadline_ms"] += 1
        for wire in (self.reply[:-1], b"log line, not binary", reply_for(encode_request(other))):
            with self.subTest(wire=wire[:8]):
                self.failed(f"sys.stdin.buffer.read()\nsys.stdout.buffer.write({wire!r})")

    def test_valid_bytes_with_nonzero_exit_are_not_success(self):
        result = self.failed(f"sys.stdin.buffer.read()\nsys.stdout.buffer.write({self.reply!r})\nsys.exit(4)")
        self.assertEqual(result["returncode"], 4)

    def test_stdout_overflow_is_bounded_and_terminated(self):
        result = self.failed(f"sys.stdin.buffer.read()\nsys.stdout.buffer.write(b'x'*{MAX_FRAME + 10000})\ntime.sleep(5)")
        self.assertLessEqual(result["stdout_bytes"], MAX_FRAME + 1)

    def test_stderr_overflow_does_not_retain_source_text(self):
        result = self.failed(f"sys.stdin.buffer.read()\nsys.stderr.buffer.write(b'secret'*{MAX_DIAGNOSTIC_BYTES})\ntime.sleep(5)")
        self.assertLessEqual(result["stderr_bytes"], MAX_DIAGNOSTIC_BYTES + 1)
        self.assertNotIn("secret", str(result))

    def test_stdout_and_stderr_are_drained_without_pipe_deadlock(self):
        result = self.execute(f"sys.stdin.buffer.read()\nsys.stderr.buffer.write(b'd'*4000)\n"
                              f"sys.stdout.buffer.write({self.reply!r})")
        self.assertEqual(result.observation["stderr_bytes"], 4000)
        self.assertEqual(result.wire, self.reply)

    def test_output_ack_without_process_exit_is_not_terminal_and_never_retries(self):
        deadline = OwnerDeadline.start(decode_request_deadline(self.wire), maximum_seconds=0.8)
        result = self.failed(f"sys.stdin.buffer.read()\nopen({str(self.marker)!r},'a').write('entry\\n')\n"
                             f"sys.stdout.buffer.write({self.reply!r})\ntime.sleep(5)", deadline)
        self.assertEqual(self.marker.read_text(), "entry\n")
        self.assertEqual(result["returncode"], -signal.SIGKILL)
        self.assertLess(result["transport_seconds"], 2)

    def test_child_closing_pipes_while_running_still_consumes_original_deadline(self):
        deadline = OwnerDeadline.start(decode_request_deadline(self.wire), maximum_seconds=0.8)
        result = self.failed("os.close(0)\nos.close(1)\nos.close(2)\ntime.sleep(5)", deadline)
        self.assertLess(result["transport_seconds"], 2)

    def test_cancel_before_spawn_never_creates_process(self):
        event = threading.Event(); event.set()
        with self.assertRaises(Rejected), patch("laya_process.subprocess.Popen") as spawn:
            self.execute("raise AssertionError", cancel=event)
        spawn.assert_not_called()

    def test_cancel_after_spawn_keeps_unknown_result_not_zero_cost(self):
        event = threading.Event()
        timer = threading.Timer(0.15, event.set)
        timer.start()
        try:
            result = self.failed("sys.stdin.buffer.read()\ntime.sleep(5)", cancel=event)
        finally:
            timer.join()
        self.assertIsNone(result["observed_memory_bytes"])
        self.assertIsNone(result["task_success"])
        self.assertEqual(result["returncode"], -signal.SIGKILL)

    def test_expiry_and_invalid_input_reject_before_spawn(self):
        value = request(); value["deadline_ms"] = 1
        with patch("laya_process.subprocess.Popen") as spawn:
            for raw in (b"invalid", encode_request(value)):
                with self.subTest(raw=raw[:8]), self.assertRaises(ValueError):
                    _exchange(self.command("raise AssertionError"), raw, self.deadline)
        spawn.assert_not_called()

    def test_external_reaper_is_rejected_before_process_creation(self):
        with patch("laya_process.signal.getsignal", return_value=signal.SIG_IGN):
            with self.assertRaises(Rejected), patch("laya_process.subprocess.Popen") as spawn:
                self.execute("raise AssertionError")
        spawn.assert_not_called()

    def test_group_signal_happens_before_leader_reap(self):
        original_wait, original_kill = subprocess.Popen.wait, os.killpg
        events = []
        def kill(group, sig):
            events.append("signal")
            return original_kill(group, sig)
        def wait(child, **kwargs):
            events.append("reap")
            return original_wait(child, **kwargs)
        with patch("laya_process.os.killpg", side_effect=kill), patch.object(subprocess.Popen, "wait", wait):
            self.execute(f"sys.stdin.buffer.read()\nsys.stdout.buffer.write({self.reply!r})")
        self.assertEqual(events, ["signal", "reap"])

    def test_inherited_pipe_cannot_keep_parent_exchange_alive_after_leader_exit(self):
        # A real same-group descendant keeps stdout open; the leader exits first.
        # The bounded owner signals while the leader PID is still reserved.
        deadline = OwnerDeadline.start(decode_request_deadline(self.wire), maximum_seconds=0.8)
        code = ("import subprocess\nsys.stdin.buffer.read()\n"
                "subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'])\n"
                f"sys.stdout.buffer.write({self.reply!r})")
        result = self.failed(code, deadline)
        self.assertLess(result["transport_seconds"], 2)
        self.assertTrue(result["group_kill_sent"])
        self.assertFalse(result["descendant_exit_verified"])

    def test_environment_does_not_forward_credentials_or_import_overrides(self):
        with patch.dict(os.environ, {"HF_TOKEN": "private", "PYTHONPATH": "evil", "LD_PRELOAD": "evil"}):
            environment = offline_environment()
        self.assertFalse({"HF_TOKEN", "PYTHONPATH", "LD_PRELOAD"} & set(environment))
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")

    def test_real_leaf_rejection_is_observed_not_missing_model_success(self):
        # This starts the actual shipped binary leaf, which rejects missing pins.
        with self.assertRaises(ProcessFailure) as caught:
            run_pinned(Path(self.directory.name).resolve() / "checkpoint", Path(self.directory.name).resolve() / "pins",
                       self.wire, self.deadline)
        self.assertTrue(caught.exception.observation["direct_child_exit_observed"])
        self.assertNotEqual(caught.exception.observation["returncode"], 0)
        self.assertIsNone(caught.exception.observation["reply_sha256"])


def decode_request_deadline(wire):
    from hepta_retrieval_wire import decode_request
    return decode_request(wire)["deadline_ms"]


if __name__ == "__main__":
    unittest.main()
