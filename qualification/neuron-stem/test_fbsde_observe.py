"""Clock-controlled view failure contracts, not real-model timing assertions."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from four_gate_common import digest
from fbsde_acquisition_observe import AttemptJournal, observe_view, ViewBudgetExceeded


class Probabilities:
    def softmax(self, _): return self
    def __getitem__(self, _): return self
    def tolist(self): return [.2, .8]
    def argmax(self): return SimpleNamespace(item=lambda: 1)


class ObservationTests(unittest.TestCase):
    def perform(self, path, clocks, encoder=lambda _: 'vector'):
        torch = SimpleNamespace(inference_mode=nullcontext, isfinite=lambda _: SimpleNamespace(
            all=lambda: SimpleNamespace(item=lambda: True)))
        journal = AttemptJournal(path)
        try:
            with patch('fbsde_acquisition_observe.tensor_digest', return_value=digest('vector')):
                return observe_view(0, lambda _: 'some text', encoder, lambda x: x,
                    lambda _: Probabilities(), torch, digest('head'), journal,
                    {'arm': 'test', 'split': 'validation', 'id': 'one'},
                    cpu_clock=iter(clocks).__next__, wall_clock=lambda: 0)
        finally:
            journal.close()

    def test_success_receipt_binds_every_cpu_stage(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'attempts'
            symbol, receipt = self.perform(path, [0, 1, 3, 6, 10])
            row = json.loads(path.read_bytes())
            self.assertEqual(symbol, 1)
            self.assertEqual(receipt['cpu_ns'], 10)
            self.assertEqual(sum(row['phase_cpu_ns'].values()), 10)
            self.assertEqual(row['attempt_sha256'], receipt['attempt_sha256'])
            self.assertEqual(row['status'], 'returned')

    def test_overrun_persists_original_time_without_returning_prediction(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'attempts'
            with self.assertRaises(ViewBudgetExceeded):
                self.perform(path, [0, 1, 100_000_001, 100_000_002, 100_000_003])
            row = json.loads(path.read_bytes())
            self.assertEqual(row['cpu_ns'], 100_000_003)
            self.assertEqual(row['limit_ns'], 100_000_000)
            self.assertEqual(row['status'], 'budget_exceeded')
            self.assertFalse(row['prediction_returned'])
            self.assertEqual(row['phase_cpu_ns']['encoder_cpu_ns'], 100_000_000)

    def test_exact_limit_inclusive_but_hash_work_not_free(self):
        with tempfile.TemporaryDirectory() as d:
            self.perform(Path(d)/'a', [0, 1, 2, 3, 100_000_000])
            with self.assertRaises(ViewBudgetExceeded):
                self.perform(Path(d)/'b', [0, 1, 2, 3, 100_000_001])

    def test_execution_error_record_is_not_a_success_and_does_not_leak_text(self):
        def fail(_): raise RuntimeError('private task content')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'attempts'
            with self.assertRaises(RuntimeError): self.perform(path, [0, 1, 4], fail)
            raw = path.read_text(); row = json.loads(raw)
            self.assertEqual(row['stage'], 'encoder')
            self.assertEqual(row['status'], 'execution_error')
            self.assertNotIn('private task content', raw)

    def test_hash_chain_and_exclusive_creation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'attempts'; ledger = AttemptJournal(path)
            try:
                first = ledger.append({'status': 'returned', 'cpu_ns': 1})
                ledger.append({'status': 'returned', 'cpu_ns': 2})
                with self.assertRaises(FileExistsError): AttemptJournal(path)
            finally: ledger.close()
            rows = [json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual(rows[1]['previous_sha256'], first)
            for i, row in enumerate(rows):
                h = row.pop('attempt_sha256')
                self.assertEqual(row['sequence'], i)
                self.assertEqual(h, digest(row))


if __name__ == '__main__': unittest.main()
