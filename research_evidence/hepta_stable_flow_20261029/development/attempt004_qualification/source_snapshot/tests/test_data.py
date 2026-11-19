"""Nonleakage, overwrite timing, parameter parity and prefix-causal reads."""

import unittest

import numpy as np
import torch

from experiments.call_put_stable_flow.data import (
    KEY_QUERY, WRITE_VALUE, TaskConfig, generate, oracle_targets,
)
from experiments.call_put_stable_flow.models import ARMS, build_model


class CausalDataTests(unittest.TestCase):
    def test_independent_oracle_and_query_value_absence(self):
        config = TaskConfig()
        for task in ("selective_copy", "mqar"):
            data = generate(task, 25, 71)
            np.testing.assert_array_equal(data["targets"], oracle_targets(data["inputs"], config))
            mask = data["targets"] != -100
            self.assertTrue(np.all(data["inputs"][..., config.value_start:config.select_index][mask] == 0))
            self.assertTrue(np.all(mask.sum(axis=1) == 4))

    def test_future_overwrite_does_not_change_early_answer(self):
        config = TaskConfig()
        data = generate("mqar", 1, 73)
        inputs = data["inputs"].copy()
        queries = np.flatnonzero(inputs[0, :, KEY_QUERY])
        old = oracle_targets(inputs, config)
        writes = np.flatnonzero(inputs[0, :, WRITE_VALUE])
        changed = writes[writes > queries[1]][0]
        original = inputs[0, changed, config.value_start:config.select_index].argmax()
        inputs[0, changed, config.value_start:config.select_index] = 0
        inputs[0, changed, config.value_start + (original + 1) % config.value_vocab] = 1
        new = oracle_targets(inputs, config)
        np.testing.assert_array_equal(old[:, :queries[1] + 1], new[:, :queries[1] + 1])
        self.assertTrue(np.any(old[:, queries[2]:] != new[:, queries[2]:]))

    def test_all_arms_same_initial_parameters_and_state_accounting(self):
        models = [build_model(arm, 81) for arm in ARMS]
        reference = models[0].state_dict()
        for model in models[1:]:
            self.assertEqual(reference.keys(), model.state_dict().keys())
            for name, value in model.state_dict().items():
                torch.testing.assert_close(value, reference[name], rtol=0, atol=0)
            self.assertEqual(model.accounting()["persistent_float_state_per_episode"],
                             models[0].accounting()["persistent_float_state_per_episode"])
        counts = [model.accounting()["parameters_trainable"] for model in models]
        self.assertEqual(len(set(counts[:-1])), 1)
        self.assertLess(counts[-1], counts[0])

    def test_prefix_predictions_independent_of_future_inputs(self):
        torch.set_num_threads(1)
        data = generate("mqar", 1, 89)
        x = torch.from_numpy(data["inputs"])
        cutoff = int(np.flatnonzero(data["inputs"][0, :, KEY_QUERY])[1]) + 1
        modified = x.clone()
        modified[:, cutoff:] = torch.flip(modified[:, cutoff:], dims=[1])
        model = build_model("analytic", 97).eval()
        with torch.no_grad():
            full = model(x)
            prefix = model(x[:, :cutoff])
            altered = model(modified)
        torch.testing.assert_close(full[:, :cutoff], prefix, rtol=0, atol=0)
        torch.testing.assert_close(full[:, :cutoff], altered[:, :cutoff], rtol=0, atol=0)

    def test_readout_zero_memory_has_no_content_answer_path(self):
        model = build_model("analytic", 101)
        data = generate("mqar", 2, 103)
        with torch.no_grad():
            model.value_projection.weight.zero_()
            logits, diagnostics = model(torch.from_numpy(data["inputs"]), return_diagnostics=True)
        torch.testing.assert_close(diagnostics["final_memory"], torch.zeros_like(diagnostics["final_memory"]), rtol=0, atol=0)
        torch.testing.assert_close(logits, model.readout.bias.expand_as(logits), rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
