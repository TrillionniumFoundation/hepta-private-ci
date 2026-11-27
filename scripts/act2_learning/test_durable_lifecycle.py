"""Actual process cuts preserve original controls, accounting and effect identity."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import time
import unittest

from durable_lifecycle import DurableLifecycle
from skill_lifecycle import SkillContract, goals_digest
from sqlite_destination import BudgetExhausted


HERE = Path(__file__).resolve().parent
CHILD = r"""
import json,os,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from durable_lifecycle import DurableLifecycle
from skill_lifecycle import SkillContract
root=Path(sys.argv[2]); mode=sys.argv[3]
inputs=json.loads((root/'inputs.json').read_text())
task=inputs['task']; contract=SkillContract(**inputs['contract'])
if mode.startswith('restore'):
    d=DurableLifecycle.restore(task,contract,root/'model',root/'session')
    if mode=='restore_complete':
        d.inspect(); d.ensure(); d.inspect()
    result=d.score(True)
    print(json.dumps(result)); d.close()
else:
    d=DurableLifecycle.start(task,contract,root/'model',root/'session')
    d.inspect()
    if mode=='paused':
        d.pause(); os._exit(17)
    original=d.owner.original.apply
    def cut(*args):
        if mode=='before_apply': os._exit(17)
        result=original(*args)
        if mode=='after_apply': os._exit(17)
        return result
    d.owner.original.apply=cut
    d.ensure(); os._exit(18)
