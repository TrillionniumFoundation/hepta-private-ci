"""Joint, non-owner shadow regression: frozen credit raw cap with causal MEM rotation."""
import unittest
from hashlib import sha256
from itertools import repeat
from study import (ContractError, Eligibility, Feedback, MemoryRecord,
                   frozen_credit_from_prefix, frozen_replay_from_prefix, FrozenCreditView)

def dg(s):
    return sha256(s.encode()).hexdigest()

class FrozenCreditMemoryBudgetUnionTests(unittest.TestCase):
    def credit(self, feedback):
        return frozen_credit_from_prefix(
            [Eligibility("a", dg("a"), 1, (0.5,0.25))],
            feedback, arm="routed", cutoff_sequence=5, decay=0.9, max_lag=10)

    def mem(self, events, seed):
        return frozen_replay_from_prefix(events, policy="stratified", query_key="q",
                                          now_sequence=5, max_items=1, seed=seed)

    def test_unbounded_future_suffix_refused_without_resurrecting_memory(self):
        future = Feedback(dg("future"), "a", 100, (0.0, 0.0))
        with self.assertRaisesRegex(ContractError, "size limit"):
            self.credit(repeat(future, 65_537))
        # The 65,536-row accepted raw budget still never trains on future data.
        candidate = self.credit(repeat(future, 65_536))
        self.assertIs(type(candidate), FrozenCreditView)
        self.assertEqual((candidate.matched, candidate.expired), (0,0))
        self.assertEqual(candidate.deltas, (0.0,0.0))
        self.assertEqual(candidate.authority, "DENY_ALL")

    def test_frozen_credit_and_sticky_mem_deletion_share_cutoff_invariants(self):
        visible = Feedback(dg("f"), "a", 2, (0.8, -0.5))
        future = Feedback(dg("z"), "a", 100, (0.9, 0.9))
        self.assertEqual(self.credit([visible]), self.credit([visible,future]))
        records = [
            MemoryRecord("fact-1", "fact", "q", dg("fact"), 1, logical_id="L"),
            MemoryRecord("episode-1", "episode", "q", dg("episode"), 2),
            MemoryRecord("fact-delete", "fact", "q", dg("delete"), 3, tombstoned=True, logical_id="L"),
        ]
        malformed_future = MemoryRecord("episode-1", "episode", "q", "bad-future", 100)
        for seed in ["s:"+str(i) for i in range(16)]:
            expected = self.mem(records, seed)
            self.assertEqual(expected, self.mem(records+[malformed_future], seed))
            self.assertEqual(expected, ("episode-1",))
if __name__ == "__main__":
    unittest.main()
