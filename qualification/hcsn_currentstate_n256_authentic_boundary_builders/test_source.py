"""Static-only tests; authentic builders and comparator are never imported."""

import unittest

from qualification.hcsn_currentstate_n256_authentic_boundary_builders import (
    static_inspector,
    verify_source,
)


class AuthenticBoundaryBuilderSourceTest(unittest.TestCase):
    def test_builder_sources_stop_before_propagation(self):
        result = static_inspector.verify()
        self.assertEqual(result["status"], "PASS_STATIC_AUTHENTIC_BUILDERS_HOLD")
        self.assertEqual(result["authentic_builder_calls"], 0)
        self.assertEqual(result["propagation_calls"], 0)

    def test_complete_source_and_parent_freeze(self):
        result = verify_source.verify()
        self.assertEqual(result["boundary_coordinates"], 68105)
        self.assertEqual(result["canonical_container_bytes"], 545171)
        self.assertFalse(result["qualification"])


if __name__ == "__main__":
    unittest.main()
