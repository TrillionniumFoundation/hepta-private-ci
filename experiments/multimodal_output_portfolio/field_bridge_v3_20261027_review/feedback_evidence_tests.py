"""Synthetic actual-media and independent arithmetic contracts only."""

import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import numpy as np
import torch

from feedback_evidence import MediaIndex, ObserverArithmetic, decode, event, feedback_values, nonnative_action
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.feedback_media import MediaWriter
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.feedback_task import Delivered, verifier_review, public_event
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027 import runtime_controller as production
from experiments.multimodal_output_portfolio.field_bridge_20261027.task import public_features
from experiments.multimodal_output_portfolio.v6.data import Observation, Target
from experiments.multimodal_output_portfolio.v6.observer import observe_tensors


class SyntheticObserver(torch.nn.Module):
    def forward(self, image):
        values = image.flatten(1).mean(1)
        return torch.stack([values * (index - 4) + index / 10 for index in range(10)], dim=1)


def fixture():
    rng = torch.Generator().manual_seed(271027)
    output = SimpleNamespace(image_logits=torch.randn(1, 1, 28, 56, generator=rng),
        text_logits=torch.randn(1, 7, 24, generator=rng), token_ids=torch.tensor([[1, 3, 14, 4, 15, 5, 6, 2]]))
    mask = (torch.rand(1, 1, 28, 56, generator=rng) > .2).float()
    observation = Observation(torch.zeros_like(mask), mask, torch.zeros(1, 8, dtype=torch.long))
    target = Target(torch.rand(1, 1, 28, 56, generator=rng), output.token_ids.clone(), torch.tensor([[0, 1]]))
    observer = SyntheticObserver().eval().requires_grad_(False)
    return output, observation, target, observer


