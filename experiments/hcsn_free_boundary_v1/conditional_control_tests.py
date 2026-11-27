"""Validate only the new conditional-threshold arm and frozen-trainer integration."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch
from torch.nn import functional as F

from . import training
from .benchmark_models import build_model as original_build_model
from .conditional_control import build_model, run_conditional_search


class ConditionalControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_zero_slope_is_exact_original_direct_with_same_common_weights(self):
        direct = original_build_model("direct_dual", 5, 3, width=8, depth=2, seed=17)
        conditional = build_model("conditional_dual", 5, 3, width=8, depth=2, seed=17)
        for name, tensor in direct.state_dict().items():
            torch.testing.assert_close(conditional.state_dict()[name], tensor, rtol=0, atol=0)
        generator = torch.Generator().manual_seed(18)
        x = torch.randn(3, 7, 5, generator=generator)
        dt = torch.rand(3, 7, generator=generator) + 0.1
        first, aux_first = direct(x, dt, return_sequence=True)
        second, aux_second = conditional(x, dt, return_sequence=True)
        torch.testing.assert_close(first, second, rtol=0, atol=0)
        for key in ("boundary", "continuation", "intervention", "voltage", "refractory"):
            torch.testing.assert_close(aux_first[key], aux_second[key], rtol=0, atol=0)
        free = original_build_model("free_dual", 64, 8, width=32, seed=9101)
        extra = build_model("conditional_dual", 64, 8, width=32, seed=9101)
        self.assertEqual(extra.counts()["backbone"]-free.counts()["backbone"], 64)
        self.assertLess(64/free.counts()["backbone"], 0.01)
        for name in ("frontend", "readout"):
            for a, b in zip(getattr(free, name).parameters(), getattr(extra, name).parameters(), strict=True):
                torch.testing.assert_close(a, b, rtol=0, atol=0)

    def test_real_task_gradients_train_conditional_slopes_and_all_groups(self):
        model = build_model("conditional_dual", 3, 2, width=8, seed=41)
        generator = torch.Generator().manual_seed(42)
        x = torch.randn(8, 8, 3, generator=generator)
        dt = torch.full((8, 8), 0.4)
        target = (x[:, :3, 0].sum(1)>0).long()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.003)
        logits, _ = model(x, dt)
        F.cross_entropy(logits, target).backward()
        groups = training._gradient_summary(model)
        self.assertTrue(all(record["finite"] and record["l2"] > 0 for record in groups.values()), groups)
        self.assertGreater(groups["boundary_conditioning"]["l2"], 1e-10)
        optimizer.step()
        self.assertGreater(float(model.layers[0].raw_boundary_gap_slope.detach().abs().sum()), 0)
        encoded = model._encode(x, dt, dt.cumsum(1), None)
        _, local = model.layers[0].prepare(encoded)
        self.assertGreater(float(local["boundary"].std(1).max().detach()), 1e-7)
        model.layers[0].raw_boundary_gap_slope.data.fill_(0.7)
        _, local = model.layers[0].prepare(encoded)
        expected = local["K"] + F.softplus(model.layers[0].raw_boundary_gap
                                             + model.layers[0].raw_boundary_gap_slope*local["mu"])
        torch.testing.assert_close(local["boundary"], expected)

    def test_dynamic_threshold_reuses_own_policy_values_and_streaming(self):
        model = build_model("conditional_dual", 3, 2, width=6, seed=56)
        with torch.no_grad():
            model.layers[0].raw_boundary_gap_slope.fill_(0.6)
        x = torch.randn(2, 6, 3, generator=torch.Generator().manual_seed(57))
        dt = torch.full((2, 6), 0.3)
        batch, _ = model(x, dt, return_sequence=True)
        state, logits = None, []
        for i in range(6):
            output, state, _ = model.step(x[:, i], dt[:, i], state)
            logits.append(output)
        torch.testing.assert_close(torch.stack(logits, 1), batch, rtol=2e-5, atol=2e-6)
        cell = model.layers[0]
        encoded = model._encode(x[:, :1], dt[:, :1], dt[:, :1], None)
        signal, local = cell.prepare(encoded)
        local = {key: value[:, 0] if value.ndim == 3 else value for key, value in local.items()}
        start = cell.initial_state(2, x)
        start["voltage"] = local["boundary"]
        _, _, aux = cell.advance(encoded[:, 0], signal[:, 0], dt[:, :1], start, local)
        torch.testing.assert_close(aux["continuation"], aux["intervention"], rtol=1e-6, atol=1e-6)

    def test_tiny_frozen_search_selection_replay_and_factory_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            rng = np.random.default_rng(63)
            arrays = {}
            for split, count in (("train", 16), ("val", 8), ("test", 8)):
                x = rng.normal(size=(count, 4, 3)).astype(np.float32)
                y = np.full((count, 4), -100, np.int64)
                y[:, -1] = (x[:, 0, 0]>0)
                arrays.update({f"{split}_x": x, f"{split}_dt": np.full((count, 4), .4, np.float32),
                               f"{split}_y": y})
            data = directory / "tiny.npz"
            np.savez_compressed(data, **arrays)
            before = training.build_model
            result = run_conditional_search(data, 65, directory / "search", cpu_seconds=.03,
                                             width=4, batch_size=4, max_updates=2)
            self.assertIs(training.build_model, before)
            self.assertEqual(result["selection"]["completed_lr_candidates"], 2)
            events = result["access_log"]
            lock = next(i for i, entry in enumerate(events) if entry["event"] == "selection_locked")
            self.assertTrue(all(i>lock for i, entry in enumerate(events)
                                if entry.get("split") in ("test", "ood")))
            model = build_model("conditional_dual", 3, 2, width=4, seed=65)
            training.load_weights(directory / "search" / "selected.npz", model)
            x = torch.from_numpy(arrays["test_x"])
            dt = torch.from_numpy(arrays["test_dt"])
            actual, _ = model(x, dt, return_sequence=True)
            with np.load(directory / "search" / "test_predictions.npz", allow_pickle=False) as replay:
                np.testing.assert_allclose(actual[:, -1].detach().numpy(), replay["logits"], rtol=0, atol=0)
            for candidate in result["candidates"]:
                self.assertGreater(candidate["final_parameter_changes"]["boundary_conditioning"]["l2"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
