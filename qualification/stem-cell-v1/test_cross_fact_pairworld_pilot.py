"""Cheap source and truth checks; full 700-update pilot is explicit, not a unit test."""
import unittest

import torch

from cross_fact_pairworld_pilot import paired_world_rows


class PairedWorldPilotTests(unittest.TestCase):
    def test_all_worlds_labels_are_recoverable_from_public_facts(self):
        tensors, labels = paired_world_rows(17, 1)
        facts, question, candidate, *masks = tensors
        self.assertEqual(len(labels), 16)
        self.assertEqual(int(labels.sum()), 8)
        self.assertTrue(all(mask.all() for mask in masks))
        for row in range(len(labels)):
            owners, stores = {}, {}
            for item in facts[row, :, 0]:
                if item[0] == 1:
                    obj = int(item[2:4].argmax())
                    owner = int(item[4:6].argmax())
                    owners[obj] = owner
                else:
                    owner = int(item[4:6].argmax())
                    color = int(item[6:8].argmax())
                    stores[owner] = color
            obj = int(question[row, 0, 2:4].argmax())
            color = int(candidate[row, 0, 6:8].argmax())
            self.assertEqual(int(labels[row]), int(stores[owners[obj]] == color))

    def test_all_cohorts_are_same_semantic_family_not_independent_future(self):
        train, train_targets = paired_world_rows(17, 8)
        test, test_targets = paired_world_rows(71, 3)
        self.assertEqual(len(train_targets), 128)
        self.assertEqual(len(test_targets), 48)
        self.assertEqual(train[0].shape, (128, 4, 1, 8))
        self.assertEqual(test[0].shape, (48, 4, 1, 8))
        self.assertEqual(int(train_targets.sum()), 64)
        self.assertEqual(int(test_targets.sum()), 24)
        # This panel varies fact order only: it cannot be treated as OOD.
        self.assertEqual(train[1][0].shape, test[1][0].shape)

    def test_invalid_generator_bounds_rejected(self):
        with self.assertRaises(ValueError):
            paired_world_rows(41, 0)
        with self.assertRaises(ValueError):
            paired_world_rows(41, 33)


if __name__ == '__main__':
    unittest.main()
