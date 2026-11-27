"""Offline schema, paragraph partition, outcome isolation and grouped metrics."""

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from multirc_data import load_jsonl, partition_cases, score_multirc


def paragraph(idx=0, text="First fact. Second fact."):
    return {"idx": idx, "passage": {"text": text, "questions": [
        {"idx": 3, "question": "What follows from both facts?", "answers": [
            {"idx": 10, "text": "A supported answer", "label": 1},
            {"idx": 11, "text": "A wrong answer", "label": 0}]}]}}


class MultiRCDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "source.jsonl"

    def load(self, rows, source_split="train", **kwargs):
        payload = "".join(json.dumps(row) + "\n" for row in rows).encode()
        self.path.write_bytes(payload)
        result = load_jsonl(self.path, source_split, **kwargs)
        self.assertEqual(result.sha256, sha256(payload).hexdigest())
        return result

    def test_official_schema_full_chunks_source_digest_and_ids(self):
        row = paragraph(text="<b>Sent 1: </b>First &amp; full fact.<br><b>Sent 4: </b>Second fact.")
        row["passage"]["questions"][0]["sentences_used"] = [1, 4]
        result = self.load([row])
        case = result.cases[0]
        self.assertEqual((case.paragraph_id, case.question_id, case.answer_id), ("0", "3", "10"))
        self.assertEqual(case.facts, ("First & full fact.", "Second fact."))
        self.assertEqual((case.sentence_ids, case.evidence_sentence_indices), ((1, 4), (1, 4)))
        self.assertEqual(case.source_hash, sha256(row["passage"]["text"].encode()).hexdigest())
        self.assertEqual(json.loads(case.case_id), ["train", "0", "3", "10"])
        with self.assertRaises(FrozenInstanceError):
            case.label = 0
        self.assertEqual(result.counts["accepted_candidates"], 2)
        self.assertEqual(result.counts["rejected_candidates"], 0)

    def test_plain_sentences_lines_and_original_dialect(self):
        plain = self.load([paragraph()]).cases[0]
        self.assertEqual((plain.facts, plain.sentence_ids, plain.segmentation),
                         (("First fact.", "Second fact."), (None, None), "punctuation-v1"))
        lines = self.load([paragraph(text="Line one without punctuation\nLine two")]).cases[0]
        self.assertEqual(lines.facts, ("Line one without punctuation", "Line two"))
        row = paragraph()
        row["paragraph"] = row.pop("passage")
        for answer in row["paragraph"]["questions"][0]["answers"]:
            answer["isAnswer"] = bool(answer.pop("label"))
        result = self.load([row])
        self.assertEqual(tuple(c.label for c in result.cases), (1, 0))
        self.assertEqual(result.schema_counts, (("original-multirc", 1),))

    def test_public_identity_excludes_all_outcomes_and_annotations(self):
        case = self.load([paragraph()]).cases[0]
        poisoned = replace(case, label=1 - case.label, evidence_sentence_indices=(999,))
        self.assertEqual((case.public_text, case.feature_source_hash, case.source_hash),
                         (poisoned.public_text, poisoned.feature_source_hash, poisoned.source_hash))
        self.assertIn(case.candidate, case.public_text)
        self.assertTrue(all(fact in case.public_text for fact in case.facts))
        self.assertNotEqual(case.feature_source_hash, replace(case, candidate="Different actual answer").feature_source_hash)

    def test_empty_official_candidate_is_preserved_without_relabeling(self):
        row = paragraph()
        row["passage"]["questions"][0]["answers"][1]["text"] = ""
        result = self.load([row])
        self.assertEqual((result.cases[1].candidate, result.cases[1].label), ("", 0))
        self.assertEqual(result.counts["empty_candidate_texts"], 1)

    def test_bounds_reject_entire_paragraph_without_partial_questions(self):
        for bound in ({"max_facts": 1}, {"max_sentence_chars": 4}, {"max_cases": 1}):
            result = self.load([paragraph()], **bound)
            self.assertEqual((result.cases, result.counts["rejected_paragraphs"], result.counts["rejected_candidates"]),
                             ((), 1, 2))
        with self.assertRaisesRegex(ValueError, "byte bound"):
            self.load([paragraph()], max_bytes=1)

    def test_invalid_schema_duplicate_ids_and_unlabeled_sources(self):
        row = paragraph()
        del row["passage"]["questions"][0]["answers"][0]["label"]
        self.assertEqual(self.load([row]).counts["rejection_reasons"], {"invalid_schema": 1})
        row = paragraph()
        row["passage"]["questions"][0]["answers"][1]["idx"] = 10
        self.assertFalse(self.load([row]).cases)
        with self.assertRaisesRegex(ValueError, "duplicate paragraph"):
            self.load([paragraph(), paragraph()])
        with self.assertRaises(ValueError):
            self.load([paragraph()], source_split="test")

    def test_partition_keeps_all_paragraph_candidates_together_and_validation_final(self):
        train = self.load([paragraph(i, f"Paragraph {i}. Complete evidence.") for i in range(100)]).cases
        final = self.load([paragraph(0, "Official held-out evidence.")], "validation").cases
        parts = partition_cases(train + final, seed=41)
        self.assertEqual(set(parts), {"train", "tune", "verifier_fit", "critic_fit", "critic_calibration", "final"})
        self.assertEqual(parts["final"], final)
        memberships = {}
        for split, cases in parts.items():
            for case in cases:
                memberships.setdefault(case.source_hash, set()).add(split)
        self.assertTrue(all(len(splits) == 1 for splits in memberships.values()))
        poisoned = tuple(replace(case, label=1 - case.label) for case in train + final)
        self.assertEqual({k: [c.case_id for c in v] for k, v in parts.items()},
                         {k: [c.case_id for c in v] for k, v in partition_cases(poisoned).items()})
        with self.assertRaisesRegex(ValueError, "overlaps official"):
            partition_cases(train + (replace(train[0], source_split="validation"),))

    def test_grouped_metrics_use_complete_candidate_predictions(self):
        case = self.load([paragraph()]).cases[0]
        cases = [replace(case, question_id="q1", answer_id=str(i), label=label) for i, label in enumerate((1, 0, 1))]
        cases += [replace(case, question_id="q2", answer_id=str(i), label=0) for i in range(2)]
        scores = score_multirc(cases, [1, 0, 0, 0, 0])
        self.assertEqual((scores["candidates"], scores["questions"], scores["exact_match"], scores["accuracy"]), (5, 2, .5, .8))
        self.assertAlmostEqual(scores["f1_a"], 2 / 3)
        self.assertAlmostEqual(scores["f1_m"], 5 / 6)
        all_negative = [replace(case, label=0)]
        self.assertEqual((score_multirc(all_negative, [0])["f1_a"], score_multirc(all_negative, [0])["f1_m"]), (0, 1))
        for references, predictions in ((cases, [1]), (cases, [2] * 5), ([case, case], [1, 1]), ([], [])):
            with self.assertRaises(ValueError):
                score_multirc(references, predictions)


if __name__ == "__main__":
    unittest.main()
