"""No original material needed: independent MT19937 and NumPy gradient guards."""
import ast
from pathlib import Path
import tempfile
import unittest

import numpy as np
from v20_independent_numpy_training import (
    BUDGETS, CpuMT19937, Invalid, adam_checkpoints, folds_for_train, load_source,
    require,
)


class NumPyTrainingCore(unittest.TestCase):
    def test_cpu_rng_48_matches_external_torch_golden(self):
        g = CpuMT19937(10041)
        self.assertEqual(g.randint(48, 16).tolist(),
                         [42, 35, 33, 36, 37, 31, 45, 9, 9, 26, 17, 30, 34, 27, 28, 14])

    def test_cpu_rng_64_matches_external_torch_golden(self):
        g = CpuMT19937(1041)
        self.assertEqual(g.randint(64, 16).tolist(),
                         [41, 1, 60, 63, 28, 27, 4, 20, 13, 25, 53, 5, 27, 42, 54, 28])

    def test_rng_twist_624_crosses_external_torch_boundary(self):
        g = CpuMT19937(10041)
        values = [g.draw() % 48 for _ in range(640)]
        self.assertEqual(values[621:629], [41, 24, 2, 10, 47, 4, 24, 1])
        self.assertEqual(values[-8:], [8, 10, 27, 32, 34, 16, 44, 14])

    def test_rng_rejects_non_registered_shapes(self):
        g = CpuMT19937(41)
        self.assertRaises(Invalid, g.randint, 49, 16)
        self.assertRaises(Invalid, g.randint, 48, 17)
        self.assertRaises(Invalid, CpuMT19937, -1)
        self.assertRaises(Invalid, CpuMT19937, True)

    def test_pure_numpy_imports_no_torch(self):
        src = Path(__file__).with_name('v20_independent_numpy_training.py')
        tree = ast.parse(src.read_text())
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module)
        self.assertTrue(all(m != 'torch' and not str(m).startswith('torch.') for m in modules))
        self.assertTrue(all('v19_train_only_budget' != str(m) for m in modules))

    def test_numpy_optimizer_real_nonzero_weights(self):
        rng = np.random.default_rng(55)
        x = rng.normal(size=(48, 384)).astype(np.float32)
        y = np.arange(48, dtype=np.int64) % 4
        out = adam_checkpoints(x, y, 10041, x[:16])
        self.assertEqual(list(out), list(BUDGETS))
        self.assertFalse(np.array_equal(out[1][0], out[2][0]))
        self.assertTrue(np.isfinite(out[80][2]).all())
        self.assertEqual(out[80][0].shape, (4, 384))

    def test_numpy_optimizer_is_reproducible(self):
        rng = np.random.default_rng(15)
        x = rng.normal(size=(48, 384)).astype(np.float32)
        y = np.arange(48) % 4
        a, b = adam_checkpoints(x, y, 10041, x[:8]), adam_checkpoints(x, y, 10041, x[:8])
        for step in BUDGETS:
            for aa, bb in zip(a[step], b[step]):
                self.assertTrue(np.array_equal(aa, bb))

    def test_optimizer_rejects_bad_labels_and_shape(self):
        x = np.zeros((48, 384), np.float32)
        y = np.zeros(48, np.int64)
        y[1] = 4
        self.assertRaises(Invalid, adam_checkpoints, x, y, 10041, x[:8])
        self.assertRaises(Invalid, adam_checkpoints, x[:, :-1], np.zeros(48, np.int64), 10041, x[:8])

    def test_optimizer_rejects_nonfinite(self):
        x = np.zeros((48, 384), np.float32)
        x[0, 0] = np.nan
        self.assertRaises(Invalid, adam_checkpoints, x, np.zeros(48, np.int64), 10041, x[:8])

    def test_original_source_cannot_fallback_to_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertRaises((Invalid, FileNotFoundError), load_source, Path(tmp))

    def test_no_synthetic_fold_overlap(self):
        rows = [{'case_id': f'case:{i}'} for i in range(64)]
        folds = folds_for_train(rows, list(range(64)))
        self.assertEqual([len(f) for f in folds], [16] * 4)
        self.assertEqual(sorted(sum(folds, [])), list(range(64)))

    def test_fail_closed_validation_without_assert(self):
        self.assertRaises(Invalid, require, False, 'deny')


if __name__ == '__main__':
    unittest.main()
