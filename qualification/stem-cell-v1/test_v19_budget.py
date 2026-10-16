"""Pure mechanism / adversarial learning-investment source-only checks."""
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from v19_train_only_budget import (BUDGETS, SEEDS, canon, digest, four_folds,
                                   new_head, physical_fit, score, source)


class BudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_digest_is_exact(self):
        self.assertEqual(digest(b'abc'), hashlib.sha256(b'abc').hexdigest())

    def test_canonical_bytes_are_repeatable(self):
        self.assertEqual(canon({'b': 1, 'a': 2}), b'{"a":2,"b":1}')

    def test_unpinned_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'input.json').write_bytes(b'{}')
            Path(d, 'features.safetensors').write_bytes(b'fake')
            self.assertRaises(ValueError, source, d)

    def test_missing_input_denied(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertRaises(FileNotFoundError, source, d)

    def test_folds_disjoint(self):
        rows = [{'case_id': f'unused-{i}'} for i in range(64)]
        folds = four_folds(rows, list(range(64)))
        self.assertEqual([len(v) for v in folds], [16] * 4)
        self.assertEqual(sorted(sum(folds, [])), list(range(64)))

    def test_folds_ignore_labels(self):
        rows = [{'case_id': f'fixed-{i}', 'label': i % 4} for i in range(64)]
        a = four_folds(rows, list(range(64)))
        for row in rows:
            row['label'] = 999
        self.assertEqual(a, four_folds(rows, list(range(64))))

    def test_zero_initial_is_uniform(self):
        h = new_head()
        self.assertTrue(torch.equal(h(torch.ones(3, 384)), torch.zeros(3, 4)))
        self.assertEqual(sum(p.numel() for p in h.parameters()), 1540)

    def test_physical_two_step_changes_weights(self):
        gen = torch.Generator().manual_seed(7)
        x = torch.randn(12, 384, generator=gen)
        y = torch.arange(12) % 4
        # Partial checkpoint packets must fail closed rather than silently pass.
        self.assertRaises(ValueError, physical_fit, x, y, 123, x, max_steps=2)
        result = physical_fit(x, y, 123, x)
        self.assertEqual(sorted(result), list(BUDGETS))
        self.assertNotEqual(result[1]['weights_sha256'], result[2]['weights_sha256'])
        self.assertGreater(result[2]['cumulative_training_cpu_ns'], result[1]['cumulative_training_cpu_ns'])

    def test_shape_guard(self):
        x = torch.randn(4, 6)
        y = torch.tensor([0, 1, 2, 3])
        self.assertRaises(ValueError, physical_fit, x, y, 1, x)

    def test_score_multiclass_brier(self):
        r = score(torch.zeros(4, 4), torch.tensor([0, 1, 2, 3]))
        self.assertEqual(r['brier'], 0.75)
        self.assertEqual(r['correct'], 1)

    def test_registered_budgets(self):
        self.assertEqual(BUDGETS, (1, 2, 4, 8, 16, 32, 80))
        self.assertEqual(SEEDS, (41, 47, 53))


if __name__ == '__main__':
    unittest.main()
