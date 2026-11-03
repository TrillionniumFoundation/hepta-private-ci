"""Behavioral regressions for learned routing and its persistence boundary."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from v6.encoder import normalize_request
from v6.router import LABELS, Router, measure
from v6.training_language import corpus


class RouterTests(unittest.TestCase):
    def test_fitted_model_roundtrip_and_tampering(self):
        rows = corpus("train")
        router = Router(None, "lexical", 6001, 8.0)
        router.fit(rows)
        router.calibrate(corpus("selection"))
        probes = [
            "Read the newest saved observation.",
            "Inspect its saved steps, without running them.",
            "计算最新与历史记录的差值。",
            "Delete all stored readings.",
        ]
        before = router.routes(probes)
        metrics = measure(corpus("selection"), router.routes([row["text"] for row in corpus("selection")]))
        self.assertGreater(metrics["known_correct_rate"], 0.4)
        self.assertLessEqual(metrics["ood_acceptance_rate"], 0.05)
        self.assertLessEqual(metrics["known_wrong_rate"], 0.02)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "router"
            receipt = router.save(target)
            restored = Router.load(target, expected_manifest_sha256=receipt["manifest_sha256"])
            self.assertEqual(before, restored.routes(probes))
            raw = bytearray((target / "weights.npz").read_bytes())
            raw[-20] ^= 1
            (target / "weights.npz").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "identity"):
                Router.load(target)

    def test_language_partitions_are_distinct(self):
        training, selection = corpus("train"), corpus("selection")
        self.assertFalse({row["text"] for row in training} & {row["text"] for row in selection})
        self.assertEqual(set(LABELS), {row["operation"] for row in training})

    def test_explicit_entity_normalization_is_not_an_answer_side_channel(self):
        left = normalize_request("Read the latest value of future-sensor at 2026-01-02", "future-sensor")
        right = normalize_request("Read the latest value of stable-node at 2025-12-03", "stable-node")
        self.assertEqual(left, right)
        self.assertIn("latest", left)
        self.assertEqual(normalize_request("Read a at present", "a"), "read entity at present")
        with self.assertRaises(ValueError):
            normalize_request("x" * 4097)

    def test_corrupt_policy_rejected_after_hash_rebinding(self):
        router = Router(None, "lexical", 6001, 2.0)
        router.fit(corpus("train"))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "router"
            router.save(target)
            manifest = json.loads((target / "manifest.json").read_bytes())
            manifest["threshold"] = -0.1
            (target / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "acceptance"):
                Router.load(target)

    def test_foreign_encoder_identity_rejected(self):
        class Encoder:
            digest = "e" * 64
            base_bytes = 1

        encoder = Encoder()
        router = Router(encoder, "semantic")
        rows = corpus("train")
        dense = np.random.default_rng(7).normal(size=(len(rows), 384))
        router.fit(rows, dense=dense)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "router"
            router.save(target)
            encoder.digest = "f" * 64
            with self.assertRaisesRegex(ValueError, "encoder"):
                Router.load(target, encoder)


if __name__ == "__main__":
    unittest.main()
