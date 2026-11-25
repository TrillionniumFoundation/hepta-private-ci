"""Information timing and source separation checks for the new task."""

import unittest
import torch

from .data import SOURCE_IDS, make_data


class DataTests(unittest.TestCase):
    def test_source_partitions(self):
        groups = list(SOURCE_IDS.values())
        self.assertEqual(sum(map(len, groups)), len(set(sum(groups, ()))))

    def test_future_signal_never_in_prefix(self):
        data = make_data('smoke_train', per_source=17)
        for n, late in enumerate(data.late_step.tolist()):
            self.assertEqual(int(torch.count_nonzero(data.x[:late, n, 1])), 0)
            self.assertEqual(float(data.x[late, n, 3]), 1.0)
        actual = (data.x[:, :, :2].sum((0, 2)) > 0).long()
        self.assertTrue(torch.equal(actual, data.y))

    def test_reproducible_multi_initial_states(self):
        first = make_data('smoke_dev', per_source=19)
        self.assertEqual(first.digest(), make_data('smoke_dev', per_source=19).digest())
        self.assertGreater(float(first.initial_margin.std()), .05)


if __name__ == '__main__':
    unittest.main()
