"""Zero-dynamics unit controls for the N256 t=0 capsule lane."""

import hashlib
import struct
import unittest
from fractions import Fraction

from qualification.hcsn_currentstate_n256_t0_capsule_v1 import builder


class CapsuleControls(unittest.TestCase):
    def test_state_denominator_and_order(self):
        active = tuple(float(index) for index in range(257))
        content = tuple(float(index) / 10 for index in range(257 * 4))
        blocks = builder.state_blocks(active, content)
        self.assertEqual(list(blocks), ["active", "discounted_hit", "lower_hit", "occupation", "upper"])
        self.assertEqual(sum(len(values) for _, values in blocks.values()), 2600)
        self.assertEqual(blocks["active"][0], (5, 2, 255))
        self.assertEqual(blocks["upper"][1][0:3], (256.0, 0.0, 0.0))

    def test_packet_identity_is_stable_and_field_bound(self):
        first = builder.source_identity("bundle", "kind", Fraction(1, 7), Fraction(2, 7))
        second = builder.source_identity("bundle", "kind", Fraction(1, 7), Fraction(2, 7))
        changed = builder.source_identity("bundle", "kind2", Fraction(1, 7), Fraction(2, 7))
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertEqual(len(bytes.fromhex(first)), hashlib.sha256().digest_size)

    def test_all_state_values_remain_fp64_bytes(self):
        blocks = builder.state_blocks((0.25,) * 257, tuple(index / 997 for index in range(1028)))
        for _, values in blocks.values():
            self.assertEqual(len(struct.pack(f"<{len(values)}d", *values)), 8 * len(values))

    def test_wrong_shapes_reject(self):
        with self.assertRaisesRegex(ValueError, "authentic N256"):
            builder.state_blocks((0.0,) * 256, (0.0,) * 1028)


if __name__ == "__main__":
    unittest.main()
