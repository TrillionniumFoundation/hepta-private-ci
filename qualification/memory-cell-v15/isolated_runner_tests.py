"""Actual process tests; they establish isolation/failure behavior, not model gain."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest

from isolated_runner import run_arm


def cases(count=4):
    return json.dumps([dict(key=str(i), cluster=str(i), stratum='old', query=i,
                            payload=i, expected=True) for i in range(count)])


class IsolatedRunnerTests(unittest.TestCase):
    def run_model(self, predictor, factory=lambda: (lambda choice, payload: choice),
                  count=4, deadline=.5, **limits):
        return run_arm(cases(count), SimpleNamespace(predict=predictor), factory,
                       deadline, **limits)

    def test_distinct_closures_cannot_share_python_counter_between_arms(self):
        shared = {'calls': 0}

        def factory():
            def execute(choice, payload):
                shared['calls'] += 1
                return shared['calls'] <= 4
            return execute

        left, a = self.run_model(lambda _: True, factory)
        right, b = self.run_model(lambda _: True, factory)
        self.assertEqual([x['correct'] for x in left], [True]*4)
        self.assertEqual([x['correct'] for x in right], [True]*4)
        self.assertEqual(shared, {'calls': 0})
        self.assertNotEqual(a['worker_pid'], b['worker_pid'])
        self.assertEqual((a['status'], b['status']), ('completed', 'completed'))

    def test_same_executor_object_is_loaded_with_same_initial_state(self):
        class Executor:
            def __init__(self):
                self.calls = 0

            def __call__(self, choice, payload):
                self.calls += 1
                return self.calls <= 4

        executor = Executor()
        a, _ = self.run_model(lambda _: True, lambda: executor)
        b, _ = self.run_model(lambda _: True, lambda: executor)
        self.assertEqual([x['correct'] for x in a], [x['correct'] for x in b])
        self.assertEqual(executor.calls, 0)

    def test_relative_storage_is_private_per_arm(self):
        def execute(choice, payload):
            marker = Path('state.txt')
            value = int(marker.read_text()) if marker.exists() else 0
            marker.write_text(str(value+1))
            return value < 4

        a, _ = self.run_model(lambda _: True, lambda: execute)
        b, _ = self.run_model(lambda _: True, lambda: execute)
        self.assertEqual([x['correct'] for x in a], [True]*4)
        self.assertEqual([x['correct'] for x in b], [True]*4)

    def test_hung_predictor_terminates_and_keeps_full_denominator(self):
        def hang(_):
            time.sleep(100)

        before = time.monotonic()
        rows, receipt = self.run_model(hang, deadline=.05, wall_seconds=2.)
        self.assertLess(time.monotonic()-before, 3.)
        self.assertEqual(receipt['status'], 'deadline')
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(not row['correct'] and row['not_completed'] for row in rows))
        with self.assertRaises(ProcessLookupError):
            os.kill(receipt['worker_pid'], 0)

    def test_completed_prefix_survives_later_hang(self):
        def predictor(query):
            if query:
                time.sleep(100)
            return True

        rows, receipt = self.run_model(predictor, deadline=.05, wall_seconds=2.)
        self.assertEqual(receipt['status'], 'deadline')
        self.assertEqual([row['correct'] for row in rows], [True, False, False, False])

    def test_process_crash_and_exception_are_observed(self):
        def crash(_):
            os._exit(17)

        rows, receipt = self.run_model(crash)
        self.assertEqual((receipt['status'], receipt['exit_code']), ('worker_exit', 17))
        self.assertTrue(all(not row['correct'] for row in rows))

        def exception(_):
            raise ValueError('fixture')

        rows, receipt = self.run_model(exception)
        self.assertEqual(receipt['status'], 'completed')
        self.assertTrue(all(row['error']=='ValueError' and not row['correct'] for row in rows))

    def test_invalid_output_refuses_to_synthesize_success(self):
        def noisy(_):
            print('not-a-result', flush=True)
            return True

        rows, receipt = self.run_model(noisy)
        self.assertEqual(receipt['status'], 'protocol_error')
        self.assertTrue(all(not row['correct'] for row in rows))

    def test_memory_cap_and_measurements_are_real(self):
        def allocate(_):
            return bytearray(128*1024*1024) is None

        rows, receipt = self.run_model(allocate, address_space_bytes=64*1024*1024)
        self.assertEqual(receipt['status'], 'completed')
        self.assertTrue(all(row['error']=='MemoryError' for row in rows))
        self.assertGreater(receipt['cpu_seconds'], 0)
        self.assertGreater(receipt['peak_rss_bytes'], 0)
        self.assertGreater(receipt['output_bytes'], 0)
        self.assertFalse(receipt['external_state_isolated'])


if __name__ == '__main__':
    unittest.main()
