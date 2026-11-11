"""Small invariant tests only. Never substitute for native model or independent B."""
import hashlib
from pathlib import Path
import unittest
from real_cpu_clock_counterbalance import clock_schedule

ARMS = ("uniform", "heterogeneous", "inverse_heterogeneous", "phase_shifted_heterogeneous")
SCRIPT_SHA256 = "d4fafebc2024040f87092efa4465f7bbc519a94c25ef82489eaf9fc81603d495"

class ClockControls(unittest.TestCase):
    def test_frozen_execution_script(self):
        path = Path(__file__).with_name("real_cpu_clock_counterbalance.py")
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), SCRIPT_SHA256)

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
