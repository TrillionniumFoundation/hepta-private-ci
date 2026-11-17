"""Tiny real CPU LoRA continuity test; no task/generalization evidence."""

import copy
from pathlib import Path
import tempfile
import unittest

from .. import causal_probe_v3 as probe, causal_train_v3 as numeric
from .onpolicy_train import attach_adapter, checked_parameter_hash


class WarmStartTensorTests(unittest.TestCase):
    def test_actual_saved_adapter_loads_exact_previous_tensors_and_updates(self):
        import torch
        from transformers import Qwen2Config, Qwen2ForCausalLM

        torch.set_num_threads(1)
        torch.manual_seed(1729)
        base = Qwen2ForCausalLM(Qwen2Config(
            vocab_size=32, hidden_size=16, intermediate_size=32,
            num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2,
            max_position_embeddings=32, tie_word_embeddings=True))
        base.requires_grad_(False)
        initial_base = copy.deepcopy(base.state_dict())
        ids = torch.tensor([[1, 3, 5, 7, 9, 11]])
        labels = torch.tensor([[-100, -100, 5, 7, 9, 11]])
        mask = torch.ones_like(ids)
        with tempfile.TemporaryDirectory(prefix="hepta-onpolicy-tensor-") as tmp:
            root = Path(tmp)
            first = attach_adapter(base, {"schema": probe.SCHEMA}, root, trainable=True)
            first.train()
            parameters, before = checked_parameter_hash(first, torch, None)
            optimizer = torch.optim.AdamW([v for _, v in parameters], lr=0.01)
            for _ in range(2):
                optimizer.zero_grad(set_to_none=True)
                loss, selected = numeric.selected_token_loss(first, ids, mask, labels)
                self.assertEqual(selected, 4)
                loss.backward()
                optimizer.step()
            after = numeric._parameter_hash(parameters, torch)
            self.assertNotEqual(before, after)
            adapter = root / "first-adapter"
            first.save_pretrained(adapter, safe_serialization=True)
            second_base = Qwen2ForCausalLM(first.config)
            second_base.load_state_dict(initial_base)
            second_base.requires_grad_(False)
            second = attach_adapter(second_base, {
                "schema": "hepta.current-policy-sft-model.v1",
                "adapter_directory": "first-adapter"}, root, trainable=True)
            second_parameters, loaded = checked_parameter_hash(second, torch, after)
            self.assertEqual(loaded, after)
            with self.assertRaisesRegex(ValueError, "previous actual after hash"):
                checked_parameter_hash(second, torch, "0" * 64)
            fresh = torch.optim.AdamW([v for _, v in second_parameters], lr=0.01)
            self.assertEqual(len(fresh.state), 0)
            self.assertGreater(len(optimizer.state), 0)
            second.train()
            fresh.zero_grad(set_to_none=True)
            loss, selected = numeric.selected_token_loss(second, ids, mask, labels)
            self.assertEqual(selected, 4)
            loss.backward()
            fresh.step()
            self.assertNotEqual(numeric._parameter_hash(second_parameters, torch), after)


if __name__ == "__main__":
    unittest.main()
