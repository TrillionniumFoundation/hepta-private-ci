import tempfile
import unittest
from pathlib import Path

from .cost import AdmissionRefused, Budget, BudgetExceeded


class CostTests(unittest.TestCase):
    def test_real_tail_and_phase_admission(self):
        with tempfile.TemporaryDirectory() as d:
            now = [60]
            b = Budget(d, clock=lambda: now[0], memory=lambda: 0,
                       total_ns=100, byte_cap=20, rss_cap=10)
            b.check(20, tail_ns=20)
            with self.assertRaises(BudgetExceeded):
                b.check(21, tail_ns=20)
            with self.assertRaises(BudgetExceeded):
                b.check(5, start_ns=30, phase_ns=40, phase_tail_ns=6)
            now[0] = 101
            with self.assertRaises(BudgetExceeded):
                b.row("overrun", 60)

    def test_actual_phase_overrun_is_not_a_normal_forecast_stop(self):
        with tempfile.TemporaryDirectory() as d:
            now = [39]
            b = Budget(d, clock=lambda: now[0], memory=lambda: 0, total_ns=100)
            with self.assertRaises(AdmissionRefused):
                b.check(2, phase_ns=40)
            now[0] = 41
            try:
                b.check(2, phase_ns=40)
            except BudgetExceeded as error:
                self.assertNotIsInstance(error, AdmissionRefused)
            else:
                self.fail("actual phase overrun was accepted")

    def test_storage_and_RSS_are_actual(self):
        with tempfile.TemporaryDirectory() as d:
            b = Budget(d, clock=lambda: 0, memory=lambda: 10,
                       total_ns=100, byte_cap=4, rss_cap=10)
            Path(d, "partial").write_bytes(b"1234")
            b.check()
            with self.assertRaises(BudgetExceeded):
                b.check(extra_bytes=1)
            b.memory = lambda: 11
            with self.assertRaises(BudgetExceeded):
                b.check()


if __name__ == "__main__":
    unittest.main()
