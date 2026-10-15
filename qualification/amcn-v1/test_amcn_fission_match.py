"""Equal-parameter, equal-batch-size, equal-step research controls."""
import unittest

from amcn_core import Refused
from amcn_learning import train_semantic
from amcn_fission_match import matched_fission
from test_amcn import matrix


class MatchedPhysicalFission(unittest.TestCase):
    def test_actual_equal_parameter_training_and_shadow_predictions(self):
        inputs, labels = matrix()
        parent = train_semantic(inputs, labels, steps=8)["trained"]
        partition = {f"train-{i}": i % 2 for i in range(8)}
        r = matched_fission(parent, inputs, labels, partition, steps=4, batch=2)
        m = r["receipt"]["metrics"]
        a = m["arms"]["split_by_training_group"]
        b = m["arms"]["unsplit_equal_capacity"]
        self.assertEqual(a["physical_steps"], b["physical_steps"])
        self.assertEqual(a["physical_examples_processed"], b["physical_examples_processed"])
        self.assertEqual(a["logical_parameter_count"], b["logical_parameter_count"])
        self.assertEqual(a["simultaneously_live_head_bytes"], b["simultaneously_live_head_bytes"])
        self.assertEqual(a["physical_steps"], 8)
        self.assertEqual(a["physical_examples_processed"], 16)
        self.assertEqual(len(r["predictions"]), len(inputs.rows))
        self.assertTrue(m["exact_trainable_parameters_equal"])
        self.assertFalse(r["receipt"]["production_accepted"])
        self.assertFalse(m["future_task_superiority_established"])

    def test_disallow_non_train_labels_and_source_splitting(self):
        inputs, labels = matrix()
        parent = train_semantic(inputs, labels, steps=8)["trained"]
        part = {f"train-{i}": i % 2 for i in range(8)}
        leaked = dict(part, **{"future_a-1": 1})
        with self.assertRaises(Refused):
            matched_fission(parent, inputs, labels, leaked, steps=2, batch=2)
        with self.assertRaises(Refused):
            matched_fission(parent, inputs, labels, part, steps=2, batch=8)


if __name__ == "__main__":
    unittest.main()
