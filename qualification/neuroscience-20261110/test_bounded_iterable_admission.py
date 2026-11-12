import unittest
from hashlib import sha256
from study import (ContractError, Eligibility, Feedback, MemoryRecord,
                   TrialRow, time_aligned_credit, select_replay, paired_evidence)

def bounded_then_raise(item, limit):
    # A correct bounded reader inspects at most limit + 1 items.
    for _ in range(limit + 1):
        yield item
    raise AssertionError("forensic input over-read past declared raw cap")

class BoundedIteratorAdmissionTests(unittest.TestCase):
    def test_forensic_actions_bound_before_materialization(self):
        action = Eligibility("a", "a" * 64, 1, (0.5,))
        with self.assertRaises(ContractError):
            time_aligned_credit(bounded_then_raise(action, 65536), [],
                                arm="routed", cutoff_sequence=2, decay=1.0, max_lag=1)

    def test_forensic_feedback_bound_before_materialization(self):
        action = Eligibility("a", "a" * 64, 1, (0.5,))
        feedback = Feedback("f" * 64, "a", 2, (0.5,))
        with self.assertRaises(ContractError):
            time_aligned_credit([action], bounded_then_raise(feedback, 65536),
                                arm="routed", cutoff_sequence=2, decay=1.0, max_lag=1)

    def test_forensic_memory_bound_before_materialization(self):
        item = MemoryRecord("e", "fact", "key", "a" * 64, 1)
        with self.assertRaises(ContractError):
            select_replay(bounded_then_raise(item, 65536), policy="exact",
                          query_key="key", now_sequence=2, max_items=1, seed="s")

    def test_paired_trial_raw_bound_before_materialization(self):
        row = TrialRow("ep", 1, "task", "routed", "a"*64, "b"*64,
                       "c"*64, 1, 1, 1, 1, 1.0, 0.1, 1.0, False, "d"*64)
        with self.assertRaises(ContractError):
            paired_evidence(bounded_then_raise(row, 400000))

if __name__ == "__main__":
    unittest.main()
