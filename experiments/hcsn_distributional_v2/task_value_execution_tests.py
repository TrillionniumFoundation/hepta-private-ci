"""Task accounting and restart serialization checks independent of native I/O."""

from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from .task_value import ObservationModel
from .task_value_common import (PACKAGE, REPOSITORY, save_state, load_state, state_identity,
                                write_json, verify_registration)
from .task_value_heads import Policy, cached_rollouts, make_solutions


def fixture_law():
    reward = np.full((33, 4), .7)
    transition = np.full((33, 4, 4), .25)
    valid = np.ones((33, 4), dtype=bool)
    valid[0] = False
    return ObservationModel(reward, transition, np.full(4, .25), valid)


class ExecutionContractTests(unittest.TestCase):
    def exercise_registration(self, absolute):
        from .task_value_run import register
        (PACKAGE / 'results').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=PACKAGE / 'results') as temporary:
            output = Path(temporary)
            (output / 'data').mkdir()
            write_json(output / 'PROTOCOL.json', {'prior_attempts': []})
            (output / 'data/fresh_mnist.npz').write_bytes(b'path-registration-fixture-only')
            write_json(output / 'data/fresh_mnist.json', {'scope': 'registration fixture, not data inference'})
            argument = output if absolute else output.relative_to(REPOSITORY)
            register(argument)
            identity = verify_registration(argument)
            self.assertTrue(identity['files'])
            self.assertTrue((output / 'REGISTERED_SOURCE.json').is_file())
            self.assertEqual(identity['files'][str((output / 'data/fresh_mnist.npz').relative_to(REPOSITORY))],
                             __import__('hashlib').sha256(b'path-registration-fixture-only').hexdigest())

    def test_absolute_output_registration(self):
        self.exercise_registration(True)

    def test_relative_output_registration(self):
        self.exercise_registration(False)

    def test_repeated_tasks_score_actual_future_and_all_reads(self):
        solutions = make_solutions(fixture_law(), [.001])
        edges = np.tile([.3, .6, .9], (33, 1))
        policy = Policy('validation_schedule', solutions, edges,
                        settings={'.001': {'prefix': 2, 'balanced': False},
                                  '0.001': {'prefix': 2, 'balanced': False}})
        trace = {'confidence': np.full((6, 32), .8),
                 'prediction': np.zeros((6, 32), dtype=np.int64),
                 'labels': np.array([0, 1, 0, 1, 0, 1])}
        result = cached_rollouts(policy, trace, .001, 73012)
        np.testing.assert_array_equal(result['task_reads'], np.full((2, 3), 2))
        np.testing.assert_array_equal(result['fire_clock'], np.tile([2, 6, 10], (2, 1)))
        np.testing.assert_allclose(result['utility'], result['task_correct'].sum(1) - .006)
        self.assertEqual(int(result['task_correct'].sum()), 3)
        changed = dict(trace, labels=1 - trace['labels'])
        other = cached_rollouts(policy, changed, .001, 73012)
        np.testing.assert_array_equal(result['task_reads'], other['task_reads'])
        np.testing.assert_array_equal(result['task_predictions'], other['task_predictions'])
        np.testing.assert_array_equal(result['task_correct'] + other['task_correct'], np.ones((2, 3)))

    def test_generic_distributional_state_roundtrip(self):
        state = {'elapsed': torch.tensor([7.]), 'layers': [{
            'content': torch.arange(32, dtype=torch.float32)[None],
            'probability': torch.arange(80, dtype=torch.float64).reshape(1, 8, 10) / 100,
            'old_boundary': torch.linspace(.5, 2., 8)[None]}]}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'state.npz'
            save_state(path, state)
            restored = load_state(path)
            self.assertEqual(state_identity(state), state_identity(restored))
            restored['layers'][0]['probability'][0, 0, 0] += 1
            self.assertNotEqual(state_identity(state), state_identity(restored))


if __name__ == '__main__':
    unittest.main()