class MediaAndArithmeticTests(unittest.TestCase):
    def test_all_public_features_scores_and_feedback_match_independently(self):
        output, observation, target, observer = fixture()
        arithmetic = ObserverArithmetic({"reward": observer, "audit": observer})
        with tempfile.TemporaryDirectory(prefix="v3-media-synthetic-", dir="/tmp") as root:
            path = Path(root) / "media.h3m"
            with MediaWriter(path) as writer:
                hard = writer.deliver(output, ("synthetic-case",), 1)
            index = MediaIndex(path)
            record = index.receipt(hard.receipts[0])
            expected_public = (2 * public_features(observation, output, observer, hard).double().numpy() - 1)[0]
            np.testing.assert_array_equal(arithmetic.public(record, observation.mask[0]), expected_public)
            expected_score = observe_tensors(observer, hard.pixels_u8.float() / 255, hard.captions,
                                            target.pixels, target.labels)[0]
            expected_score["net_utility"] = expected_score["utility"] - .004
            self.assertEqual(arithmetic.score(record, target.pixels[0], target.labels[0], "reward", 1), expected_score)
            delivered = Delivered(observation, None, hard, expected_public[None], ("synthetic-case",), 1, np.array([2]))
            packet = verifier_review(delivered, target)[0]
            feedback = feedback_values(record, target.pixels[0], target.labels[0], "synthetic-case", 1)
            self.assertEqual(feedback, packet["public_feedback"])
            np.testing.assert_array_equal(event(expected_public, feedback, 2), public_event(delivered, [packet])[0])

    def test_physical_dedup_preserves_each_logical_delivery(self):
        output, _, _, _ = fixture()
        with tempfile.TemporaryDirectory(prefix="v3-media-dedup-", dir="/tmp") as root:
            path = Path(root) / "media.h3m"
            with MediaWriter(path) as writer:
                first = writer.deliver(output, ("case-one",), 0).receipts[0]
                second = writer.deliver(output, ("case-two",), 1).receipts[0]
                self.assertEqual((writer.records, writer.physical_records), (2, 1))
            index = MediaIndex(path)
            self.assertEqual(len(index.records), 1)
            index.receipt(first)
            index.receipt(second)
            self.assertEqual(index.logical_reads, 2)
            self.assertFalse(first["physical_record_reused"])
            self.assertTrue(second["physical_record_reused"])

    def test_changed_logits_or_component_hash_cannot_be_hidden_in_receipt(self):
        output, _, _, _ = fixture()
        with tempfile.TemporaryDirectory(prefix="v3-media-tamper-", dir="/tmp") as root:
            path = Path(root) / "media.h3m"
            with MediaWriter(path) as writer:
                receipt = writer.deliver(output, ("case",), 0).receipts[0]
            index = MediaIndex(path)
            altered = copy.deepcopy(receipt)
            altered["public_text_logits"][0][0] += .01
            with self.assertRaisesRegex(ValueError, "logit receipt"):
                index.receipt(altered)
            altered = copy.deepcopy(receipt)
            altered["sha256"]["image"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "binding differs"):
                index.receipt(altered)

    def test_truncated_or_duplicated_physical_record_rejected(self):
        output, _, _, _ = fixture()
        with tempfile.TemporaryDirectory(prefix="v3-media-invalid-", dir="/tmp") as root:
            path = Path(root) / "original.h3m"
            with MediaWriter(path) as writer:
                writer.deliver(output, ("case",), 0)
            raw = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "bounds"):
                decode(raw[:-1])
            duplicated = Path(root) / "duplicate.h3m"
            duplicated.write_bytes(raw + raw)
            with self.assertRaisesRegex(ValueError, "Duplicate physical"):
                MediaIndex(duplicated)

    def test_invalid_caption_and_strict_feedback_depth(self):
        output, observation, target, observer = fixture()
        output.token_ids = torch.tensor([[1, 3, 14, 4, 15, 2]])
        with tempfile.TemporaryDirectory(prefix="v3-media-invalid-caption-", dir="/tmp") as root:
            path = Path(root) / "media.h3m"
            with MediaWriter(path) as writer:
                hard = writer.deliver(output, ("case",), 0)
            record = MediaIndex(path).receipt(hard.receipts[0])
            arithmetic = ObserverArithmetic({"reward": observer, "audit": observer})
            score = arithmetic.score(record, target.pixels[0], target.labels[0], "audit", 0)
            self.assertFalse(score["caption_valid"])
            self.assertIsNone(score["caption_digits"])
            self.assertEqual(score["text_fact"], 1.)
            with self.assertRaisesRegex(ValueError, "Feedback cannot"):
                feedback_values(record, target.pixels[0], target.labels[0], "case", 0)

    def test_observer_cache_reports_logical_and_actual_work_separately(self):
        observer = SyntheticObserver().eval()
        arithmetic = ObserverArithmetic({"reward": observer, "audit": observer})
        pixels = np.zeros((28, 56), dtype=np.uint8)
        arithmetic.image(pixels, "reward")
        arithmetic.image(pixels, "reward")
        self.assertEqual(arithmetic.logical_images, {"reward": 2, "audit": 0})
        self.assertEqual(arithmetic.calls, {"reward": 2, "audit": 0})


class HeadReplayTests(unittest.TestCase):
    def test_current_and_history_all_transforms_stages_match_frozen_arithmetic(self):
        rng = np.random.default_rng(19)
        common = {"mean": rng.normal(size=16).tolist(), "scale": rng.uniform(.2, 1, 16).tolist()}
        histories = rng.uniform(-1, 1, (3, 16))
        histories[0, 8:] = 0
        for stage in (1, 2):
            histories[stage, 8:12] = [1., -1., 1., .4]
            histories[stage, 12:] = [1., 0., 0., 0.]
        for rep in ("current", "history"):
            fourier = production._fourier(16, 36) if rep == "current" else production._fourier(48, 20)
            heads = [{"normalizer": {"mean": rng.normal(size=88).tolist(), "scale": rng.uniform(.2, 2, 88).tolist()},
                      "coefficient": rng.normal(size=(89, 5)).tolist()} for _ in range(3)]
            for name, k in production.TRANSFORMS:
                controller = {"representation": rep, "transform": {"name": name, "k": k, "normalizer": common},
                              "fourier": fourier, "heads": heads}
                for length in (1, 2, 3):
                    action, features, values = nonnative_action(controller, histories[:length])
                    expected = production._non_native_features(rep, histories[None, :length], controller["transform"], fourier)
                    np.testing.assert_array_equal(features, expected[0])
                    np.testing.assert_array_equal(values, production._choose(heads[length - 1], expected)[0])
                    self.assertEqual(action, int(values.argmax()))


if __name__ == "__main__":
    unittest.main()
