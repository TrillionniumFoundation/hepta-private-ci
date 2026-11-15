"""Original worker/GRU checkpoint integration with real Linux process identities."""

import argparse
from dataclasses import asdict, replace
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

from async_recurrent_lifecycle import AsyncRecurrentLifecycle
from durable_lifecycle import canonical
from skill_lifecycle import SkillContract, goals_digest
from sqlite_destination import BudgetExhausted


HERE = Path(__file__).resolve().parent
MODEL = (
    HERE.parent.parent / "qualification/act2-learning-20261110/run2/B4_gru-seed-700.npz"
)
CHILD = r"""
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from async_recurrent_lifecycle import AsyncRecurrentLifecycle
from durable_lifecycle import canonical
from skill_lifecycle import SkillContract
root=Path(sys.argv[2]); inputs=json.loads((root/'inputs.json').read_text())
d=AsyncRecurrentLifecycle.start(inputs['task'],SkillContract(**inputs['contract']),root/'model.npz',root/'session')
while d.async_attempt is None: d.step()
ready=d.wait(time.monotonic_ns()+8_000_000_000)
assert ready['notice_phase']=='WAITING',ready
(root/'original-worker-spec.json').write_bytes(canonical(d._spec))
(root/'original-checkpoint.json').write_bytes(d.db.execute('SELECT body FROM state').fetchone()[0])
print(json.dumps({'worker_pid':d._process.pid,'controller_pid':os.getpid(),'ready':ready,'policy':d.policy,'owner':d.policy['owner']}),flush=True)
if sys.stdin.readline()=='release\n':
    d.release()
    with (root/'release-returned.json').open('wb') as f:
        f.write(canonical({'release_attempted':d.async_attempt['release_attempted'],'time_ns':time.monotonic_ns()}));f.flush();os.fsync(f.fileno())
    print(json.dumps({'release_returned':True}),flush=True)
sys.stdin.readline()
d.close()
"""


