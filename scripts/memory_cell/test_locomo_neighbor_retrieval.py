"""Deterministic rank/cost/label-bound checks; no learned or judged quality."""

import copy
from pathlib import Path
import tempfile
import unittest

from locomo_neighbor_retrieval import (
    check_evaluation_role,
    neighbor_rank,
    pack,
    score_terms,
    scoring,
)


def doc(identity, content):
    return dict(identity=identity, content=content)


class NeighborTests(unittest.TestCase):
    def test_same_session_immediate_turn_promoted(self):
        original = [
            doc("c/D3:1", "Zara mentioned zirconium zirconium"),
            doc("c/D3:2", "The blue object appeared"),
            doc("c/D4:2", "The red object appeared"),
            doc("c/D3:5", "other conversation"),
        ]
        result = neighbor_rank("Which zirconium object", original)
        self.assertEqual(result[0], "c/D3:1")
        self.assertEqual(result[1], "c/D3:2")

    def test_no_cross_session_or_scope_propagation(self):
        original = [
            doc("a/D1:1", "zirconium zirconium"),
            doc("a/D2:2", "adjacent-number but unrelated session"),
            doc("b/D1:2", "other memory scope"),
            doc("a/D1:2", "real neighbor"),
        ]
        order = neighbor_rank("zirconium", original)
        self.assertLess(order.index("a/D1:2"), order.index("a/D2:2"))
        self.assertLess(order.index("a/D1:2"), order.index("b/D1:2"))

    def test_budget_keeps_exact_source_bytes_not_truncated_unicode(self):
        original = [doc(f"c/D4:{i}", "中文" if i < 4 else "foo") for i in range(1, 10)]
        control = [d["identity"] for d in original[:8]]
        chosen, used, total = pack("中文", original, control)
        self.assertTrue(set(chosen) <= {x["identity"] for x in original})
        self.assertLessEqual(used, total)
        self.assertLessEqual(len(chosen), 8)
        self.assertEqual(total, sum(len(x["content"].encode()) for x in original[:8]))

    def test_duplicate_or_outside_frozen_pool_rejected(self):
        original = [doc(f"c/D1:{i}", "text") for i in range(1, 9)]
        baseline = [d["identity"] for d in original]
        for docs, selected in (
            (original, baseline[:-1]),
            (original, baseline[:7] + baseline[:1]),
            (original, baseline[:-1] + ["other"]),
            (original + [original[0]], baseline),
        ):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                pack("text", docs, selected)

    def test_gold_target_never_needed_for_ranking(self):
        original = [
            doc(f"c/D2:{i}", "actor" if i == 1 else "relation") for i in range(1, 9)
        ]
        before = neighbor_rank("actor", original)
        labeled = copy.deepcopy(original)
        for row in labeled:
            row["answer"] = "secret annotation"
            row["support"] = [original[0]["identity"]]
        self.assertEqual(before, neighbor_rank("actor", labeled))

    def test_scoring_remains_document_coverage_not_entailment(self):
        questions = [
            dict(question_id="q", family_proxy_digest="a", source_ids=["d1", "d2"])
        ]
        pub = dict(splits=dict(selection=questions))
        rows = [
            dict(question_id="q", arm=arm, selected=["d1"], selected_source_bytes=7)
            for arm in ("lexical_k8", "neighbor_k8_bytebound")
        ]
        label = {"q": dict(support=["d1"], unanswerable=False, unresolved_support=[])}
        out = scoring(pub, rows, "selection", label)
        self.assertEqual((out["baseline_covered"], out["neighbor_covered"]), (1, 1))
        self.assertIsNone(out["independent_semantic_citation_precision"])
        with self.assertRaises(ValueError):
            scoring(pub, rows, "selection", {"q": label["q"], "extra": label["q"]})

    def test_evaluation_isolation_requires_only_its_pinned_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public, select, evaluation = [
                root / x for x in ("public", "selection", "eval")
            ]
            for p in (public, select, evaluation):
                p.mkdir()
            filename = "locomo-evaluation-targets-38206328621.zip"
            (evaluation / filename).write_bytes(
                b"fake archive; checked later by read_zip"
            )
            check_evaluation_role(public, select, evaluation)
            with self.assertRaises(ValueError):
                check_evaluation_role(public, select, public)
            (evaluation / "old-policy-leak.zip").write_bytes(b"unexpected")
            with self.assertRaises(ValueError):
                check_evaluation_role(public, select, evaluation)

    def test_query_stopwords_never_inject_gold_or_empty_scoring(self):
        scored = score_terms(
            "WHAT does the person like?",
            [doc("x", "person likes games"), doc("y", "games")],
        )
        self.assertEqual(set(scored), {"x", "y"})
        with self.assertRaises(ValueError):
            score_terms("", [doc("x", "hey")])


if __name__ == "__main__":
    unittest.main()
