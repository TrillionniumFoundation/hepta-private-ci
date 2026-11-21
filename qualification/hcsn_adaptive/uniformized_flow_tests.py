"""Independent dense actions, full gradients, renewal and cold-state comparisons."""

import unittest

import torch

from .batched_flow import BatchedFlow, FlowConfig, FlowState
from .uniformized_flow import ActionBudget, UniformizedFlow


class UniformizedFlowTests(unittest.TestCase):
    def test_complete_flow_and_parameter_gradients(self):
        torch.manual_seed(8821)
        for mode, stages in (("absorbing", 3), ("reflecting", 3), ("reflecting", 1)):
            config = FlowConfig(input_size=2, content_size=2, bins=8, stages=stages, upper_mode=mode)
            dense, sparse = BatchedFlow(config), UniformizedFlow(config)
            sparse.load_state_dict(dense.state_dict())
            x = torch.randn(3, 4, 2, dtype=torch.float64) * .2
            objectives, states = [], []
            for model in (dense, sparse):
                state, outputs = None, []
                for i, inputs in enumerate(x):
                    output, state, _ = model.step(inputs, state, dt=.17, boundary_override=.07 * (i + 1))
                    outputs.append(output)
                values = torch.stack(outputs)
                objective = values.square().sum() + state.density.square().sum()
                objective.backward()
                objectives.append(values.detach())
                states.append(state)
            torch.testing.assert_close(objectives[0], objectives[1], rtol=1e-10, atol=2e-11)
            torch.testing.assert_close(states[0].density, states[1].density, rtol=1e-10, atol=2e-11)
            for (_, a), (_, b) in zip(dense.named_parameters(), sparse.named_parameters(), strict=True):
                torch.testing.assert_close(a.grad, b.grad, rtol=1e-8, atol=2e-10)
            self.assertLessEqual(sparse.last_action_report["integral_tail_bound"], 1e-14)
            # A detached full-state recovery must preserve ongoing phase/content dynamics.
            recovered = FlowState.from_record(states[1].to_record())
            a, sa, _ = sparse.step(x[0], states[1], dt=.071)
            b, sb, _ = sparse.step(x[0], recovered, dt=.071)
            torch.testing.assert_close(a, b, rtol=0, atol=0)
            torch.testing.assert_close(sa.density, sb.density, rtol=0, atol=0)

    def test_split_action_long_renewal_and_no_stale_parameters(self):
        config = FlowConfig(input_size=1, content_size=1, bins=12, stages=5, upper_mode="reflecting")
        dense, sparse = BatchedFlow(config), UniformizedFlow(config)
        sparse.load_state_dict(dense.state_dict())
        x = torch.full((2, 1), .4, dtype=torch.float64)
        a, sa, _ = dense.step(x, dt=1.7, drift_override=-1.5)
        b, sb, _ = sparse.step(x, dt=1.7, drift_override=-1.5)
        self.assertGreater(sparse.last_action_report["substeps"], 1)
        self.assertGreater(float(a[:, 0].min()), 1.)
        torch.testing.assert_close(a, b, rtol=1e-10, atol=2e-11)
        torch.testing.assert_close(sa.density, sb.density, rtol=1e-10, atol=2e-11)
        before = sparse.step(x)[0]
        with torch.no_grad():
            sparse.drive.weight.add_(.4)
            dense.load_state_dict(sparse.state_dict())
        after = sparse.step(x)[0]
        self.assertGreater(float((after-before).abs().max()), 1e-6)
        torch.testing.assert_close(after, dense.step(x)[0], rtol=1e-10, atol=2e-11)
        with self.assertRaises(ValueError):
            ActionBudget(max_substeps=1).plan(100., 1., 1.)


if __name__ == "__main__":
    torch.set_num_threads(1)
    unittest.main()
