"""Zero-numerical source tests for the one admitted attempt."""

import unittest

from qualification.hcsn_currentstate_n256_authentic_boundary_attempt001 import static_inspector, verify_source


class SourceTest(unittest.TestCase):
    def test_frozen_source(self):
        self.assertEqual(verify_source.verify(), "PASS_ATTEMPT001_PRECOMMIT")

    def test_static_admission(self):
        self.assertEqual(static_inspector.verify()["builder_calls"], 0)


if __name__ == "__main__":
    unittest.main()
