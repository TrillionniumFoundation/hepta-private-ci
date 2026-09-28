"""Real OS subprocess fault tests; fixtures are not model qualification."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock
import subprocess
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python"))
from decision_cell_process import FrozenEncoderProcess, WorkerTransportError, WorkerDeadline, WorkerCancelled
from decision_cell_process import build_request, canonical, MAX_FRAME


HELPER = r'''
import hashlib,json,sys,time,os
ready=json.loads(sys.argv[1]);mode=sys.argv[2]
with open(os.path.join(os.environ["HEPTA_DECISIONCELL_PRIVATE_ROOT"], "private-model-copy"), "wb") as snapshot:
    snapshot.write(b"fixture-private-copy")
def emit(x):
    print(json.dumps(x,separators=(",",":")),flush=True)
if mode=="startup_hang":
    time.sleep(10)
if mode=="wrong_ready":
    ready["session_id"]="other"
if mode=="numeric_ready":
    ready["advisory_only"]=1;ready["external_effect"]=0
emit(ready)
if mode=="blocked_write":
    time.sleep(10)
for raw in sys.stdin.buffer:
    if mode=="hang":
        time.sleep(10)
    if mode=="exit":
        sys.exit(0)
    if mode=="oversized":
        sys.stdout.write("x"*(96*1024+1));sys.stdout.flush();time.sleep(10)
    c=json.loads(raw);r=c["request"]
    h=hashlib.sha256((json.dumps(r,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)+"\n").encode()).hexdigest()
    x={"schema":"hepta.frozen-encoder-reply.v1","session_id":ready["session_id"],
       "request_id":r["request_id"],"request_sha256":h,"projection_sha256":r["projection_sha256"],
       "invocation_sha256":c["invocation_sha256"],"advisory_only":True,"external_effect":False,
       "status":"unknown" if c["kind"]=="lookup" else "indeterminate","observation":None}
    if mode=="authority":
        x["external_effect"]=True
    if mode=="wrong_request":
        x["request_sha256"]="e"*64
    if mode=="unknown_field":
        x["secret"]=True
    emit(x)
'''


class FrozenProcessTests(unittest.TestCase):
    def setUp(self):
        self.ready = {"schema": "hepta.frozen-encoder-ready.v1", "session_id": "session.test",
            "head_manifest_sha256": "1" * 64, "base_snapshot_digest": "2" * 64,
            "runtime_profile_sha256": "3" * 64, "device": "cpu", "advisory_only": True, "external_effect": False}
        self.children = []

    def tearDown(self):
        for process in self.children:
            process.close()

    def launch(self, mode="normal", seconds=3):
        child = FrozenEncoderProcess([sys.executable, "-u", "-c", HELPER, json.dumps(self.ready), mode],
            self.ready, environment={"PATH": os.defpath}, startup_seconds=seconds)
        self.children.append(child)
        return child

    def request(self):
        return build_request("request.1", "select file", ["a", "b", "c", "d"],
                             deadline_ns=time.monotonic_ns() + 10**10)

    def assert_reaped(self, child):
        self.assertFalse(child.private_snapshot_root.exists(), "private model copy survived cleanup")
        self.assertIsNotNone(child._process.poll())
        with self.assertRaises(ProcessLookupError):
            os.kill(child.pid, 0)

    def test_one_resident_process_multiple_bound_queries(self):
        child = self.launch()
        for _ in range(3):
            reply = child.exchange(self.request(), "a" * 64, kind="lookup")
            self.assertEqual(reply["status"], "unknown")
        self.assertIsNone(child._process.poll())
        child.close()
        self.assert_reaped(child)

    def test_timeout_kills_and_prevents_late_reuse(self):
        child = self.launch("hang")
        before = time.monotonic()
        with self.assertRaises(WorkerDeadline):
            child.exchange(self.request(), "a" * 64, timeout_seconds=0.15)
        self.assertLess(time.monotonic() - before, 2)
        self.assert_reaped(child)
        with self.assertRaises(WorkerTransportError):
            child.exchange(self.request(), "a" * 64)

    def test_cancellation_kills_actual_child(self):
        child = self.launch("hang")
        event = threading.Event()
        timer = threading.Timer(0.15, event.set)
        timer.start()
        try:
            with self.assertRaises(WorkerCancelled):
                child.exchange(self.request(), "a" * 64, cancel=event)
        finally:
            timer.join()
        self.assert_reaped(child)

    def test_bounded_write_when_worker_never_reads(self):
        child = self.launch("blocked_write")
        value = build_request("request.1", "x" * 16000, ["y" * 4000] * 4,
                              deadline_ns=time.monotonic_ns() + 10**10)
        with self.assertRaises(WorkerDeadline):
            child.exchange(value, "a" * 64, timeout_seconds=0.15)
        self.assert_reaped(child)

    def test_wrong_ready_rejects(self):
        with self.assertRaisesRegex(WorkerTransportError, "ready"):
            self.launch("wrong_ready")

    def test_startup_deadline(self):
        with self.assertRaises(WorkerDeadline):
            self.launch("startup_hang", 0.15)

    def test_exit_corrupt_or_cross_bound_responses_close_channel(self):
        for mode in ("exit", "oversized", "authority", "wrong_request", "unknown_field"):
            with self.subTest(mode=mode):
                child = self.launch(mode)
                with self.assertRaises(WorkerTransportError):
                    child.exchange(self.request(), "a" * 64)
                self.assert_reaped(child)

    def test_closed_instance_cannot_restart_itself(self):
        child = self.launch()
        child.close()
        with self.assertRaises(WorkerTransportError):
            child.exchange(self.request(), "a" * 64)
        self.assert_reaped(child)

    def test_pre_cancel_does_not_submit(self):
        child = self.launch()
        event = threading.Event();event.set()
        with self.assertRaises(WorkerCancelled):
            child.exchange(self.request(), "a" * 64, cancel=event)
        self.assertIsNone(child._process.poll())

    def test_unsupported_launch_and_oversized_input_reject(self):
        with self.assertRaises(ValueError):
            FrozenEncoderProcess(["python"], self.ready, environment={})
        child = self.launch()
        value = self.request(); value["text"] = "x" * MAX_FRAME
        with self.assertRaisesRegex(ValueError, "frame bound"):
            child.exchange(value, "a" * 64)
        self.assertIsNone(child._process.poll())

    def test_failed_spawn_cleans_owned_snapshot_parent(self):
        created = []
        original = tempfile.TemporaryDirectory
        def tracked(*args, **kwargs):
            value = original(*args, **kwargs)
            created.append(Path(value.name))
            return value
        with original(prefix="hepta-spawn-test-") as missing_root:
            executable = str(Path(missing_root) / "missing-executable")
            with mock.patch("decision_cell_process.tempfile.TemporaryDirectory", side_effect=tracked):
                with self.assertRaises(FileNotFoundError):
                    FrozenEncoderProcess([executable], self.ready, environment={})
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists())

    def test_uncertain_exit_retains_snapshot_and_can_finish_cleanup(self):
        child = self.launch("hang")
        with mock.patch.object(child._process, "wait", side_effect=subprocess.TimeoutExpired("fixture", 5)):
            with self.assertRaises(subprocess.TimeoutExpired):
                child.close()
        self.assertTrue(child.private_snapshot_root.exists())
        self.assertTrue(child._closed)
        self.assertFalse(child._reaped)
        with self.assertRaises(WorkerTransportError):
            child.exchange(self.request(), "a" * 64)
        child.close()
        self.assert_reaped(child)


    def test_numeric_ready_cannot_impersonate_boolean_authority(self):
        with self.assertRaisesRegex(WorkerTransportError, "ready"):
            self.launch("numeric_ready")

    def test_launch_binding_is_immutable_and_isolated_from_caller(self):
        child = self.launch()
        original = dict(child.expected)
        self.ready["session_id"] = "caller.changed"
        with self.assertRaises(TypeError):
            child.expected["session_id"] = "attacker.changed"
        with self.assertRaises(AttributeError):
            child.expected = dict(self.ready)
        self.assertEqual(dict(child.expected), original)
        self.assertEqual(child.exchange(self.request(), "a" * 64, kind="lookup")["status"], "unknown")

    def test_malformed_request_rejects_before_any_pipe_write(self):
        child = self.launch()
        for field, replacement in (("schema", "other"), ("request_id", "bad id"),
                ("projection_sha256", "b" * 64), ("candidates", ["one"]),
                ("deadline_monotonic_ns", True), ("unexpected", "field")):
            value = self.request(); value[field] = replacement
            with self.subTest(field=field), mock.patch.object(child, "_write") as send:
                with self.assertRaises(ValueError):
                    child.exchange(value, "a" * 64)
                send.assert_not_called()
            self.assertFalse(child._closed)
        self.assertEqual(child.exchange(self.request(), "a" * 64, kind="lookup")["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
