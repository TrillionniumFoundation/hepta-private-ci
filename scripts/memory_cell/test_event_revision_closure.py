"""Correction-chain regressions; authored state examples, not semantic labels."""

from itertools import permutations
import unittest

from event_projection import EventProjection, Lookup
from event_revision_closure import select_current
from test_event_projection import doc


def chain():
    return (
        doc("a"),
        doc("b", value="site_b", revision=2, supersedes=("a",)),
        doc("c", value="site_c", revision=3, supersedes=("b",)),
    )


class RevisionClosureTests(unittest.TestCase):
    def select(self, rows, candidates, revision=3, limit=4, path=("location",)):
        return select_current(
            EventProjection(rows),
            Lookup("service", path, revision),
            tuple(candidates),
            revoked=set(),
            limit=limit,
        )

    def test_missing_intermediate_does_not_resurrect_old_candidate(self):
        rows = chain()
        p = EventProjection(rows)
        old, _ = p.select(
            Lookup("service", ("location",), 3),
            ("a", "c"),
            mode="organized",
            revoked=set(),
        )
        self.assertEqual(old, ("a", "c"))
        current, receipt = self.select(rows, ("a", "c"))
        self.assertEqual(current, ("c",))
        self.assertFalse(receipt["incomplete"])
        self.assertEqual(receipt["obsolete_candidates"], ["a"])
        self.assertEqual(receipt["correction_edges_read"], 2)

    def test_out_of_pool_successor_blocks_stale_read_without_injecting_it(self):
        rows = chain()[:2]
        current, receipt = self.select(rows, ("a",))
        self.assertEqual(current, ())
        self.assertTrue(receipt["incomplete"])
        self.assertEqual(receipt["missing_current_heads"], ["b"])
        self.assertEqual(receipt["injected_out_of_pool_sources"], 0)

    def test_future_correction_does_not_change_historical_read(self):
        current, receipt = self.select(chain(), ("a", "c"), revision=1)
        self.assertEqual(current, ("a",))
        self.assertFalse(receipt["incomplete"])
        self.assertEqual(receipt["active_event_reads"], 1)

    def test_newer_unlinked_fact_is_conflict_not_replacement(self):
        rows = (doc("a"), doc("b", value="site_b", revision=3))
        selected, receipt = self.select(rows, ("b", "a"))
        self.assertEqual(selected, ("b", "a"))
        self.assertEqual(receipt["conflicts"], 1)
        self.assertEqual(receipt["obsolete_candidates"], [])

    def test_missing_conflicting_head_never_releases_only_the_other(self):
        rows = (doc("a"), doc("b", value="site_b", revision=3))
        selected, receipt = self.select(rows, ("a",))
        self.assertEqual(selected, ())
        self.assertTrue(receipt["incomplete"])
        self.assertEqual(receipt["conflicts"], 1)

    def test_complete_group_respects_budget_and_retrieval_order(self):
        rows = (doc("a"), doc("b", value="site_b", revision=3))
        for order in permutations(("a", "b")):
            selected, receipt = self.select(rows, order, limit=1)
            self.assertEqual(selected, ())
            self.assertTrue(receipt["incomplete"])
            selected, receipt = self.select(rows, order, limit=2)
            self.assertEqual(selected, order)
            self.assertFalse(receipt["incomplete"])

    def test_multihop_follows_only_current_bridge(self):
        rows = (
            doc("a", attribute="component", value="old_part"),
            doc(
                "b",
                attribute="component",
                value="new_part",
                revision=2,
                supersedes=("a",),
            ),
            doc("c", entity="old_part"),
            doc("d", entity="new_part", value="site_new"),
        )
        selected, receipt = self.select(
            rows, ("c", "a", "d", "b"), path=("component", "location")
        )
        self.assertEqual(selected, ("b", "d"))
        self.assertFalse(receipt["incomplete"])

    def test_withdrawal_and_bad_candidates_reject_before_closure(self):
        p = EventProjection((doc("a"),))
        lookup = Lookup("service", ("location",), 1)
        with self.assertRaises(ValueError):
            select_current(p, lookup, ("a",), revoked={"root_a"})
        with self.assertRaises(ValueError):
            select_current(p, lookup, ("missing",), revoked=set())

    def test_ancestry_missing_from_source_view_is_not_assumed(self):
        with self.assertRaises(ValueError):
            self.select((doc("b", revision=2, supersedes=("missing",)),), ("b",))


if __name__ == "__main__":
    unittest.main()
