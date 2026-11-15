"""Finite differences of the resumed task, independent of the SGD oracle.

The numerical oracle perturbs every scalar parameter and evaluates only losses;
it does not use the worker's gradient routine or replay its update formula.
These are bounded CPU engineering tests, not task-quality experiments.
"""

import hashlib
import itertools
from pathlib import Path
import tempfile
import unittest

import torch
from .joint_graph import load_training_checkpoint, tensor_digest
from .test_joint_graph import fixture as value_fixture
from .test_population_graph import fixture as population_fixture
from .test_population_age_graph import fixture as age_fixture
from .test_training_state import bind_initialization
from .training_state import resolve_training_initialization, state_digest
from .worker import propose, task_gradients


class ResumedDerivativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def check_resumed_derivatives(self, factory):
        with tempfile.TemporaryDirectory() as directory:
            model, request, inputs, targets, intervals = factory(directory)
            payload, _ = propose(model, request)
            checkpoint = Path(directory)/"candidate.pt"
            checkpoint.write_bytes(payload)
            identity = hashlib.sha256(payload).hexdigest()
            model, saved, metadata = load_training_checkpoint(checkpoint, identity)
            offset = metadata["last_end_micros"]-request["intervals"][0]["start_micros"]
            for plan in request["intervals"]:
                plan["start_micros"] += offset
                plan["end_micros"] += offset
            request["target_time_micros"] += offset
            request["binding"]["model_digest"] = identity
            request["base_checkpoint"] = dict(path=str(checkpoint), sha256=identity)
            bind_initialization(request, saved, "resume")
            initial = resolve_training_initialization(model, request, saved, metadata, inputs)
            before_state, before_weights = state_digest(initial), tensor_digest(model.state_dict())
            loss, gradients = task_gradients(model, inputs, targets, intervals, initial)
            with torch.no_grad():
                reset = (model(inputs, intervals)[0][:, -1]-targets).square().mean()
            self.assertGreater(abs(float(loss.detach()-reset)), 1e-8,
                               "fixture must distinguish resumed state from zero state")
            epsilon = 1e-5
            connected_cells = set()
            for name, parameter in model.named_parameters():
                for index in itertools.product(*(range(size) for size in parameter.shape)):
                    original = float(parameter[index].detach())
                    losses = []
                    try:
                        with torch.no_grad():
                            for direction in (-1, 1):
                                parameter[index] = original+direction*epsilon
                                prediction, _ = model(inputs, intervals, initial)
                                losses.append(float((prediction[:, -1]-targets).square().mean()))
                    finally:
                        with torch.no_grad():
                            parameter[index] = original
                    numerical = (losses[1]-losses[0])/(2*epsilon)
                    analytic = float(gradients[name][index])
                    self.assertAlmostEqual(analytic, numerical,
                        delta=1e-8+abs(numerical)*4e-4, msg=f"{name}{index}")
                    if name.startswith("cells.") and abs(analytic) > 1e-9:
                        connected_cells.add(int(name.split(".")[1]))
            self.assertEqual(connected_cells, set(range(len(model.cells))))
            self.assertEqual(state_digest(initial), before_state)
            self.assertEqual(tensor_digest(model.state_dict()), before_weights)
            self.assertEqual(checkpoint.read_bytes(), payload)

    def test_resumed_value_graph_all_scalar_parameter_derivatives(self):
        self.check_resumed_derivatives(value_fixture)

    def test_resumed_population_graph_all_scalar_parameter_derivatives(self):
        self.check_resumed_derivatives(population_fixture)

    def test_resumed_variable_time_graph_all_scalar_parameter_derivatives(self):
        self.check_resumed_derivatives(age_fixture)


if __name__ == "__main__":
    unittest.main()