class AsyncRecurrentTests(unittest.TestCase):
    evidence = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        if self.evidence:
            self.addCleanup(
                lambda: shutil.copytree(self.root, self.evidence / self._testMethodName)
            )
        shutil.copyfile(MODEL, self.root / "model.npz")
        self.task = {
            "id": "original",
            "version": 2,
            "goals": ["payload"],
            "fault": "normal",
        }
        self.contract = SkillContract(
            "original",
            2,
            goals_digest(self.task["goals"]),
            time.monotonic_ns() + 60_000_000_000,
            1,
        )

    def start(self):
        d = AsyncRecurrentLifecycle.start(
            self.task, self.contract, self.root / "model.npz", self.root / "session"
        )
        while d.async_attempt is None:
            d.step()
        return d

    def restore(self):
        return AsyncRecurrentLifecycle.restore(
            self.task, self.contract, self.root / "model.npz", self.root / "session"
        )

    def record(self, event, **values):
        with (self.root / "events.jsonl").open("ab") as stream:
            stream.write(
                canonical({"event": event, "time_ns": time.monotonic_ns(), **values})
                + b"\n"
            )

    def read_controller(self, process):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(
                selector.select(timeout=10), "original controller response absent"
            )
        line = process.stdout.readline()
        with (self.root / "controller.stdout").open("a") as stream:
            stream.write(line)
        self.assertTrue(line, "original controller exited before response")
        return json.loads(line)

    def controller(self):
        (self.root / "inputs.json").write_bytes(
            canonical({"task": self.task, "contract": asdict(self.contract)})
        )
        process = subprocess.Popen(
            [sys.executable, "-c", CHILD, str(HERE), str(self.root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ready = self.read_controller(process)
        self.record("original_worker_ready", **ready)
        return process, ready, os.pidfd_open(ready["worker_pid"])

    def stop_original(self, pidfd, pid):
        signal.pidfd_send_signal(pidfd, signal.SIGSTOP)
        deadline = time.monotonic() + 3
        while "\nState:\tT" not in Path(f"/proc/{pid}/status").read_text():
            self.assertLess(time.monotonic(), deadline)
            threading.Event().wait(0.001)
        self.record("original_worker_stopped", worker_pid=pid)

    def wait_original_exit(self, pidfd):
        with selectors.DefaultSelector() as selector:
            selector.register(pidfd, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=8), "original worker did not exit")
        self.record("original_worker_exit_observed")

    def finish_controller(self, process, pidfd):
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGCONT)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.kill()
        if process.stdin is not None:
            process.stdin.close()
            process.stdin = None
        out, err = process.communicate(timeout=10)
        with (self.root / "controller.stdout").open("a") as stream:
            stream.write(out)
        (self.root / "controller.stderr").write_text(err)
        (self.root / "controller-exit.json").write_bytes(
            canonical({"returncode": process.returncode})
        )
        os.close(pidfd)

    def test_original_worker_publishes_after_controller_sigkill_with_hidden_recovery(
        self,
    ):
        process, ready, pidfd = self.controller()
        d = None
        try:
            self.stop_original(pidfd, ready["worker_pid"])
            process.stdin.write("release\n")
            process.stdin.flush()
            self.assertTrue(self.read_controller(process)["release_returned"])
            controller_fd = os.pidfd_open(process.pid)
            try:
                signal.pidfd_send_signal(controller_fd, signal.SIGKILL)
            finally:
                os.close(controller_fd)
            self.assertEqual(process.wait(timeout=5), -signal.SIGKILL)
            self.record("controller_sigkill_observed", controller_pid=process.pid)
            with patch(
                "async_recurrent_lifecycle.multiprocessing.get_context",
                side_effect=AssertionError("redispatch"),
            ):
                d = self.restore()
                self.assertEqual(d.policy["owner"], ready["owner"])
                with patch.object(
                    d.model, "choose", side_effect=AssertionError("re-inference")
                ):
                    before = d.wait(time.monotonic_ns())
                    self.assertEqual(
                        (
                            before["knowledge"],
                            before["recovery_query_only"],
                            before["original_pipe_available"],
                        ),
                        ("UNKNOWN", True, False),
                    )
                    with self.assertRaises(ValueError):
                        d.release()
                    with self.assertRaisesRegex(ValueError, "cannot be paused"):
                        d.pause()
                    self.assertEqual(
                        list((self.root / "session/destination/effects").iterdir()), []
                    )
                    signal.pidfd_send_signal(pidfd, signal.SIGCONT)
                    self.record(
                        "original_worker_continued", worker_pid=ready["worker_pid"]
                    )
                    self.wait_original_exit(pidfd)
                    after = d.wait(time.monotonic_ns())
                    self.assertEqual(
                        (
                            after["knowledge"],
                            after["invocation"],
                            after["recovery_query_only"],
                        ),
                        ("CONFIRMED_COMPLETE", "original:0", True),
                    )
                    self.assertEqual(
                        (after["hidden"], after["sequence"]),
                        (ready["policy"]["hidden"], ready["policy"]["sequence"]),
                    )
                    result = d.report()
                    self.assertEqual(
                        (
                            result["effect_count"],
                            result["duplicate_effects"],
                            result["complete"],
                        ),
                        (1, 0, True),
                    )
                    value = next(
                        (self.root / "session/destination/effects").glob("*/value")
                    )
                    self.assertEqual(
                        json.loads(value.read_text()), {"content": "payload"}
                    )
                    self.assertEqual(
                        list(self.root.glob("session/**/control.db")),
                        [self.root / "session/control.db"],
                    )
                    self.record(
                        "restored_original_readback",
                        before=before,
                        after=after,
                        result=result,
                    )
        finally:
            if d is not None:
                d.close()
            self.finish_controller(process, pidfd)

    def test_controller_sigkill_before_release_never_recreates_original_io(self):
        process, ready, pidfd = self.controller()
        try:
            process.kill()
            self.assertEqual(process.wait(timeout=5), -signal.SIGKILL)
            self.wait_original_exit(pidfd)
            d = self.restore()
            try:
                with (
                    patch.object(
                        d.model, "choose", side_effect=AssertionError("re-inference")
                    ),
                    patch(
                        "async_recurrent_lifecycle.multiprocessing.get_context",
                        side_effect=AssertionError("redispatch"),
                    ),
                ):
                    row = d.wait(time.monotonic_ns())
                    self.assertEqual(
                        (
                            row["knowledge"],
                            row["release_attempted"],
                            row["recovery_query_only"],
                        ),
                        ("UNKNOWN", False, True),
                    )
                    self.assertEqual(
                        (row["hidden"], row["sequence"]),
                        (ready["policy"]["hidden"], ready["policy"]["sequence"]),
                    )
                    with self.assertRaises(ValueError):
                        d.release()
                    self.record("before_release_recovery", result=row)
                self.assertEqual(d.owner.audit()["effect_count"], 0)
            finally:
                d.close()
        finally:
            self.finish_controller(process, pidfd)

    def test_live_pipe_and_pre_release_pause_preserve_original_effect_owner(self):
        d = self.start()
        try:
            owner = dict(d.policy["owner"])
            ready = d.wait(time.monotonic_ns() + 5_000_000_000)
            self.assertEqual(
                (ready["notice_phase"], ready["original_pipe_available"]),
                ("WAITING", True),
            )
            d.pause()
            with self.assertRaises(ValueError):
                d.release()
            self.assertEqual(d.owner.audit()["effect_count"], 0)
            d.resume()
            d.release()
            with self.assertRaises(ValueError):
                d.release()
            with self.assertRaisesRegex(ValueError, "cannot be paused"):
                d.pause()
            row = d.wait(time.monotonic_ns() + 5_000_000_000)
            self.assertEqual(
                (row["knowledge"], row["recovery_query_only"]),
                ("CONFIRMED_COMPLETE", False),
            )
            self.assertEqual(d.policy["owner"], owner)
            self.assertEqual(d.owner.audit()["effect_count"], 1)
            self.record("live_original_pipe", ready=ready, completed=row)
        finally:
            d.close()

    def test_original_worker_checks_expired_deadline_after_actual_release(self):
        self.contract = replace(
            self.contract, deadline_ns=time.monotonic_ns() + 1_500_000_000
        )
        d = self.start()
        pidfd = os.pidfd_open(d._process.pid)
        try:
            d.wait(time.monotonic_ns() + 1_000_000_000)
            self.stop_original(pidfd, d._process.pid)
            d.release()
            time.sleep(
                max(0, self.contract.deadline_ns - time.monotonic_ns()) / 1e9 + 0.002
            )
            signal.pidfd_send_signal(pidfd, signal.SIGCONT)
            self.wait_original_exit(pidfd)
            row = d.wait(time.monotonic_ns())
            self.assertEqual(
                (row["knowledge"], d.owner.audit()["effect_count"]), ("UNKNOWN", 0)
            )
            self.assertEqual(d.contract.deadline_ns, self.contract.deadline_ns)
            self.record("expired_original_release", result=row)
        finally:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGCONT)
            except ProcessLookupError:
                pass
            os.close(pidfd)
            d.close()

    def test_wait_budget_survives_controller_reopen_without_inference(self):
        d = self.start()
        try:
            d.wait(time.monotonic_ns() + 5_000_000_000)
            while d.calls < d.budget:
                d.inspect()
            hidden, sequence = d.policy["hidden"], d.policy["sequence"]
        finally:
            d.close()
        d = self.restore()
        try:
            with patch.object(
                d.model, "choose", side_effect=AssertionError("re-inference")
            ):
                with self.assertRaises(BudgetExhausted):
                    d.wait(time.monotonic_ns())
            self.assertEqual(
                (d.calls, d.policy["hidden"], d.policy["sequence"]),
                (d.budget, hidden, sequence),
            )
            self.assertEqual(d.owner.audit()["effect_count"], 0)
        finally:
            d.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    args, remaining = parser.parse_known_args()
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=False)
        AsyncRecurrentTests.evidence = args.evidence
        (args.evidence / "child-source.py").write_text(CHILD)
        sources = args.evidence / "source-postimages"
        sources.mkdir()
        for name in (
            "async_recurrent_lifecycle.py",
            "test_async_recurrent_lifecycle.py",
            "recurrent_lifecycle.py",
            "durable_lifecycle.py",
            "file_family.py",
            "skill_lifecycle.py",
            "models.py",
            "run.py",
            "diagnose.py",
            "sqlite_destination.py",
        ):
            shutil.copyfile(HERE / name, sources / name)
    unittest.main(argv=[__file__, *remaining])
