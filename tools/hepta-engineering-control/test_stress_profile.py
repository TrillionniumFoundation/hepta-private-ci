import unittest

from control_engineering_v2.stress_profile import build_stress_profile


class StressProfileTests(unittest.TestCase):
    def test_bounded_small_profile_survives_reopen_and_contention(self):
        value = build_stress_profile(
            crash_reopens=1,
            concurrent_writers=2,
            growth_records=3,
        )
        self.assertEqual(value["schema"], "hepta.control-engineering-stress-profile.v1")
        self.assertGreaterEqual(value["measurements"]["envelopeCount"], 6)
        self.assertFalse(value["runtimeAuthority"])
        self.assertFalse(value["releaseAuthority"])


if __name__ == "__main__":
    unittest.main()
