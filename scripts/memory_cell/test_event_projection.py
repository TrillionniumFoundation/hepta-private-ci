"""Source, correction, scope and identical-candidate tests; no pretrained scores."""

from dataclasses import replace
import json
import unittest

from event_projection import EventProjection, Lookup, PROFILE
from native import Document


def doc(
    key,
    entity="service",
    attribute="location",
    value="site_one",
    revision=1,
    supersedes=(),
):
    row = dict(
        schema=PROFILE,
        id=key,
        entity=entity,
        attribute=attribute,
        value=value,
        revision=revision,
        supersedes=list(supersedes),
    )
    return Document(
        key, "root_" + key, "scope", "scope", "2026-01-01T00:00:00Z", json.dumps(row)
    )


class EventProjectionTests(unittest.TestCase):
    def test_explicit_correction_not_last_write_wins_and_future_not_applied(self):
        rows = (
            doc("a"),
            doc("b", value="site_two", revision=2, supersedes=("a",)),
            doc("c", value="site_three", revision=3, supersedes=("b",)),
        )
        p = EventProjection(rows)
        at_one = p.select(
            Lookup("service", ("location",), 1),
            ("c", "b", "a"),
            mode="organized",
            revoked=set(),
        )
        at_two = p.select(
            Lookup("service", ("location",), 2),
            ("c", "b", "a"),
            mode="organized",
            revoked=set(),
        )
        self.assertEqual(at_one[0], ("a",))
        self.assertEqual(at_two[0], ("b",))
        self.assertEqual(
            p.select(
                Lookup("service", ("location",), 2),
                ("c", "b", "a"),
                mode="entity_time",
                revoked=set(),
            )[0],
            ("b", "a"),
        )

    def test_conflicting_heads_are_preserved_and_not_silently_truncated(self):
        p = EventProjection((doc("a"), doc("b", value="site_two", revision=2)))
        answer, receipt = p.select(
            Lookup("service", ("location",), 2),
            ("a", "b"),
            mode="organized",
            revoked=set(),
        )
        self.assertEqual(answer, ("a", "b"))
        self.assertEqual(receipt["conflicts"], 1)
        answer, receipt = p.select(
            Lookup("service", ("location",), 2),
            ("a", "b"),
            mode="organized",
            revoked=set(),
            limit=1,
        )
        self.assertEqual(answer, ())
        self.assertTrue(receipt["incomplete"])

    def test_bridge_completion_uses_only_same_candidate_pool(self):
        p = EventProjection(
            (
                doc("a", attribute="component", value="part"),
                doc("b", entity="part"),
                doc("noise", entity="other"),
            )
        )
        lookup = Lookup("service", ("component", "location"), 1)
        selected, receipt = p.select(
            lookup, ("noise", "a", "b"), mode="organized", revoked=set()
        )
        self.assertEqual(selected, ("a", "b"))
        self.assertFalse(receipt["incomplete"])
        partial, receipt = p.select(
            lookup, ("noise", "a"), mode="organized", revoked=set()
        )
        self.assertEqual(partial, ("a",))
        self.assertTrue(receipt["incomplete"])

    def test_cross_key_missing_nonmonotonic_corrections_reject(self):
        for rows in (
            (doc("a", supersedes=("missing",)),),
            (doc("a"), doc("b", entity="different", revision=2, supersedes=("a",))),
            (doc("a"), doc("b", supersedes=("a",))),
        ):
            with self.assertRaises(ValueError):
                EventProjection(rows)

    def test_bad_shape_scope_duplicates_and_revision_reject(self):
        original = doc("a")
        for rows in (
            (original, original),
            (original, replace(doc("b"), scope="other")),
            (doc("a", revision=True),),
            (replace(original, content=original.content[:-1] + ',"revision":2}'),),
        ):
            with self.assertRaises(ValueError):
                EventProjection(rows)
        with self.assertRaises(ValueError):
            Lookup("service", ("a", "b", "c", "d"), 1).validate()

    def test_current_revocation_rejects_all_paths_including_raw_hybrid(self):
        p = EventProjection((doc("a"),))
        for mode in ("hybrid", "entity_time", "organized"):
            with self.assertRaises(ValueError):
                p.select(
                    Lookup("service", ("location",), 1),
                    ("a",),
                    mode=mode,
                    revoked={"root_a"},
                )
        with self.assertRaises(ValueError):
            p.select(
                Lookup("service", ("location",), 1),
                ("invented",),
                mode="hybrid",
                revoked=set(),
            )


if __name__ == "__main__":
    unittest.main()
