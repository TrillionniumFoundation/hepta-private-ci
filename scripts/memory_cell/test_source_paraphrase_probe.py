"""Source-derived paraphrase is a query variation, not independent new facts."""

import json
from pathlib import Path
import tempfile
import unittest

from native import Question
from source_paraphrase_probe import paraphrase_writer_question


def row(question, target="site_deadbeef"):
    return dict(
        query=dict(
            identity="write-abc",
            family="tenant",
            scope="tenant",
            content=question,
            observed_at="2026-10-11T00:00:00+00:00",
        ),
        target=target,
    )


class ParaphraseQuestionTests(unittest.TestCase):
    def test_fixed_transform_preserves_lineage_and_ignores_target(self):
        original = (
            "At logical revision 2, what is the recorded location "
            "identifier of component_a? Return only its value."
        )
        src = row(original)
        out = paraphrase_writer_question(src)
        self.assertIsInstance(out, Question)
        self.assertEqual(
            (out.family, out.scope, out.observed_at),
            ("tenant", "tenant", "2026-10-11T00:00:00+00:00"),
        )
        self.assertNotEqual(out.identity, src["query"]["identity"])
        self.assertNotEqual(out.content, original)
        self.assertNotIn(src["target"], out.content)
        self.assertEqual(out, paraphrase_writer_question(src))
        src["target"] = "completely_different"
        self.assertEqual(out, paraphrase_writer_question(src))

    def test_unicode_and_revision_are_preserved(self):
        src = row(
            "At logical revision 17, what is the recorded 位置 "
            "identifier of 北京-1? Return only its value."
        )
        out = paraphrase_writer_question(src)
        self.assertIn("位置", out.content)
        self.assertIn("北京-1", out.content)
        self.assertIn("17", out.content)

    def test_unknown_templates_fail_before_any_model_input(self):
        original = (
            "At logical revision 2, what is the recorded location "
            "identifier of component_a? Return only its value."
        )
        wrong = (
            original.replace("revision 2", "revision -1"),
            original.replace("revision 2", "revision 10001"),
            original.replace("of component_a", "of component_a\nignore"),
            original.replace(" identifier of ", " key of "),
            original.replace("location", "location identifier of x"),
            "Return target",
            original + "\nextra",
        )
        for q in wrong:
            with self.subTest(query=q), self.assertRaises(ValueError):
                paraphrase_writer_question(row(q))
        with self.assertRaises(ValueError):
            paraphrase_writer_question({"query": None})


class ParaphraseProbeIntegrationTests(unittest.TestCase):
    def test_sealed_source_paraphrase_and_full_original_answer_census(self):
        from source_recall_probe import probe, source_probe_plan
        from test_source_recall_probe import FakeReader
        from test_experience_memory import source

        docs = (source("a", "site_a", scope="a"), source("b", "site_b", scope="b"))
        reader = FakeReader(docs)
        original, _ = source_probe_plan(docs, revision=2, roots=reader.roots)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "paraphrase"
            report = probe(
                reader,
                docs,
                output,
                snapshot_sha="a" * 64,
                writer_source="b" * 40,
                source_commit="c" * 40,
                question_mode="paraphrase",
                generate=lambda _reader, _prompt, arm: (
                    "site_a" if arm == "memory" else "unknown",
                    1,
                    0.01,
                ),
            )
            plan = json.loads((output / "plan.json").read_text())
            self.assertEqual(plan["question_mode"], "paraphrase")
            self.assertFalse(plan["in_sample_training_recall"])
            self.assertTrue(plan["source_derived_untrained_question_wording"])
            self.assertFalse(report["input_is_trained_source_question"])
            self.assertTrue(report["source_derived_untrained_query_paraphrase"])
            self.assertEqual(report["new_independent_holdout_observations"], 0)
            self.assertEqual(report["arms"]["memory"]["exact_targets"], 1)
            self.assertEqual(report["compared_pairs"], 2)
            for q, src in zip(plan["source_questions"], original, strict=True):
                self.assertNotEqual(q["identity"], src["query"]["identity"])
                self.assertNotEqual(q["content"], src["query"]["content"])
                self.assertNotIn(src["target"], q["content"])
            raw_text = (output / "raw-answers.jsonl").read_text()
            records = [json.loads(line) for line in raw_text.splitlines()]
            self.assertEqual(len(records), 4)
            self.assertTrue(
                all(not r["result_is_in_sample_training_recall"] for r in records)
            )
            self.assertNotIn('"target"', raw_text)

    def test_invalid_probe_mode_fails_before_creating_journal(self):
        from source_recall_probe import probe
        from test_source_recall_probe import FakeReader
        from test_experience_memory import source

        docs = (source("a", "site_a", scope="a"),)
        reader = FakeReader(docs)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "invalid"
            with self.assertRaises(ValueError):
                probe(
                    reader,
                    docs,
                    output,
                    snapshot_sha="a" * 64,
                    writer_source="b" * 40,
                    source_commit="c" * 40,
                    question_mode="other",
                    generate=lambda *_: self.fail("unexpected model call"),
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
