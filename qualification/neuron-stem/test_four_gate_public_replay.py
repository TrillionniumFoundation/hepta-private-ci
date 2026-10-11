"""Publisher-view integrity fixtures, never a substitute for actual model runs."""
from copy import deepcopy
import unittest

from four_gate_public_replay import DOMAINS, combine_cells, dataset_view


def publisher_fixture():
    domains = {d: [f"{d}-intent-{i}" for i in range(15)] for d in DOMAINS}
    data = {split: [[f"{split}: {intent}: utterance {i}", intent]
                    for choices in domains.values() for intent in choices for i in range(n)]
            for split, n in (("train", 8), ("val", 20), ("test", 10))}
    for split, n in (("oos_train", 100), ("oos_test", 200)):
        data[split] = [[f"{split} unknown request {i}", "oos"] for i in range(n)]
    return data, domains


class PublicReplayViewTests(unittest.TestCase):
    def test_original_partitions_and_unknown_labels_are_not_invented(self):
        data, domains = publisher_fixture()
        view, overlap = dataset_view(data, domains)
        self.assertEqual({k: len(v) for k, v in view.items()},
                         {"train": 480, "calibration": 600, "retention": 600,
                          "replay": 600, "oos_train": 100, "oos_test": 200})
        self.assertFalse(overlap)
        for row in view["replay"]:
            self.assertEqual(row["publisher_split"], "test")
            self.assertEqual(row["options"][row["label"]], row["intent"])
        self.assertTrue(all("label" not in row for row in view["oos_test"]))
        self.assertEqual(view["replay"], dataset_view(deepcopy(data), domains)[0]["replay"])

    def test_overlap_preserved_and_reported_not_filtered_for_better_scores(self):
        data, domains = publisher_fixture()
        data["test"][0][0] = data["train"][0][0]
        view, overlap = dataset_view(data, domains)
        self.assertEqual(len(view["replay"]), 600)
        self.assertTrue(overlap)
        self.assertIn(["replay", "train"], overlap.values())

    def test_group_prediction_takes_no_gold_domain_and_is_normalized(self):
        conditional = {d: [1.] + [0.] * 14 for d in DOMAINS}
        support = {d: .1 for d in DOMAINS}
        support["work"] = .7
        probabilities = combine_cells(conditional, support)
        self.assertAlmostEqual(sum(probabilities), 1.)
        self.assertEqual(probabilities.index(max(probabilities)), DOMAINS.index("work") * 15)
        support["work"] = float("nan")
        with self.assertRaisesRegex(ValueError, "support"):
            combine_cells(conditional, support)

    def test_missing_intent_fails_without_substituting_a_task(self):
        data, domains = publisher_fixture()
        data["train"].pop(0)
        with self.assertRaisesRegex(ValueError, "incomplete selected intent"):
            dataset_view(data, domains)


if __name__ == "__main__":
    unittest.main()
