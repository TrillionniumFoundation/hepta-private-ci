"""Real SIGKILL cuts around one atomic GRU/lifecycle checkpoint and file effect."""

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from durable_lifecycle import canonical
from recurrent_lifecycle import RecurrentLifecycle
from skill_lifecycle import SkillContract, goals_digest
from sqlite_destination import BudgetExhausted


HERE = Path(__file__).resolve().parent
MODEL = (
    HERE.parent.parent / "qualification/act2-learning-20261110/run2/B4_gru-seed-700.npz"
)
CHILD = r"""
import json,os,signal,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from durable_lifecycle import canonical
from recurrent_lifecycle import RecurrentLifecycle
from skill_lifecycle import SkillContract
root=Path(sys.argv[2]); mode=sys.argv[3]
inputs=json.loads((root/'inputs.json').read_text())
args=(inputs['task'],SkillContract(**inputs['contract']),root/'model.npz',root/'session')
if mode=='restore_once':
    d=RecurrentLifecycle.restore(*args)
    before=json.loads(canonical(d.policy))
    def forbid(*args): raise AssertionError('pending decision was inferred twice')
    d.model.choose=forbid
    more=d.step()
    after=json.loads(canonical(d.policy))
    print(json.dumps({'pid':os.getpid(),'before':before,'after':after,'more':more,'result':d.report()}))
    d.close()
else:
    d=RecurrentLifecycle.start(*args)
    original_save=d._save; original_apply=d.owner.original.apply
    def die():
        raw=d.db.execute('SELECT body FROM state WHERE id=1').fetchone()[0]
        with (root/'interrupted-checkpoint.json').open('wb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        with (root/'cut.json').open('w') as f:
            json.dump({'pid':os.getpid(),'uid':os.geteuid(),'mode':mode,'policy':d.policy,'calls':d.calls},f)
            f.flush(); os.fsync(f.fileno())
        os.kill(os.getpid(),signal.SIGKILL)
    def save():
        original_save()
        if mode=='prepared' and d.policy['phase']=='prepared' and d.policy['pending']['action']=='ensure': die()
    def apply(*args):
        if mode=='before_apply': die()
        result=original_apply(*args)
        if mode=='after_publish': die()
        return result
    d._save=save; d.owner.original.apply=apply
    while d.step(): pass
    raise AssertionError('requested real crash boundary was never reached')
"""


