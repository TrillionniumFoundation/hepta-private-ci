"""Real child/pipe/termination tests, with explicit synthetic model output."""
import hashlib
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from scripts import hepta_laya_process as process
from scripts import hepta_retrieval_wire as wire
from scripts.tests.test_hepta_retrieval_wire import request

ROOT = Path(__file__).resolve().parents[2]
ENV = {"PATH": os.defpath, "LANG": "C.UTF-8", "HF_HUB_OFFLINE": "1",
       "TRANSFORMERS_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
PRELUDE = f"""import hashlib,os,sys,time
sys.path.insert(0, {str(ROOT)!r})
from scripts.hepta_retrieval_wire import decode_request,encode_reply
frame=sys.stdin.buffer.read()
r=decode_request(frame)
reply=encode_reply(dict(request_sha256=hashlib.sha256(frame).hexdigest(),
 bundle_digest=r['bundle_digest'],prediction_ppm=[100000,900000],
 input_tokens=12,output_tokens=0,latency_us=7))
"""


@unittest.skipUnless(sys.platform == "linux", "Linux process profile")
class ProcessTests(unittest.TestCase):
    def frame(self, budget=2000):
        value = request()
        value["deadline_ms"] = time.time_ns() // 1_000_000 + budget
        return wire.encode_request(value)

    def run_leaf(self, script, *, frame=None, cancelled=lambda: False, env=ENV):
        return process.run_process(self.frame() if frame is None else frame,
                                   command=(sys.executable, "-I", "-c", script),
                                   cwd=ROOT, env=env, cancelled=cancelled)

    def test_real_reply_and_host_resource_observation(self):
        frame = self.frame()
        result = self.run_leaf(PRELUDE + "sys.stdout.buffer.write(reply)", frame=frame)
        self.assertEqual(wire.decode_reply(result.reply_wire, frame)["prediction_ppm"], [100000, 900000])
        self.assertEqual(result.request_sha256, hashlib.sha256(frame).hexdigest())
        self.assertGreater(result.peak_rss_bytes, 0)
        self.assertGreater(result.elapsed_us, 0)
        self.assertTrue(result.leader_reaped)
        self.assertTrue(result.process_group_signalled)
        self.assertEqual(result.stderr_bytes, 0)

    def test_stdin_eof_delivered_without_deadlock(self):
        self.run_leaf(PRELUDE + "assert len(frame)>100; sys.stdout.buffer.write(reply)")

    def test_stdout_flood_is_bounded_and_not_retried(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "calls"
            script = f"open({str(marker)!r},'a').write('call\\n'); " + "import os; os.write(1,b'x'*1000000)"
            with self.assertRaises(process.ProcessUnavailable) as caught:
                self.run_leaf(script)
            self.assertEqual(marker.read_text(), "call\n")
            self.assertTrue(caught.exception.spawned)
            self.assertIsNone(caught.exception.child)

    def test_stderr_flood_is_bounded_and_redacted(self):
        with self.assertRaises(process.ProcessUnavailable) as caught:
            self.run_leaf("import os; os.write(2,b'SECRET'*1000000)")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertIsNone(caught.exception.child)

    def test_stderr_is_hashed_not_returned(self):
        result = self.run_leaf(PRELUDE + "os.write(2,b'private diagnostic'); sys.stdout.buffer.write(reply)")
        self.assertEqual(result.stderr_bytes, 18)
        self.assertEqual(result.stderr_sha256, hashlib.sha256(b"private diagnostic").hexdigest())

    def test_nonzero_exit_cannot_publish_valid_reply(self):
        with self.assertRaises(process.ProcessUnavailable) as caught:
            self.run_leaf(PRELUDE + "sys.stdout.buffer.write(reply);sys.stdout.flush();sys.exit(7)")
        self.assertTrue(caught.exception.spawned)

    def test_truncated_and_rebound_replies_reject(self):
        for suffix in ("sys.stdout.buffer.write(reply[:-1])",
                       "sys.stdout.buffer.write(reply+b'x')",
                       "sys.stdout.buffer.write(reply[:8]+b'x'*32+reply[40:])"):
            with self.subTest(suffix=suffix), self.assertRaises(process.ProcessUnavailable):
                self.run_leaf(PRELUDE + suffix)

    def test_hanging_child_is_killed_and_reaped_at_deadline(self):
        before = time.monotonic()
        with self.assertRaises(process.ProcessUnavailable) as caught:
            self.run_leaf("import time;time.sleep(60)", frame=self.frame(100))
        self.assertLess(time.monotonic() - before, 3)
        self.assertTrue(caught.exception.spawned)
        self.assertIsNone(caught.exception.child)
        self.assertTrue(caught.exception.reconcile_cleanup())

    def test_stdout_eof_without_child_exit_is_not_success(self):
        script = PRELUDE + "sys.stdout.buffer.write(reply);sys.stdout.flush();os.close(1);os.close(2);time.sleep(60)"
        with self.assertRaises(process.ProcessUnavailable):
            self.run_leaf(script, frame=self.frame(150))

    def test_parent_exit_cleans_inherited_pipe_holder_without_waiting_full_deadline(self):
        script = PRELUDE + """pid=os.fork()
if pid==0:
 time.sleep(60)
 os._exit(0)
sys.stdout.buffer.write(reply)
sys.stdout.flush()
os._exit(0)
"""
        before = time.monotonic()
        result = self.run_leaf(script, frame=self.frame(4000))
        self.assertLess(time.monotonic() - before, 2)
        self.assertTrue(result.process_group_signalled)

    def test_cancel_before_spawn_never_calls_popen(self):
        with patch.object(process.subprocess, "Popen") as spawn:
            with self.assertRaises(process.ProcessUnavailable) as caught:
                self.run_leaf("raise Exception()", cancelled=lambda: True)
            spawn.assert_not_called()
        self.assertFalse(caught.exception.spawned)

    def test_cancel_after_spawn_has_unknown_execution_not_negative(self):
        cancellation = threading.Event()
        timer = threading.Timer(0.1, cancellation.set)
        timer.start()
        try:
            with self.assertRaises(process.ProcessUnavailable) as caught:
                self.run_leaf("import time;time.sleep(60)", cancelled=cancellation.is_set)
            self.assertTrue(caught.exception.spawned)
            self.assertIsNone(caught.exception.child)
        finally:
            timer.cancel()
            timer.join()

    def test_invalid_frame_never_spawns(self):
        with patch.object(process.subprocess, "Popen") as spawn:
            with self.assertRaises(wire.WireError):
                self.run_leaf("raise Exception()", frame=b"bad")
            spawn.assert_not_called()

    def test_environment_cannot_inherit_credentials_or_pythonpath(self):
        for name in ("GH_TOKEN", "PYTHONPATH", "LD_PRELOAD"):
            with self.subTest(name=name), patch.object(process.subprocess, "Popen") as spawn:
                with self.assertRaises(process.ProcessUnavailable):
                    self.run_leaf("pass", env=dict(ENV, **{name: "private"}))
                spawn.assert_not_called()

    def test_missing_offline_flag_never_spawns(self):
        env = dict(ENV)
        del env["HF_HUB_OFFLINE"]
        with patch.object(process.subprocess, "Popen") as spawn:
            with self.assertRaises(process.ProcessUnavailable):
                self.run_leaf("pass", env=env)
            spawn.assert_not_called()

    def test_custom_sigchld_reaper_is_rejected(self):
        with patch.object(process.signal, "getsignal", return_value=signal.SIG_IGN):
            with self.assertRaises(process.ProcessUnavailable) as caught:
                self.run_leaf("pass")
        self.assertFalse(caught.exception.spawned)

    def test_group_signal_precedes_reap(self):
        events = []
        real_signal, real_reap = process._signal_group, process._reap
        def signal_child(child):
            self.assertIsNone(child.returncode)
            events.append("signal")
            return real_signal(child)
        def reap_child(child):
            self.assertEqual(events, ["signal"])
            events.append("reap")
            return real_reap(child)
        with patch.object(process, "_signal_group", signal_child), patch.object(process, "_reap", reap_child):
            self.run_leaf(PRELUDE + "sys.stdout.buffer.write(reply)")
        self.assertEqual(events, ["signal", "reap"])

    def test_unobserved_cleanup_retains_child_until_reconciled(self):
        decisions = iter((False, True))
        with patch.object(process, "CLEANUP_SECONDS", 0), patch.object(process, "_exited", return_value=False):
            with self.assertRaises(process.ProcessUnavailable) as caught:
                self.run_leaf("import time;time.sleep(60)", cancelled=lambda: next(decisions))
            self.assertIsNotNone(caught.exception.child)
        deadline = time.monotonic() + 2
        while not caught.exception.reconcile_cleanup() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(caught.exception.child)
        self.assertTrue(caught.exception.reconcile_cleanup())

    def test_reaped_leader_does_not_hide_failed_group_signal(self):
        with patch.object(process, "_signal_group", side_effect=PermissionError("denied")):
            with self.assertRaises(process.ProcessUnavailable) as caught:
                self.run_leaf(PRELUDE + "sys.stdout.buffer.write(reply)")
        self.assertIsNone(caught.exception.child)
        self.assertTrue(caught.exception.cleanup_error)
        self.assertFalse(caught.exception.reconcile_cleanup())

    def test_clock_failure_after_spawn_reaps_without_publishing(self):
        calls = [0]
        def now():
            calls[0] += 1
            return (100 if calls[0] <= 2 else 99)
        value = request()
        with self.assertRaises(process.ProcessUnavailable) as caught:
            process.run_process(wire.encode_request(value),
                command=(sys.executable,"-I","-c","import time;time.sleep(60)"),
                cwd=ROOT, env=ENV, cancelled=lambda:False, now_ms=now)
        self.assertTrue(caught.exception.spawned)
        self.assertIsNone(caught.exception.child)


if __name__ == "__main__":
    unittest.main()
