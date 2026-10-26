from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from memory_cells.data import make_associative
from memory_cells.encoding import FrozenEncoder
from memory_cells.model import MemoryCell
from memory_cells.routing import LearnedRouter, LiteralRouter, TypedRouter


class TextOnlyQuery:
    def __init__(self, text):
        self.text = text

    @property
    def domain(self):
        raise AssertionError("inference must not consult oracle domain")

    @property
    def target(self):
        raise AssertionError("routing must not consult the memory answer")


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.data = make_associative(103, (6, 6), 16)
        self.domains = tuple(dict.fromkeys(event.domain for event in self.data.events))

    def test_typed_routing_preserves_explicit_interface_and_abstains_unknown(self):
        router = TypedRouter(self.domains)
        queries = self.data.test + (replace(self.data.test[0], domain="unseen"),)
        self.assertEqual(
            router.route(queries), [query.domain for query in self.data.test] + [None]
        )
        self.assertEqual(router.manifest()["inference_inputs"], ["query.domain"])

    def test_literal_routing_uses_text_and_rejects_prefixes_and_ambiguity(self):
        router = LiteralRouter(self.domains)
        text_only = [TextOnlyQuery(query.text) for query in self.data.test]
        self.assertEqual(
            router.route(text_only), [query.domain for query in self.data.test]
        )
        probes = [
            TextOnlyQuery(f"{self.domains[0]}-suffix"),
            TextOnlyQuery("unknown-domain"),
            TextOnlyQuery(" and ".join(self.domains)),
            TextOnlyQuery(self.domains[0].upper()),
        ]
        self.assertEqual(router.route(probes), [None, None, None, self.domains[0]])

    def test_learned_router_trains_on_domains_and_reads_no_inference_oracle(self):
        encoder = FrozenEncoder(128, 9)
        router = LearnedRouter(self.domains, encoder=encoder, rank=4, seed=5)
        before = router.model.A.copy()
        receipt = router.fit(self.data.train, steps=120, lr=0.03)
        self.assertLess(receipt["final_loss"], receipt["initial_loss"])
        self.assertFalse(np.array_equal(before, router.model.A))
        original = router.route(self.data.test)
        poisoned = tuple(
            replace(query, domain="oracle-is-forbidden", target=999)
            for query in self.data.test
        )
        self.assertEqual(original, router.route(poisoned))
        self.assertEqual(
            original,
            router.route([TextOnlyQuery(query.text) for query in self.data.test]),
        )
        np.testing.assert_allclose(router.scores(self.data.test).sum(axis=1), 1.0)
        self.assertFalse(receipt["calibrated"])
        with self.assertRaisesRegex(ValueError, "training queries"):
            router.fit(self.data.test, steps=1)

    def test_training_does_not_read_memory_targets(self):
        class TrainingQuery(TextOnlyQuery):
            def __init__(self, query):
                super().__init__(query.text)
                self.domain_label = query.domain
                self.split = "train"

            @property
            def domain(self):
                return self.domain_label

        router = LearnedRouter(self.domains)
        router.fit([TrainingQuery(query) for query in self.data.train], steps=2)

    def test_threshold_is_explicit_and_metadata_costs_are_saved(self):
        router = LearnedRouter(self.domains, threshold=1.0)
        self.assertEqual(router.route(self.data.test), [None] * len(self.data.test))
        router.fit(self.data.train, steps=5)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = router.save(root / "learned")
            loaded = MemoryCell.load(
                root / "learned" / "model",
                expected_encoder_digest=router.encoder.digest,
            )
            features = router.encoder.encode([query.text for query in self.data.test])
            np.testing.assert_array_equal(
                loaded.predict(features), router.model.predict(features)
            )
            manifest_path = root / "learned" / "router.json"
            self.assertEqual(manifest_path.stat().st_size, receipt["manifest_bytes"])
            self.assertEqual(json.loads(manifest_path.read_text()), receipt["manifest"])
            self.assertGreater(receipt["manifest"]["domain_vocabulary_bytes"], 0)
            literal = LiteralRouter(self.domains).save(root / "literal")
            self.assertEqual(literal["manifest"]["parameter_bytes"], 0)

    def test_bounded_domains_and_query_input(self):
        with self.assertRaises(ValueError):
            TypedRouter(["SAME", "same"])
        with self.assertRaises(ValueError):
            LearnedRouter(self.domains, threshold=float("nan"))
        with self.assertRaises(ValueError):
            LiteralRouter(self.domains).route([TextOnlyQuery("x" * 16385)])


if __name__ == "__main__":
    unittest.main()
