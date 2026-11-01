"""Independent interface checks on development objects only."""

import unittest

import numpy as np

from .models import Memory, predict
from .task import CLASSES, DIMENSION, QUERIES, episode, exact_address_oracle, registry, task_fee


class ContentContract(unittest.TestCase):
    def test_disjoint_unseen_key_pools(self):
        owner = registry(160099)
        pools = [set(map(int, owner["pools"][name])) for name in ("train", "selection", "confirmation")]
        self.assertEqual([len(x) for x in pools], [96, 64, 96])
        self.assertFalse(pools[0] & pools[1] or pools[0] & pools[2] or pools[1] & pools[2])
        self.assertEqual(len(set.union(*pools)), 256)

    def test_private_identity_never_enters_public_query(self):
        owner = registry(160099)
        public, private = episode(owner, "development", 99)
        self.assertEqual(len(private["targets"]), QUERIES)
        for event in public:
            expected = {"kind", "feature", "dt"} | ({"value"} if event["kind"] != "QUERY" else set())
            self.assertEqual(set(event), expected)
            self.assertEqual(len(event["feature"]), DIMENSION)
        self.assertEqual(exact_address_oracle(public, private["key_ids"]), private["targets"])
        self.assertAlmostEqual(task_fee(public), (13 * .002 + QUERIES * .001) / QUERIES)

    def test_overwrite_and_typed_distractor_effect(self):
        features = np.eye(DIMENSION)
        events = [dict(kind="WRITE", feature=features[i].tolist(), value=i % CLASSES, dt=.1) for i in range(8)]
        events.extend([dict(kind="DISTRACTOR", feature=features[3].tolist(), value=7, dt=1.),
                       dict(kind="QUERY", feature=features[3].tolist(), dt=.1),
                       dict(kind="WRITE", feature=features[3].tolist(), value=2, dt=.1),
                       dict(kind="QUERY", feature=features[3].tolist(), dt=.1)])
        configurations = {"cosine": dict(threshold=.85), "ridge": dict(threshold=.85, penalty=.01),
                          "gated_delta": dict(step=1., decay=0., passes=1)}
        for kind, config in configurations.items():
            result = predict(events, np.eye(DIMENSION), kind, config)
            self.assertEqual(result["answers"], [3, 2])
            self.assertEqual(result["operations"]["distractors"], 1)
            self.assertEqual(result["operations"]["writes"], 9)
            self.assertEqual(result["operations"]["binding_matvecs"], 2)

    def test_model_state_contains_no_owner_objects(self):
        model = Memory(np.eye(DIMENSION), "cosine", dict(threshold=.85))
        self.assertTrue(all(name not in vars(model) for name in ("targets", "key_ids", "owner", "registry")))


if __name__ == "__main__":
    unittest.main()
