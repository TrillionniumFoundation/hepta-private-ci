"""Local marker processes verify write-before-dispatch and clock admission behavior."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from . import transport
from .ledger import append_event, complete_events, reconcile
from .test_transport import CONTEXT, invoice, provider, reply


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.ledger = self.directory/"ledger.jsonl"
        self.marker = self.directory/"worker-ran.txt"
        code = "from pathlib import Path;Path("+repr(str(self.marker))+").write_text('ran');print("+repr(json.dumps(reply()))+")"
        self.config = provider(code)

    def records(self):
        return [json.loads(s) for s in self.ledger.read_text().splitlines()]

    def test_unwritable_ledger_prevents_actual_worker_start(self):
        for invalid_path in (self.directory, self.directory/"missing"/"ledger.jsonl"):
            with self.subTest(path=str(invalid_path)):
                with self.assertRaises(OSError):
                    transport.call(self.config, {}, CONTEXT, invalid_path, 1.)
                self.assertFalse(self.marker.exists())

    def test_slow_intent_exhausts_request_or_episode_deadline_without_dispatch(self):
        def slow_write(path, event):
            if event["phase"] == "intent": time.sleep(.06)
            append_event(path, event)
        for mode in ("request", "episode"):
            timeout = .02 if mode == "request" else 2.
            absolute = None if mode == "request" else time.perf_counter()+.02
            self.ledger.unlink(missing_ok=True)
            with patch.object(transport, "append_event", side_effect=slow_write):
                event, text = transport.call(self.config, {}, CONTEXT, self.ledger, timeout, absolute_deadline=absolute)
            self.assertEqual(event["status"], "timeout")
            self.assertFalse(event["dispatched"])
            self.assertIsNone(event["dispatch_monotonic"])
            self.assertIsNone(text)
            self.assertFalse(self.marker.exists())
            self.assertGreaterEqual(event["wall_seconds"], .06)
            self.assertEqual(len(complete_events(self.records())), 1)

    def test_terminal_write_failure_leaves_durable_unfinished_intent(self):
        def fail_end(path, event):
            if event["phase"] == "terminal": raise OSError("fixture disk failure")
            append_event(path, event)
        with patch.object(transport, "append_event", side_effect=fail_end):
            with self.assertRaises(OSError):
                transport.call(self.config, {}, CONTEXT, self.ledger, 1.)
        self.assertTrue(self.marker.exists())
        records = self.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["phase"], "intent")
        with self.assertRaisesRegex(ValueError, "unfinished_intent"):
            complete_events(records)

    def test_dispatched_worker_observes_intent_already_on_disk(self):
        code = "import json;rows=[json.loads(s) for s in open("+repr(str(self.ledger))+")];assert rows[-1]['phase']=='intent';print("+repr(json.dumps(reply()))+")"
        end, _ = transport.call(provider(code), {}, CONTEXT, self.ledger, 1.)
        self.assertEqual(end["status"], "ok")
        self.assertLessEqual(end["intent_finished_monotonic"], end["dispatch_monotonic"])
        events = complete_events(self.records())
        self.assertEqual(len(events), 1)
        costs, problems = reconcile(events, [invoice(end, .04)], "USD")
        self.assertFalse(problems)
        self.assertEqual(sum(costs.values()), .04)


if __name__ == "__main__":
    unittest.main()
