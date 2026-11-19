"""Check matched controls, actual parameter learning and cost-curve selection."""

import importlib.util
import unittest

from ..ablation import cost_comparison


class CostCurveTests(unittest.TestCase):
    def test_budget_censoring_and_quality_use_only_available_validation(self):
        first = dict(step=20, wall_seconds=5.0, mse=0.8, best_mse=0.8)
        second = dict(step=40, wall_seconds=12.0, mse=0.6, best_mse=0.6)
        late = dict(step=45, wall_seconds=14.0, mse=0.1, best_mse=0.1, eligible=False)
        record = dict(validation_constant_mse=1.0, validation_curve=[first, second, late])
        result = cost_comparison(record, [1, 7, 15], [0.9, 0.75, 0.5])
        self.assertEqual([row["observation"] for row in result["same_wall_validation"]],
                         [None, first, second])
        self.assertEqual([row["first_observed"] for row in result["same_quality_validation"]],
                         [first, second, None])


@unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch not installed")
class MatchedCellTests(unittest.TestCase):
    def test_equal_parameters_shared_initialization_and_live_hx_gradients(self):
        import torch
        from ..baselines import make_encoder
        from ..cost_metrics import persistent_state, tensor_bytes

        torch.manual_seed(41)
        hx = make_encoder("hx_dual", 2, 8).double()
        torch.manual_seed(41)
        gate = make_encoder("matched_gate", 2, 8).double()
        self.assertEqual(sum(p.numel() for p in hx.parameters() if p.requires_grad),
                         sum(p.numel() for p in gate.parameters() if p.requires_grad))
        self.assertEqual(set(hx.state_dict()), set(gate.state_dict()))
        for name, value in hx.state_dict().items():
            torch.testing.assert_close(value, gate.state_dict()[name], rtol=0, atol=0)
        x = torch.randn(3, 4, 2, dtype=torch.float64)
        for cell in (hx, gate):
            before = cell.raw_financial.detach().clone()
            optimizer = torch.optim.Adam(cell.parameters(), lr=0.003)
            cell(x).square().mean().backward()
            self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all()
                                for p in cell.parameters() if p.requires_grad))
            self.assertGreater(float(cell.raw_financial.grad.norm()), 0)
            optimizer.step()
            self.assertFalse(torch.equal(before, cell.raw_financial))
            state = cell.initial_state(3, like=x)
            self.assertEqual(persistent_state(cell, x, torch)["bytes"], 2*3*8*8)
            self.assertEqual(tensor_bytes((state, state)), tensor_bytes(state))
        self.assertFalse(torch.allclose(hx(x), gate(x)))

    def test_real_fit_records_updates_state_optimizer_and_validation_time(self):
        import torch
        from ..benchmark import _run_one, make_dataset

        config = dict(hidden_size=8, dt=0.1, batch_size=4, train_steps=2,
                      learning_rate=0.003, validation_interval=1, length=4, latency_repeats=1)
        splits = []
        for seed in (40, 41, 42):
            splits.extend(make_dataset("adding", 8, 4, seed))
        record = _run_one(config, "adding", "matched_gate", 41, splits, torch.device("cpu"), torch)
        self.assertEqual(record["status"], "completed", record)
        self.assertEqual(record["training_steps_completed"], 2)
        self.assertEqual(record["persistent_state"]["bytes"], 2*4*8*4)
        self.assertGreater(record["optimizer_tensor_bytes"], 0)
        self.assertGreater(record["selected_parameter_delta_l2"]["encoder.raw_financial"], 0)
        self.assertEqual([point["step"] for point in record["validation_curve"]], [1, 2])
        self.assertLess(record["validation_curve"][0]["wall_seconds"],
                        record["validation_curve"][1]["wall_seconds"])


if __name__ == "__main__":
    unittest.main()
