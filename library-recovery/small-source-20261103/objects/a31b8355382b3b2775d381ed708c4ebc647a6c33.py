"""Synthetic held-out mechanism proof; not an accuracy claim on real tasks."""

import hashlib
import unittest

import torch
from torch.nn import functional as F

from multimodal_bridge import FrozenLinearBridge, ModalityFeature, SharedStemComposer
from multimodal_head import StateGatedCellHead


def pin(label):
    return hashlib.sha256(label.encode()).hexdigest()


class GatedHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_384d_64state_rank8_head_stays_below_16k(self):
        head = StateGatedCellHead(384, 64, 8, 8)
        self.assertLessEqual(head.parameter_count(), 16384)
        self.assertEqual(head.parameter_count(), 9744)

    def test_two_cell_heads_learn_opposing_tasks_without_mutating_shared_input(self):
        text = FrozenLinearBridge("text", ((1.0, 0.0), (0.0, 1.0)), (0.0, 0.0))
        image = FrozenLinearBridge("image", ((0.0, 1.0), (1.0, 0.0)), (0.0, 0.0))
        composer = SharedStemComposer(pin("stem"), pin("pre"), (image, text))

        def vector(value):
            # Both modalities are externally supplied toy frozen features.
            # Their source digests change for each distinct input.
            tag = str(value)
            source = (ModalityFeature.from_vector("image", pin("img-" + tag), pin("vision"),
                                                   (0.0, value)),
                      ModalityFeature.from_vector("text", pin("txt-" + tag), pin("language"),
                                                   (value, 0.0)))
            key = composer.key("scope_A", 1, pin("fence"), source)
            return composer.compose(key, source).neuron_q24()[0] / (1 << 24)

        train_values = [-0.9, -0.8, -0.7, -0.6, -0.5, -0.4, -0.3, -0.2,
                         0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        holdout_values = [-0.95, -0.85, -0.75, -0.65, -0.55, -0.45,
                           0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
        train = torch.tensor([[vector(v), 0.0] for v in train_values])
        holdout = torch.tensor([[vector(v), 0.0] for v in holdout_values])
        original = train.clone()
        state_train = torch.zeros((len(train), 2))
        state_holdout = torch.zeros((len(holdout), 2))
        label_a = torch.tensor([int(v > 0) for v in train_values])
        label_b = 1 - label_a
        test_a = torch.tensor([int(v > 0) for v in holdout_values])
        test_b = 1 - test_a

        torch.manual_seed(13)
        first = StateGatedCellHead(2, 2, 2, 2)
        torch.manual_seed(13)
        second = StateGatedCellHead(2, 2, 2, 2)
        first_initial = [p.clone() for p in first.parameters()]

        def learn(model, labels):
            opt = torch.optim.AdamW(model.parameters(), lr=0.06, weight_decay=0.0)
            for _ in range(160):
                opt.zero_grad(set_to_none=True)
                loss = F.cross_entropy(model(train, state_train), labels)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            return [p.clone() for p in model.parameters()]

        after_first = learn(first, label_a)
        after_second = learn(second, label_b)
        self.assertTrue(torch.equal(train, original))
        self.assertTrue(any(not torch.equal(a, b) for a, b in zip(after_first, first_initial)))
        self.assertTrue(all(torch.equal(a, b) for a, b in zip(after_first, first.parameters())))
        self.assertTrue(any(not torch.equal(a, b) for a, b in zip(after_first, after_second)))
        with torch.no_grad():
            accuracy_a = (first(holdout, state_holdout).argmax(-1) == test_a).float().mean().item()
            accuracy_b = (second(holdout, state_holdout).argmax(-1) == test_b).float().mean().item()
        self.assertGreaterEqual(accuracy_a, 0.95)
        self.assertGreaterEqual(accuracy_b, 0.95)

    def test_reject_malformed_inputs_without_stem_gradient(self):
        head = StateGatedCellHead(4, 2, 2, 2)
        shared = torch.ones((3, 4), requires_grad=True)
        state = torch.zeros((3, 2), requires_grad=True)
        head(shared, state).sum().backward()
        self.assertIsNone(shared.grad)
        self.assertIsNone(state.grad)
        with self.assertRaises(ValueError):
            head(torch.full((3, 4), float("nan")), state)
        with self.assertRaises(ValueError):
            head(shared, torch.zeros((4, 2)))


if __name__ == "__main__":
    unittest.main()
