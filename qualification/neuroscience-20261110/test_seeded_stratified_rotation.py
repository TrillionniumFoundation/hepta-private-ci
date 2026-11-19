"""Small shadow-only regression: stratified per-kind budget must not favor fact."""
import unittest
from hashlib import sha256

from study import MEMORY_KINDS, MemoryRecord, select_replay


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


class SeededStratifiedRotationTests(unittest.TestCase):
    def records(self):
        return [
            MemoryRecord("id:" + kind, kind, "shared", digest("source:" + kind), 1)
            for kind in MEMORY_KINDS
        ]

    def test_narrow_budget_seed_changes_the_starting_kind(self):
        records = self.records()
        chosen = {
            select_replay(records, policy="stratified", query_key="shared",
                          now_sequence=2, max_items=1, seed="fixed-owner-seed:" + str(i))[0]
            for i in range(64)
        }
        self.assertEqual(chosen, {"id:" + kind for kind in MEMORY_KINDS})

    def test_stable_under_input_reordering_and_repeat_reads(self):
        records = self.records()
        for seed in ("s0", "s1", "s2", "s3"):
            original = select_replay(records, policy="stratified", query_key="shared",
                                     now_sequence=2, max_items=3, seed=seed)
            self.assertEqual(original, select_replay(list(reversed(records)),
                                                     policy="stratified", query_key="shared",
                                                     now_sequence=2, max_items=3, seed=seed))
            self.assertEqual(original, select_replay(records, policy="stratified",
                                                     query_key="shared", now_sequence=2,
                                                     max_items=3, seed=seed))

    def test_full_budget_and_exact_key_unchanged(self):
        records = self.records()
        for seed in ("s0", "s1", "s2"):
            self.assertEqual(set(select_replay(records, policy="stratified",
                                               query_key="shared", now_sequence=2,
                                               max_items=4, seed=seed)),
                             {"id:" + kind for kind in MEMORY_KINDS})
            self.assertEqual(
                select_replay(records, policy="exact", query_key="shared",
                              now_sequence=2, max_items=4, seed=seed),
                ("id:episode", "id:fact", "id:recovery", "id:skill"),
            )

    def test_tombstoned_kind_does_not_reappear_through_rotation(self):
        records = self.records() + [
            MemoryRecord("id:skill-delete", "skill", "shared",
                         digest("delete-skill"), 2, tombstoned=True,
                         logical_id="skill")
        ]
        # Explicit logical IDs are intentionally separate from implicit event
        # identities. Construct proper prior revision with matching logical ID.
        records = [r for r in records if r.event_id != "id:skill"] + [
            MemoryRecord("id:skill", "skill", "shared", digest("source:skill"),
                         1, logical_id="skill")
        ]
        for i in range(16):
            selected = select_replay(records, policy="stratified", query_key="shared",
                                     now_sequence=3, max_items=4, seed=str(i))
            self.assertNotIn("id:skill", selected)
            self.assertNotIn("id:skill-delete", selected)


if __name__ == "__main__":
    unittest.main()
