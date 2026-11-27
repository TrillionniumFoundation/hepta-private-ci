"""Actual archived GRU state across original controller death and late effect."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from gru_async_continuation import GRUAsyncContinuation


HERE = Path(__file__).resolve().parent
MODEL = (
    HERE.parents[1] / "qualification/act2-learning-20261110/run2/B4_gru-seed-700.npz"
)
CHILD = r"""
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from gru_async_continuation import GRUAsyncContinuation
root=Path(sys.argv[2]);mode=sys.argv[3]
args=json.loads((root/'inputs.json').read_text())
c=GRUAsyncContinuation.start(directory=root/'session',**args)
assert c.observe(time.monotonic_ns()+5_000_000_000)['phase']=='WAITING'
assert c.plan()=='ensure'
print(json.dumps({'controller_pid':os.getpid(),'worker_pid':c.owner.owner._process.pid,'checkpoint':c.state}),flush=True)
if mode=='before_release':os._exit(17)
assert sys.stdin.readline()=='release\n'
c.release();os._exit(18)
"""

RESTORE_CUT = r"""
import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from gru_async_continuation import GRUAsyncContinuation
root=Path(sys.argv[2]);args=json.loads((root/'inputs.json').read_text())
c=GRUAsyncContinuation.restore(directory=root/'session',**args)
c._save=lambda:os._exit(19)
c.finish()
raise AssertionError('post-inference checkpoint cut did not exit')
"""


class GRUAsyncTests(unittest.TestCase):
    evidence = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        if self.evidence:
            self.addCleanup(
                lambda: shutil.copytree(self.root, self.evidence / self._testMethodName)
            )
        sums = json.loads((MODEL.parent / "SHA256SUMS.json").read_text())
        self.assertEqual(
            hashlib.sha256(MODEL.read_bytes()).hexdigest(), sums[MODEL.name]
        )
        self.args = {
            "model_path": str(MODEL),
            "task": {
                "id": "original",
                "version": 2,
                "goals": ["payload"],
                "fault": "normal",
            },
            "key": 0,
            "invocation": "original:0",
            "deadline_ns": time.monotonic_ns() + 30_000_000_000,
            "observation_budget": 32,
        }

    def record(self, event, **values):
        with (self.root / "events.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"event": event, "time_ns": time.monotonic_ns(), **values})
                + "\n"
            )

    def controller(self, mode):
        (self.root / "inputs.json").write_text(json.dumps(self.args))
        p = subprocess.Popen(
            [sys.executable, "-c", CHILD, str(HERE), str(self.root), mode],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            self.assertTrue(
                selector.select(timeout=8),
                "original controller did not report committed inference",
            )
        row = json.loads(p.stdout.readline())
        self.record("committed_original_gru_checkpoint", **row)
        return p, row

    def restore(self, **changes):
        return GRUAsyncContinuation.restore(
            directory=self.root / "session", **{**self.args, **changes}
        )

    def reference(self):
        c = GRUAsyncContinuation.start(directory=self.root / "reference", **self.args)
        try:
            self.assertEqual(
                c.observe(time.monotonic_ns() + 5_000_000_000)["phase"], "WAITING"
            )
            self.assertEqual(c.plan(), "ensure")
            c.release()
            self.assertEqual(
                c.observe(time.monotonic_ns() + 5_000_000_000)["knowledge"],
                "CONFIRMED_COMPLETE",
            )
            result = c.finish()
            self.record("uninterrupted_reference", checkpoint=c.state, result=result)
            return json.loads(json.dumps(c.state))
        finally:
            c.close()

    def test_committed_gru_hidden_survives_controller_death_and_late_original_effect(
        self,
    ):
        reference = self.reference()
        controller, original = self.controller("after_release")
        pid = original["worker_pid"]
        pidfd = os.pidfd_open(pid)
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGSTOP)
            until = time.monotonic() + 3
            while "\nState:\tT" not in Path(f"/proc/{pid}/status").read_text():
                self.assertLess(time.monotonic(), until)
                threading.Event().wait(0.001)
            controller.stdin.write("release\n")
            controller.stdin.flush()
            self.assertEqual(controller.wait(timeout=5), 18)
            self.record(
                "original_controller_exit_observed", pid=controller.pid, returncode=18
            )
            self.assertEqual(
                list((self.root / "session/destination/effects").iterdir()), []
            )
            c = self.restore()
            try:
                self.assertNotEqual(os.getpid(), original["controller_pid"])
                self.assertEqual(c.state, original["checkpoint"])
                self.assertNotEqual(c.state["hidden"], "00" * 96)
                self.assertEqual(c.observe(time.monotonic_ns())["knowledge"], "UNKNOWN")
                with self.assertRaises(ValueError):
                    c.plan()
                with self.assertRaises(ValueError):
                    c.release()
                with self.assertRaisesRegex(ValueError, "UNKNOWN"):
                    c.finish()
                self.assertEqual(c.state, original["checkpoint"])
                signal.pidfd_send_signal(pidfd, signal.SIGCONT)
                self.record("original_worker_continued", worker_pid=pid)
                with selectors.DefaultSelector() as selector:
                    selector.register(pidfd, selectors.EVENT_READ)
                    self.assertTrue(
                        selector.select(timeout=8), "original worker did not terminate"
                    )
                result = c.finish()
                self.assertEqual(
                    (result["knowledge"], result["model_hidden_state_restored"]),
                    ("CONFIRMED_COMPLETE", True),
                )
                self.assertEqual(
                    {
                        k: c.state[k]
                        for k in (
                            "hidden",
                            "sequence",
                            "actions",
                            "features",
                            "phase",
                            "pending",
                        )
                    },
                    {
                        k: reference[k]
                        for k in (
                            "hidden",
                            "sequence",
                            "actions",
                            "features",
                            "phase",
                            "pending",
                        )
                    },
                )
                before = json.loads(json.dumps(c.state))
                c.finish()
                self.assertEqual(c.state, before)
                self.record(
                    "restored_gru_final",
                    checkpoint=c.state,
                    result=result,
                    restore_pid=os.getpid(),
                )
            finally:
                c.close()
        finally:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGCONT)
            except ProcessLookupError:
                pass
            os.close(pidfd)
            controller.stdin.close()
            controller.stdin = None
            controller.communicate(timeout=8)

    def test_death_before_release_preserves_pending_hidden_and_unknown(self):
        controller, original = self.controller("before_release")
        self.assertEqual(controller.wait(timeout=5), 17)
        controller.communicate(timeout=5)
        c = self.restore()
        try:
            for _ in range(2):
                self.assertEqual(c.observe(time.monotonic_ns())["knowledge"], "UNKNOWN")
                with self.assertRaisesRegex(ValueError, "UNKNOWN"):
                    c.finish()
                self.assertEqual(c.state, original["checkpoint"])
            with self.assertRaises(ValueError):
                c.release()
            self.assertEqual(
                list((self.root / "session/destination/effects").iterdir()), []
            )
            self.record("never_released_gru_unknown", checkpoint=c.state)
        finally:
            c.close()

    def test_different_real_archived_model_cannot_restore_original_hidden(self):
        controller, _ = self.controller("before_release")
        self.assertEqual(controller.wait(timeout=5), 17)
        controller.communicate(timeout=5)
        with self.assertRaisesRegex(ValueError, "binding"):
            self.restore(model_path=str(MODEL.with_name("B4_gru-seed-701.npz")))

    def test_death_after_second_inference_before_commit_recomputes_from_h1(self):
        reference = self.reference()
        controller, original = self.controller("after_release")
        pidfd = os.pidfd_open(original["worker_pid"])
        try:
            controller.stdin.write("release\n")
            controller.stdin.flush()
            self.assertEqual(controller.wait(timeout=5), 18)
            with selectors.DefaultSelector() as selector:
                selector.register(pidfd, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=8))
            cut = subprocess.run(
                [sys.executable, "-c", RESTORE_CUT, str(HERE), str(self.root)],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            self.assertEqual(cut.returncode, 19, cut.stderr)
            c = self.restore()
            try:
                self.assertEqual(c.state, original["checkpoint"])
                result = c.finish()
                self.assertEqual(result["knowledge"], "CONFIRMED_COMPLETE")
                keys = ("hidden", "sequence", "actions", "features", "phase", "pending")
                self.assertEqual(
                    {key: c.state[key] for key in keys},
                    {key: reference[key] for key in keys},
                )
                self.record("post_inference_cut_recovered", checkpoint=c.state)
            finally:
                c.close()
        finally:
            os.close(pidfd)
            controller.stdin.close()
            controller.stdin = None
            controller.communicate(timeout=8)

    def test_semantically_changed_checkpoint_rejects_even_with_new_checksum(self):
        controller, _ = self.controller("before_release")
        self.assertEqual(controller.wait(timeout=5), 17)
        controller.communicate(timeout=5)
        path = self.root / "session/control.db"
        with sqlite3.connect(path) as db:
            revision, raw = db.execute(
                "SELECT revision,body FROM gru_state WHERE id=1"
            ).fetchone()
            original = json.loads(raw)
            changed = json.loads(raw)
            changed["pending"]["invocation"] = "foreign"
            encoded = json.dumps(
                changed, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            db.execute(
                "UPDATE gru_state SET digest=?,body=? WHERE id=1",
                (hashlib.sha256(encoded).hexdigest(), encoded),
            )
        with self.assertRaisesRegex(ValueError, "pending identity"):
            self.restore()
        encoded = json.dumps(
            original, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        with sqlite3.connect(path) as db:
            db.execute(
                "UPDATE gru_state SET revision=?,digest=?,body=? WHERE id=1",
                (revision, hashlib.sha256(encoded).hexdigest(), encoded),
            )
        c = self.restore()
        c.close()

    def test_effect_disappearing_after_confirmation_cannot_advance_hidden(self):
        controller, original = self.controller("after_release")
        pidfd = os.pidfd_open(original["worker_pid"])
        try:
            controller.stdin.write("release\n")
            controller.stdin.flush()
            self.assertEqual(controller.wait(timeout=5), 18)
            with selectors.DefaultSelector() as selector:
                selector.register(pidfd, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=8))
            c = self.restore()
            try:
                before = json.loads(json.dumps(c.state))
                observe = c.owner.observe

                def confirm_then_remove(deadline_ns):
                    result = observe(deadline_ns)
                    if result["knowledge"] == "CONFIRMED_COMPLETE":
                        shutil.rmtree(
                            next((self.root / "session/destination/effects").iterdir())
                        )
                    return result

                with patch.object(c.owner, "observe", side_effect=confirm_then_remove):
                    with self.assertRaisesRegex(ValueError, "knowledge changed"):
                        c.finish()
                self.assertEqual(c.state, before)
                self.record("disappearing_effect_rejected", checkpoint=c.state)
            finally:
                c.close()
        finally:
            os.close(pidfd)
            controller.stdin.close()
            controller.stdin = None
            controller.communicate(timeout=8)

    def test_actual_opaque_effect_never_advances_pending_gru_after_death(self):
        self.args["task"]["fault"] = "opaque_after_apply"
        controller, original = self.controller("after_release")
        pidfd = os.pidfd_open(original["worker_pid"])
        try:
            controller.stdin.write("release\n")
            controller.stdin.flush()
            self.assertEqual(controller.wait(timeout=5), 18)
            with selectors.DefaultSelector() as selector:
                selector.register(pidfd, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=8))
            self.assertEqual(
                len(list((self.root / "session/destination/effects").glob("*/value"))),
                1,
            )
            c = self.restore()
            try:
                self.assertEqual(c.observe(time.monotonic_ns())["knowledge"], "UNKNOWN")
                with self.assertRaisesRegex(ValueError, "UNKNOWN"):
                    c.finish()
                self.assertEqual(c.state, original["checkpoint"])
                self.record(
                    "physical_effect_stays_observably_unknown", checkpoint=c.state
                )
            finally:
                c.close()
        finally:
            os.close(pidfd)
            controller.stdin.close()
            controller.stdin = None
            controller.communicate(timeout=8)

    def test_failed_hidden_commit_cannot_release_original(self):
        c = GRUAsyncContinuation.start(directory=self.root / "session", **self.args)
        try:
            c.observe(time.monotonic_ns() + 5_000_000_000)
            with patch.object(
                c, "_save", side_effect=RuntimeError("injected checkpoint failure")
            ):
                with self.assertRaises(RuntimeError):
                    c.plan()
            with self.assertRaisesRegex(ValueError, "committed original checkpoint"):
                c.release()
            self.assertFalse(c.owner.state["release_attempted"])
            self.assertEqual(
                list((self.root / "session/destination/effects").iterdir()), []
            )
        finally:
            c.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    args, remaining = parser.parse_known_args()
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=True)
        GRUAsyncTests.evidence = args.evidence
    unittest.main(argv=[__file__, *remaining])
