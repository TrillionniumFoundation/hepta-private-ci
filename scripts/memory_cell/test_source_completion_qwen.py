"""Real randomly initialized Qwen2 + PEFT LoRA gradient parity (not task quality)."""

import copy
import unittest

import torch
from peft import LoraConfig, get_peft_model
from transformers import Qwen2Config, Qwen2ForCausalLM

from source_completion_loss import completion_loss


class QwenSourceCompletionTests(unittest.TestCase):
    def test_pinned_model_implementation_and_peft_adapter(self):
        config = Qwen2Config(
            vocab_size=257,
            hidden_size=64,
            intermediate_size=128,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=128,
            attention_dropout=0.0,
        )
        with torch.random.fork_rng():
            torch.manual_seed(4931)
            model = get_peft_model(
                Qwen2ForCausalLM(config),
                LoraConfig(
                    r=4,
                    lora_alpha=8,
                    lora_dropout=0.0,
                    target_modules=["q_proj", "v_proj"],
                    bias="none",
                    task_type="CAUSAL_LM",
                ),
            )
        model.eval()
        baseline = copy.deepcopy(model)
        ids = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]
        labels = [-100] * 8 + ids[8:]
        frozen = {
            name: p.detach().clone()
            for name, p in model.named_parameters()
            if not p.requires_grad
        }
        runs = []
        for current, backend in (
            (baseline, "full"),
            (model, "supervised_positions"),
        ):
            current.zero_grad(set_to_none=True)
            loss, receipt = completion_loss(current, ids, labels, backend=backend)
            loss.backward()
            grads = {
                name: p.grad.detach().clone()
                for name, p in current.named_parameters()
                if p.requires_grad
            }
            optimizer = torch.optim.AdamW(
                [p for p in current.parameters() if p.requires_grad], lr=2e-4
            )
            optimizer.step()
            updated = {
                name: p.detach().clone()
                for name, p in current.named_parameters()
                if p.requires_grad
            }
            runs.append((loss.detach(), grads, updated, receipt))
        full, sliced = runs
        torch.testing.assert_close(full[0], sliced[0], rtol=1e-4, atol=1e-4)
        self.assertEqual(set(full[1]), set(sliced[1]))
        for name in full[1]:
            torch.testing.assert_close(
                full[1][name], sliced[1][name], rtol=2e-3, atol=2e-4
            )
            torch.testing.assert_close(
                full[2][name], sliced[2][name], rtol=2e-3, atol=2e-4
            )
        current_parameters = dict(model.named_parameters())
        for name, value in frozen.items():
            self.assertTrue(torch.equal(current_parameters[name], value))
        self.assertEqual(full[3]["actual_projection_positions"], len(ids))
        self.assertEqual(sliced[3]["actual_projection_positions"], 4)
        self.assertEqual(full[3]["input_tokens"], sliced[3]["input_tokens"])


if __name__ == "__main__":
    unittest.main()
