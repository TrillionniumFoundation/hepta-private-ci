"""Source-bound, executable ceiling regression tests."""
import json
import unittest
from source_graph_ceiling import resolve


def event(ident, entity, attribute, value, revision, supersedes=(), scope="s"):
    return dict(scope=scope, content=json.dumps(dict(
        schema="hepta.controlled-event.v1", id=ident, entity=entity,
        attribute=attribute, value=value, revision=revision,
        supersedes=list(supersedes),
    )))


class SourceGraphCeilingTests(unittest.TestCase):
    def test_multi_hop_requires_both_original_sources(self):
        question = dict(id="s", entity="api", path=["component", "location"], revision=2)
        docs = dict(
            a=event("a", "api", "component", "worker", 1),
            b=event("b", "worker", "location", "site", 1),
        )
        self.assertEqual(resolve(question, ["a", "b"], docs), "site")
        self.assertIsNone(resolve(question, ["a"], docs))
        self.assertIsNone(resolve(question, ["b"], docs))

    def test_conflict_supersession_and_future_cut(self):
        question = dict(id="s", entity="api", path=["location"], revision=2)
        docs = dict(
            a=event("a", "api", "location", "old", 1),
            b=event("b", "api", "location", "other", 2),
            c=event("c", "api", "location", "future", 3),
            d=event("d", "api", "location", "new", 2, ["a"]),
        )
        self.assertIsNone(resolve(question, ["a", "b"], docs))
        self.assertEqual(resolve(question, ["a", "c"], docs), "old")
        self.assertEqual(resolve(question, ["a", "d"], docs), "new")
        self.assertIsNone(resolve(question, ["a", "b", "d"], docs))

    def test_scope_and_source_identity_cannot_be_rebound(self):
        question = dict(id="s", entity="api", path=["location"], revision=2)
        doc = event("a", "api", "location", "here", 1, scope="other")
        self.assertIsNone(resolve(question, [], {"a": doc}))
        self.assertIsNone(resolve(question, ["a", "a"], {"a": doc}))
        with self.assertRaisesRegex(ValueError, "scope leak"):
            resolve(question, ["a"], {"a": doc})
        doc["scope"] = "s"
        with self.assertRaisesRegex(ValueError, "identity changed"):
            resolve(question, ["bad"], {"bad": doc})


if __name__ == "__main__":
    unittest.main()
