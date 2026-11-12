"""Actual controller death with one original async owner and read-only recovery."""

import argparse
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from async_owner_wait import start_async_owner
from durable_async_owner import DurableAsyncOwner
from sqlite_destination import BudgetExhausted


HERE = Path(__file__).resolve().parent
CHILD = r"""
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from durable_async_owner import DurableAsyncOwner
root=Path(sys.argv[2]); mode=sys.argv[3]
args=json.loads((root/'inputs.json').read_text())
d=DurableAsyncOwner.start(**args,directory=root/'session')
ready=d.observe(time.monotonic_ns()+5_000_000_000)
assert ready['phase']=='WAITING'
print(json.dumps({'worker_pid':d.owner._process.pid,'ready':ready}),flush=True)
if mode=='before_release': os._exit(17)
assert sys.stdin.readline()=='release\n'
d.release()
with (root/'release-returned.json').open('w') as f:
    json.dump({'time_ns':time.monotonic_ns(),'release_returned':True},f);f.flush();os.fsync(f.fileno())
os._exit(18)
"""


class DurableAsyncTests(unittest.TestCase):
    evidence = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        if self.evidence:
            self.addCleanup(
                lambda: shutil.copytree(self.root, self.evidence / self._testMethodName)
            )
        self.args = {
            "task": {
                "id": "original",
                "version": 2,
                "goals": ["payload"],
                "fault": "normal",
            },
            "key": 0,
            "invocation": "original:0",
            "deadline_ns": time.monotonic_ns() + 30_000_000_000,
            "observation_budget": 8,
        }

    def record(self, event, **values):
        with (self.root / "events.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"event": event, "time_ns": time.monotonic_ns(), **values})
                + "\n"
            )

    def controller(self, mode):
        (self.root / "inputs.json").write_text(json.dumps(self.args))
        process = subprocess.Popen(
            [sys.executable, "-c", CHILD, str(HERE), str(self.root), mode],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(
                selector.select(timeout=8),
                "original controller did not report readiness",
            )
        ready = json.loads(process.stdout.readline())
        self.record("original_worker_ready", controller_pid=process.pid, **ready)
        return process, ready["worker_pid"]

    def restore(self):
        return DurableAsyncOwner.restore(**self.args, directory=self.root / "session")

    def test_controller_death_before_release_never_replays(self):
        controller, _ = self.controller("before_release")
        self.assertEqual(controller.wait(timeout=5), 17)
        self.record("controller_exit_observed", returncode=17)
        controller.communicate(timeout=5)
        d = self.restore()
        try:
            row = d.observe(time.monotonic_ns())
            self.assertEqual(
                (
                    row["knowledge"],
                    row["release_attempted"],
                    row["recovery_query_only"],
                ),
                ("UNKNOWN", False, True),
            )
            with self.assertRaises(ValueError):
                d.release()
            self.assertEqual(
                list((self.root / "session/destination/effects").iterdir()), []
            )
            self.record("restored_readback", result=row)
        finally:
            d.close()

    def test_original_caller_mutation_cannot_change_frozen_worker_goal(self):
        original = json.loads(json.dumps(self.args))
        (self.root / "inputs.json").write_text(json.dumps(original))

        def admit(path, **spec):
            self.args["task"]["goals"][0] = "changed-after-durable-admission"
            return start_async_owner(path, **spec)

        with patch("durable_async_owner.start_async_owner", admit):
            d = DurableAsyncOwner.start(**self.args, directory=self.root / "session")
        try:
            self.assertEqual(
                d.observe(time.monotonic_ns() + 5_000_000_000)["phase"], "WAITING"
            )
            d.release()
            row = d.observe(time.monotonic_ns() + 5_000_000_000)
            self.assertEqual(row["knowledge"], "CONFIRMED_COMPLETE")
            intent = json.loads(
                next(
                    (self.root / "session/destination/effects").glob("*/intent.json")
                ).read_text()
            )
            self.assertEqual(
                (intent["goal"], d.spec["task"]["goals"]), ("payload", ["payload"])
            )
            self.assertEqual(
                self.args["task"]["goals"], ["changed-after-durable-admission"]
            )
        finally:
            d.close()

    def test_released_original_completes_only_after_controller_death(self):
        controller, pid = self.controller("after_release")
        pidfd = os.pidfd_open(pid)
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGSTOP)
            stop_deadline = time.monotonic() + 3
            while "\nState:\tT" not in Path(f"/proc/{pid}/status").read_text():
                self.assertLess(time.monotonic(), stop_deadline)
                threading.Event().wait(0.001)
            self.record(
                "original_worker_stop_observed",
                worker_pid=pid,
                signal_identity="retained_original_pidfd",
            )
            controller.stdin.write("release\n")
            controller.stdin.flush()
            self.assertEqual(controller.wait(timeout=5), 18)
            self.record("controller_exit_observed", returncode=18)
            self.assertEqual(
                list((self.root / "session/destination/effects").iterdir()), []
            )
            d = self.restore()
            try:
                self.assertEqual(d.observe(time.monotonic_ns())["knowledge"], "UNKNOWN")
                with self.assertRaises(ValueError):
                    d.release()
                with self.assertRaisesRegex(ValueError, "cannot be paused"):
                    d.pause()
                signal.pidfd_send_signal(pidfd, signal.SIGCONT)
                self.record(
                    "original_worker_continued",
                    worker_pid=pid,
                    signal_identity="retained_original_pidfd",
                )
                with selectors.DefaultSelector() as selector:
                    selector.register(pidfd, selectors.EVENT_READ)
                    self.assertTrue(
                        selector.select(timeout=8), "original owner did not terminate"
                    )
                row = d.observe(time.monotonic_ns())
                self.assertEqual(
                    (row["knowledge"], row["invocation"], row["release_attempted"]),
                    ("CONFIRMED_COMPLETE", "original:0", True),
                )
                self.assertEqual(
                    json.loads(
                        next(
                            (self.root / "session/destination/effects").glob("*/value")
                        ).read_text()
                    ),
                    {"content": "payload"},
                )
                self.record("restored_readback", result=row)
                intent = next(
                    (self.root / "session/destination/effects").glob("*/intent.json")
                )
                original = intent.read_bytes()
                (self.root / "original-intent.json").write_bytes(original)
                foreign = json.loads(original)
                foreign["invocation"] = "foreign-operation"
                intent.write_text(json.dumps(foreign, sort_keys=True))
                (self.root / "rejected-intent.json").write_bytes(intent.read_bytes())
                with self.assertRaisesRegex(ValueError, "invocation binding changed"):
                    d.observe(time.monotonic_ns())
                self.record("foreign_intent_rejected")
                intent.write_bytes(original)
            finally:
                d.close()
        finally:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGCONT)
            except ProcessLookupError:
                pass
            os.close(pidfd)
            controller.stdin.close()
            controller.stdin = None
            controller.communicate(timeout=8)

    def test_writer_binding_and_observation_budget_survive_reopen(self):
        self.args["observation_budget"] = 1
        d = DurableAsyncOwner.start(**self.args, directory=self.root / "session")
        try:
            d.observe(time.monotonic_ns() + 5_000_000_000)
            with self.assertRaises(BlockingIOError):
                self.restore()
            d.pause()
        finally:
            d.close()
        d = self.restore()
        try:
            self.assertTrue(d.state["paused"])
            with self.assertRaises(BudgetExhausted):
                d.observe(time.monotonic_ns())
            with self.assertRaises(ValueError):
                d.release()
        finally:
            d.close()
        with self.assertRaises(ValueError):
            DurableAsyncOwner.restore(
                **{**self.args, "deadline_ns": self.args["deadline_ns"] + 1},
                directory=self.root / "session",
            )
        with self.assertRaises(ValueError):
            DurableAsyncOwner.restore(
                **{**self.args, "observation_budget": 2},
                directory=self.root / "session",
            )

    def test_pause_and_expiry_never_release_original(self):
        self.args["deadline_ns"] = time.monotonic_ns() + 1_000_000_000
        d = DurableAsyncOwner.start(**self.args, directory=self.root / "session")
        try:
            d.observe(time.monotonic_ns() + 3_000_000_000)
            d.pause()
            with self.assertRaises(ValueError):
                d.release()
            expired = d.observe(time.monotonic_ns() + 3_000_000_000)
            self.assertTrue(expired["mutation_deadline_reached"])
            d.resume()
            with self.assertRaises(ValueError):
                d.release()
        finally:
            d.close()
        d = self.restore()
        try:
            self.assertTrue(d.state["expired"])
            self.assertEqual(d.observe(time.monotonic_ns())["knowledge"], "UNKNOWN")
            self.assertFalse(d.state["release_attempted"])
        finally:
            d.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    args, remaining = parser.parse_known_args()
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=True)
        DurableAsyncTests.evidence = args.evidence
    unittest.main(argv=[__file__, *remaining])
