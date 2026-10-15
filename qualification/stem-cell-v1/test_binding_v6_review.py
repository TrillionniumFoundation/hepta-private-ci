"""No Torch or pretrained weights needed: independent receipt falsification tests."""
from copy import deepcopy
import json
import math
import unittest

from binding_v6_review import _truth, score, read


def panel():
    ids, labels, probabilities, sources = [], [], [], []
    for i in range(32):
        for world in (0, 1):
            for answer in (0, 1):
                ids.append(json.dumps(["train", f"binding-v4/train/41/{i}/world-{world}",
                                       "0", str(answer)], separators=(",", ":")))
                label = int(world == answer)
                labels.append(label)
                probabilities.append(.9 if label else .1)
                sources.append(f"sha-source-{i}-{world}")
    return dict(case_ids=ids, targets=labels, source_groups=sources,
        labels_entered_inference=False, metrics=dict(n=128,
            probabilities=probabilities, predictions=labels.copy(), accuracy=1.,
            both_worlds_correct=1., evidence_switch_rate=1.))


class IndependentBridgeReviewerTests(unittest.TestCase):
    def test_exact_world_truth_and_complete_pairs(self):
        row = panel()
        self.assertEqual(score(row), (128, 64, 64))
        self.assertEqual(_truth(row["case_ids"][0])[-1], 1)
        self.assertEqual(_truth(row["case_ids"][2])[-1], 0)

    def test_label_contamination_and_scope_change_rejected(self):
        for damage in ("label", "source", "identity", "duplicate"):
            row = deepcopy(panel())
            if damage == "label":
                row["targets"][0] ^= 1
            elif damage == "source":
                row["source_groups"][2] = row["source_groups"][0]
            elif damage == "identity":
                row["case_ids"][0] = row["case_ids"][0].replace("binding-v4/train/41", "binding-v5/fresh")
            else:
                row["case_ids"][1] = row["case_ids"][0]
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                score(row)

    def test_false_success_and_invalid_probabilities_rejected(self):
        for damage in ("score", "switch", "probability", "prediction", "leak"):
            row = deepcopy(panel())
            if damage == "score":
                row["metrics"]["accuracy"] = .99
            elif damage == "switch":
                row["metrics"]["both_worlds_correct"] = 0.
            elif damage == "probability":
                row["metrics"]["probabilities"][0] = float("nan")
            elif damage == "prediction":
                row["metrics"]["predictions"][0] ^= 1
            else:
                row["labels_entered_inference"] = True
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                score(row)


if __name__ == "__main__":
    unittest.main()
