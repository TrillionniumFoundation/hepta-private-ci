"""Behavioral tests for real training and the shared integer artifact contract."""

import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from v3.bitcell import HEADER, IntegerBitCell, q12_inputs


class IntegerBitCellTests(unittest.TestCase):
    def test_exact_integer_rounding_and_signed_logits(self):
        cell = IntegerBitCell(
            np.array([[2048], [0]], dtype=np.int16),
            np.array([[4096, -4096], [0, 0]], dtype=np.int16),
        )
        x = np.array([[-3], [-2], [-1], [0], [1], [2], [3]], dtype=np.int16)
        np.testing.assert_array_equal(
            cell.logits_q24(x),
            [
                [-4096, 4096],
                [-4096, 4096],
                [0, 0],
                [0, 0],
                [4096, -4096],
                [4096, -4096],
                [8192, -8192],
            ],
        )
        np.testing.assert_array_equal(cell.predict(x), [2, 2, 3, 3, 1, 1, 1])
        np.testing.assert_array_equal(
            q12_inputs([[-1, -1 / 8192, 0, 1 / 8192, 1]]), [[-4096, 0, 0, 1, 4096]]
        )

    def test_real_training_reloads_and_generalizes_to_new_addresses(self):
        rng = np.random.default_rng(8011)
        x = q12_inputs(rng.uniform(-1, 1, (256, 2)))
        y = (x[:, 0] > 0).astype(np.uint32) | ((x[:, 1] > 0).astype(np.uint32) << 1)
        cell, receipt = IntegerBitCell.fit(
            x,
            y,
            hidden=8,
            bits=2,
            steps=300,
            batch_size=128,
            learning_rate=0.03,
            seed=8011,
        )
        held = q12_inputs(rng.uniform(-1, 1, (256, 2)))
        targets = (held[:, 0] > 0).astype(np.uint32) | (
            (held[:, 1] > 0).astype(np.uint32) << 1
        )
        self.assertGreaterEqual(float(np.mean(cell.predict(held) == targets)), 0.95)
        self.assertEqual(receipt["optimizer_steps"], 300)
        self.assertEqual(receipt["examples_seen"], 38400)
        self.assertGreater(receipt["optimization_seconds"], 0)
        self.assertNotEqual(
            receipt["loss_trace"][0]["batch_bce"],
            receipt["loss_trace"][-1]["batch_bce"],
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cell.bin"
            saved = cell.save(path)
            restored = IntegerBitCell.load(path, saved["sha256"])
            np.testing.assert_array_equal(
                restored.logits_q24(held), cell.logits_q24(held)
            )
            self.assertEqual(restored.to_bytes(), cell.to_bytes())
            with self.assertRaises(FileExistsError):
                cell.save(path)
            damaged = bytearray(path.read_bytes())
            damaged[-1] ^= 1
            with self.assertRaisesRegex(ValueError, "digest"):
                IntegerBitCell.from_bytes(bytes(damaged), saved["sha256"])

    def test_parent_inheritance_is_actual_and_does_not_mutate_parent(self):
        x = np.array([[-4096], [0], [4096]], dtype=np.int16)
        y = np.array([0, 1, 1], dtype=np.uint32)
        parent, _ = IntegerBitCell.fit(x, y, hidden=3, bits=1, steps=10, seed=8011)
        before = parent.to_bytes()
        child, receipt = IntegerBitCell.fit(
            x, y, hidden=2, bits=1, steps=10, seed=8017, parent=parent
        )
        self.assertEqual(parent.to_bytes(), before)
        self.assertEqual(receipt["parent_digest"], hashlib.sha256(before).hexdigest())
        self.assertEqual(len(receipt["inherited_hidden_indices"]), 2)
        self.assertNotEqual(child.digest, parent.digest)
        self.assertFalse(child.w1.flags.writeable)

    def test_malformed_artifacts_and_inputs_are_rejected(self):
        cell = IntegerBitCell(
            np.zeros((2, 1), dtype=np.int16), np.zeros((2, 1), dtype=np.int16)
        )
        payload = cell.to_bytes()
        invalid = [payload[:-1], payload + b"x", b"X" + payload[1:]]
        fields = list(HEADER.unpack_from(payload))
        fields[2] = 513
        invalid.append(HEADER.pack(*fields) + payload[HEADER.size :])
        invalid.append(
            struct.pack("<8sHHHHII", b"HMCELL3\0", 1, 1, 1, 1, 4096, 1000000)
        )
        for item in invalid:
            with self.subTest(length=len(item)), self.assertRaises(ValueError):
                IntegerBitCell.from_bytes(item)
        for x in [
            np.array([[65536]], dtype=np.int64),
            np.array([[0.5]]),
            np.array([[0, 0]], dtype=np.int16),
        ]:
            with self.assertRaises(ValueError):
                cell.predict(x)
        for x in [[[float("nan")]], [[float("inf")]], [[1.01]]]:
            with self.assertRaises(ValueError):
                q12_inputs(x)


if __name__ == "__main__":
    unittest.main()
