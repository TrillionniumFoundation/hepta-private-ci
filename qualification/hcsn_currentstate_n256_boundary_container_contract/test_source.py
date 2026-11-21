"""Synthetic development fixtures; these are not authentic boundary originals."""

import struct
import unittest

from qualification.hcsn_currentstate_n256_boundary_container_contract import (
    boundary_codec,
    compare_boundary,
    static_inspector,
    verify_source,
)


def synthetic_sections():
    result = {}
    for name, shape in boundary_codec.SECTION_SPECS:
        coordinates = 1
        for dimension in shape:
            coordinates *= dimension
        result[name] = bytearray(coordinates * 8)
    result["initial"][:8] = struct.pack("<Q", 0x8000000000000000)
    return result


class BoundaryContainerContractTest(unittest.TestCase):
    def test_round_trip_preserves_signed_zero(self):
        sections = synthetic_sections()
        encoded = boundary_codec.encode_boundary(sections)
        decoded = boundary_codec.decode_boundary(encoded)
        self.assertEqual(decoded["initial"][:8], struct.pack("<Q", 0x8000000000000000))
        self.assertEqual(list(decoded), [item[0] for item in boundary_codec.SECTION_SPECS])

    def test_independent_exact_comparator(self):
        encoded = boundary_codec.encode_boundary(synthetic_sections())
        result = compare_boundary.compare_exact(encoded, encoded)
        self.assertEqual(result["coordinates_compared"], 68105)
        self.assertEqual(result["mismatches"], 0)

    def test_one_coordinate_mismatch_is_red(self):
        left = synthetic_sections()
        right = synthetic_sections()
        right["lower_selector"][0:8] = struct.pack("<d", 1.0)
        with self.assertRaisesRegex(ValueError, "boundary mismatch"):
            compare_boundary.compare_exact(
                boundary_codec.encode_boundary(left),
                boundary_codec.encode_boundary(right),
            )

    def test_corruption_and_nonfinite_rejected(self):
        encoded = bytearray(boundary_codec.encode_boundary(synthetic_sections()))
        encoded[-33] ^= 1
        with self.assertRaisesRegex(ValueError, "digest"):
            boundary_codec.decode_boundary(encoded)
        sections = synthetic_sections()
        sections["initial"][:8] = struct.pack("<Q", 0x7FF0000000000000)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            boundary_codec.encode_boundary(sections)

    def test_source_contract(self):
        self.assertEqual(static_inspector.verify()["authentic_boundary_calls"], 0)
        self.assertEqual(verify_source.verify()["boundary_coordinates"], 68105)


if __name__ == "__main__":
    unittest.main()