"""


class DurableLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {
            "id": "original",
            "version": 1,
            "goals": ["payload"],
            "fault": "normal",
        }
        self.contract = SkillContract(
            "original",
            1,
            goals_digest(self.task["goals"]),
            time.monotonic_ns() + 60_000_000_000,
            1,
        )
        (self.root / "model").write_bytes(
            b"controlled artifact; no inference qualification"
        )
        self.write_inputs()

    def write_inputs(self):
        (self.root / "inputs.json").write_text(
            json.dumps({"task": self.task, "contract": asdict(self.contract)})
        )

    def child(self, mode, expected=0):
        result = subprocess.run(
            [sys.executable, "-c", CHILD, str(HERE), str(self.root), mode],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def open(self):
        return DurableLifecycle.restore(
            self.task, self.contract, self.root / "model", self.root / "session"
        )

    def test_process_death_before_apply_remains_unknown_without_replay(self):
        self.child("before_apply", 17)
        row = self.child("restore_complete")
        self.assertEqual(
            (
                row["effect_count"],
                row["effect_knowledge"],
                row["claimed_success"],
                row["primitive_calls"],
            ),
            (0, "UNKNOWN", False, 6),
        )
        self.assertEqual(
            len(list((self.root / "session/destination/effects").iterdir())), 0
        )

    def test_process_death_after_real_publication_reconciles_original_once(self):
        self.child("after_apply", 17)
        row = self.child("restore_complete")
        self.assertEqual(
            (
                row["effect_count"],
                row["duplicate_effects"],
                row["claimed_success"],
                row["primitive_calls"],
            ),
            (1, 0, True, 6),
        )
        payload = next((self.root / "session/destination/effects").glob("*/value"))
        self.assertEqual(payload.read_text(), "payload")
        self.assertIsNone(row["owner_requests"])

    def replace_with_foreign_invocation(self):
        folder = next((self.root / "session/destination/effects").iterdir())
        path = folder / "intent.json"
        intent = json.loads(path.read_text())
        intent["invocation"] = "foreign-self-consistent-operation"
        path.write_text(json.dumps(intent, sort_keys=True))
        folder.rename(
            folder.parent / hashlib.sha256(intent["invocation"].encode()).hexdigest()
        )

    def test_foreign_but_self_consistent_invocation_is_never_original_receipt(self):
        self.child("after_apply", 17)
        self.replace_with_foreign_invocation()
        with self.assertRaisesRegex(ValueError, "original invocation identity drift"):
            self.open()

    def test_foreign_receipt_after_restore_clears_old_success_and_is_rejected(self):
        self.child("after_apply", 17)
        d = self.open()
        try:
            self.assertTrue(d.inspect()["complete"])
            self.replace_with_foreign_invocation()
            with self.assertRaisesRegex(
                ValueError, "original invocation identity drift"
            ):
                d.inspect()
            self.assertIsNone(d.view)
            with self.assertRaisesRegex(
                ValueError, "original invocation identity drift"
            ):
                d.score(True)
        finally:
            d.close()

    def test_paused_state_and_original_deadline_survive_two_processes(self):
        self.child("paused", 17)
        first = self.child("restore")
        self.assertEqual(
            (first["state"], first["pause_count"], first["primitive_calls"]),
            ("PAUSED", 1, 1),
        )
        d = self.open()
        try:
            d.ensure()
            self.assertEqual(
                (d.state, d.calls, d.owner.audit()["effect_count"]), ("PAUSED", 1, 0)
            )
            d.resume()
            d.ensure()
            d.ensure()
            d.inspect()
            row = d.score(True)
            self.assertEqual(
                (row["complete"], row["primitive_calls"], d.contract.deadline_ns),
                (True, 5, self.contract.deadline_ns),
            )
        finally:
            d.close()

    def test_second_writer_and_contract_model_drift_are_rejected(self):
        d = DurableLifecycle.start(
            self.task, self.contract, self.root / "model", self.root / "session"
        )
        try:
            with self.assertRaises(BlockingIOError):
                self.open()
            process = subprocess.run(
                [sys.executable, "-c", CHILD, str(HERE), str(self.root), "restore"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("BlockingIOError", process.stderr)
        finally:
            d.close()
        with self.assertRaisesRegex(ValueError, "drift"):
            DurableLifecycle.restore(
                self.task,
                replace(self.contract, deadline_ns=self.contract.deadline_ns + 1),
                self.root / "model",
                self.root / "session",
            )
        (self.root / "model").write_bytes(b"different actual model bytes")
        with self.assertRaisesRegex(ValueError, "drift"):
            self.open()

    def test_deadline_expiry_after_restart_cannot_extend_original_budget(self):
        self.contract = replace(
            self.contract, deadline_ns=time.monotonic_ns() + 2_000_000_000
        )
        self.write_inputs()
        self.child("paused", 17)
        with sqlite3.connect(self.root / "session/control.db") as db:
            saved = json.loads(
                db.execute("SELECT body FROM state WHERE id=1").fetchone()[0]
            )
        self.assertFalse(saved["fields"]["expired"])
        self.assertLess(saved["fields"]["last_clock"], self.contract.deadline_ns)
        remaining = max(0, self.contract.deadline_ns - time.monotonic_ns())
        time.sleep(remaining / 1_000_000_000 + 0.002)
        restored = self.child("restore")
        self.assertEqual(
            (restored["state"], restored["primitive_calls"], restored["effect_count"]),
            ("DEADLINE", 1, 0),
        )
        with self.assertRaisesRegex(ValueError, "drift"):
            DurableLifecycle.restore(
                self.task,
                replace(
                    self.contract, deadline_ns=time.monotonic_ns() + 60_000_000_000
                ),
                self.root / "model",
                self.root / "session",
            )
        d = self.open()
        try:
            d.resume()
            d.ensure()
            d.inspect()
            row = d.score(True)
            self.assertEqual(
                (row["state"], row["effect_count"], row["primitive_calls"]),
                ("DEADLINE", 0, 2),
            )
        finally:
            d.close()

    def test_fully_spent_primitive_budget_survives_reopen(self):
        d = DurableLifecycle.start(
            self.task, self.contract, self.root / "model", self.root / "session"
        )
        budget = d.budget
        for _ in range(budget):
            d.inspect()
        with self.assertRaises(BudgetExhausted):
            d.inspect()
        d.close()
        d = self.open()
        try:
            with self.assertRaises(BudgetExhausted):
                d.ensure()
            with self.assertRaises(BudgetExhausted):
                d.inspect()
            self.assertEqual(
                (d.budget, d.calls, d.owner.calls, d.owner.audit()["effect_count"]),
                (budget, budget, [], 0),
            )
        finally:
            d.close()

    def test_known_precommit_repair_budget_survives_reopen(self):
        self.task["goals"] = ["first", "second"]
        self.task["fault"] = "partial_failure"
        self.contract = replace(
            self.contract, goals_digest=goals_digest(self.task["goals"])
        )
        d = DurableLifecycle.start(
            self.task, self.contract, self.root / "model", self.root / "session"
        )
        d.inspect()
        d.ensure()
        d.inspect()
        d.ensure()
        spent = d.calls
        d.close()
        d = self.open()
        try:
            d.inspect()
            d.ensure()
            d.inspect()
            row = d.score(True)
            self.assertEqual(
                (
                    row["complete"],
                    row["repair_count"],
                    row["duplicate_effects"],
                    row["primitive_calls"],
                ),
                (True, 1, 0, spent + 3),
            )
        finally:
            d.close()


if __name__ == "__main__":
    unittest.main()