class RecurrentLifecycleTests(unittest.TestCase):
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
        self.child_number = 0

    def child(self, mode, expected=0):
        (self.root / "inputs.json").write_bytes(
            canonical({"task": self.task, "contract": asdict(self.contract)})
        )
        result = subprocess.run(
            [sys.executable, "-c", CHILD, str(HERE), str(self.root), mode],
            capture_output=True,
            text=True,
            timeout=20,
        )
        prefix = self.root / f"child-{self.child_number}-{mode}"
        self.child_number += 1
        prefix.with_suffix(".stdout").write_text(result.stdout)
        prefix.with_suffix(".stderr").write_text(result.stderr)
        prefix.with_suffix(".json").write_bytes(
            canonical({"mode": mode, "returncode": result.returncode})
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def start(self):
        return RecurrentLifecycle.start(
            self.task, self.contract, self.root / "model.npz", self.root / "session"
        )

    def restore(self):
        return RecurrentLifecycle.restore(
            self.task, self.contract, self.root / "model.npz", self.root / "session"
        )

    def check_hidden(self, row):
        cut = json.loads((self.root / "cut.json").read_text())
        saved = json.loads((self.root / "interrupted-checkpoint.json").read_text())
        for name in ("hidden", "sequence", "decisions", "pending"):
            self.assertEqual(row["before"][name], cut["policy"][name])
            self.assertEqual(saved["fields"]["policy"][name], cut["policy"][name])
        for name in ("hidden", "sequence", "decisions"):
            self.assertEqual(row["after"][name], row["before"][name])
        self.assertNotEqual(row["pid"], cut["pid"])
        self.assertEqual(cut["uid"], os.geteuid())
        self.assertEqual(saved["fields"]["calls"], cut["calls"])
        self.assertGreater(row["result"]["primitive_calls"], cut["calls"])

    def test_prepared_real_sigkill_consumes_original_decision_without_inference(self):
        self.child("prepared", -signal.SIGKILL)
        row = self.child("restore_once")
        self.check_hidden(row)
        self.assertEqual(
            (
                row["before"]["phase"],
                row["after"]["phase"],
                row["result"]["effect_count"],
                row["result"]["duplicate_effects"],
            ),
            ("prepared", "ready", 1, 0),
        )

    def test_prepared_resume_matches_uninterrupted_learned_policy_and_goal(self):
        reference = RecurrentLifecycle.start(
            self.task, self.contract, self.root / "model.npz", self.root / "reference"
        )
        try:
            while reference.step():
                pass
            expected = reference.report()
        finally:
            reference.close()
        self.child("prepared", -signal.SIGKILL)
        restored = self.restore()
        try:
            while restored.step():
                pass
            actual = restored.report()
        finally:
            restored.close()
        fields = (
            "complete",
            "claimed_success",
            "effect_records",
            "duplicate_effects",
            "primitive_calls",
        )
        self.assertEqual(
            {k: actual[k] for k in fields}, {k: expected[k] for k in fields}
        )
        self.assertTrue(actual["claimed_success"])
        policy_fields = (
            "hidden",
            "sequence",
            "decisions",
            "phase",
            "pending",
            "claimed",
        )
        self.assertEqual(
            {k: actual["policy"][k] for k in policy_fields},
            {k: expected["policy"][k] for k in policy_fields},
        )
        self.assertTrue(actual["model_hidden_state_restored"])
        (self.root / "full-reference.json").write_bytes(canonical(expected))
        (self.root / "full-restored.json").write_bytes(canonical(actual))

    def test_entered_real_sigkill_before_apply_remains_unknown_without_resend(self):
        self.child("before_apply", -signal.SIGKILL)
        row = self.child("restore_once")
        self.check_hidden(row)
        self.assertEqual(
            (
                row["more"],
                row["after"]["phase"],
                row["result"]["effect_count"],
                row["result"]["effect_knowledge"],
                row["result"]["claimed_success"],
            ),
            (False, "entered", 0, "UNKNOWN", False),
        )
        again = self.child("restore_once")
        self.assertEqual(again["result"]["effect_count"], 0)
        self.assertEqual(again["after"]["hidden"], row["after"]["hidden"])

    def test_after_publish_real_sigkill_reconciles_only_original_key(self):
        self.task["goals"] = ["first", "second"]
        self.contract = replace(
            self.contract, goals_digest=goals_digest(self.task["goals"])
        )
        self.child("after_publish", -signal.SIGKILL)
        row = self.child("restore_once")
        self.check_hidden(row)
        self.assertEqual(
            (
                row["before"]["phase"],
                row["after"]["phase"],
                row["result"]["effect_count"],
                row["result"]["duplicate_effects"],
                row["result"]["claimed_success"],
            ),
            ("entered", "ready", 1, 0, False),
        )
        self.assertEqual(
            [r["invocation"] for r in row["result"]["effect_records"]], ["original:0"]
        )

    def test_opaque_published_effect_preserves_unknown_and_hidden(self):
        self.task["fault"] = "opaque_after_apply"
        self.child("after_publish", -signal.SIGKILL)
        row = self.child("restore_once")
        self.check_hidden(row)
        self.assertEqual(
            (
                row["more"],
                row["after"]["phase"],
                row["result"]["effect_count"],
                row["result"]["effect_knowledge"],
                row["result"]["claimed_success"],
            ),
            (False, "entered", 1, "UNKNOWN", False),
        )

    def test_pause_and_elapsed_original_deadline_preserve_hidden_without_inference(
        self,
    ):
        self.contract = replace(
            self.contract, deadline_ns=time.monotonic_ns() + 800_000_000
        )
        d = self.start()
        try:
            d.step()
            d.pause()
            prior, spent = canonical(d.policy), d.calls
        finally:
            d.close()
        time.sleep(
            max(0, self.contract.deadline_ns - time.monotonic_ns()) / 1e9 + 0.002
        )
        d = self.restore()
        try:
            with patch.object(
                d.model, "choose", side_effect=AssertionError("expired inference")
            ):
                self.assertFalse(d.step())
                d.resume()
                self.assertFalse(d.step())
            self.assertEqual(
                (canonical(d.policy), d.calls, d.state, d.contract.deadline_ns),
                (prior, spent, "DEADLINE", self.contract.deadline_ns),
            )
            self.assertEqual(d.owner.audit()["effect_count"], 0)
        finally:
            d.close()

    def test_exhausted_budget_is_not_refunded_and_cannot_advance_hidden(self):
        d = self.start()
        try:
            d.step()
            while d.calls < d.budget:
                d.inspect()
            prior = canonical(d.policy)
        finally:
            d.close()
        d = self.restore()
        try:
            with patch.object(
                d.model, "choose", side_effect=AssertionError("unbudgeted inference")
            ):
                with self.assertRaises(BudgetExhausted):
                    d.step()
            self.assertEqual((canonical(d.policy), d.calls), (prior, d.budget))
            self.assertEqual(d.report()["effect_knowledge"], "UNKNOWN")
        finally:
            d.close()

    def test_different_real_model_is_rejected_without_checkpoint_write(self):
        d = self.start()
        d.step()
        d.close()

        def checkpoint():
            with sqlite3.connect(self.root / "session/control.db") as db:
                return db.execute("SELECT revision,digest,body FROM state").fetchall()

        before = checkpoint()
        shutil.copyfile(MODEL.with_name("B4_gru-seed-701.npz"), self.root / "model.npz")
        with self.assertRaisesRegex(ValueError, "drift"):
            self.restore()
        self.assertEqual(checkpoint(), before)
        self.assertEqual(
            list((self.root / "session/destination/effects").iterdir()), []
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    args, remaining = parser.parse_known_args()
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=False)
        RecurrentLifecycleTests.evidence = args.evidence
        (args.evidence / "child-source.py").write_text(CHILD)
        sources = args.evidence / "source-postimages"
        sources.mkdir()
        for name in (
            "recurrent_lifecycle.py",
            "durable_lifecycle.py",
            "test_recurrent_lifecycle.py",
            "skill_lifecycle.py",
            "file_family.py",
            "models.py",
            "run.py",
            "diagnose.py",
        ):
            shutil.copyfile(HERE / name, sources / name)
    unittest.main(argv=[__file__, *remaining])
