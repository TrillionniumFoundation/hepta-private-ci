"""Decoder-versus-adapter controls are fixtures, not pretrained outcomes."""

import json
from pathlib import Path
import tempfile
import unittest

from experience_memory import render
from native import Question
from source_decode_factorial import paired_probe, summarize
from source_paraphrase_probe import paraphrase_writer_question
from source_recall_probe import source_probe_plan
from test_experience_memory import source
from test_source_recall_probe import FakeReader


def record(qid, arm, answer, *, failed=False):
    row = dict(
        question_id=qid,
        arm=arm,
        status="failed" if failed else "succeeded",
        prompt_sha256="prompt-" + qid,
        input_tokens=12,
        delivered_evidence=[],
        scope=qid,
        source_training_question_id="source-" + qid,
        source_example_optimizer_visits=1,
    )
    if not failed:
        row.update(answer=answer, generated_tokens=2, seconds=0.01)
    return row


class UniqueQuestionTokenizer:
    eos_token_id = 2

    def apply_chat_template(self, messages, **kwargs):
        # The native Reader sees the *entire* JSON user prompt, including
        # explicit memory_scope. Ignoring scope merges incompatible targets.
        text = messages[1]["content"]
        return [1, *text.encode("utf-8")]


class DecoderFactorialTests(unittest.TestCase):
    def setUp(self):
        self.docs = (
            source("a", "site_a", scope="a"),
            source("b", "site_b", scope="b"),
        )
        self.reader = FakeReader(self.docs)
        self.reader.tokenizer = UniqueQuestionTokenizer()
        self.targets = {"a": "site_a", "b": "site_b"}
        self.greedy = [
            record(qid, arm, "wrong")
            for qid in self.targets
            for arm in ("base", "memory")
        ]
        self.beam = [
            record(qid, arm, self.targets[qid] if arm == "memory" else "wrong")
            for qid in self.targets
            for arm in ("base", "memory")
        ]

    def test_algorithm_gain_is_not_misattributed_to_lora(self):
        result = summarize(self.greedy, self.beam, self.targets)
        self.assertEqual(
            result["decoder_effect_holding_adapter_fixed"]["memory"]["candidate_wins"],
            2,
        )
        self.assertEqual(
            result["adapter_effect_holding_decoder_fixed"]["greedy"]["candidate_wins"],
            0,
        )
        self.assertEqual(
            result["adapter_effect_holding_decoder_fixed"]["beam2"]["candidate_wins"],
            2,
        )
        self.assertEqual(result["observed_interaction_mean"], 1.0)
        self.assertFalse(result["production_accepted"])
        self.assertIsNone(result["independent_citation_semantics"])

    def test_missing_failure_kept_in_planned_bounds(self):
        self.beam[1] = record("a", "memory", "unused", failed=True)
        result = summarize(self.greedy, self.beam, self.targets)
        item = result["decoder_effect_holding_adapter_fixed"]["memory"]
        self.assertEqual(item["planned_pairs"], 2)
        self.assertEqual(item["complete_pairs"], 1)
        self.assertEqual(item["missing_pairs"], 1)
        self.assertEqual(item["all_planned_effect_bounds"], [0, 1])
        self.assertEqual(result["observed_four_arm_interactions"], 1)

    def test_changed_inputs_duplicate_rows_and_fake_evidence_reject(self):
        for key, changed in (
            ("prompt_sha256", "different"),
            ("source_example_optimizer_visits", 99),
            ("delivered_evidence", [{"excerpt": "leak"}]),
        ):
            rows = [dict(r) for r in self.beam]
            rows[0][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                summarize(self.greedy, rows, self.targets)
        with self.assertRaises(ValueError):
            summarize(self.greedy, self.beam[:-1], self.targets)
        with self.assertRaises(ValueError):
            summarize(self.greedy, self.beam[:-1] + [self.beam[0]], self.targets)

    def test_real_journal_first_then_score_with_source_derived_targets(self):
        selected, _ = source_probe_plan(
            self.docs, revision=2, roots=self.reader.roots, maximum=2
        )
        answers = {}
        for item in selected:
            q = paraphrase_writer_question(item)
            answers[tuple(render(self.reader.tokenizer, q, [], []))] = item["target"]
        self.assertEqual(len(answers), 2)
        with tempfile.TemporaryDirectory() as root:
            result = paired_probe(
                self.reader,
                self.docs,
                Path(root) / "factorial",
                snapshot_sha="a" * 64,
                writer_source="b" * 40,
                source_commit="c" * 40,
                maximum=2,
                greedy=lambda r, prompt, arm: ("wrong", 1, 0.01),
                beam=lambda r, prompt, arm: (
                    answers[tuple(prompt)] if arm == "memory" else "wrong",
                    1,
                    0.02,
                ),
            )
            self.assertEqual(result["actual_generator_calls"], 8)
            self.assertEqual(
                result["decoder_effect_holding_adapter_fixed"]["memory"][
                    "candidate_wins"
                ],
                2,
            )
            self.assertEqual(self.reader.verified, 2)
            base = Path(root) / "factorial"
            self.assertTrue((base / "plan.json").exists())
            self.assertTrue((base / "report.json").exists())
            for decoder in ("greedy", "beam2"):
                original = (base / decoder / "raw-answers.jsonl").read_text()
                self.assertNotIn('"target"', original)
                self.assertEqual(len(original.splitlines()), 4)

    def test_same_tokens_with_different_scope_fail_before_generation(self):
        class ScopeErasingTokenizer(UniqueQuestionTokenizer):
            def apply_chat_template(self, messages, **kwargs):
                # This is deliberately NOT the actual Reader contract.
                text = json.loads(messages[1]["content"])["question"]
                return [1, *text.encode("utf-8")]

        self.reader.tokenizer = ScopeErasingTokenizer()
        calls = []
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "factorial"
            with self.assertRaisesRegex(ValueError, "colliding source questions"):
                paired_probe(
                    self.reader,
                    self.docs,
                    destination,
                    snapshot_sha="a" * 64,
                    writer_source="b" * 40,
                    source_commit="c" * 40,
                    maximum=2,
                    greedy=lambda *args: calls.append("greedy"),
                    beam=lambda *args: calls.append("beam"),
                )
            self.assertEqual(calls, [])
            self.assertFalse(destination.exists())

    def test_generation_failure_persists_without_false_joint_success(self):
        calls = 0

        def fail_once(reader, prompt, arm):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("injected failure")
            return "wrong", 1, 0.01

        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "factorial"
            with self.assertRaises(ValueError):
                paired_probe(
                    self.reader,
                    self.docs,
                    dest,
                    snapshot_sha="a" * 64,
                    writer_source="b" * 40,
                    source_commit="c" * 40,
                    maximum=2,
                    greedy=fail_once,
                    beam=lambda *args: self.fail("beam called despite failed greedy"),
                )
            self.assertTrue((dest / "greedy/raw-answers.jsonl").exists())
            self.assertFalse((dest / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
