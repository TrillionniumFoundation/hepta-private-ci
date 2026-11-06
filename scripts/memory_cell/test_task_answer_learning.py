from types import SimpleNamespace
import unittest

from native import Document, Question, digest
from selector_head import TrainingCut
from selector_windows import candidate_windows
from span_supervision import SpanTarget
from task_answer_learning import ABSTAIN, answer_examples, prompt_ids


class TaskAnswerTests(unittest.TestCase):
    def setup_data(self):
        text = "Nara moved to Kyoto in 2020."
        doc = Document("doc", "root", "scope", "family", "2020", text)
        q = Question("q", "family", "scope", "Where did Nara move?", "2020")
        pool = candidate_windows((doc,), q, revoked=set())
        start = len(text[: text.index("Kyoto")].encode())
        target = SpanTarget(
            "q", "doc", digest(text), ((start, start + 5, "Kyoto"),), False, "ann"
        )
        corpus = SimpleNamespace(targets={"q": target}, documents={"scope": doc})
        cut = TrainingCut(
            frozenset({"q"}),
            frozenset({"family"}),
            frozenset({"root"}),
            frozenset(),
            "test",
        )
        return q, pool, corpus, cut

    def test_actual_answer_target_and_empty_evidence_augmentation(self):
        q, pool, corpus, cut = self.setup_data()
        rows, _ = answer_examples((q,), corpus, {"q": pool}, cut, revoked=set())
        self.assertEqual([r.completion for r in rows], ["Kyoto [E1]", ABSTAIN])
        self.assertTrue(rows[0].sources)
        self.assertEqual(rows[1].sources, ())

    def test_no_annotation_access_before_cut_and_withdrawal(self):
        q, pool, _, cut = self.setup_data()
        corpus = SimpleNamespace(targets={}, documents={})
        with self.assertRaises(ValueError):
            answer_examples((q,), corpus, {"q": pool}, cut, revoked={"root"})
        cut = TrainingCut(
            frozenset(), cut.families, cut.allowed_roots, frozenset(), "test"
        )
        with self.assertRaises(ValueError):
            answer_examples((q,), corpus, {"q": pool}, cut, revoked=set())

    def test_prompt_receives_question_and_source_not_target(self):
        q, pool, corpus, cut = self.setup_data()
        rows, _ = answer_examples((q,), corpus, {"q": pool}, cut, revoked=set())

        class Tokenizer:
            def apply_chat_template(self, messages, **_):
                self.messages = messages
                return [1, 2, 3]

        tokenizer = Tokenizer()
        self.assertEqual(
            prompt_ids(tokenizer, q, rows[0].sources, revoked=set()), [1, 2, 3]
        )
        self.assertNotIn("annotation_digest", str(tokenizer.messages))
        self.assertNotIn("completion", str(tokenizer.messages))
        with self.assertRaises(ValueError):
            prompt_ids(tokenizer, q, rows[0].sources, revoked={"root"})


if __name__ == "__main__":
    unittest.main()
