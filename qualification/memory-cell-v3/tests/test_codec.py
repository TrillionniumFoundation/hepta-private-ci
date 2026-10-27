import hashlib
import unittest

import numpy as np

from v3.codec import (
    compress_bytes,
    decode_exact,
    decode_factor,
    decompress_bytes,
    encode_factor,
    exact_matrix_archives,
    read_signed_varints,
    signed_varints,
)
from v3.factor_cell import FactorBank


class NumericCodecTests(unittest.TestCase):
    def test_residual_round_trip_is_distinct_from_parameter_read(self):
        values = np.array(
            [[30, -7, 12], [-20, 18, 31], [12, 42, -25], [50, -2, 9]], dtype=np.int32
        )
        mask = np.ones(values.shape, dtype=bool)
        mask[2, 1] = False
        values[2, 1] = 0
        bank, _ = FactorBank.fit(values, ranks=[1], mask=mask)
        loaded = FactorBank.from_bytes(bank.to_bytes(), bank.digest)
        self.assertGreater(
            np.count_nonzero(loaded.reconstruct()[mask] != values[mask]), 0
        )
        for mode in ("embedded", "external"):
            for compressor in ("raw", "zlib", "lzma", "best"):
                archive, receipt = encode_factor(
                    loaded, values, model_storage=mode, method=compressor
                )
                restored, observed = decode_factor(
                    archive,
                    model=loaded if mode == "external" else None,
                    expected_sha256=receipt["archive_sha256"],
                )
                np.testing.assert_array_equal(values, restored)
                np.testing.assert_array_equal(mask, observed)
                self.assertEqual(
                    receipt["complete_standalone_bytes"],
                    len(archive)
                    + (len(loaded.to_bytes()) if mode == "external" else 0),
                )
                self.assertFalse(receipt["parameter_only_readout"])
        archive, _ = encode_factor(loaded, values)
        with self.assertRaises(ValueError):
            decode_factor(archive)
        other, _ = FactorBank.fit(values, ranks=[0], mask=mask)
        with self.assertRaises(ValueError):
            decode_factor(archive, model=other)
        with self.assertRaises(ValueError):
            decode_factor(archive, model=loaded, expected_sha256="0" * 64)

    def test_all_strong_exact_baselines_round_trip(self):
        cases = [
            np.array([[0, 0], [0, 0]], dtype=np.int32),
            np.array([[-(2**31), 2**31 - 1], [-4, 12]], dtype=np.int32),
            np.arange(-9, 9, dtype=np.int32).reshape(6, 3),
        ]
        for values in cases:
            for missing in (False, True):
                mask = np.ones(values.shape, dtype=bool)
                matrix = values.copy()
                if missing:
                    mask[0, 0] = False
                    matrix[0, 0] = 0
                archives = exact_matrix_archives(matrix, mask)
                self.assertEqual(len(archives), 12)
                for name, archive in archives.items():
                    with self.subTest(case=matrix.tolist(), baseline=name):
                        restored, observed = decode_exact(
                            archive, hashlib.sha256(archive).hexdigest()
                        )
                        np.testing.assert_array_equal(matrix, restored)
                        np.testing.assert_array_equal(mask, observed)
                        with self.assertRaises(ValueError):
                            decode_exact(archive, "0" * 64)

    def test_canonical_varints_and_bounded_decompression(self):
        values = np.array([-(2**63), -1, 0, 1, 2**63 - 1], dtype=np.int64)
        np.testing.assert_array_equal(
            read_signed_varints(signed_varints(values), len(values)), values
        )
        for payload, count in (
            (b"\x80", 1),
            (b"\x80\x00", 1),
            (b"\x00\x00", 1),
            (b"\xff" * 10, 1),
            (b"\xff" * 9 + b"\x02", 1),
        ):
            with self.assertRaises(ValueError):
                read_signed_varints(payload, count)
        for method in ("raw", "zlib", "lzma"):
            archive = compress_bytes(b"x" * 4096, method)
            self.assertEqual(decompress_bytes(archive, 5000), b"x" * 4096)
            with self.assertRaises(ValueError):
                decompress_bytes(archive, 128)
            if method != "raw":
                with self.assertRaises(ValueError):
                    decompress_bytes(archive + b"trailing")
        for payload in (b"", b"\x03", b"\x00garbage"):
            with self.assertRaises(ValueError):
                decode_exact(payload)


if __name__ == "__main__":
    unittest.main()
