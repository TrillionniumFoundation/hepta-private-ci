"""Small invariant tests only. Never substitute for native model or independent B."""
from pathlib import Path
import sys
import unittest
from real_cpu_clock_counterbalance import clock_schedule

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "qa/repository-consolidation/20261115"))
from restore_raw_evidence import read_verified

ARMS = ("uniform", "heterogeneous", "inverse_heterogeneous", "phase_shifted_heterogeneous")
SCRIPT_SHA256 = "d4fafebc2024040f87092efa4465f7bbc519a94c25ef82489eaf9fc81603d495"

class ClockControls(unittest.TestCase):
    def test_frozen_execution_script(self):
        path = Path(__file__).resolve().with_name("real_cpu_clock_counterbalance.py")
        original = read_verified(
            REPOSITORY, path.relative_to(REPOSITORY), 14905, SCRIPT_SHA256
        )
        self.assertIn(path.read_bytes(), (original, original[:-1]))

    def test_group_opportunity(self):
        vals = [clock_schedule(a, 12) for a in ARMS]
        self.assertEqual(list(map(len, vals)), [12] * 4)
        self.assertEqual([v.count(0) for v in vals], [6, 9, 3, 9])
        self.assertEqual([v.count(1) for v in vals], [6, 3, 9, 3])
        self.assertEqual(len(set(vals)), 4)

    def test_phase_control_preserves_allocation(self):
        a = clock_schedule("heterogeneous", 12)
        b = clock_schedule("phase_shifted_heterogeneous", 12)
        self.assertNotEqual(a,b)
        self.assertEqual(sorted(a), sorted(b))
        self.assertEqual(a, (0,0,0,1) * 3)
        self.assertEqual(b, (1,0,0,0) * 3)

    def test_inverse_counterbalance(self):
        a = clock_schedule("heterogeneous",12)
        b = clock_schedule("inverse_heterogeneous",12)
        self.assertEqual(b, tuple(1-x for x in a))

    def test_unknown_arm_rejected(self):
        with self.assertRaises(ValueError):
            clock_schedule("future",12)

if __name__ == "__main__":
    unittest.main()
