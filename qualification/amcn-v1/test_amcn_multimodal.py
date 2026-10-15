"""Actual train-only cross-modal connector and source coherence controls."""
from hashlib import sha256
import unittest

import torch

from amcn_core import Refused
from amcn_multimodal import Span, Binding, TrainingPair, train_connector
from experiments.shared_stem_cell.execution import tensor_digest


def sha(text):
    return sha256(text.encode()).hexdigest()


def span(event, modality, suffix, *, start=100, end=300, scope="lab", revoked=False):
    return Span(f"{event}-{suffix}", event, f"root-{event}", scope, "g1",
                modality, sha("asset-"+event+suffix), sha("normalizer-v1"),
                sha("encoder-"+modality), tensor_digest(torch.tensor([1., 0.] if event == "e1" else [0., 1.], dtype=torch.float32)),
                start, end, revoked)


class CrossModalMechanicsTests(unittest.TestCase):
    def test_supported_binding_and_negative_pair_isolation(self):
        t1, t2 = span("e1", "text", "t"), span("e2", "text", "t")
        i1, i2 = span("e1", "image", "i"), span("e2", "image", "i")
        good = Binding(t1, i1, sha("external-support"), 200)
        self.assertEqual(good.text_span.source_event, good.other_span.source_event)
        with self.assertRaises(Refused):
            Binding(t1, i2, sha("forged-support"), 200)
        with self.assertRaises(Refused):
            Binding(t1, span("e1", "image", "shifted", start=5000, end=9000),
                    sha("support"), 200)
        with self.assertRaises(Refused):
            Binding(t1, span("e1", "image", "revoked", revoked=True),
                    sha("support"), 200)
        with self.assertRaises(Refused):
            TrainingPair(t1, i1, sha("bad-negative"), False, "train")
        with self.assertRaises(Refused):
            TrainingPair(t1, i2, sha("wrong-split"), False, "future_a")

    def test_training_is_real_and_does_not_authorize_new_modality(self):
        t1, t2 = span("e1", "text", "t"), span("e2", "text", "t")
        i1, i2 = span("e1", "image", "i"), span("e2", "image", "i")
        pairs = [
            TrainingPair(t1, i1, sha("p1"), True, "train", sha("review1")),
            TrainingPair(t2, i2, sha("p2"), True, "train", sha("review2")),
            TrainingPair(t1, i2, sha("n1"), False, "train"),
            TrainingPair(t2, i1, sha("n2"), False, "train"),
        ]
        txt = torch.tensor([[1., 0.], [0., 1.], [1., 0.], [0., 1.]], dtype=torch.float32)
        img = torch.tensor([[1., 0.], [0., 1.], [0., 1.], [1., 0.]], dtype=torch.float32)
        result = train_connector(pairs, txt, img, split="train", steps=8, latent=4)
        self.assertEqual(len(result["scores"]), 4)
        self.assertFalse(result["receipt"]["production_accepted"])
        self.assertFalse(result["receipt"]["metrics"]["pretrained_modal_towers_executed_here"])
        self.assertNotEqual(result["receipt"]["metrics"]["trained"]["sha256"],
                            result["receipt"]["metrics"]["frozen"]["sha256"])
        with self.assertRaises(Refused):
            train_connector(pairs, txt, img, split="future_a", steps=2)
        mismatched = img.clone()
        mismatched[0] = torch.tensor([0., 1.])
        with self.assertRaises(Refused):
            train_connector(pairs, txt, mismatched, split="train", steps=2)


if __name__ == "__main__":
    unittest.main()
