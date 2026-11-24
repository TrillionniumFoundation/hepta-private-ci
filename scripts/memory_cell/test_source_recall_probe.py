"""Source-only recall proof fixtures; outputs are authored, not real Qwen runs."""

from pathlib import Path
import json
import tempfile
import unittest

from native import digest
from source_recall_probe import ARMS, probe, source_probe_plan
from test_experience_memory import source


class FakeTokenizer:
    eos_token_id = 2

    def apply_chat_template(self, messages, **kwargs):
        question = json.loads(messages[1]["content"])["question"]
        return [1, (sum(map(ord, question)) % 100) + 3]


class FakeReader:
    def __init__(self, docs):
        self.roots = {d.root for d in docs}
        self.scopes = {d.scope for d in docs}
        self.identity = "reader-1"
        self.profile = "writer-profile"
        self.tokenizer = FakeTokenizer()
        self.verified = 0

    def verify_frozen(self):
        self.verified += 1


class SourceRecallTests(unittest.TestCase):
    def setUp(self):
        self.docs = (
            source("a", "site_a", scope="a"),
            source("b", "site_b", scope="b"),
        )
        self.reader = FakeReader(self.docs)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "probe"

    def do_probe(self, fn):
        return probe(
            self.reader,
            self.docs,
            self.path,
            snapshot_sha="a" * 64,
            writer_source="b" * 40,
            source_commit="c" * 40,
            generate=fn,
        )

    def test_fixed_source_questions_and_no_results_in_model_input(self):
        selected, unknown = source_probe_plan(
            self.docs, revision=2, roots=self.reader.roots
        )
        reversed_selected, _ = source_probe_plan(
            tuple(reversed(self.docs)), revision=2, roots=self.reader.roots
        )
        self.assertEqual(selected, reversed_selected)
        self.assertEqual(len(selected), 2)
        self.assertEqual(unknown, [])
        calls = []

        def generated(reader, prompt, arm):
            calls.append((prompt, arm))
            return ("site_a" if arm == "memory" else "unknown", 1, 0.5)

        report = self.do_probe(generated)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(len(prompt) == 2 for prompt, _ in calls))
        self.assertEqual({a for _, a in calls}, set(ARMS))
        self.assertEqual(report["arms"]["base"]["exact_targets"], 0)
        self.assertEqual(report["arms"]["memory"]["exact_targets"], 1)
        self.assertEqual((report["memory_wins"], report["memory_losses"]), (1, 0))
        self.assertEqual(report["new_independent_holdout_observations"], 0)
        self.assertEqual(self.reader.verified, 1)
        raw = (self.path / "raw-answers.jsonl").read_text()
        self.assertNotIn('"target"', raw)
        with self.assertRaises(ValueError):
            self.do_probe(generated)

    def test_invalid_empty_context_citations_are_not_perfect_precision(self):
        result = self.do_probe(lambda reader, prompt, arm: ("site_a [E1]", 2, 0.01))
        self.assertEqual(result["arms"]["memory"]["exact_targets"], 0)
        self.assertEqual(result["arms"]["memory"]["unsupported_citation_answers"], 2)
        self.assertIsNone(result["semantic_citation_precision"])

    def test_failed_call_is_recorded_before_scoring_and_widens_bounds(self):
        calls = 0

        def fails(reader, prompt, arm):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("deliberate upstream failure")
            return ("incorrect", 1, 0.02)

        with self.assertRaises(ValueError):
            self.do_probe(fails)
        raw = [
            json.loads(row)
            for row in (self.path / "raw-answers.jsonl").read_text().splitlines()
        ]
        self.assertEqual(len(raw), 4)
        self.assertEqual(raw[0]["status"], "failed")
        self.assertEqual(
            json.loads((self.path / "report.json").read_text())["compared_pairs"], 1
        )
        self.assertEqual(self.reader.verified, 1)

    def test_nonfinite_or_boolean_receipts_are_failures_not_successes(self):
        for receipt in (
            ("correct", True, 0.1),
            ("correct", 1, float("nan")),
            ("", 1, 0.1),
            ("correct", 1000, 0.1),
        ):
            with self.subTest(receipt=receipt):
                output = Path(self.tmp.name) / ("probe-" + digest(str(receipt))[:9])
                with self.assertRaises(ValueError):
                    probe(
                        self.reader,
                        self.docs,
                        output,
                        snapshot_sha="a" * 64,
                        writer_source="b" * 40,
                        source_commit="c" * 40,
                        generate=lambda reader, prompt, arm: receipt,
                    )
                recorded = [
                    json.loads(x)
                    for x in (output / "raw-answers.jsonl").read_text().splitlines()
                ]
                self.assertEqual(len(recorded), 4)
                self.assertTrue(all(row["status"] == "failed" for row in recorded))

    def test_source_or_provenance_changes_reject_before_generation(self):
        for name, documents, sha in (
            ("missing_scope", self.docs[:1], "a" * 64),
            ("invalid_sha", self.docs, "no-sha"),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    probe(
                        self.reader,
                        documents,
                        self.path,
                        snapshot_sha=sha,
                        writer_source="b" * 40,
                        source_commit="c" * 40,
                        generate=lambda *args: self.fail("model invoked"),
                    )
                self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
