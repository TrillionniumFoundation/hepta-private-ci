"""Real tiny random Qwen loss/gradient and adapter tests; no capability claim."""

import copy
import importlib.util
import tempfile
import unittest

from . import causal_train_v3 as train

BACKEND_AVAILABLE = all(
    importlib.util.find_spec(name) is not None
    for name in ("torch", "transformers", "peft")
)


@unittest.skipUnless(
    BACKEND_AVAILABLE,
    "real torch/transformers/peft are absent; numeric tests must run in the pinned runtime",
)
class TinyQwenNumericalTests(unittest.TestCase):
    def setUp(self):
        import torch
        import transformers

        self.torch = torch
        torch.set_num_threads(1)
        torch.manual_seed(1729)
        config = transformers.Qwen2Config(
            vocab_size=67,
            hidden_size=32,
            intermediate_size=48,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=64,
            tie_word_embeddings=True,
            attention_dropout=0.0,
            bos_token_id=1,
            eos_token_id=2,
            pad_token_id=0,
        )
        config._attn_implementation = "eager"
        self.model = transformers.Qwen2ForCausalLM(config).float().train()
        self.ids = torch.tensor([[1, 4, 5, 6, 7, 8, 9, 2, 0, 0]])
        self.mask = torch.tensor([[1, 1, 1, 1, 1, 1, 1, 1, 0, 0]])
        self.labels = torch.tensor([[-100, -100, -100, 6, -100, 8, 9, 2, -100, -100]])

    def test_selected_causal_loss_and_all_parameter_gradients_match_dense(self):
        torch, dense = self.torch, copy.deepcopy(self.model)
        full = dense(
            input_ids=self.ids,
            attention_mask=self.mask,
            labels=self.labels,
            use_cache=False,
        ).loss
        full.backward()
        head_shapes = []
        handle = self.model.lm_head.register_forward_hook(
            lambda module, inputs, output: head_shapes.append(tuple(output.shape))
        )
        selected, count = train.selected_token_loss(
            self.model, self.ids, self.mask, self.labels
        )
        handle.remove()
        selected.backward()
        self.assertEqual((count, head_shapes), (4, [(1, 4, 67)]))
        torch.testing.assert_close(selected, full, rtol=1e-6, atol=1e-7)
        compared = 0
        for (name, actual), (other_name, expected) in zip(
            self.model.named_parameters(), dense.named_parameters()
        ):
            self.assertEqual(name, other_name)
            self.assertEqual(actual.grad is None, expected.grad is None)
            if actual.grad is not None:
                torch.testing.assert_close(
                    actual.grad, expected.grad, rtol=1e-5, atol=1e-7, msg=name
                )
                compared += 1
        self.assertGreater(compared, 10)

    def test_lora_checkpointed_selected_loss_updates_adapter_and_reloads(self):
        import peft

        torch = self.torch
        model = peft.get_peft_model(
            self.model,
            peft.LoraConfig(
                r=4,
                lora_alpha=8,
                lora_dropout=0.0,
                target_modules=["q_proj", "v_proj"],
                bias="none",
                task_type="CAUSAL_LM",
            ),
        )
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
        model.enable_input_require_grads()
        parameters = [
            (name, value)
            for name, value in model.named_parameters()
            if value.requires_grad
        ]
        before = train._parameter_hash(parameters, torch)
        optimizer = torch.optim.AdamW([value for _, value in parameters], lr=0.01)
        loss, _ = train.selected_token_loss(model, self.ids, self.mask, self.labels)
        loss.backward()
        optimizer.step()
        self.assertNotEqual(before, train._parameter_hash(parameters, torch))
        model.eval()
        with torch.inference_mode():
            expected = model(
                input_ids=self.ids, attention_mask=self.mask, use_cache=False
            ).logits
        with tempfile.TemporaryDirectory() as temporary:
            model.save_pretrained(temporary, safe_serialization=True)
            # The original object was wrapped in place; recover its actual base
            # weights via merge-free unload, then compare an explicit fresh load.
            base = copy.deepcopy(model).unload()
            restored = peft.PeftModel.from_pretrained(
                base, temporary, is_trainable=False, local_files_only=True
            ).eval()
            with torch.inference_mode():
                actual = restored(
                    input_ids=self.ids, attention_mask=self.mask, use_cache=False
                ).logits
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)

    def test_empty_or_padding_supervision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "next-token supervision"):
            train.selected_token_loss(
                self.model, self.ids, self.mask, self.torch.full_like(self.labels, -100)
            )
        bad = self.labels.clone()
        bad[0, -1] = 1
        with self.assertRaisesRegex(ValueError, "next-token supervision"):
            train.selected_token_loss(self.model, self.ids, self.mask, bad)


if __name__ == "__main__":
    unittest.main()
