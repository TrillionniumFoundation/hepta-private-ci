import math
import hashlib
import json
import unittest

from cell_field_fixed_actions import development_role_admission, fixed_library


class LibraryTests(unittest.TestCase):
    def test_golden_vector_digest(self):
        expected = {
            36: "4d832a2c9af678e780c16dde34c740cf51b882e9fc38811de5daf88bcd453f66",
            52: "7bc6e85c1bd69cc965a4149504c295b31e34b91704aa60dfea081981f5bae003",
        }
        for p, digest in expected.items():
            payload = json.dumps([[name, [v.hex() for v in vector]]
                                  for name, vector in fixed_library(p)],
                                 separators=(",", ":")).encode("ascii")
            self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)

    def test_fixed_size_identity_and_determinism(self):
        for p in (36, 52):
            rows = fixed_library(p)
            self.assertEqual(rows, fixed_library(p))
            self.assertEqual(len(rows), 49)
            self.assertEqual(len({name for name, _ in rows}), 49)
            self.assertEqual(len({u for _, u in rows}), 49)
            self.assertEqual(rows[0], ("zero", (0.0,) * p))

    def test_coordinate_and_physical_budget(self):
        for p in (36, 52):
            for _, u in fixed_library(p):
                self.assertTrue(all(math.isfinite(v) for v in u))
                self.assertLessEqual(max(map(abs, u)), 1 / math.sqrt(p))
                self.assertLessEqual(0.02 * math.sqrt(sum(v*v for v in u)), 0.02 + 1e-15)

    def test_antipodes(self):
        for p in (36, 52):
            rows = fixed_library(p)
            for i in range(1, 49, 2):
                self.assertEqual(tuple(-v for v in rows[i][1]), rows[i+1][1])

    def test_amplitude_norms_match_across_head_dimensions(self):
        for p in (36, 52):
            rows = fixed_library(p)
            for direction in range(8):
                for amplitude_index, amplitude in enumerate((0.125, 0.5, 1.0)):
                    for polarity in range(2):
                        u = rows[1 + direction*6 + amplitude_index*2 + polarity][1]
                        self.assertAlmostEqual(math.sqrt(sum(v*v for v in u)), amplitude, places=14)

    def test_dimension_rejection(self):
        for p in (True, 36.0, "36", 0, 108, 156, None):
            with self.assertRaises(ValueError):
                fixed_library(p)

    def test_final_and_validation_rejected(self):
        for role in ("old_test", "future_june", "future_july", "future_august",
                     "old_validation", "current_validation", "OLD_TRAIN", None):
            with self.assertRaises(ValueError):
                development_role_admission(["old_train", role])

    def test_role_contract(self):
        self.assertEqual(development_role_admission(["old_train", "current_probe"]),
                         ("old_train", "current_probe"))
        for invalid in ([], {}, "old_train", ["old_train", "old_train"]):
            with self.assertRaises(ValueError):
                development_role_admission(invalid)


if __name__ == "__main__":
    unittest.main()
