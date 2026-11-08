"""Negative gates for owner eligibility and the fixed stream."""

from dataclasses import replace
import random
import unittest

from environment import Experience, Owner, ReplayPool, schedule


def experience(owner, source):
    fact = owner.facts[source]
    return Experience(source, fact.version, owner.features[source], fact.label, 1, 0.4, source[0], owner.generation)


class OwnerTests(unittest.TestCase):
    def test_revocation_between_selection_and_training_fails(self):
        owner = Owner(0)
        selected = experience(owner, "A:10")
        self.assertIsNotNone(owner.support(selected))
        owner.change_rules_and_revoke()
        self.assertIsNone(owner.support(selected))
        self.assertIsNone(owner.resolve("A:10"))
        self.assertIsNone(owner.resolve("A:11"))

    def test_replacement_retains_current_fact_but_rejects_old_training(self):
        owner = Owner(2)
        old = experience(owner, "A:8")
        owner.change_rules_and_revoke()
        current = experience(owner, "A:8")
        self.assertNotEqual(old.label, current.label)
        self.assertIsNone(owner.support(old))
        self.assertIsNotNone(owner.support(current))
        self.assertEqual(owner.resolve("A:8").version, 2)

    def test_recall_does_not_grant_replay(self):
        owner = Owner(3)
        owner.facts["A:0"] = replace(owner.facts["A:0"], replay=False)
        self.assertIsNotNone(owner.resolve("A:0", "Recall"))
        self.assertIsNone(owner.resolve("A:0", "Replay"))
        self.assertIsNone(owner.support(experience(owner, "A:0")))

    def test_current_fact_cannot_back_a_corrupted_training_target(self):
        owner = Owner(3)
        row = experience(owner, "A:0")
        self.assertIsNone(owner.support(replace(row, label=(row.label + 1) % 8)))
        self.assertIsNotNone(owner.support(row))

    def test_replay_selector_rechecks_all_four_strata(self):
        owner, pool = Owner(4), ReplayPool()
        for source in owner.facts:
            pool.add(experience(owner, source))
        owner.change_rules_and_revoke()
        fresh = ReplayPool()
        for row in pool.rows.values():
            fact = owner.resolve(row.source, "Replay", row.version)
            if fact is not None:
                fresh.add(replace(row, key_generation=owner.generation))
        pool = fresh
        rng = random.Random(0)
        for index in range(64):
            row = pool.sample(owner, rng, "structured", index)
            self.assertNotIn(row.source, {"A:8", "A:9", "A:10", "A:11"})
            self.assertIsNotNone(owner.support(row))

    def test_pool_is_bounded_and_keeps_latest_source_version(self):
        owner, pool = Owner(1), ReplayPool()
        for source in owner.facts:
            pool.add(experience(owner, source))
        owner.change_rules_and_revoke()
        pool.add(experience(owner, "A:8"))
        self.assertEqual(len(pool.rows), 24)
        self.assertEqual(pool.rows["A:8"].version, 2)

    def test_stream_has_relearning_and_excludes_revoked_training(self):
        for seed in range(5):
            phases = schedule(seed)
            self.assertEqual([phase for phase, _ in phases], ["A1", "B", "A2"])
            self.assertEqual([len(rows) for _, rows in phases], [96, 104, 40])
            for _, rows in phases[1:]:
                self.assertTrue({"A:10", "A:11"}.isdisjoint(rows))


if __name__ == "__main__":
    unittest.main()
