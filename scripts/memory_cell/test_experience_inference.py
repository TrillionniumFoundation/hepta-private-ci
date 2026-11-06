"""Real PEFT control-state regressions on a random tiny model, not a benchmark."""

import unittest

import torch
from peft import LoraConfig, get_peft_model
from transformers import LlamaConfig, LlamaForCausalLM

from experience_inference import frozen_adapter_mode


def tiny_model():
    with torch.random.fork_rng():
        torch.manual_seed(9)
        base = LlamaForCausalLM(
            LlamaConfig(
                vocab_size=32,
                hidden_size=16,
                intermediate_size=32,
                num_hidden_layers=1,
                num_attention_heads=2,
                num_key_value_heads=2,
            )
        )
        model = get_peft_model(
            base,
            LoraConfig(
                r=2,
                lora_alpha=4,
                target_modules=["q_proj", "v_proj"],
                task_type="CAUSAL_LM",
            ),
        ).eval()
    model.requires_grad_(False)
    return model


class FrozenAdapterTests(unittest.TestCase):
    def test_pinned_library_reenables_flags_without_changing_values(self):
        model = tiny_model()
        before = {k: v.clone() for k, v in model.state_dict().items()}
        with model.disable_adapter():
            self.assertFalse(any(p.requires_grad for p in model.parameters()))
        self.assertTrue(any(p.requires_grad for p in model.parameters()))
        self.assertTrue(
            all(torch.equal(v, before[k]) for k, v in model.state_dict().items())
        )

    def test_actual_forwards_preserve_values_flags_and_baseline_output(self):
        model = tiny_model()
        before = {k: v.clone() for k, v in model.state_dict().items()}
        values = []
        for enabled in (False, True, False):
            with frozen_adapter_mode(model, enabled=enabled):
                result = model(input_ids=torch.tensor([[1, 2, 3]]))
                values.append(result.logits.clone())
                self.assertFalse(result.logits.requires_grad)
            self.assertFalse(any(p.requires_grad for p in model.parameters()))
            self.assertTrue(
                all(torch.equal(v, before[k]) for k, v in model.state_dict().items())
            )
        self.assertTrue(torch.equal(values[0], values[2]))

    def test_exception_restores_flags_but_is_not_swallowed(self):
        model = tiny_model()
        with self.assertRaisesRegex(RuntimeError, "deliberate failure"):
            with frozen_adapter_mode(model, enabled=False):
                raise RuntimeError("deliberate failure")
        self.assertFalse(any(p.requires_grad for p in model.parameters()))

    def test_changed_weights_and_trainable_entry_are_rejected(self):
        for enabled in (False, True):
            model = tiny_model()
            with self.assertRaises(ValueError):
                with frozen_adapter_mode(model, enabled=enabled):
                    parameter = next(
                        p for k, p in model.named_parameters() if "lora_" in k
                    )
                    parameter.add_(1)
        model = tiny_model()
        next(model.parameters()).requires_grad_(True)
        with self.assertRaises(ValueError):
            with frozen_adapter_mode(model, enabled=False):
                self.fail("trainable model was admitted")


if __name__ == "__main__":
    unittest.main()
