"""Observable curriculum and exact source-position regressions, not native scores."""

from types import SimpleNamespace
import unittest

from native import Question
from stem_cell import route_text
from stem_cell_protocol import oracle_sources
from stem_cell_trial import select_questions


class NativeFixture:
    def __init__(self, questions):
        self.questions = questions

    def partition(self, question):
        return question.family

    @property
    def targets(self):
        raise AssertionError("curriculum must not inspect answer annotations")


def corpus():
    train = [
        Question(f"train-{kind}-{i}", "train", f"scope-{i}", text, "2024")
        for kind, text in (
            ("general", "What happened?"),
            ("temporal", "When did it happen?"),
        )
        for i in range(30)
    ]
    evaluation = [
        Question(f"{phase}-{i}", phase, f"scope-{phase}-{i}", "What happened?", "2024")
        for phase, count in (("select", 8), ("test", 16))
        for i in range(count)
    ]
    transfer = [
        Question(
            f"transfer-{i}", "transfer", "transfer-scope", "What happened?", "2025"
        )
        for i in range(8)
    ]
    return dict(
        locomo=NativeFixture(train + evaluation), longmemeval=NativeFixture(transfer)
    )


class TrialTests(unittest.TestCase):
    def test_balanced_curriculum_is_observable_and_deterministic(self):
        sources = corpus()
        selected = select_questions(sources)
        self.assertEqual(len(selected["train"]), 48)
        for size in (16, 32, 48):
            routes = [route_text(q.content) for q in selected["train"][:size]]
            self.assertEqual(routes.count("general"), size // 2)
            self.assertEqual(routes.count("temporal"), size // 2)
        sources["locomo"].questions.reverse()
        self.assertEqual(select_questions(sources), selected)
        all_ids = [q.identity for group in selected.values() for q in group]
        self.assertEqual(len(all_ids), 80)
        self.assertEqual(len(set(all_ids)), 80)

    def test_missing_route_examples_fail_instead_of_changing_registered_budget(self):
        sources = corpus()
        sources["locomo"].questions = [
            q
            for q in sources["locomo"].questions
            if route_text(q.content) != "temporal"
        ]
        with self.assertRaises(ValueError):
            select_questions(sources)

    def test_unicode_reference_positions_are_original_utf8_byte_offsets(self):
        text = "背景" * 120 + "原定目的地是东京。" + "详细说明" * 70
        doc = SimpleNamespace(
            identity="source",
            root="root",
            scope="scope",
            observed_at="2023",
            content=text,
        )
        source = SimpleNamespace(history=lambda q: [doc])
        target = SimpleNamespace(
            unanswerable=False,
            unresolved_evidence=(),
            evidence=("source",),
            answer="东京",
        )
        q = Question("q", "family", "scope", "目的地是哪儿？", "2024")
        evidence, kind = oracle_sources(source, q, target)
        self.assertEqual(kind, "native-source-literal-span")
        item = evidence[0]
        self.assertEqual(item["offset_encoding"], "original-utf8-bytes")
        original = text.encode("utf-8")[
            item["source_start"] : item["source_end"]
        ].decode("utf-8")
        self.assertEqual(item["excerpt"], original)
        self.assertIn("东京", original)
        self.assertGreater(item["source_start"], 0)


if __name__ == "__main__":
    unittest.main()
