"""Real tiny Qwen2/PEFT paired-margin parity, not pretrained knowledge quality.

This test uses the pinned library's actual transformer and PEFT forward paths,
with randomly initialized weights. It does not read benchmark tasks, model
publisher weights, source gold labels or independent reviewer decisions.
"""

from copy import deepcopy
import unittest

import peft
import torch
import transformers
from peft import LoraConfig, get_peft_model
from transformers import Qwen2Config, Qwen2ForCausalLM

from source_binding_margin import binding_margin_loss


class LiteralTokenizer:
    eos_token_id = 1

    def encode(self, text, add_special_tokens=False):
        if add_special_tokens or text not in ("A", "B"):
            raise ValueError("test accepts only the two fixed source values")
        return [ord(text)]


class PairedMarginQwenTests(unittest.TestCase):
    def test_pinned_qwen_peft_margin_gradients_and_updates_match(self):
        self.assertEqual(transformers.__version__, "4.57.1")
        self.assertEqual(peft.__version__, "0.17.1")
        for dtype, atol in ((torch.float32, 2e-6), (torch.bfloat16, 4e-3)):
            with self.subTest(dtype=dtype), torch.random.fork_rng():
                torch.manual_seed(4112)
                config = Qwen2Config(
                    vocab_size=97,
                    hidden_size=32,
                    intermediate_size=64,
                    num_hidden_layers=2,
                    num_attention_heads=4,
                    num_key_value_heads=2,
                    max_position_embeddings=128,
                    attention_dropout=0.0,
                )
                config._attn_implementation = "eager"
                base = get_peft_model(
                    Qwen2ForCausalLM(config).to(dtype=dtype),
                    LoraConfig(
                        r=4,
                        lora_alpha=8,
                        lora_dropout=0.0,
                        target_modules=["q_proj", "v_proj"],
                        bias="none",
                        task_type="CAUSAL_LM",
                    ),
                )
                models = (base, deepcopy(base))
                initial = {
                    name: parameter.detach().clone()
                    for name, parameter in base.named_parameters()
                }
                optimizers = [
                    torch.optim.AdamW(
                        [p for p in model.parameters() if p.requires_grad],
                        lr=0.0002,
                    )
                    for model in models
                ]
                for step in range(3):
                    prompt = [2, 3, 4, 5, 6, 7 + step]
                    target, negative = ("A", "B") if step % 2 == 0 else ("B", "A")
                    losses, receipts, gradients = [], [], []
                    for backend, model, optimizer in zip(
                        ("full", "supervised_positions"),
                        models,
                        optimizers,
                        strict=True,
                    ):
                        optimizer.zero_grad(set_to_none=True)
                        loss, receipt = binding_margin_loss(
                            model,
                            LiteralTokenizer(),
                            prompt,
                            target,
                            negative,
                            backend=backend,
                        )
                        loss.backward()
                        losses.append(loss.detach())
                        receipts.append(receipt)
                        gradients.append(
                            {
                                name: p.grad.detach().clone()
                                for name, p in model.named_parameters()
                                if p.requires_grad
                            }
                        )
                    torch.testing.assert_close(losses[0], losses[1], rtol=0, atol=atol)
                    self.assertEqual(
                        receipts[0]["actual_input_tokens"],
                        receipts[1]["actual_input_tokens"],
                    )
                    self.assertEqual(
                        receipts[0]["actual_supervised_tokens"],
                        receipts[1]["actual_supervised_tokens"],
                    )
                    self.assertEqual(
                        receipts[0]["actual_model_forwards"],
                        receipts[1]["actual_model_forwards"],
                    )
                    self.assertEqual(receipts[0]["actual_model_forwards"], 2)
                    self.assertEqual(receipts[0]["actual_projection_positions"], 16)
                    self.assertEqual(receipts[1]["actual_projection_positions"], 4)
                    for name in gradients[0]:
                        torch.testing.assert_close(
                            gradients[0][name],
                            gradients[1][name],
                            rtol=0.02 if dtype == torch.bfloat16 else 1e-4,
                            atol=atol,
                        )
                    for model, optimizer in zip(models, optimizers, strict=True):
                        torch.nn.utils.clip_grad_norm_(
                            [p for p in model.parameters() if p.requires_grad],
                            1.0,
                            error_if_nonfinite=True,
                        )
                        optimizer.step()
                    for (name, a), (_, b) in zip(
                        models[0].named_parameters(),
                        models[1].named_parameters(),
                        strict=True,
                    ):
                        if a.requires_grad:
                            torch.testing.assert_close(a, b, rtol=0.02, atol=atol)
                        else:
                            self.assertTrue(torch.equal(a, initial[name]))
                            self.assertTrue(torch.equal(b, initial[name]))
                self.assertTrue(
                    any(
                        not torch.equal(p, initial[name])
                        for name, p in models[1].named_parameters()
                        if p.requires_grad
                    )
                )

    def test_pair_fails_closed_before_any_model_forward(self):
        config = Qwen2Config(
            vocab_size=97,
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=4,
            num_key_value_heads=2,
        )
        config._attn_implementation = "eager"
        model = Qwen2ForCausalLM(config)
        with self.assertRaises(ValueError):
            binding_margin_loss(
                model,
                LiteralTokenizer(),
                [2, 3],
                "A",
                "A",
                backend="supervised_positions",
            )
        with self.assertRaises(ValueError):
            binding_margin_loss(
                model,
                LiteralTokenizer(),
                [2, 3],
                "A",
                "B",
                backend="unknown_backend",
            )


if __name__ == "__main__":
    unittest.main()
