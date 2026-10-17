"""In-sample conditional likelihood mechanics; fixture scores are not evidence."""

import json
from pathlib import Path
import tempfile
import unittest

import torch

from source_recall_likelihood import (
    ARMS,
    COMPLETIONS,
    REFUSAL,
    WORDINGS,
    conditional_nll,
    probe,
)
from test_experience_memory import source
from test_source_recall_probe import FakeReader
from test_source_write_training import reader as tiny_qwen_reader


class LikelihoodTests(unittest.TestCase):
    def setUp(self):
        self.documents = (
            source("a", "site_a", scope="a"),
            source("b", "site_b", scope="b"),
        )
        self.reader = FakeReader(self.documents)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "likelihood"

    def run_probe(self, scorer):
        return probe(
            self.reader,
            self.documents,
            self.output,
            snapshot_sha="a" * 64,
            writer_source="b" * 40,
            source_commit="c" * 40,
            maximum=2,
            scorer=scorer,
        )

    @staticmethod
    def scored(reader, prompt, completion, arm):
        is_target = completion != REFUSAL
        nll = (
            (0.6 if arm == "base" else 0.3)
            if is_target
            else (0.2 if arm == "base" else 0.4)
        )
        return dict(
            mean_nll=nll,
            input_tokens=len(prompt) + 2,
            supervised_tokens=2,
            seconds=0.01,
        )

    def test_balanced_census_and_two_wordings_no_evaluation_targets(self):
        result = self.run_probe(self.scored)
        self.assertEqual(result["planned_records"], 16)
        self.assertEqual(result["completed_records"], 16)
        self.assertEqual(self.reader.verified, 1)
        for wording in WORDINGS:
            comparison = result["score_comparisons"][wording]
            self.assertEqual(comparison["complete_base_adapter_pairs"], 2)
            self.assertEqual(comparison["target_mean_nll_decreased_count"], 2)
            self.assertEqual(
                comparison["relative_target_refusal_margin_improved_count"], 2
            )
            self.assertAlmostEqual(comparison["mean_target_nll_change"], 0.3)
            self.assertAlmostEqual(comparison["mean_relative_margin_change"], 0.5)
        plan = json.loads((self.output / "plan.json").read_text())
        rows = [
            json.loads(line)
            for line in (self.output / "raw-likelihoods.jsonl").read_text().splitlines()
        ]
        self.assertEqual({r["wording"] for r in rows}, set(WORDINGS))
        self.assertEqual({r["arm"] for r in rows}, set(ARMS))
        self.assertEqual({r["completion_kind"] for r in rows}, set(COMPLETIONS))
        self.assertTrue(all(r["delivered_evidence"] == [] for r in rows))
        self.assertTrue(all("target" not in r or r["target"] is None for r in rows))
        self.assertNotIn('"target": "site_', (self.output / "plan.json").read_text())
        self.assertFalse(plan["future_evaluation_plan_or_answers_used"])
        self.assertIsNone(result["parameter_memory_task_gain"])
        self.assertFalse(result["production_accepted"])
        with self.assertRaises(ValueError):
            self.run_probe(self.scored)

    def test_invalid_score_is_not_silently_counted_as_gain(self):
        def invalid(reader, prompt, completion, arm):
            if arm == "memory" and completion == REFUSAL:
                return dict(
                    mean_nll=float("nan"),
                    input_tokens=len(prompt) + 2,
                    supervised_tokens=2,
                    seconds=0.01,
                )
            return self.scored(reader, prompt, completion, arm)

        with self.assertRaises(ValueError):
            self.run_probe(invalid)
        result = json.loads((self.output / "report.json").read_text())
        self.assertEqual(result["completed_records"], 12)
        self.assertEqual(
            result["score_comparisons"]["training"]["complete_base_adapter_pairs"], 0
        )
        self.assertEqual(
            result["score_comparisons"]["paraphrase"]["missing_or_failed_scopes"], 2
        )

    def test_scope_and_provenance_reject_before_any_scoring(self):
        invoked = []
        for docs, sha in (
            (self.documents[:1], "a" * 64),
            (self.documents, "missing-sha"),
        ):
            with self.subTest(sha=sha, scope_count=len(docs)):
                with self.assertRaises(ValueError):
                    probe(
                        self.reader,
                        docs,
                        self.output,
                        snapshot_sha=sha,
                        writer_source="b" * 40,
                        source_commit="c" * 40,
                        scorer=lambda *args: invoked.append(True),
                    )
        self.assertEqual(invoked, [])
        self.assertFalse(self.output.exists())

    def test_real_tiny_qwen_base_adapter_likelihood_does_not_update_weights(self):
        model = tiny_qwen_reader()
        model.model.eval()
        for parameter in model.model.parameters():
            parameter.grad = None
            parameter.requires_grad_(False)
        before = {
            name: p.detach().clone() for name, p in model.model.named_parameters()
        }
        prompt = [1, 2, 3]
        for completion in ("site_a", REFUSAL):
            for arm in ARMS:
                score = conditional_nll(model, prompt, completion, arm)
                self.assertTrue(0 <= score["mean_nll"] < float("inf"))
                self.assertEqual(score["supervised_tokens"], 2)
                self.assertEqual(score["input_tokens"], 5)
        self.assertTrue(
            all(
                torch.equal(p, before[name])
                for name, p in model.model.named_parameters()
            )
        )
        self.assertTrue(
            all(
                not p.requires_grad and p.grad is None for p in model.model.parameters()
            )
        )


if __name__ == "__main__":
    unittest.main()
