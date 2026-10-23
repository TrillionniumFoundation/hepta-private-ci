import unittest

import numpy as np

from data import caption, dataset, decoded_metrics, outcome_table, parse_caption, templates
from model import JointModel


class DataTests(unittest.TestCase):
    def test_source_groups_and_input_bytes_are_disjoint(self):
        # Do not open the sealed test split during development.
        a, b = dataset("train", 1), dataset("validation", 1)
        self.assertFalse(set(a["groups"]) & set(b["groups"]))
        self.assertFalse(set(a["input_hashes"]) & set(b["input_hashes"]))
        self.assertEqual(set(a["labels"]), set(range(12)))
        self.assertEqual(parse_caption(caption(7)), 7)

    def test_observer_uses_actual_pixels(self):
        model = JointModel(202, 12, 192)
        model.fit_decoder(templates())
        p = np.eye(12)
        before = decoded_metrics(model, p, p, np.arange(12))
        reward_before = outcome_table(model)[np.arange(12), np.arange(12), np.arange(12)]
        model.params["decoder"][:] = 0
        model.params["decoder_bias"][:] = 0
        after = decoded_metrics(model, p, p, np.arange(12))
        reward_after = outcome_table(model)[np.arange(12), np.arange(12), np.arange(12)]
        self.assertGreater(before["joint_success"].mean(), after["joint_success"].mean() + 0.5)
        self.assertGreater(reward_before.mean(), reward_after.mean() + 0.3)


if __name__ == "__main__":
    unittest.main()
