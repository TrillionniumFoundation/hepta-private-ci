"""Real SQLite effects and process exits; no HIA migration qualification claim."""

from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from hepta_cells.component_types import Budget, CellError, Partition, PendingExecution
from hepta_cells.component_types import Qualification, RequestConflict, StepContext
from hepta_cells.deterministic import ToolCell
from hepta_cells.lifecycle import CellOwner
from hepta_cells.receiver_handoff import ReceiverLease, ReceiverLedger, ReceiverPort


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        retained = os.environ.get("HEPTA_RECEIVER_TEST_ARTIFACT_ROOT")
        self.temp = None if retained else tempfile.TemporaryDirectory()
        self.root = (
            Path(retained) / self._testMethodName if retained else Path(self.temp.name)
        )
        self.root.mkdir(parents=True, exist_ok=not bool(retained))
        self.partition = Partition("principal", "agent", "cell", "run")
        self.old = ReceiverLease(self.partition.digest, "old", 0, "a" * 64)
        self.new = ReceiverLease(self.partition.digest, "new", 1, "b" * 64)
        self.ledger = ReceiverLedger.create(self.root / "receiver.sqlite", "7" * 64)
        self.tool = ToolCell(
            "append_record", "c" * 64, ReceiverPort(self.ledger, self.old), "d" * 64
        )
        self.ledger.provision(
            self.old, self.tool.identity.digest, self.tool.tool_digest
        )
        self.owner = CellOwner(self.root / "owner.sqlite")
        self.owner.create(self.partition, self.tool)
        self.invocation = self.tool._invocation(
            {"record": {"value": 7}},
            StepContext(self.partition, "effect", self.tool.identity, None, Budget()),
        )
        self.environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parent))

    def tearDown(self):
        self.owner.close()
        self.ledger.close()
        if self.temp is not None:
            self.temp.cleanup()

    def child(self, body, *, stdin=None):
        code = (
            """
import os, sys
from pathlib import Path
from hepta_cells.component_types import Partition
from hepta_cells.deterministic import ToolCell
from hepta_cells.lifecycle import CellOwner
from hepta_cells.receiver_handoff import ReceiverLease, ReceiverLedger, ReceiverPort
root = Path(sys.argv[1]); partition = Partition('principal', 'agent', 'cell', 'run')
lease = ReceiverLease(partition.digest, 'old', 0, 'a' * 64)
ledger = ReceiverLedger(root / 'receiver.sqlite', '7' * 64)
"""
            + body
        )
        return subprocess.Popen(
            [sys.executable, "-c", code, str(self.root)],
            env=self.environment,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def finish(self, child, expected=0):
        out, err = child.communicate(timeout=20)
        with (self.root / "processes.jsonl").open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "pid": child.pid,
                        "exit": child.returncode,
                        "stdout": out,
                        "stderr": err,
                    }
                )
                + "\n"
            )
        self.assertEqual((child.returncode, err), (expected, ""))
        return out

    def records(self):
        return self.ledger.db.execute(
            "SELECT record FROM effects ORDER BY rowid"
        ).fetchall()

    def test_healthy_toolcell_replays_retained_receipt_after_cold_open(self):
        receipt = self.owner.step(
            self.partition, self.tool, "effect", {"record": {"value": 7}}
        )
        self.owner.close()
        self.owner = CellOwner(self.root / "owner.sqlite")
        self.assertEqual(
            self.owner.step(
                self.partition, self.tool, "effect", {"record": {"value": 7}}
            ),
            receipt,
        )
        self.assertEqual([row[0] for row in self.records()], ['{"value":7}'])
        self.assertEqual(
            self.owner.checkpoint(self.partition)["state"], {"completed": 1}
        )

    def test_process_exit_after_effect_retains_unknown_cost_and_never_retries(self):
        child = self.child("""
class Crash(ReceiverPort):
    def invoke(self, invocation):
        super().invoke(invocation)
        os._exit(41)
tool = ToolCell('append_record', 'c' * 64, Crash(ledger, lease), 'd' * 64)
CellOwner(root / 'owner.sqlite').step(partition, tool, 'effect', {'record': {'value': 7}})
""")
        self.finish(child, 41)
        self.owner.close()
        self.owner = CellOwner(self.root / "owner.sqlite")
        self.assertEqual(self.ledger.readback(self.invocation)["outcome"], "committed")
        self.assertEqual(self.owner.status(self.partition)["pending"], ["effect"])
        for request in ("effect", "new-request"):
            with self.assertRaises(PendingExecution):
                self.owner.step(
                    self.partition, self.tool, request, {"record": {"value": 7}}
                )
        self.assertEqual(
            self.owner.request_cancel(self.partition, self.tool, "effect")["outcome"],
            "unknown",
        )
        with self.assertRaises(PendingExecution):
            self.owner.reconcile(
                self.partition, self.tool, "effect", self.tool.readback
            )
        self.assertEqual(
            self.owner.attempts(self.partition, "effect")[-1]["outcome"],
            "original_cost_unknown",
        )
        candidate = ToolCell("append_record", "c" * 64, self.tool.port, "e" * 64)
        qualification = Qualification(
            self.tool.identity.digest, candidate.identity.digest, "f" * 64
        )
        self.owner.qualify = lambda received: received == qualification
        with self.assertRaisesRegex(CellError, "separate custody"):
            self.owner.migrate(
                self.partition,
                self.tool,
                candidate,
                qualification,
                operation_id="move",
                checkpoint_id="1" * 64,
            )
        self.assertEqual([row[0] for row in self.records()], ['{"value":7}'])

    def test_process_exit_before_dispatch_does_not_turn_absence_into_retry_permission(
        self,
    ):
        self.finish(
            self.child("""
class Crash(ReceiverPort):
    def invoke(self, invocation):
        os._exit(42)
tool = ToolCell('append_record', 'c' * 64, Crash(ledger, lease), 'd' * 64)
CellOwner(root / 'owner.sqlite').step(partition, tool, 'effect', {'record': {'value': 7}})
"""),
            42,
        )
        self.assertIsNone(self.ledger.readback(self.invocation))
        with self.assertRaises(PendingExecution):
            self.owner.reconcile(
                self.partition, self.tool, "effect", self.tool.readback
            )
        self.assertEqual(self.records(), [])
        self.assertEqual(self.owner.status(self.partition)["pending"], ["effect"])

    def test_prepare_crash_fences_both_writers_until_exact_target_commit(self):
        body = f"""
target = ReceiverLease(partition.digest, 'new', 1, 'b' * 64)
ledger.prepare('move', lease, target, {self.tool.identity.digest!r}, {{'pending': ['effect']}})
os._exit(43)
"""
        self.finish(self.child(body), 43)
        for lease in (self.old, self.new):
            with self.assertRaises(CellError):
                self.ledger.invoke(lease, self.invocation)
        receipt = self.ledger.commit("move", self.new)
        self.assertEqual(self.ledger.commit("move", self.new), receipt)
        self.ledger.prepare(
            "move",
            self.old,
            self.new,
            self.tool.identity.digest,
            {"pending": ["effect"]},
        )
        with self.assertRaises(CellError):
            self.ledger.invoke(self.old, self.invocation)
        new_request = replace(
            self.invocation, operation_id="2" * 64, request_id="after", epoch=1
        )
        self.assertEqual(self.ledger.invoke(self.new, new_request)["owner"], "new")

    def test_concurrent_processes_commit_one_stable_effect(self):
        body = """
from hepta_cells.component_types import Budget, StepContext
import json
tool = ToolCell('append_record', 'c' * 64, ReceiverPort(ledger, lease), 'd' * 64)
invocation = tool._invocation({'record': {'value': 7}}, StepContext(partition, 'effect', tool.identity, None, Budget()))
print(json.dumps(ledger.invoke(lease, invocation), sort_keys=True))
"""
        children = [self.child(body) for _ in range(4)]
        receipts = [self.finish(child) for child in children]
        self.assertEqual(receipts, [receipts[0]] * 4)
        self.assertEqual(len(self.records()), 1)

    def test_changed_effect_or_handoff_binding_is_rejected(self):
        original = self.ledger.invoke(self.old, self.invocation)
        with self.assertRaisesRegex(CellError, "mapping"):
            self.ledger.prepare(
                "not-a-map", self.old, self.new, self.tool.identity.digest, None
            )
        with self.assertRaises(CellError):
            self.ledger.invoke(
                self.old,
                replace(self.invocation, request_id="wrong-tool", tool_digest="9" * 64),
            )
        changed = replace(self.invocation, arguments={"record": "changed"})
        for invoke in (
            lambda: self.ledger.invoke(self.old, changed),
            lambda: self.ledger.readback(changed),
        ):
            with self.assertRaises(RequestConflict):
                invoke()
        self.ledger.prepare(
            "move", self.old, self.new, self.tool.identity.digest, {"pending": []}
        )
        with self.assertRaises(RequestConflict):
            self.ledger.prepare(
                "move",
                self.old,
                self.new,
                self.tool.identity.digest,
                {"pending": ["other"]},
            )
        with self.assertRaises(CellError):
            self.ledger.commit("move", replace(self.new, key="3" * 64))
        self.ledger.commit("move", self.new)
        with self.assertRaises(RequestConflict):
            self.ledger.invoke(
                self.new, replace(self.invocation, epoch=1, operation_id="4" * 64)
            )
        self.assertEqual(self.ledger.readback(self.invocation), original)
        self.assertEqual(len(self.records()), 1)

    def test_operation_alias_is_rejected_before_and_after_handoff(self):
        original = self.ledger.invoke(self.old, self.invocation)
        alias = replace(self.invocation, request_id="alias", arguments={"record": 8})
        for action in (
            lambda: self.ledger.invoke(self.old, alias),
            lambda: self.ledger.readback(alias),
        ):
            with self.assertRaises(RequestConflict):
                action()
        self.ledger.prepare("move", self.old, self.new, self.tool.identity.digest, {})
        self.ledger.commit("move", self.new)
        with self.assertRaises(RequestConflict):
            self.ledger.invoke(self.new, replace(alias, epoch=1))
        self.assertEqual(self.ledger.readback(self.invocation), original)
        self.assertEqual(len(self.records()), 1)

    def test_concurrent_operation_aliases_have_one_winner(self):
        body = """
from hepta_cells.component_types import Budget, StepContext, RequestConflict
from dataclasses import replace
tool = ToolCell('append_record', 'c' * 64, ReceiverPort(ledger, lease), 'd' * 64)
invocation = tool._invocation({'record': os.getpid()}, StepContext(partition, str(os.getpid()), tool.identity, None, Budget()))
try:
    ledger.invoke(lease, replace(invocation, operation_id='6' * 64))
    print('committed')
except RequestConflict:
    print('rejected')
"""
        children = [self.child(body) for _ in range(4)]
        outcomes = [self.finish(child).strip() for child in children]
        self.assertEqual(sorted(outcomes), ["committed"] + ["rejected"] * 3)
        self.assertEqual(len(self.records()), 1)

    def test_replaying_old_commit_never_reactivates_old_owner(self):
        self.ledger.prepare("move", self.old, self.new, self.tool.identity.digest, {})
        original = self.ledger.commit("move", self.new)
        third = ReceiverLease(self.partition.digest, "third", 2, "5" * 64)
        self.ledger.prepare("again", self.new, third, self.tool.identity.digest, {})
        self.ledger.commit("again", third)
        self.assertEqual(self.ledger.commit("move", self.new), original)
        with self.assertRaises(CellError):
            self.ledger.invoke(self.new, replace(self.invocation, epoch=1))
        self.assertEqual(
            self.ledger.invoke(third, replace(self.invocation, epoch=2))["owner"],
            "third",
        )

    def test_failed_handoff_transaction_preserves_old_writer(self):
        self.ledger.db.execute(
            "CREATE TRIGGER refuse BEFORE INSERT ON transfers BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.prepare(
                "move", self.old, self.new, self.tool.identity.digest, {}
            )
        self.assertEqual(self.ledger.invoke(self.old, self.invocation)["owner"], "old")
        self.assertEqual(
            self.ledger.db.execute("SELECT count(*) FROM transfers").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
