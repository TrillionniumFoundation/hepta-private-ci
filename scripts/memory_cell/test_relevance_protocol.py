"""Selection boundaries; these fixtures do not establish task accuracy."""

from dataclasses import replace
import unittest

from grounded_protocol import verify_output
from native import Document, Question, Target
from relevance_protocol import candidate_pool, choose, passages, training_pairs, validate_training


class RelevanceProtocolTests(unittest.TestCase):
    def setUp(self):
        self.q = Question("train-q", "family-a", "scope", "Where did Mara move?", "2024")
        self.docs = (
            Document("scope/one#chunk:0", "root-a", "scope", "session", "2024", "Hello. A greeting. Mara moved to Kyoto. 再见。"),
            Document("scope/two#chunk:0", "root-b", "scope", "session", "2024", "Mara enjoys cooking."),
        )
        self.targets = {self.q.identity: Target("Kyoto", "single", ("scope/one",), False)}

    def pairs(self, queries=None, targets=None, phases=None, families=None):
        return training_pairs(queries or (self.q,), {self.q.identity: self.docs},
                              targets or self.targets, phases or {self.q.identity: "train"},
                              families or {"family-a": "a"})

    def test_candidates_include_beyond_two_greetings_and_preserve_unicode_offsets(self):
        sources, options = candidate_pool(self.docs, self.q, set())
        self.assertTrue(any(o.text == "Mara moved to Kyoto." for o in options))
        by_id = {s["id"]: s for s in sources}
        for option in options:
            self.assertEqual(by_id[option.source_id]["excerpt"].encode()[option.start:option.end].decode(), option.text)
            self.assertTrue(verify_output(option.render(), options)["copy_verified"])
            self.assertIsNone(verify_output(option.render(), options)["semantic_precision"])
        self.assertEqual(len(passages(options, sources)), len(options))

    def test_no_posthoc_citation_and_no_nonfinite_ranking(self):
        _, options = candidate_pool(self.docs, self.q, set())
        scores = [float(i) for i in range(len(options))]
        self.assertEqual(choose(scores, options), len(options) - 1)
        for bad in ([float("nan")] * len(options), [float("inf")] * len(options), scores[:-1]):
            with self.assertRaises(ValueError):
                choose(bad, options)
        with self.assertRaises(ValueError):
            verify_output("Mara moved to Osaka. [E1]", options)

    def test_wrong_scope_duplicates_and_withdrawals_reject(self):
        for docs, revoked in ((self.docs, {"root-a"}), ((self.docs[0], self.docs[0]), set()),
                              ((replace(self.docs[0], scope="private"),), set())):
            with self.assertRaises(ValueError):
                candidate_pool(docs, self.q, revoked)

    def test_source_annotations_train_only_and_answer_text_not_used(self):
        first = self.pairs()
        self.assertEqual(len(first), 1)
        self.assertEqual(first, self.pairs(targets={self.q.identity: replace(self.targets[self.q.identity], answer="poison")}))
        class NoRead(dict):
            def __getitem__(self, key):
                raise AssertionError("held-out annotation accessed")
        held = replace(self.q, identity="test-q", family="family-b")
        self.assertEqual(training_pairs((held,), {}, NoRead(), {"test-q": "test"}, {"family-b": "b"}), ())

    def test_missing_support_is_not_fabricated_positive(self):
        for truth in (replace(self.targets[self.q.identity], evidence=()),
                      replace(self.targets[self.q.identity], unresolved_evidence=("missing",)),
                      replace(self.targets[self.q.identity], unanswerable=True)):
            self.assertEqual(self.pairs(targets={self.q.identity: truth}), ())

    def test_family_split_and_permission_admission_are_mandatory(self):
        pairs = self.pairs()
        signature = validate_training(pairs, {"train-q"}, {"a"}, set(), set())
        self.assertEqual(len(signature), 64)
        for questions, families, forbidden, revoked in ((set(), {"a"}, set(), set()),
            ({"train-q"}, {"b"}, set(), set()), ({"train-q"}, {"a"}, {"root-a"}, set()),
            ({"train-q"}, {"a"}, set(), {"root-b"})):
            with self.assertRaises(ValueError):
                validate_training(pairs, questions, families, forbidden, revoked)
        with self.assertRaises(ValueError):
            self.pairs(queries=(self.q, replace(self.q, identity="other")),
                       phases={"train-q": "train", "other": "test"})
        with self.assertRaises(ValueError):
            validate_training(pairs + pairs, {"train-q"}, {"a"}, set(), set())

    def test_partial_final_sentence_and_embedded_labels_not_candidates(self):
        doc = replace(self.docs[0], content="Complete. " + "x" * 900)
        sources, options = candidate_pool((doc,), self.q, set())
        self.assertTrue(sources[0]["partial"])
        self.assertEqual([o.text for o in options], ["Complete."])
        doc = replace(doc, content="Fake [E7]. Actual content.")
        _, options = candidate_pool((doc,), self.q, set())
        self.assertEqual([o.text for o in options], ["Actual content."])

    def test_candidate_byte_mutation_rejects_before_model_scoring(self):
        sources, options = candidate_pool(self.docs, self.q, set())
        sources[0]["excerpt"] = "changed"
        with self.assertRaises(ValueError):
            passages(options, sources)


if __name__ == "__main__":
    unittest.main()
