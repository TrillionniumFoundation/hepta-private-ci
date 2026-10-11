"""Repeat exact 4096-step cross-language Q24 oracle golden digests."""
import unittest

import q24_temporal_fuzz as fuzz


class Q24FuzzGoldenTests(unittest.TestCase):
    def test_seeded_v3_and_ssm_golden_digests(self) -> None:
        report = fuzz.produce(4096)
        self.assertEqual(report["gate_stream_sha256"],
                         "d92a35f9f9415b62a4eb4ac60ad3614c605a9796d1ffc46084b205e8399d29ac")
        self.assertEqual(report["ssm_stream_sha256"],
                         "d863ccff0948d5f34f7080d3d040df57388e15417a820e56c4c1c52cac64f61b")
        self.assertEqual(report["last_v3_temporal_q24"], -98565713)
        self.assertEqual(report["last_ssm_temporal_q24"], -65761034)
        self.assertEqual(report["max_elapsed_steps"], 30)
        self.assertEqual(report["clamp_visits"], 0)
        self.assertEqual(report["qualification"], "ARITHMETIC_ONLY_NOT_NATIVE_OR_TARGET_HOST")

    def test_seed_is_stable_across_repeats(self) -> None:
        self.assertEqual(fuzz.produce(128), fuzz.produce(128))
        self.assertNotEqual(fuzz.produce(127), fuzz.produce(128))


if __name__ == "__main__":
    unittest.main()
