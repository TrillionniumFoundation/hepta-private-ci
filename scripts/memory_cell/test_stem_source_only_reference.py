"""Registered native-source IDs do not authorize answer-literal target leakage."""

from dataclasses import replace
import unittest

from native import Benchmark, Document, Question, Target
from stem_source_only_reference import make_publisher_source_cases


def fixture():
    from dataclasses import asdict
    from selector_windows import WindowBudget

    phases = ("select", "retention", "test", "transfer")
    questions = {phase: [f"{phase}-{i}" for i in range(8)] for phase in phases}
    questions["train"] = [f"train-{i}" for i in range(48)]
    queries, docs, targets = {}, [], {}
    for phase in phases:
        for i, qid in enumerate(questions[phase]):
            q = Question(
                qid,
                "native-family",
                "scope-" + qid,
                "When did the orchardberry shipment leave?",
                "2024-01-01",
            )
            doc = Document(
                "source-" + qid,
                "root-" + qid,
                q.scope,
                "session",
                "2023-01-01",
                "Unrelated context. " * 40
                + "The orchardberry shipment left on Tuesday morning.",
            )
            queries[qid] = q
            docs.append(doc)
            targets[qid] = Target(
                "Do not read this reference answer",
                "fixture",
                (doc.identity,),
                False,
            )
    corpus = Benchmark(
        "locomo",
        "a" * 64,
        tuple(docs),
        tuple(queries.values()),
        targets,
        {"native-family": "family-pinned"},
    )
    plan = dict(
        questions=questions,
        arms=[
            "frozen_rerank",
            "prototype",
            "linear",
            "gated",
            "lineage_lora_gated",
            "independent_lora_gated",
        ],
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
        dataset_sha256={"locomo": "a" * 64},
        question_families={qid: "family-pinned" for qid in queries},
        window_budget=asdict(WindowBudget()),
    )
    return plan, queries, {qid: corpus for qid in queries}


class PublisherSourceOnlyTests(unittest.TestCase):
    def test_exact_32_question_source_window_can_be_supplied_with_original_offsets(
        self,
    ):
        plan, queries, source_for = fixture()
        rows = make_publisher_source_cases(plan, queries, source_for)
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(meta["status"] == "planned" for _, _, meta in rows))
        self.assertTrue(all(len(evidence) == 1 for _, evidence, _ in rows))
        for q, evidence, meta in rows:
            doc = next(
                d for d in source_for[q.identity].documents if d.scope == q.scope
            )
            x = evidence[0]
            self.assertEqual(
                doc.content.encode()[x["source_start"] : x["source_end"]].decode(),
                x["excerpt"],
            )
            self.assertEqual(x["scope"], q.scope)
            self.assertTrue(meta["answer_text_read_by_planner"] is False)
            self.assertTrue(meta["nonqualifying_privileged_diagnostic"])
            self.assertIn("orchardberry", x["excerpt"].lower())

    def test_answer_string_cannot_be_read_during_source_selection(self):
        plan, queries, source_for = fixture()
        corpus = source_for["select-0"]

        class OpaqueSourceOnlyTarget:
            unanswerable = False
            evidence = ("source-select-0",)
            unresolved_evidence = ()

            @property
            def answer(self):
                raise AssertionError("gold answer inspected during planning")

        corpus.targets["select-0"] = OpaqueSourceOnlyTarget()
        rows = make_publisher_source_cases(plan, queries, source_for)
        self.assertEqual(rows[0][2]["status"], "planned")

    def test_unanswerable_and_unresolved_support_stay_in_the_32_case_census(self):
        plan, queries, source_for = fixture()
        corpus = source_for["select-0"]
        corpus.targets["select-0"] = replace(
            corpus.targets["select-0"], unanswerable=True
        )
        corpus.targets["select-1"] = replace(
            corpus.targets["select-1"],
            unresolved_evidence=("source-unavailable",),
        )
        rows = make_publisher_source_cases(plan, queries, source_for)
        self.assertEqual(len(rows), 32)
        self.assertEqual(rows[0][2]["reason"], "native-unanswerable")
        self.assertEqual(rows[1][2]["reason"], "unresolved-native-support")
        self.assertEqual(rows[0][1], ())
        self.assertEqual(rows[1][1], ())

    def test_future_gold_source_not_promoted_into_reader(self):
        plan, queries, source_for = fixture()
        corpus = source_for["select-0"]
        docs = list(corpus.documents)
        for i, doc in enumerate(docs):
            if doc.scope == "scope-select-0":
                docs[i] = replace(doc, observed_at="2025-01-01")
        new_corpus = replace(corpus, documents=tuple(docs))
        for qid in source_for:
            source_for[qid] = new_corpus
        with self.assertRaisesRegex(ValueError, "no as-of-admissible"):
            make_publisher_source_cases(plan, queries, source_for)

    def test_unknown_native_date_fails_closed(self):
        plan, queries, source_for = fixture()
        corpus = source_for["select-0"]
        docs = list(corpus.documents)
        docs[0] = replace(docs[0], observed_at="not a native time")
        updated = replace(corpus, documents=tuple(docs))
        for qid in source_for:
            source_for[qid] = updated
        with self.assertRaisesRegex(ValueError, "uncomparable native source time"):
            make_publisher_source_cases(plan, queries, source_for)

    def test_missing_published_support_is_not_forged_from_available_other_doc(self):
        plan, queries, source_for = fixture()
        corpus = source_for["select-0"]
        corpus.targets["select-0"] = replace(
            corpus.targets["select-0"], evidence=("missing-source-id",)
        )
        rows = make_publisher_source_cases(plan, queries, source_for)
        self.assertEqual(
            rows[0][2]["reason"], "published-support-source-not-admissible"
        )
        self.assertEqual(rows[0][1], ())
        self.assertEqual(len(rows), 32)

    def test_corpus_sha_registered_family_and_phase_census_are_immutable(self):
        for kind in ("source-file", "family", "duplicate", "phase"):
            plan, queries, source_for = fixture()
            if kind == "source-file":
                plan["dataset_sha256"]["locomo"] = "b" * 64
            elif kind == "family":
                plan["question_families"]["test-0"] = "wrong-family"
            elif kind == "duplicate":
                plan["questions"]["test"][0] = "select-0"
            else:
                plan["questions"]["test"].pop()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                make_publisher_source_cases(plan, queries, source_for)


if __name__ == "__main__":
    unittest.main()
