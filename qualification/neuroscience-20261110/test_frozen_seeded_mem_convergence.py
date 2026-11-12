"""Joint shadow-only regression for frozen MEM replay and seeded kind rotation.

This never attests source time or Owner custody and never asserts learned benefit.
"""
import unittest
from hashlib import sha256

from study import (ContractError, MEMORY_KINDS, MemoryRecord,
                   frozen_replay_from_prefix, select_replay)


def record(name, kind, seq, *, logical_id=None, tombstoned=False):
    return MemoryRecord(
        event_id=name, kind=kind, key="q",
        source_digest=sha256(name.encode()).hexdigest(),
        observed_sequence=seq, logical_id=logical_id, tombstoned=tombstoned,
    )


class FrozenSeededMemConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.four = [
            record("f", "fact", 1, logical_id="fact-object"),
            record("e", "episode", 2),
            record("s", "skill", 3),
            record("r", "recovery", 4),
        ]
        self.future_bad = MemoryRecord(
            "e", "episode", "q", "INVALID_FUTURE_SOURCE", 40,
        )

    def choose(self, records, cutoff, seed, policy="stratified", budget=1):
        return frozen_replay_from_prefix(
            records, policy=policy, query_key="q",
            now_sequence=cutoff, max_items=budget, seed=seed,
        )

    def test_all_four_kinds_reachable_without_fact_first_starvation(self):
        outcomes = {self.choose(self.four, 5, f"owner-proposed-seed:{i}")[0]
                    for i in range(128)}
        self.assertEqual(outcomes, {"f", "e", "s", "r"})

    def test_future_bad_event_cannot_change_frozen_seeded_choice(self):
        for i in range(64):
            seed = f"owner-proposed-seed:{i}"
            self.assertEqual(
                self.choose(self.four, 5, seed),
                self.choose(self.four + [self.future_bad], 5, seed),
            )
        with self.assertRaises(ContractError):
            select_replay(self.four + [self.future_bad],
                          policy="stratified", query_key="q",
                          now_sequence=5, max_items=1, seed="s")

    def test_visible_tombstone_cannot_resurrect_fact_in_seeded_prefix(self):
        deletion = record("f-delete", "fact", 8, logical_id="fact-object",
                          tombstoned=True)
        attempted_revival = record("f-revive", "fact", 12,
                                   logical_id="fact-object")
        stream = self.four + [deletion, attempted_revival]
        before = {self.choose(stream, 5, f"s:{i}")[0] for i in range(128)}
        after = {self.choose(stream, 15, f"s:{i}")[0] for i in range(128)}
        self.assertEqual(before, {"f", "e", "s", "r"})
        self.assertEqual(after, {"e", "s", "r"})
        for i in range(128):
            self.assertNotIn(
                self.choose(stream, 15, f"s:{i}")[0], {"f", "f-revive", "f-delete"}
            )

    def test_full_budget_and_exact_control_do_not_change(self):
        self.assertEqual(
            self.choose(self.four + [self.future_bad], 5, "s",
                        policy="exact", budget=4),
            ("r", "s", "e", "f"),
        )
        self.assertEqual(
            set(self.choose(self.four, 5, "s", budget=4)),
            {"f", "e", "s", "r"},
        )
        self.assertEqual(set(MEMORY_KINDS),
                         {"fact", "episode", "skill", "recovery"})


if __name__ == "__main__":
    unittest.main()
