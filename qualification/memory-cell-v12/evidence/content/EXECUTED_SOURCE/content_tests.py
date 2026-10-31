"""Content encoding, held-label isolation and explicit scope-contract tests."""

import copy
import unittest

import numpy as np

from content_experiment import decode, encode, predict, queries, resolve, select_threshold


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.codebook = dict(owner=["owner-a", "owner-b"], deputy=["deputy-a", "deputy-b"],
                             lifecycle=["existing", "target"])
        self.metadata = [dict(module="memory.retrieval", fields=dict(owner="owner-a", deputy="deputy-b", lifecycle="existing")),
                         dict(module="neuron.runtime", fields=dict(owner="owner-b", deputy="deputy-a", lifecycle="target"))]

    def test_actual_field_roundtrip_and_invalid_code(self):
        for item in self.metadata:
            bits = encode(item["fields"], self.codebook)
            self.assertEqual(decode(np.asarray(bits) * 2 - 1, self.codebook), item["fields"])
        self.assertIsNone(decode(np.ones(10), self.codebook))

    def test_scope_resolver_has_no_target_access(self):
        modules = [m["module"] for m in self.metadata]
        rows = queries(self.metadata[:1], self.metadata)
        for row in rows:
            self.assertEqual(resolve(row["text"], modules[:1]), row["module"] if row["target"] else None)
        self.assertIsNone(resolve("State owner deputy lifecycle for memory.retrieval and neuron.runtime", modules))

    def test_threshold_does_not_consume_test_targets(self):
        rows = [dict(split="calibration", target=dict(owner="a")),
                dict(split="calibration", target=dict(owner="a")),
                dict(split="test", target=dict(owner="b"))]
        predictions = [dict(module="known", fields=dict(owner="a"), confidence=.9),
                       dict(module="known", fields=dict(owner="b"), confidence=.7),
                       dict(module="known", fields=dict(owner="a"), confidence=.99)]
        threshold = select_threshold(rows, predictions, [0, .8, 1.000000001])
        self.assertEqual(threshold, .8)
        changed = copy.deepcopy(rows)
        changed[2]["target"] = dict(owner="a")
        self.assertEqual(select_threshold(changed, predictions, [0, .8, 1.000000001]), threshold)

    def test_model_fields_are_decoded_from_logits_not_address_lookup(self):
        class ConstantModel:
            def predict(self, X):
                return np.full((len(X), 10), -2.0)

        modules = [m["module"] for m in self.metadata]
        texts = [f"State owner deputy lifecycle for {m}." for m in modules]
        output = predict([ConstantModel()], np.zeros((2, 4)), texts, modules, self.codebook)
        expected = dict(owner="owner-a", deputy="deputy-a", lifecycle="existing")
        self.assertEqual([p["fields"] for p in output], [expected, expected])
        self.assertNotEqual(output[1]["fields"], self.metadata[1]["fields"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
