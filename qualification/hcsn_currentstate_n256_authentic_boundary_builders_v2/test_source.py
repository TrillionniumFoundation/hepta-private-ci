"""Source-only v2 tests."""

import unittest

from qualification.hcsn_currentstate_n256_authentic_boundary_builders_v2 import static_inspector, verify_source


class SourceTest(unittest.TestCase):
    def test_complete_freeze(self):
        self.assertEqual(verify_source.verify(), "PASS_V2_SOURCE_FREEZE")

    def test_symmetric_layout_repair(self):
        result = static_inspector.verify()
        self.assertEqual(result["canonicalizations_per_builder"], 1)
        self.assertEqual(result["builder_calls"], 0)


if __name__ == "__main__":
    unittest.main()
