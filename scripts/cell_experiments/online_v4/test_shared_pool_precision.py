"""Real CPU BF16/F32 loading regression; these fixtures are not trained Cells."""

import copy
from pathlib import Path
import tempfile
import unittest

from .. import causal_probe_v3 as probe, causal_train_v3 as numeric, data
from .onpolicy_train import attach_adapter
from .shared_pool_v4 import SharedAdapterPool, adapter_parameters


class SharedPoolPrecisionTests(unittest.TestCase):
    def test_bfloat16_base_keeps_all_float32_adapters_exact_and_rejects_tampering(self):
        import torch
        from transformers import Qwen2Config, Qwen2ForCausalLM

        torch.set_num_threads(1)
        torch.manual_seed(1729)
        config = Qwen2Config(
            vocab_size=32,
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=2,
            max_position_embeddings=64,
            tie_word_embeddings=True,
            bos_token_id=1,
            eos_token_id=2,
            pad_token_id=0,
        )
        template = Qwen2ForCausalLM(config).to(dtype=torch.bfloat16)
        initial = copy.deepcopy(template.state_dict())
        del template
        with tempfile.TemporaryDirectory(prefix="hepta-pool-precision-cpu-") as tmp:
            root = Path(tmp)
            entries, saved = {}, {}
            for index, cell in enumerate(("C", "F", "T")):
                base = Qwen2ForCausalLM(config).to(dtype=torch.bfloat16)
                base.load_state_dict(initial)
                base.requires_grad_(False)
                model = attach_adapter(
                    base, {"schema": probe.SCHEMA}, root, trainable=True
                )
                parameters = adapter_parameters(model, "default")
                with torch.no_grad():
                    for offset, (_, value) in enumerate(parameters):
                        self.assertEqual(value.dtype, torch.float32)
                        value.copy_(
                            torch.arange(value.numel(), dtype=torch.float32).reshape(
                                value.shape
                            )
                            / 10007
                            + (index + 1) / 37
                            + offset / 101
                        )
                        self.assertFalse(torch.equal(value, value.bfloat16().float()))
                saved[cell] = [
                    (name, value.detach().clone()) for name, value in parameters
                ]
                after = numeric._parameter_hash(parameters, torch)
                directory = root / ("adapter-" + cell)
                model.save_pretrained(directory, safe_serialization=True)
                manifest = {
                    "schema": "tiny.cpu.precision.fixture.v1",
                    "adapter_directory": directory.name,
                    "engineering_only": True,
                }
                entries[cell] = {
                    "manifest": manifest,
                    "model_digest": data.digest(manifest),
                    "adapter_label": "cell_" + str(index),
                    "training": {
                        "parameter_after": after,
                        "trainable_parameters": sum(p.numel() for _, p in parameters),
                    },
                }
                del parameters, model, base
            view = probe.Predictor.__new__(probe.Predictor)
            view.model = Qwen2ForCausalLM(config).to(dtype=torch.bfloat16)
            view.model.load_state_dict(initial)
            view.model.requires_grad_(False)
            base_object = view.model
            base_parameters = [
                (value, value.detach().clone()) for value in view.model.parameters()
            ]
            view.torch, view.tokenizer, view.closed = torch, None, False
            view.generation_digest = data.digest({"fixture": "no_generation"})
            pool = SharedAdapterPool.__new__(SharedAdapterPool)
            try:
                pool._install(view, entries, root, {"engineering_only": True})
                logits = []
                for cell in ("C", "F", "T", "C"):
                    entry = entries[cell]
                    actual, count = pool._activate(entry)
                    self.assertEqual(actual, entry["training"]["parameter_after"])
                    self.assertEqual(count, entry["training"]["trainable_parameters"])
                    loaded = adapter_parameters(view.model, entry["adapter_label"])
                    self.assertEqual(
                        [n for n, _ in loaded], [n for n, _ in saved[cell]]
                    )
                    for (_, value), (_, original) in zip(
                        loaded, saved[cell], strict=True
                    ):
                        self.assertEqual(value.dtype, torch.float32)
                        self.assertTrue(
                            torch.equal(
                                value.view(torch.uint8), original.view(torch.uint8)
                            )
                        )
                    self.assertIs(view.model.get_base_model(), base_object)
                    self.assertFalse(
                        any(p.requires_grad for p in view.model.parameters())
                    )
                    for value, original in base_parameters:
                        self.assertEqual(value.dtype, torch.bfloat16)
                        self.assertTrue(torch.equal(value, original))
                    with torch.inference_mode():
                        logits.append(
                            view.model(torch.tensor([[3, 4, 5]])).logits.clone()
                        )
                self.assertTrue(torch.equal(logits[0], logits[3]))
                self.assertFalse(torch.equal(logits[0], logits[1]))
                self.assertFalse(torch.equal(logits[1], logits[2]))

                # Each mutation preserves the other properties, exercising the complete hash gate.
                entry = entries["F"]
                value = adapter_parameters(view.model, entry["adapter_label"])[0][1]
                original = value.detach().clone()
                with torch.no_grad():
                    value.view(torch.int32).reshape(-1)[0].bitwise_xor_(1)
                with self.assertRaisesRegex(ValueError, "actual training after hash"):
                    pool._activate(entry)
                with torch.no_grad():
                    value.copy_(original)
                value.data = value.data.to(torch.float64)
                with self.assertRaisesRegex(ValueError, "actual training after hash"):
                    pool._activate(entry)
                value.data = original.clone()

                layer = base_object.model.layers[0].self_attn.q_proj
                selected = layer.lora_A[entry["adapter_label"]]
                original_names = selected._parameters.copy()
                selected._parameters["renamed_weight"] = selected._parameters.pop(
                    "weight"
                )
                with self.assertRaisesRegex(ValueError, "actual training after hash"):
                    pool._activate(entry)
                selected._parameters = original_names
                original_order = layer._modules.copy()
                layer._modules = dict(reversed(tuple(layer._modules.items())))
                with self.assertRaisesRegex(ValueError, "actual training after hash"):
                    pool._activate(entry)
                layer._modules = original_order
                altered_count = copy.deepcopy(entry)
                altered_count["training"]["trainable_parameters"] += 1
                with self.assertRaisesRegex(ValueError, "active adapter count differs"):
                    pool._activate(altered_count)
                self.assertEqual(
                    pool._activate(entry)[0], entry["training"]["parameter_after"]
                )
            finally:
                pool.close()
            self.assertIsNone(view.model)


if __name__ == "__main__":
    unittest.main()
