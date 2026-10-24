import unittest

import numpy as np

from cell_action_cohort import (ActionBaselines, ActionCohort, action_training_order,
    validate_action_roles)
from cell_learning_baselines import FrozenBaselines
from cell_learning_curve import Cohort, training_order


def cohort(split, offset=0, long=False):
    rows = tuple(dict(source_id=f"s-{offset+i}", group_id=f"g-{offset+i}",
                      text=("prefix "*6000 if long else "")+f"action token{offset+i}") for i in range(4))
    return ActionCohort(np.eye(4, dtype=np.float32), np.array([0, 1, 0, 1]), rows, split)


class ActionCohortTests(unittest.TestCase):
    def test_full_text_roles_and_sampling_preserve_tail_and_unique_groups(self):
        train, tune, cal = cohort("train", 0, True), cohort("tuning", 4), cohort("calibration", 8)
        validate_action_roles(train, tune, cal)
        order = action_training_order(train, 7)
        self.assertEqual(len(order), 4)
        self.assertEqual([int(train.labels[i]) for i in order], [0, 1, 0, 1])
        self.assertTrue(all(len(row["text"].encode()) > 32768 for row in train.rows))
        self.assertFalse(train.features.flags.writeable)
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_action_roles(train, cohort("tuning"), cal)

    def test_short_source_baselines_and_sampler_match_frozen_formulas(self):
        train, query = cohort("train"), cohort("holdout", 4)
        old = Cohort(train.features, train.labels, train.rows, "train")
        self.assertEqual(action_training_order(train, 17), training_order(old, 2, 17))
        a = ActionBaselines(train.features, train.labels, train.rows)
        b = FrozenBaselines(train.features, train.labels, train.rows, 2)
        for arm in ("exact", "bm25", "dense_nearest", "prototype"):
            actual, expected = a.predict(arm, query.features, query.rows), b.predict(arm, query.features, query.rows)
            np.testing.assert_array_equal(actual["logits"], expected["logits"])
            np.testing.assert_array_equal(actual["eligible"], expected["eligible"])
            self.assertEqual(actual["retrieved_source_ids"], expected["retrieved_source_ids"])

    def test_long_tail_is_used_by_exact_and_bm25(self):
        train = cohort("train", long=True)
        bank = ActionBaselines(train.features, train.labels, train.rows)
        result = bank.predict("exact", train.features, train.rows)
        self.assertTrue(result["eligible"].all())
        np.testing.assert_array_equal(result["logits"].argmax(axis=1), train.labels)
        query = [dict(source_id="new", group_id="new", text="token1")]
        result = bank.predict("bm25", train.features[:1], query)
        self.assertEqual(result["retrieved_source_ids"], ["s-1"])

    def test_over_cap_hidden_labels_and_wrong_roles_reject(self):
        train = cohort("train")
        broken = [dict(row) for row in train.rows]
        broken[0]["text"] = "x"*131073
        with self.assertRaises(ValueError):
            ActionCohort(train.features, train.labels, tuple(broken), "train")
        broken = [dict(row, outcome=1) for row in train.rows]
        with self.assertRaisesRegex(ValueError, "only"):
            ActionCohort(train.features, train.labels, tuple(broken), "train")
        with self.assertRaisesRegex(ValueError, "roles"):
            validate_action_roles(train, cohort("calibration", 4), cohort("tuning", 8))


if __name__ == "__main__":
    unittest.main()
