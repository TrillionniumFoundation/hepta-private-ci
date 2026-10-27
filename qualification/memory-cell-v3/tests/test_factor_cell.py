"""Actual fitted numeric-memory persistence and bounded readout tests."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from v3.factor_cell import FactorBank, HEADER


class FactorCellTests(unittest.TestCase):
    def test_fitted_numeric_values_survive_only_parameter_artifact(self):
        matrix = np.array(
            [[10, -4, 7], [20, 2, 1], [15, 13, -8], [3, 8, 16]], dtype=np.int32
        )
        bank, receipt = FactorBank.fit(matrix, ranks=[3], seed=8011)
        np.testing.assert_array_equal(bank.reconstruct(), matrix)
        self.assertEqual(bank.read([3, 0, 2], [2, 1, 0]), [16, -4, 15])
        self.assertEqual(receipt["svd_calls"], 1)
        self.assertEqual(receipt["optimizer_steps"], 0)
        self.assertGreater(receipt["fit_wall_seconds"], 0)
        self.assertEqual(receipt["artifact_bytes"], 20 + 8 + 4 * 3 + 2 * 3 * (4 + 3))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "numeric.bin"
            artifact = bank.save(path)
            loaded = FactorBank.load(path, artifact["sha256"])
            self.assertEqual(loaded.read([3, 0, 2], [2, 1, 0]), [16, -4, 15])
            self.assertEqual(loaded.to_bytes(), bank.to_bytes())
            corrupted = bytearray(path.read_bytes())
            corrupted[-2] ^= 1
            with self.assertRaisesRegex(ValueError, "digest"):
                FactorBank.from_bytes(bytes(corrupted), artifact["sha256"])

    def test_routes_mask_and_center_only_cells_are_preserved(self):
        matrix = np.array(
            [[1, 3, 0], [1, 3, 5], [10, 20, 30], [10, 20, 30]], dtype=np.int32
        )
        mask = np.ones(matrix.shape, dtype=bool)
        mask[0, 2] = False
        routes = np.array([0, 0, 1, 1], dtype=np.uint8)
        bank, receipt = FactorBank.fit(matrix, ranks=[0, 0], routes=routes, mask=mask)
        self.assertEqual(bank.read([0, 1, 2, 3], [2, 2, 0, 1]), [None, 5, 10, 20])
        self.assertEqual(receipt["svd_calls"], 0)
        self.assertEqual(receipt["availability_mask_bytes"], 2)
        self.assertEqual(receipt["routing_bytes"], 1)
        loaded = FactorBank.from_bytes(bank.to_bytes(), bank.digest)
        np.testing.assert_array_equal(loaded.routes, routes)
        np.testing.assert_array_equal(loaded.mask, mask)
        self.assertEqual(loaded.read([0, 1, 2], [2, 2, 0]), [None, 5, 10])

    def test_missing_value_fit_never_returns_an_observed_fact_for_missing_key(self):
        matrix = np.array([[10, 11, 12], [20, 0, 22], [30, 31, 32]], dtype=np.int32)
        mask = np.ones(matrix.shape, dtype=bool)
        mask[1, 1] = False
        bank, receipt = FactorBank.fit(matrix, ranks=[1], mask=mask, imputation_steps=8)
        self.assertIsNone(bank.read([1], [1])[0])
        self.assertEqual(receipt["svd_calls"], 9)
        loaded = FactorBank.from_bytes(bank.to_bytes())
        self.assertIsNone(loaded.read([1], [1])[0])
        np.testing.assert_array_equal(loaded.reconstruct(), bank.reconstruct())

    def test_rank_scope_and_malformed_data_are_rejected(self):
        matrix = np.arange(12, dtype=np.int32).reshape(4, 3)
        with self.assertRaises(ValueError):
            FactorBank.fit(matrix, ranks=[4])
        with self.assertRaises(ValueError):
            FactorBank.fit(matrix, ranks=[1, 1], routes=np.array([0, 0, 2, 2]))
        bank, _ = FactorBank.fit(matrix, ranks=[1])
        for payload in [
            bank.to_bytes()[:-1],
            bank.to_bytes() + b"x",
            b"x" + bank.to_bytes()[1:],
        ]:
            with self.assertRaises(ValueError):
                FactorBank.from_bytes(payload)
        fields = list(HEADER.unpack_from(bank.to_bytes()))
        fields[1] = 1_000_001
        with self.assertRaises(ValueError):
            FactorBank.from_bytes(HEADER.pack(*fields) + bank.to_bytes()[HEADER.size :])
        with self.assertRaises(ValueError):
            bank.read([-1], [0])
        with self.assertRaises(ValueError):
            bank.read([0], [3])

    def test_full_eight_bit_route_identity_survives_256_cells(self):
        matrix = np.arange(-256, 256, dtype=np.int32).reshape(256, 2)
        routes = np.arange(256, dtype=np.uint16)
        bank, receipt = FactorBank.fit(matrix, ranks=[0] * 256, routes=routes)
        loaded = FactorBank.from_bytes(bank.to_bytes(), bank.digest)
        self.assertEqual(receipt["routing_bytes"], 256)
        np.testing.assert_array_equal(loaded.routes, routes)
        self.assertEqual(loaded.read([0, 128, 255], [0, 1, 1]), [-256, 1, 255])
        self.assertEqual(len(loaded.to_bytes()), 20 + 256 + 256 * (8 + 8))
        with self.assertRaises(ValueError):
            FactorBank.fit(
                np.zeros((257, 2), dtype=np.int32),
                ranks=[0] * 257,
                routes=np.arange(257),
            )


if __name__ == "__main__":
    unittest.main()
