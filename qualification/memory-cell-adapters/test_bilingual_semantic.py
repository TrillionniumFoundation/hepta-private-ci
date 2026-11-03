import copy
import unittest

import numpy as np

from bilingual_semantic_protocol import corpus, normalized, weight_digest
from prepare_semantic_v2 import prepare
from semantic_protocol import INTENTS, SHAPES, SCHEMA, bounded_address, gold, hypothesis, route
from train_bilingual_semantic import from_scores


def baseline_fixture():
    aliases = [{"kind":kind, "key":f"inventory:{kind}:{index}", "phrases":[f"{kind} name {index}"]}
               for kind in ("entity", "workflow") for index in range(8)]
    model = {"schema":SCHEMA, "aliases":aliases, "threshold":.5, "minimum_margin":.05,
             "intent_weights":np.zeros((len(INTENTS), 384), dtype=np.float32).tolist(), "intent_bias":[8.] + [0.] * (len(INTENTS)-1),
             "shape_weights":np.zeros((len(SHAPES), 384), dtype=np.float32).tolist(), "shape_bias":[8.] + [0.] * (len(SHAPES)-1)}
    return prepare(model)


class BilingualProtocolTests(unittest.TestCase):
    def test_new_held_is_disjoint_and_history_is_explicit_training_replay(self):
        original, history = baseline_fixture()
        untouched = copy.deepcopy(original)
        expanded, sets, replay = corpus(original, history)
        self.assertEqual(original, untouched)
        self.assertEqual(weight_digest(expanded), weight_digest(original))
        self.assertEqual(len(expanded["query_templates"]), 51)
        self.assertEqual(replay, 120)
        self.assertEqual({key:len(rows) for key, rows in sets.items()}, {"train":344, "development":240, "held":400})
        history_text = {normalized(row["text"]) for row in history}
        partitions = [{normalized(row["text"]) for row in rows} for rows in sets.values()]
        self.assertFalse(partitions[2] & history_text)
        self.assertFalse(partitions[0] & partitions[1]); self.assertFalse(partitions[0] & partitions[2]); self.assertFalse(partitions[1] & partitions[2])
        self.assertEqual(len(partitions[0] & history_text), 120)
        self.assertEqual({row["intent"] for row in sets["train"]}, set(INTENTS))
        for rows in sets.values():
            for row in rows:
                self.assertEqual(bounded_address(row["text"], expanded["aliases"], expanded["query_templates"]), gold(row))

    def test_cached_calibration_retains_head_agreement_and_unknown_rejection(self):
        original, history = baseline_fixture()
        model, sets, _ = corpus(original, history)
        rows = sets["development"]
        feature = np.zeros(384, dtype=np.float32)
        scores = [hypothesis(model, feature)] * len(rows)
        for threshold, margin in ((0., 0.), (.5, .05), (1.01, 0.)):
            cached = from_scores(model, rows, scores, threshold, margin)
            reference = [route(model, row["text"], feature, threshold=threshold, margin=margin) for row in rows]
            self.assertEqual(cached, reference)
            self.assertTrue(all(predicted is None for row, predicted in zip(rows, cached, strict=True) if row["role"] in ("unknown", "skill", "compose")))


if __name__ == "__main__":
    unittest.main()
