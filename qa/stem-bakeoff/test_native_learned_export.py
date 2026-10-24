"""Synthetic framing checks; the full Rust/NumPy comparison uses frozen real data."""

import hashlib
import struct
import unittest

import numpy as np

from cell_learning_models import NumpyCellHead
from native_learned_export import (FEATURE_MAGIC, HEAD_MAGIC, MODES, encode_features,
                                   encode_head)


class NativeLearnedExportTests(unittest.TestCase):
    def test_feature_payload_keeps_raw_values_and_ordered_sources(self):
        x = np.linspace(-2, 3, 2*770, dtype=np.float32).reshape(2, 770)
        sources = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(2)]
        identity = "12"*32
        expected = (FEATURE_MAGIC+bytes.fromhex(identity)+struct.pack("<QQ", 3, 2)
            + b"".join(bytes.fromhex(s) for s in sources)+x.astype("<f8").tobytes())
        self.assertEqual(encode_features(x, sources, identity, 3), expected)
        self.assertNotEqual(encode_features(x, sources[::-1], identity, 3), expected)

    def test_head_payload_retains_all_arrays_and_original_digest(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                head = NumpyCellHead(770, 2, mode, rank=4)
                head.feature_identity = "12"*32
                for i, value in enumerate(head.params.values()):
                    value += (i+1)*.001
                expected = (HEAD_MAGIC+bytes([MODES.index(mode)])+bytes.fromhex("12"*32)
                    + struct.pack("<Q", 3)+hashlib.sha256(b"action_usefulness").digest()
                    + bytes.fromhex(head.digest())
                    + b"".join(head.params[k].tobytes() for k in sorted(head.params)))
                self.assertEqual(encode_head(head, "12"*32, 3, "action_usefulness"), expected)
                head.params["b"] = head.params["b"].astype(np.float32)
                with self.assertRaises(ValueError):
                    encode_head(head, "12"*32, 3, "action_usefulness")

    def test_invalid_identity_shape_generation_and_values_fail(self):
        x = np.ones((2, 770), dtype=np.float64)
        sources = ["12"*32, "34"*32]
        cases = [(x, sources, "0"*64, 1), (x, sources, "12"*32, 0),
            (x, sources, "12"*32, True), (x, sources*2, "12"*32, 1),
            (x, sources[:1]*2, "12"*32, 1), (x[:, :769], sources, "12"*32, 1),
            (np.ones((65, 770)), sources, "12"*32, 1),
            (x*float("nan"), sources, "12"*32, 1)]
        for args in cases:
            with self.subTest(generation=args[-1], shape=args[0].shape), self.assertRaises(ValueError):
                encode_features(*args)
        head = NumpyCellHead(770, 2, rank=4)
        with self.assertRaises(ValueError):
            encode_head(head, "12"*32, 1, "action_usefulness")
        head.feature_identity = "34"*32
        with self.assertRaises(ValueError):
            encode_head(head, "12"*32, 1, "action_usefulness")
        with self.assertRaises(ValueError):
            encode_head(head, "12"*32, 1, "another-task")


if __name__ == "__main__":
    unittest.main()
