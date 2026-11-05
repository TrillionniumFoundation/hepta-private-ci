"""Independent failure probes for the trusted isolated evaluator.

Run from this directory with the actual qualification directory and python-deps
on PYTHONPATH. These probes do not change the production implementation. Every
probe cleans any process that it launches, including the cancellation counterexample.
"""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import isolated_runner as runner
import runner_review_fixture


def wire():
    return json.dumps([dict(key='one', cluster='one', stratum='old', query='q',
                            payload='p', expected=True)])


def run(predict, **limits):
    return runner.run_arm(wire(), SimpleNamespace(predict=predict),
                          lambda: (lambda choice, payload: choice), 5., **limits)


class IndependentRunnerReview(unittest.TestCase):
    def test_arm_cpu_cap_includes_joined_children(self):
        def child_work(_):
            code = ('import time\nstart=time.process_time()\n'
                    'while time.process_time()-start < 0.65:\n    pass\n')
            for _ in range(2):
                subprocess.run([sys.executable, '-c', code], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

        rows, receipt = run(child_work, cpu_seconds=1, wall_seconds=5.)
        print('joined_children', json.dumps(dict(rows=rows, receipt=receipt)), flush=True)
        self.assertTrue(receipt['status'] != 'completed' or receipt['cpu_seconds'] <= 1,
                        'An arm exceeded its declared CPU cap using ordinary joined children.')

    def test_frozen_host_module_configuration_is_preserved(self):
        old_mode = runner_review_fixture.MODE
        try:
            runner_review_fixture.MODE = 'configured-before-freeze'
            self.assertTrue(runner_review_fixture.predict('q'))
            rows, receipt = run(runner_review_fixture.predict)
            print('module_configuration', json.dumps(dict(rows=rows, receipt=receipt)), flush=True)
            self.assertEqual((receipt['status'], rows[0]['correct']), ('completed', True),
                             'Cloudpickle re-imported module defaults instead of frozen host state.')
        finally:
            runner_review_fixture.MODE = old_mode

    def test_process_start_failure_retains_denominator(self):
        with patch.object(runner.subprocess, 'Popen', side_effect=OSError(11, 'Resource temporarily unavailable')):
            rows, receipt = run(lambda _: True)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['correct'])
        self.assertNotEqual(receipt['status'], 'completed')

    def test_cancel_after_launch_cleans_owned_group(self):
        created = []
        original_popen = subprocess.Popen
        original_clock = time.perf_counter
        clock_calls = 0

        def capture_launch(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            created.append(child)
            return child

        def interrupt_setup():
            nonlocal clock_calls
            clock_calls += 1
            if clock_calls == 2:
                # The second call occurs after Popen and before the current try/finally.
                # Allow the owned worker to load its private snapshot first.
                time.sleep(.2)
                raise KeyboardInterrupt('cancel at post-launch setup boundary')
            return original_clock()

        def hang(_):
            time.sleep(30)
            return True

        try:
            with patch.object(runner.subprocess, 'Popen', capture_launch), \
                    patch.object(runner.time, 'perf_counter', interrupt_setup):
                with self.assertRaises(KeyboardInterrupt):
                    run(hang, wall_seconds=6.)
            self.assertEqual(len(created), 1)
            alive = created[0].poll() is None
            print('cancellation_boundary', json.dumps(dict(worker_pid=created[0].pid,
                                                           alive_after_cancel=alive)), flush=True)
            self.assertFalse(alive, 'Worker survived cancellation before entering cleanup try/finally.')
        finally:
            for child in created:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=3.)


if __name__ == '__main__':
    print('runner_sha256', hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(), flush=True)
    unittest.main(verbosity=2)
