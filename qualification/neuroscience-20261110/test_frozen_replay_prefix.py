"""Reference-only causal replay selection: suffix isolation and no resurrection.

No production owner, attestation, neural benefit, or release authority.
"""
import unittest
from hashlib import sha256

from study import ContractError, MemoryRecord, select_replay, frozen_replay_from_prefix


def digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def rec(eid, kind, key, seq, logical=None, **kw):
    return MemoryRecord(eid, kind, key, digest(eid), seq, logical_id=logical, **kw)


class FrozenReplayPrefixTests(unittest.TestCase):
    def setUp(self):
        self.prefix = (
            rec("fact-a", "fact", "query", 1, "fact-lid"),
            rec("episode-b", "episode", "other", 2),
            rec("skill-c", "skill", "query", 3),
            rec("recovery-d", "recovery", "other", 4),
        )
        self.kw = dict(query_key="query", now_sequence=10, max_items=4, seed="seed-v1")

    def test_future_invalid_duplicate_and_revision_do_not_affect_frozen_roster(self):
        suffix = (
            MemoryRecord("fact-a", "fact", "query", "INVALID", 40, logical_id="fact-lid"),
            rec("future-identity-drift", "episode", "new", 41, "fact-lid"),
        )
        # The full forensic selector (by design) sees and rejects the suffix.
        with self.assertRaises(ContractError):
            select_replay(self.prefix + suffix, policy="exact", **self.kw)
        for policy in ("exact", "uniform", "stratified"):
            with self.subTest(policy=policy):
                frozen = frozen_replay_from_prefix(self.prefix, policy=policy, **self.kw)
                self.assertEqual(frozen, frozen_replay_from_prefix(
                    self.prefix + suffix, policy=policy, **self.kw))
        self.assertEqual(frozen_replay_from_prefix(
            self.prefix, policy="exact", **self.kw), ("skill-c", "fact-a"))

    def test_future_valid_tombstone_only_affects_later_cutoff_and_never_revives(self):
        tombstone = rec("fact-delete", "fact", "query", 20, "fact-lid", tombstoned=True)
        revival = rec("fact-revive", "fact", "query", 30, "fact-lid")
        records = self.prefix + (tombstone, revival)
        self.assertIn("fact-a", frozen_replay_from_prefix(
            records, policy="exact", **self.kw))
        at_25 = dict(self.kw, now_sequence=25)
        at_35 = dict(self.kw, now_sequence=35)
        for kw in (at_25, at_35):
            self.assertNotIn("fact-a", frozen_replay_from_prefix(
                records, policy="exact", **kw))
            self.assertNotIn("fact-revive", frozen_replay_from_prefix(
                records, policy="exact", **kw))

    def test_present_invalid_fails_closed_even_if_future_ok(self):
        bad = MemoryRecord("bad", "fact", "query", "bogus", 5)
        with self.assertRaises(ContractError):
            frozen_replay_from_prefix(self.prefix + (bad,), policy="exact", **self.kw)
        with self.assertRaises(ContractError):
            frozen_replay_from_prefix(self.prefix, policy="exact", **dict(
                self.kw, now_sequence=True))

    def test_observed_future_sequence_must_be_well_typed(self):
        bad = MemoryRecord("bad", "fact", "query", digest("bad"), "later")
        with self.assertRaises(ContractError):
            frozen_replay_from_prefix(self.prefix + (bad,), policy="uniform", **self.kw)

    def test_before_after_time_no_implicit_same_key_revocation(self):
        independent = rec("different-owner", "fact", "query", 3)
        tombstone = rec("fact-delete", "fact", "query", 20, "fact-lid", rights_revoked=True)
        result = frozen_replay_from_prefix(
            self.prefix + (independent, tombstone), policy="exact",
            **dict(self.kw, now_sequence=25))
        self.assertIn("different-owner", result)
        self.assertNotIn("fact-a", result)


if __name__ == "__main__":
    unittest.main()
