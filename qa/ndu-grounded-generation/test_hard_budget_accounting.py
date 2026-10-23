"""Regression: the parent must charge native work, IPC and output serialization.

These controls use real spawned resident workers, not mocked receipts. They
cannot validate Florence quality or close v2's scientific acceptance gates.
"""
import time
import unittest

from hard_budget import HardBudgetPool


def noop_initialize():
    pass


class SlowWireResult:
    def __reduce__(self):
        # Pipe.send pickles the answer after the worker stamped its result.
        # This simulated serialization overhead must still be charged.
        time.sleep(0.25)
        return (bytes, (b"slow-result",))


def return_slow_wire(_job):
    return SlowWireResult()


def reject_job(_job):
    raise ValueError("intentional failure")


class ExternalBudgetAccountingTests(unittest.TestCase):
    def test_success_receipt_charges_slow_result_serialization(self):
        with HardBudgetPool(noop_initialize, (), return_slow_wire,
                            workers=1, init_timeout=10) as pool:
            rows = list(pool.run([{"kind": "fixture"}], budget=2))
        self.assertEqual(len(rows), 1)
        index, output, receipt = rows[0]
        self.assertEqual(index, 0)
        self.assertEqual(output, b"slow-result")
        self.assertEqual(receipt["status"], "completed")
        self.assertGreaterEqual(receipt["measured_wall_seconds"], 0.20)
        self.assertFalse(receipt["worker_killed"])
        self.assertEqual(len(pool.initializations), 1)

    def test_deadline_rejects_reply_stuck_serializing(self):
        with HardBudgetPool(noop_initialize, (), return_slow_wire,
                            workers=1, init_timeout=10) as pool:
            rows = list(pool.run([{"kind": "fixture"}], budget=0.05))
        self.assertEqual(len(rows), 1)
        index, output, receipt = rows[0]
        self.assertEqual(index, 0)
        self.assertIsNone(output)
        self.assertEqual(receipt["status"], "hard_timeout")
        self.assertTrue(receipt["worker_killed"])
        self.assertGreaterEqual(receipt["measured_wall_seconds"], 0.05)
        self.assertFalse(receipt["internal_call_counts_complete"])

    def test_native_task_exception_is_not_a_completed_result(self):
        with HardBudgetPool(noop_initialize, (), reject_job,
                            workers=1, init_timeout=10) as pool:
            rows = list(pool.run([{"kind": "fixture"}], budget=2))
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0][1])
        self.assertEqual(rows[0][2]["status"], "worker_failed")
        self.assertGreater(rows[0][2]["measured_wall_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
