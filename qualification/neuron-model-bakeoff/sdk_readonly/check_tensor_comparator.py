import unittest
import numpy as np
from compare import compare_arrays


class CompareTests(unittest.TestCase):
    def test_exact(self):
        a = np.array([[1, 2]], dtype=np.float32)
        self.assertTrue(compare_arrays(a, a.copy())["bit_identical"])

    def test_dtype_mismatch(self):
        with self.assertRaises(ValueError):
            compare_arrays(np.array([1], dtype=np.float32), np.array([1], dtype=np.float64))

    def test_shape_mismatch(self):
        with self.assertRaises(ValueError):
            compare_arrays(np.array([1]), np.array([[1]]))

    def test_small_mutation(self):
        with self.assertRaises(ValueError):
            compare_arrays(np.array([1.0]), np.array([1.0 + 1e-15]))

    def test_nonfinite(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                compare_arrays(np.array([value]), np.array([value]))

    def test_signed_zero_is_byte_difference(self):
        with self.assertRaises(ValueError):
            compare_arrays(np.array([0.0]), np.array([-0.0]))


class RecordedArrayTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = self.root / "tensor.npy"
        np.save(path, np.array([[1, 2]], dtype=np.int64), allow_pickle=False)
        self.entry = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "shape": [1, 2], "dtype": "torch.int64"}

    def test_valid_record(self):
        from compare import load_recorded_array
        self.assertEqual(load_recorded_array(self.root, self.entry).tolist(), [[1, 2]])

    def test_invalid_metadata_rejects(self):
        from compare import load_recorded_array
        for key, value in (("shape", [2]), ("dtype", "float64"), ("sha256", "0" * 64), ("file", "../tensor.npy")):
            with self.subTest(key=key), self.assertRaises((ValueError, FileNotFoundError)):
                load_recorded_array(self.root, {**self.entry, key: value})


if __name__ == "__main__":
    unittest.main()
