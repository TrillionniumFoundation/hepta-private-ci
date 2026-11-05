"""Independent adversarial checks; all media/features here are synthetic fixtures.

These checks establish I/O, identity, acquisition, and persistence behavior only.
They do not establish encoder quality, semantic retrieval, independent recordings,
learned identity binding, analytic-core benefit, or deployment admission.
"""

import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from .boundary import BoundaryError, FrozenInput, Packet
from .runtime import Session
from .test_boundary import FixtureCore, document, h, packet, source


class DurableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "session.sqlite"
        self.frozen = FrozenInput(document())

    def open(self, **changes):
        options = {
            "path": self.path, "frozen": self.frozen, "core": FixtureCore(),
            "session_id": "fixture-recording-session", "source_clock_id": "fixture-source-clock",
        }
        options.update(changes)
        session = Session(**options)
        self.addCleanup(session.close)
        return session

    def accept(self, session, index=0, modality="text", content=None):
        start, end = index * 10, (index + 1) * 10
        item = packet(modality=modality, start_ns=start, end_ns=end,
                      sample_times_ns=(start, end),
                      content="fixture payload " + str(index) if content is None else content)
        read_id = "read-" + str(index)
        session.issue(read_id, item.source_id, modality, start, end, now_ns=end)
        receipt = session.complete(read_id, item, now_ns=end + 1)
        return item, receipt

    def test_acquired_content_has_exact_citation_and_unknown_stays_unknown(self):
        session = self.open()
        item, receipt = self.accept(session, content="真实字符串仍为合成测试：α\nexact")
        self.assertEqual(session.query(receipt["address"]), {
            "status": "ok", "text": item.content,
            "citation": {
                "address": receipt["address"], "source_id": item.source_id,
                "source_sha256": item.source_sha256, "encoder_sha256": item.encoder_sha256,
                "clock_id": item.clock_id, "start_ns": 0, "end_ns": 10,
                "epoch": 0, "read_id": "read-0", "packet_sha256": receipt["packet_sha256"],
            },
        })
        self.assertEqual(session.query(h("never acquired")),
                         {"status": "unknown", "text": None, "citation": None})
        self.assertEqual(session.output(), {"accepted": 1, "elapsed_ns": 10, "last_modality": "text"})

    def test_duplicate_read_and_completion_do_not_repeat_charge_or_state(self):
        session = self.open()
        request = session.issue("read", "fixture-source", "text", 0, 10, now_ns=0, cost_units=7)
        before = session.receipt()
        self.assertEqual(session.issue("read", "fixture-source", "text", 0, 10,
                                      now_ns=100, cost_units=7), request)
        self.assertEqual(session.receipt(), before)
        receipt = session.complete("read", packet(), now_ns=10)
        accepted = session.receipt()
        self.assertEqual(session.complete("read", packet(), now_ns=100), receipt)
        self.assertEqual(session.receipt(), accepted)
        self.assertEqual((accepted["charge_units"], accepted["operations"], accepted["content_items"]), (7, 1, 1))

    def test_idempotency_conflicts_are_rejected_without_mutation(self):
        session = self.open()
        session.issue("read", "fixture-source", "text", 0, 10, now_ns=0)
        before = session.receipt()
        for modality, start, end, cost in (("audio", 0, 10, 1), ("text", 1, 10, 1),
                                           ("text", 0, 11, 1), ("text", 0, 10, 2)):
            with self.subTest(modality=modality, start=start, end=end, cost=cost), self.assertRaises(BoundaryError):
                session.issue("read", "fixture-source", modality, start, end, now_ns=2, cost_units=cost)
            self.assertEqual(session.receipt(), before)
        with self.assertRaises(BoundaryError):
            session.reset("read", now_ns=3)
        session.complete("read", packet(), now_ns=10)
        accepted = session.receipt()
        with self.assertRaises(BoundaryError):
            session.complete("read", packet(content="different response"), now_ns=11)
        self.assertEqual(session.receipt(), accepted)

    def test_completion_checks_window_identity_and_source_release_before_accepting(self):
        self.frozen = FrozenInput(document(source(release_offset_ns=100, sync_uncertainty_ns=3)))
        session = self.open()
        session.issue("read", "fixture-source", "text", 0, 10, now_ns=0)
        before = session.receipt()
        for item, now in ((packet(), 112), (packet(start_ns=1, sample_times_ns=(1, 10)), 113),
                          (packet(end_ns=11), 114), (packet(encoder_sha256=h("other encoder")), 114),
                          (packet(source_sha256=h("other source")), 114),
                          (packet(modality="audio"), 114)):
            with self.subTest(item=item, now=now), self.assertRaises(BoundaryError):
                session.complete("read", item, now_ns=now)
            self.assertEqual(session.receipt(), before)
        self.assertEqual(session.complete("read", packet(), now_ns=113)["status"], "ok")

    def test_duck_typed_or_subclass_packet_cannot_change_persisted_evidence(self):
        class RewrittenPacket(Packet):
            def document(self):
                result = super().document()
                result["content"] = "different from core-visible content"
                return result

        session = self.open()
        session.issue("read", "fixture-source", "text", 0, 10, now_ns=0)
        before = session.receipt()
        forged = RewrittenPacket(**packet().document())
        with self.assertRaises(BoundaryError):
            session.complete("read", forged, now_ns=10)
        self.assertEqual(session.receipt(), before)

    def test_other_recording_session_cannot_issue_into_current_session(self):
        self.frozen = FrozenInput(document(source(), source("other", session_id="other-session")))
        session = self.open()
        before = session.receipt()
        with self.assertRaises(BoundaryError):
            session.issue("cross-session", "other", "audio", 0, 10, now_ns=0)
        self.assertEqual(session.receipt(), before)

    def test_missing_and_ood_are_charged_without_fabricated_observation(self):
        session = self.open()
        for i, status in enumerate(("missing", "ood", "corrupt", "unsupported", "denied", "unknown", "timeout")):
            read_id = "failed-" + str(i)
            session.issue(read_id, "fixture-source", "audio", 0, 10, now_ns=i)
            failed = packet(modality="audio", status=status, sample_times_ns=(), features=(), content="")
            receipt = session.complete(read_id, failed, now_ns=i)
            self.assertEqual((receipt["status"], receipt["address"]), (status, None))
        self.assertEqual(session.output(), FixtureCore().initial())
        receipt = session.receipt()
        self.assertEqual((receipt["charge_units"], receipt["content_items"], receipt["content_bytes"]), (7, 0, 0))

    def test_reset_invalidates_late_read_preserves_content_and_is_idempotent(self):
        session = self.open()
        item, accepted = self.accept(session)
        session.issue("late", "fixture-source", "text", 10, 20, now_ns=12, cost_units=5)
        reset = session.reset("reset", now_ns=13, cost_units=3)
        after = session.receipt()
        self.assertEqual(session.output(), FixtureCore().initial())
        self.assertEqual(session.query(accepted["address"])["text"], item.content)
        self.assertEqual((after["epoch"], after["charge_units"], after["pending_read_ids"]), (1, 9, []))
        self.assertEqual(session.reset("reset", now_ns=30, cost_units=3), reset)
        with self.assertRaises(BoundaryError):
            session.complete("late", packet(start_ns=10, end_ns=20, sample_times_ns=(10, 20)), now_ns=20)
        self.assertEqual(session.receipt(), after)
        self.assertEqual(session.complete("read-0", item, now_ns=30), accepted)
        self.assertEqual(session.receipt(), after)

    def test_abrupt_process_exit_keeps_pending_read_and_restart_is_exact(self):
        script = (
            "import os,sys\n"
            "from experiments.hcsn_v14_causal_io_20261104.test_runtime import FrozenInput,document,FixtureCore,Session,packet\n"
            "s=Session(sys.argv[1],FrozenInput(document()),FixtureCore(),'fixture-recording-session','fixture-source-clock')\n"
            "s.issue('pending','fixture-source','text',0,10,now_ns=0,cost_units=4)\n"
            "s.db.set_trace_callback(lambda sql: os._exit(23) if sql.strip().upper()=='COMMIT' else None)\n"
            "s.complete('pending',packet(),now_ns=10)\n"
            "os._exit(24)\n"
        )
        # The child exits after the accepted snapshot has been written inside
        # the transaction, immediately before SQLite executes COMMIT.
        child_python = [sys.executable] + (["-O"] if sys.flags.optimize else [])
        child = subprocess.run([*child_python, "-c", script, str(self.path)], timeout=20,
                               capture_output=True, cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(child.returncode, 23, child.stderr.decode("utf-8", errors="replace"))
        session = self.open()
        pending = session.receipt()
        self.assertEqual((pending["pending_read_ids"], pending["charge_units"]), (["pending"], 4))
        self.assertEqual((pending["content_items"], session.output()), (0, FixtureCore().initial()))
        session.issue("pending", "fixture-source", "text", 0, 10, now_ns=1, cost_units=4)
        receipt = session.complete("pending", packet(), now_ns=10)
        expected_receipt, expected_output = session.receipt(), session.output()
        expected_query = session.query(receipt["address"])
        session.close()
        restarted = self.open()
        self.assertEqual(restarted.receipt(), expected_receipt)
        self.assertEqual(restarted.output(), expected_output)
        self.assertEqual(restarted.query(receipt["address"]), expected_query)
        self.assertEqual(restarted.complete("pending", packet(), now_ns=20), receipt)
        self.assertEqual(restarted.receipt(), expected_receipt)

    def test_restart_refuses_changed_inputs_model_and_budget(self):
        session = self.open()
        self.accept(session)
        session.close()

        class ChangedCore(FixtureCore):
            model_id = h("different core")

        for changes in ({"core": ChangedCore()}, {"memory_bytes": 65537},
                        {"frozen": FrozenInput(document(source(sha256=h("different source"))))}):
            with self.subTest(changes=changes), self.assertRaises(BoundaryError):
                self.open(**changes)
        self.assertEqual(self.open().output()["accepted"], 1)

    def test_memory_and_operation_exhaustion_preserve_atomic_state(self):
        session = self.open(memory_bytes=1, max_operations=1)
        session.issue("read", "fixture-source", "text", 0, 10, now_ns=0)
        before = session.receipt()
        with self.assertRaises(BoundaryError):
            session.complete("read", packet(), now_ns=10)
        self.assertEqual(session.receipt(), before)
        self.assertEqual(session.output(), FixtureCore().initial())
        with self.assertRaises(BoundaryError):
            session.issue("second", "fixture-source", "audio", 0, 10, now_ns=1)
        self.assertEqual(session.receipt(), before)

    def test_exported_receipt_cannot_change_live_identity_or_limits(self):
        session = self.open()
        expected = copy.deepcopy(session.receipt())
        exposed = session.receipt()
        exposed["identity"]["memory_bytes"] = 2**60
        exposed["identity"]["model"] = h("different model")
        exposed["pending_read_ids"].append("invented pending read")
        self.assertEqual(session.receipt(), expected)

    def test_snapshot_corruption_fails_closed_on_reopen(self):
        session = self.open()
        self.accept(session)
        session.close()
        with sqlite3.connect(self.path) as database:
            body = database.execute("SELECT body FROM snapshot WHERE id=1").fetchone()[0]
            changed = json.loads(body)
            changed["core"]["accepted"] = 999
            database.execute("UPDATE snapshot SET body=? WHERE id=1", (json.dumps(changed),))
        with self.assertRaises(BoundaryError):
            self.open()

    def test_exact_retrieval_survives_1024_intervening_reads_and_restart(self):
        session = self.open(memory_bytes=4 * 1024 * 1024)
        item, first = self.accept(session, content="fixture first item, no ground-truth label")
        for index in range(1, 1025):
            self.accept(session, index=index, modality=("text", "audio", "video", "image")[index % 4])
        expected = session.query(first["address"])
        self.assertEqual(expected["text"], item.content)
        self.assertEqual(session.output()["accepted"], 1025)
        final_receipt = session.receipt()
        self.assertEqual((final_receipt["charge_units"], final_receipt["content_items"]), (1025, 1025))
        session.close()
        restarted = self.open(memory_bytes=4 * 1024 * 1024)
        self.assertEqual(restarted.receipt(), final_receipt)
        self.assertEqual(restarted.query(first["address"]), expected)



if __name__ == "__main__":
    unittest.main()
