"""Required pinned-library conformance; tiny random Qwen2 is NOT task evidence.

Missing dependencies fail this module, rather than silently skip verification.
The opt-in backend must not be adopted on the strength of fixture tests alone.
"""

from copy import deepcopy
import unittest

import peft
import torch
import transformers
from peft import LoraConfig, get_peft_model
from transformers import Qwen2Config, Qwen2ForCausalLM

from source_completion_loss import completion_loss


class QwenCompletionTests(unittest.TestCase):
    def test_actual_qwen_peft_loss_gradients_and_optimizer_updates(self):
        self.assertEqual(transformers.__version__, "4.57.1")
        self.assertEqual(peft.__version__, "0.17.1")
        for dtype, tolerance in ((torch.float32, 2e-6), (torch.bfloat16, 2e-3)):
            with self.subTest(dtype=dtype), torch.random.fork_rng():
                torch.manual_seed(2718)
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
                full = get_peft_model(
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
                sliced = deepcopy(full)
                models = (full, sliced)
                initial = {n: p.detach().clone() for n, p in full.named_parameters()}
                optimizers = [
                    torch.optim.AdamW(
                        [p for p in m.parameters() if p.requires_grad], lr=0.0002
                    )
                    for m in models
                ]
                for step in range(3):
                    ids = [(i * 7 + step) % 97 for i in range(31)]
                    labels = [-100] * 25 + ids[25:]
                    losses = []
                    for backend, model, optimizer in zip(
                        ("full", "supervised_positions"), models, optimizers
                    ):
                        optimizer.zero_grad(set_to_none=True)
                        loss, receipt = completion_loss(
                            model, ids, labels, backend=backend
                        )
                        self.assertEqual(receipt["input_tokens"], 31)
                        self.assertEqual(receipt["supervised_tokens"], 6)
                        loss.backward()
                        losses.append(loss.detach())
                    torch.testing.assert_close(
                        losses[0], losses[1], rtol=0, atol=tolerance
                    )
                    for (name, a), (_, b) in zip(
                        full.named_parameters(), sliced.named_parameters()
                    ):
                        if a.requires_grad:
                            torch.testing.assert_close(
                                a.grad, b.grad, rtol=tolerance, atol=tolerance
                            )
                        else:
                            self.assertIsNone(a.grad)
                            self.assertIsNone(b.grad)
                    for model, optimizer in zip(models, optimizers):
                        torch.nn.utils.clip_grad_norm_(
                            [p for p in model.parameters() if p.requires_grad],
                            1.0,
                            error_if_nonfinite=True,
                        )
                        optimizer.step()
                    for (name, a), (_, b) in zip(
                        full.named_parameters(), sliced.named_parameters()
                    ):
                        if a.requires_grad:
                            torch.testing.assert_close(a, b, rtol=0, atol=tolerance)
                        else:
                            self.assertTrue(torch.equal(a, initial[name]))
                            self.assertTrue(torch.equal(b, initial[name]))


if __name__ == "__main__":
    unittest.main()
