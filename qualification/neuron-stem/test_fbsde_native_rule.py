"""Local adapter contracts. Transport fixtures explicitly do NOT verify native authority."""
import tempfile
from pathlib import Path
import threading
import unittest

from fbsde_native_rule import NativeRuleSlotConsumer
from fbsde_rule_checkpoint import CheckpointError, RuleCheckpoint
from fbsde_durable_rule import DurableRuleSlot
from test_fbsde_durable_rule import create
from test_fbsde_rule_lifecycle import CONTEXT, source, begin


class TransportFixture:
    def __init__(self):
        self.calls = []
        self.response = None

    def call(self, command):
        self.calls.append(command)
        if command['command'] == 'init': return dict(ok=True)
        if isinstance(self.response, BaseException): raise self.response
        if self.response is not None: return self.response
        return dict(ok=True, sequence=command['sequence'],
            checkpoint_digest=command['checkpoint_digest'], rule_revision=command['rule_revision'],
            generation=command['generation'], effect=[x // (1 << 24) for x in command['expected_prediction_q24']])

    def close(self): pass


class NativeRuleAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.slot = create(Path(self.temp.name))
        self.port = TransportFixture()
        self.consumer = NativeRuleSlotConsumer(self.slot, self.port)

    def tearDown(self):
        self.consumer.close()
        self.slot.close()
        self.temp.cleanup()

    def test_verified_use_and_single_delivery(self):
        ticket = begin(self.slot)
        self.assertTrue(self.consumer.verify(ticket, source(1)))
        self.assertEqual(self.consumer.finish(ticket), (0, 2, 1))
        with self.assertRaises(ValueError): self.consumer.finish(ticket)
        self.assertEqual([c['command'] for c in self.port.calls], ['init', 'execute'])

    def test_unverified_prediction_never_enters_native(self):
        with self.assertRaisesRegex(ValueError, 'verification required'):
            self.consumer.finish(begin(self.slot))
        self.assertEqual([c['command'] for c in self.port.calls], ['init'])
        self.assertEqual(self.slot.status()['state'], 'quarantined')

    def test_native_receipt_binds_the_transformed_nonidentity_state(self):
        ticket = begin(self.slot, state=(1, 2, 0))
        self.assertTrue(self.consumer.verify(ticket, source(1)))
        self.assertEqual(self.consumer.finish(ticket), (1, 0, 2))
        self.assertEqual(self.port.calls[-1]['expected_prediction_q24'], [1 << 24, 0, 2 << 24])

    def test_generation_change_requires_new_selected_candidate(self):
        ticket = begin(self.slot)
        self.assertTrue(self.consumer.verify(ticket, source(1)))
        self.slot.advance_generation(2)
        with self.assertRaises(ValueError): self.consumer.finish(ticket)
        self.assertEqual(len(self.port.calls), 1)

    def test_native_refusal_quarantines_and_prevents_retry(self):
        ticket = begin(self.slot)
        self.assertTrue(self.consumer.verify(ticket, source(1)))
        self.port.response = dict(ok=False, reason='fixture refusal')
        with self.assertRaisesRegex(ValueError, 'native final-use'):
            self.consumer.finish(ticket)
        with self.assertRaises(ValueError): self.consumer.finish(ticket)
        self.assertEqual(len(self.port.calls), 2)
        self.assertEqual(self.slot.status()['state'], 'quarantined')

    def test_native_unknown_cannot_replay_and_retains_attempt_cost(self):
        ticket = begin(self.slot)
        self.assertTrue(self.consumer.verify(ticket, source(1)))
        self.port.response = OSError('response lost AFTER fixture execution')
        with self.assertRaises(OSError): self.consumer.finish(ticket)
        with self.assertRaises(ValueError): self.consumer.finish(ticket)
        self.assertEqual(len(self.port.calls), 2)
        self.assertTrue(all(c['wall_ns'] > 0 for c in self.consumer.costs))
        self.assertFalse(any(c['returned'] for c in self.consumer.costs))

    def test_mismatching_receipt_is_never_published(self):
        ticket = begin(self.slot)
        self.assertTrue(self.consumer.verify(ticket, source(1)))
        self.port.response = dict(ok=True, sequence=ticket.sequence + 1)
        with self.assertRaises(ValueError): self.consumer.finish(ticket)
        self.assertEqual(self.slot.status()['state'], 'quarantined')

    def test_uncertain_local_finish_suppresses_native_success(self):
        ticket = begin(self.slot)
        self.assertTrue(self.consumer.verify(ticket, source(1)))
        def fault(stage, event):
            if event == 'finish' and stage == 'after_commit': raise OSError('lost local commit reply')
        self.slot._store._fault = fault
        with self.assertRaises(CheckpointError): self.consumer.finish(ticket)
        self.assertTrue(self.consumer.costs[-1]['native_response']['ok'])
        self.assertFalse(self.consumer.costs[-1]['returned'])
        with self.assertRaises(ValueError): self.consumer.finish(ticket)
        self.assertEqual(len(self.port.calls), 2)

    def test_restart_never_loads_historical_native_candidate(self):
        floor = self.slot.checkpoint_anchor()
        self.slot.close()
        self.slot = DurableRuleSlot.reopen(RuleCheckpoint(Path(self.temp.name), anchor=floor), CONTEXT)
        with self.assertRaisesRegex(ValueError, 'fresh active'):
            NativeRuleSlotConsumer(self.slot, self.port)
        self.assertEqual(len(self.port.calls), 1)

    def test_late_receipt_after_concurrent_retirement_never_enters_native(self):
        started, release = threading.Event(), threading.Event()
        ticket = begin(self.slot)
        outcome = []
        def reveal(request):
            started.set()
            if not release.wait(5): raise TimeoutError('test rendezvous')
            return source(1)(request)
        thread = threading.Thread(target=lambda: outcome.append(self.consumer.verify(ticket, reveal)))
        thread.start()
        self.assertTrue(started.wait(5))
        self.slot.advance_generation(2)
        release.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [False])
        with self.assertRaises(ValueError): self.consumer.finish(ticket)
        self.assertEqual(len(self.port.calls), 1)
        self.assertEqual(sum(r['event'] == 'late_receipt' for r in self.slot.records()), 1)

    def test_two_simultaneous_finishes_enter_once(self):
        ticket = begin(self.slot)
        self.assertTrue(self.consumer.verify(ticket, source(1)))
        gate = threading.Barrier(3)
        successes, failures = [], []
        def run():
            gate.wait()
            try: successes.append(self.consumer.finish(ticket))
            except ValueError as error: failures.append(str(error))
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        gate.wait()
        for thread in threads: thread.join(5)
        self.assertEqual(successes, [(0, 2, 1)])
        self.assertEqual(len(failures), 1)
        self.assertEqual(len(self.port.calls), 2)


if __name__ == '__main__': unittest.main()
