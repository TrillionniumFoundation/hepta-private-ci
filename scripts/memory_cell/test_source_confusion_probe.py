"""Source-only confusion probe mechanics; authored rows are not model results."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from source_confusion_probe import (
    ARMS,
    KINDS,
    WORDINGS,
    eligible_pairs,
    probe,
)
from test_experience_memory import source
from test_source_recall_probe import FakeReader, FakeTokenizer


class EqualLengthTokenizer(FakeTokenizer):
    def encode(self, value, *, add_special_tokens=False):
        return [7] if value.startswith("site_") else [8, 9]


def other_entity(document, entity):
    data = json.loads(document.content)
    data["entity"] = entity
    return replace(document, content=json.dumps(data))


class ConfusionTests(unittest.TestCase):
    def setUp(self):
        self.docs = (
            source("a", "site_a"),
            other_entity(source("b", "site_b"), "backup"),
        )
        self.reader = FakeReader(self.docs)
        self.reader.tokenizer = EqualLengthTokenizer()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "confusion"

    @staticmethod
    def score(reader, prompt, completion, arm):
        is_positive = completion == "site_b"
        mean_nll = (
            (0.5 if is_positive else 0.4)
            if arm == "base"
            else (0.2 if is_positive else 0.6)
        )
        return dict(
            mean_nll=mean_nll,
            input_tokens=len(prompt) + 2,
            supervised_tokens=2,
            seconds=0.01,
        )

    def run_probe(self, scorer=None):
        return probe(
            self.reader,
            self.docs,
            self.output,
            snapshot_sha="a" * 64,
            writer_source="b" * 40,
            source_commit="c" * 40,
            maximum=1,
            scorer=scorer or self.score,
        )

    def test_fixed_source_pairs_no_future_answer_in_prompts(self):
        selected, unavailable, unknown = eligible_pairs(
            self.docs, self.reader.tokenizer, roots=self.reader.roots, maximum=1
        )
        reverse, _, _ = eligible_pairs(
            tuple(reversed(self.docs)),
            self.reader.tokenizer,
            roots=self.reader.roots,
            maximum=1,
        )
        self.assertEqual(selected, reverse)
        self.assertEqual(unavailable, ())
        self.assertEqual(unknown, [])
        self.assertEqual(
            selected[0]["negative_category"], "same_attribute_other_entity"
        )
        seen = []

        def scored(reader, prompt, completion, arm):
            seen.append((tuple(prompt), completion, arm))
            return self.score(reader, prompt, completion, arm)

        report = self.run_probe(scored)
        self.assertEqual(report["scores_completed"], 8)
        self.assertEqual(len(seen), 8)
        self.assertEqual(self.reader.verified, 1)
        plan = json.loads((self.output / "plan.json").read_text())
        self.assertNotIn('"target": "site_', (self.output / "plan.json").read_text())
        self.assertEqual({x["wording"] for x in plan["comparisons"]}, set(WORDINGS))
        rows = [
            json.loads(x)
            for x in (self.output / "raw-likelihoods.jsonl").read_text().splitlines()
        ]
        self.assertEqual({x["arm"] for x in rows}, set(ARMS))
        self.assertEqual({x["completion_kind"] for x in rows}, set(KINDS))
        self.assertTrue(all(x["delivered_evidence"] == [] for x in rows))
        self.assertFalse(report["production_accepted"])
        self.assertIsNone(report["actual_end_to_end_task_gain"])

    def test_failed_score_is_retained_not_an_improved_margin(self):
        def fail(reader, prompt, completion, arm):
            if completion == "site_b" and arm == "memory":
                raise RuntimeError("deliberate model failure")
            return self.score(reader, prompt, completion, arm)

        with self.assertRaisesRegex(ValueError, "incomplete source-confusion"):
            self.run_probe(fail)
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["scores_expected"], 8)
        self.assertEqual(report["scores_completed"], 6)
        self.assertEqual(report["results_by_wording"]["training"]["complete_pairs"], 0)

    def test_no_equal_length_or_distinct_relation_refuses_admission(self):
        self.reader.tokenizer.encode = lambda value, **kwargs: (
            [1] if value == "site_a" else [1, 2]
        )
        calls = []
        result = self.run_probe(lambda *args: calls.append(args))
        self.assertFalse(result["comparison_eligible"])
        self.assertEqual(result["available_relation_pairs"], 0)
        self.assertEqual(result["scores_expected"], 0)
        self.assertIsNone(result["results_by_wording"]["training"]["mean_margin_delta"])
        self.assertEqual(calls, [])

    def test_wrong_scope_or_source_dependency_rejected_before_scoring(self):
        for docs, sha in ((self.docs[:1], "a" * 64), (self.docs, "invalid")):
            seen = []
            with self.assertRaises(ValueError):
                probe(
                    self.reader,
                    docs,
                    self.output,
                    snapshot_sha=sha,
                    writer_source="b" * 40,
                    source_commit="c" * 40,
                    scorer=lambda *args: seen.append(True),
                )
            self.assertEqual(seen, [])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
