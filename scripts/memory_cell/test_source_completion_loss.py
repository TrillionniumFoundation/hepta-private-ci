"""Actual autograd contracts on an authored causal network, NOT Qwen evidence."""

from copy import deepcopy
from types import SimpleNamespace
import unittest

import torch
import torch.nn.functional as F

from source_completion_loss import completion_loss


class CausalFixture(torch.nn.Module):
    """Frozen embedding/head and a trainable low-rank causal residual."""

    def __init__(self, dtype=torch.float32, vocab=257, width=32):
        super().__init__()
        self.config = SimpleNamespace(model_type="qwen2", vocab_size=vocab)
        with torch.random.fork_rng():
            torch.manual_seed(314159)
            self.embedding = torch.nn.Embedding(vocab, width, dtype=dtype)
            self.down = torch.nn.Linear(width, 4, bias=False, dtype=dtype)
            self.up = torch.nn.Linear(4, width, bias=False, dtype=dtype)
            self.head = torch.nn.Linear(width, vocab, bias=False, dtype=dtype)
        self.embedding.requires_grad_(False)
        self.head.requires_grad_(False)
        self.calls = 0

    def forward(
        self,
        input_ids,
        attention_mask,
        use_cache,
        return_dict=True,
        labels=None,
        logits_to_keep=0,
    ):
        self.calls += 1
        self.last_input = input_ids.detach().clone()
        self.last_mask = attention_mask.detach().clone()
        self.last_cache = use_cache
        h = self.embedding(input_ids)
        h = h + self.up(torch.tanh(self.down(h)))
        h.retain_grad()
        self.hidden = h
        causal = h.cumsum(dim=1) / torch.arange(1, h.shape[1] + 1).reshape(1, -1, 1)
        indices = (
            slice(-logits_to_keep, None)
            if isinstance(logits_to_keep, int)
            else logits_to_keep
        )
        self.last_positions = torch.arange(h.shape[1])[indices]
        logits = self.head(causal[:, indices, :])
        loss = None
        if labels is not None:
            # Independent reference: full output, pad then shift labels once.
            shifted = F.pad(labels, (0, 1), value=-100)[:, 1:]
            loss = F.cross_entropy(
                logits.float().reshape(-1, logits.shape[-1]), shifted.reshape(-1)
            )
        return SimpleNamespace(loss=loss, logits=logits)


class CompletionLossTests(unittest.TestCase):
    def test_loss_gradients_updates_and_frozen_parameters_match(self):
        for dtype, tolerance in ((torch.float32, 2e-6), (torch.bfloat16, 2e-3)):
            for prefix, tail in ((1, 1), (7, 3), (63, 8)):
                with self.subTest(dtype=dtype, prefix=prefix, tail=tail):
                    models = [CausalFixture(dtype), CausalFixture(dtype)]
                    ids = [i % 251 for i in range(prefix + tail)]
                    labels = [-100] * prefix + ids[prefix:]
                    before = {k: v.clone() for k, v in models[0].state_dict().items()}
                    losses, gradients, receipts = [], [], []
                    for backend, model in zip(("full", "supervised_positions"), models):
                        opt = torch.optim.AdamW(
                            [p for p in model.parameters() if p.requires_grad],
                            lr=0.0002,
                        )
                        loss, receipt = completion_loss(
                            model, ids, labels, backend=backend
                        )
                        loss.backward()
                        losses.append(loss.detach())
                        gradients.append(
                            {
                                n: p.grad.clone()
                                for n, p in model.named_parameters()
                                if p.requires_grad
                            }
                        )
                        self.assertGreater(
                            model.hidden.grad[:, :prefix].abs().sum().item(), 0
                        )
                        torch.nn.utils.clip_grad_norm_(
                            [p for p in model.parameters() if p.requires_grad],
                            1.0,
                            error_if_nonfinite=True,
                        )
                        opt.step()
                        receipts.append(receipt)
                        self.assertEqual(model.last_input.tolist(), [ids])
                        self.assertEqual(model.last_mask.tolist(), [[1] * len(ids)])
                        self.assertFalse(model.last_cache)
                        for name in ("embedding.weight", "head.weight"):
                            self.assertTrue(
                                torch.equal(model.state_dict()[name], before[name])
                            )
                    torch.testing.assert_close(
                        losses[0], losses[1], rtol=0, atol=tolerance
                    )
                    for name in gradients[0]:
                        torch.testing.assert_close(
                            gradients[0][name],
                            gradients[1][name],
                            rtol=tolerance,
                            atol=tolerance,
                        )
                        torch.testing.assert_close(
                            models[0].state_dict()[name],
                            models[1].state_dict()[name],
                            rtol=0,
                            atol=tolerance,
                        )
                    self.assertEqual(
                        models[1].last_positions.tolist(),
                        list(range(prefix - 1, len(ids) - 1)),
                    )
                    self.assertEqual(receipts[1]["actual_projection_positions"], tail)
                    self.assertEqual(
                        receipts[0]["input_tokens"], receipts[1]["input_tokens"]
                    )

    def test_malformed_supervision_rejects_before_forward(self):
        model = CausalFixture()
        for ids, labels in (
            ([], []),
            ([1, 2], [-100, -100]),
            ([1, 2], [1, 2]),
            ([1, 2, 3], [-100, 2, -100]),
            ([1, 2], [-100, 3]),
            ([True, 2], [-100, 2]),
            ([1, 2], [-100, True]),
            ([1, 999], [-100, 999]),
            ([1] * 2113, [-100] + [1] * 2112),
        ):
            with self.subTest(ids=ids[:5]), self.assertRaises(ValueError):
                completion_loss(model, ids, labels, backend="supervised_positions")
        self.assertEqual(model.calls, 0)

    def test_unknown_backend_or_model_does_not_fall_back(self):
        model = CausalFixture()
        with self.assertRaises(ValueError):
            completion_loss(model, [1, 2], [-100, 2], backend="auto")
        model.config.model_type = "other"
        with self.assertRaises(ValueError):
            completion_loss(model, [1, 2], [-100, 2], backend="supervised_positions")
        self.assertEqual(model.calls, 0)

    def test_ignored_slice_and_nonfinite_output_do_not_produce_loss(self):
        class Ignored(CausalFixture):
            def forward(self, *args, logits_to_keep=0, **kwargs):
                return super().forward(*args, logits_to_keep=0, **kwargs)

        with self.assertRaises(ValueError):
            completion_loss(
                Ignored(), [1, 2, 3], [-100, -100, 3], backend="supervised_positions"
            )
        model = CausalFixture()
        with torch.no_grad():
            model.head.weight.fill_(float("nan"))
        for backend in ("full", "supervised_positions"):
            with self.assertRaises(ValueError):
                completion_loss(model, [1, 2], [-100, 2], backend=backend)


if __name__ == "__main__":
    unittest.main()
