"""Authored source-only two-hop admissions, not pretrained model scores."""

from dataclasses import replace
import json
import unittest

from event_projection import PROFILE
from native import Document
from source_composition_curriculum import compositions, combine_source_examples


def event(identity, entity, attribute, value, revision=1, supersedes=(), scope="a"):
    content = dict(
        schema=PROFILE,
        id=identity,
        entity=entity,
        attribute=attribute,
        value=value,
        revision=revision,
        supersedes=list(supersedes),
    )
    return Document(
        identity,
        "root_" + identity,
        scope,
        scope,
        "2026-10-11T00:00:00+00:00",
        json.dumps(content, sort_keys=True),
    )


def fixture(scope="a"):
    suffix = "" if scope == "a" else "_b"
    return (
        event("bridge" + suffix, "service", "component", "component_a", scope=scope),
        event("old" + suffix, "component_a", "location", "site_old", scope=scope),
        event(
            "new" + suffix,
            "component_a",
            "location",
            "site_new",
            2,
            ("old" + suffix,),
            scope=scope,
        ),
        event("noise" + suffix, "other", "location", "site_noise", scope=scope),
        event(
            "future" + suffix,
            "component_a",
            "location",
            "site_future",
            3,
            scope=scope,
        ),
    )


def compile_examples(rows, **kwargs):
    return compositions(
        rows,
        revision=kwargs.pop("revision", 2),
        allowed_roots={r.root for r in rows},
        revoked=kwargs.pop("revoked", set()),
        **kwargs,
    )


class SourceCompositionTests(unittest.TestCase):
    def test_two_hop_targets_are_source_bound_and_revision_correct(self):
        rows, unresolved = compile_examples(fixture())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target"], "site_new")
        self.assertEqual(set(rows[0]["sources"]), {"bridge", "new"})
        self.assertNotIn("site_new", rows[0]["query"]["content"])
        self.assertEqual(unresolved, ())

    def test_input_permutation_and_past_revision(self):
        rows = fixture()
        self.assertEqual(
            compile_examples(rows), compile_examples(tuple(reversed(rows)))
        )
        past, _ = compile_examples(rows, revision=1)
        self.assertEqual(past[0]["target"], "site_old")
        self.assertEqual(set(past[0]["sources"]), {"bridge", "old"})

    def test_conflict_does_not_become_positive_supervision(self):
        docs = fixture() + (
            event("other_head", "component_a", "location", "site_competing", 2),
        )
        examples, problems = compile_examples(docs)
        self.assertEqual(examples, ())
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["status"], "ambiguous_or_incomplete")

    def test_future_and_revocation_fail_closed(self):
        rows = fixture()
        self.assertNotIn(
            "site_future",
            [item["target"] for item in compile_examples(rows)[0]],
        )
        with self.assertRaises(ValueError):
            compile_examples(rows, revoked={"root_bridge"})
        with self.assertRaises(ValueError):
            compositions(
                rows,
                revision=2,
                allowed_roots={"root_new"},
                revoked=set(),
            )

    def test_cross_scope_edges_cannot_join(self):
        docs = (
            event("local", "service", "component", "component_a"),
            event("foreign", "component_a", "location", "site_wrong", scope="b"),
        )
        self.assertEqual(compile_examples(docs)[0], ())

    def test_curriculum_is_scope_stratified_and_does_not_read_gold(self):
        rows = fixture() + fixture("b")
        combined, unresolved, profile = combine_source_examples(
            rows,
            revision=2,
            allowed_roots={d.root for d in rows},
            revoked=set(),
        )
        self.assertEqual(profile["composition_examples"], 2)
        self.assertEqual(profile["direct_examples"], 6)
        self.assertFalse(profile["independent_task_labels_seen"])
        self.assertFalse(profile["production_accepted"])
        self.assertEqual(unresolved, [])
        for scope in ("a", "b"):
            first = next(x for x in combined if x["query"]["scope"] == scope)
            self.assertTrue(first["query"]["identity"].startswith("source_path_"))
        self.assertEqual(len({x["query"]["identity"] for x in combined}), len(combined))
        with self.assertRaises(ValueError):
            compile_examples(rows, limit=1)

    def test_bad_limit_or_unzoned_source_date_rejects(self):
        for invalid in (True, 0, -1, 129):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                compile_examples(fixture(), limit=invalid)
        rows = fixture()
        with self.assertRaises(ValueError):
            compile_examples((replace(rows[0], observed_at="2026-10-11"), *rows[1:]))


if __name__ == "__main__":
    unittest.main()
