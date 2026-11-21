"""Static tests for the execution-disabled dense-compatible action intent."""

import unittest

from qualification.hcsn_currentstate_n256_dense_compatible_action_intent import (
    verify_source,
)


class IntentTest(unittest.TestCase):
    def test_source_only_hold(self):
        result = verify_source.verify()
        self.assertEqual(result["status"], "PASS_SOURCE_ONLY_HOLD")
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["numerical_calls"], 0)


if __name__ == "__main__":
    unittest.main()
