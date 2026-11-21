"""Static tests for the unexecuted N256 action boundary."""

import unittest

from qualification.hcsn_currentstate_n256_dense_compatible_action_boundary_intent import (
    static_inspector,
    verify_source,
)


class BoundaryIntentTest(unittest.TestCase):
    def test_action_source_is_static_and_oracle_identical(self):
        result = static_inspector.verify()
        self.assertEqual(result["status"], "PASS_STATIC_ACTION_BOUNDARY_HOLD")
        self.assertTrue(result["action_ast_identical"])
        self.assertEqual(result["numerical_calls"], 0)

    def test_complete_source_freeze(self):
        result = verify_source.verify()
        self.assertEqual(result["status"], "PASS_SOURCE_ONLY_BOUNDARY_HOLD")
        self.assertEqual(result["boundary_coordinates"], 68105)
        self.assertEqual(result["numerical_calls"], 0)


if __name__ == "__main__":
    unittest.main()
