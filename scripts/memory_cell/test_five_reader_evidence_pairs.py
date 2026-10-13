"""Paired-objective tests use tiny random fixtures, not capability evidence."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import torch

import five_causal_experiments as c
import five_reader_response_learning as learning
import five_reader_evidence_pairs as p
import five_reader_evidence_pair_trial as study
from test_five_reader_response import Tokenizer, examples, NativeAdapterTests


class ContextTokenizer(Tokenizer):
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        prefix = [1, 10 if "fixture source" in messages[1]["content"] else 11, 3]
        if add_generation_prompt:
            return prefix
        return prefix + [4 + ord(x) % 64 for x in messages[-1]["content"]] + [2]


def backend():
    obj = NativeAdapterTests().backend()
    obj.tokenizer = ContextTokenizer()
    return obj


class PairContractTests(unittest.TestCase):
    def test_pairing_independent_of_input_order(self):
        rows = examples()
        self.assertEqual(p.paired_examples(rows), p.paired_examples(list(reversed(rows))))

    def test_missing_and_duplicate_partner_rejected(self):
        for rows in (examples()[:-1], examples()+[deepcopy(examples()[0])]):
            with self.assertRaises(c.Invalid): p.paired_examples(rows)

    def test_context_question_family_and_scope_cannot_change(self):
        for key, value in (("family", "other"), ("source_sha256", "b"*64), ("split", "select")):
            rows = examples(); rows[1][key] = value
            with self.assertRaises(c.Invalid): p.paired_examples(rows)
        rows = examples(); rows[1]["request"]["question"] = "Another question"
        with self.assertRaises(c.Invalid): p.paired_examples(rows)

    def test_nonempty_negative_and_refusal_positive_rejected(self):
        rows = examples(); rows[1]["request"] = deepcopy(rows[0]["request"])
        with self.assertRaises(c.Invalid): p.paired_examples(rows)
        rows = examples(); rows[0]["response"] = learning.REFUSAL
        with self.assertRaises(c.Invalid): p.paired_examples(rows)

    def test_select_not_relabelled_train(self):
        rows = examples()
        for row in rows: row["split"] = "select"
        self.assertEqual(p.paired_examples(rows, training=False)[0][0]["split"], "select")
        with self.assertRaises(c.Invalid): p.prepare(ContextTokenizer(), rows, position_cap=128)
        for row in rows: row["split"] = "test"
        with self.assertRaises(c.Invalid): p.paired_examples(rows, training=False)

    def test_four_real_context_target_sequences_and_masks(self):
        rows = examples(); old = deepcopy(rows)
        batch, meta = p.prepare(ContextTokenizer(), rows, position_cap=128)[0]
        self.assertEqual(rows, old)
        self.assertEqual(len(batch["variants"]), 4)
        self.assertEqual(len({m["input_ids_sha256"] for _, m in batch["variants"]}), 4)
        for item, rec in batch["variants"]:
            self.assertTrue(bool((item["labels"][:, :rec["prefix_tokens"]] == -100).all()))
        self.assertGreater(meta["response_tokens"], meta["target_fit_tokens"])

    def test_metadata_only_conditions_cannot_be_neural_evidence(self):
        with self.assertRaisesRegex(c.Invalid, "identical input"):
            p.prepare(Tokenizer(), examples(), position_cap=128)

    def test_no_silent_response_truncation(self):
        rows = examples(); rows[0]["response"] = "x"*100
        with self.assertRaises(c.Invalid): p.prepare(ContextTokenizer(), rows, position_cap=128)

    def test_input_and_target_objects_never_mutated(self):
        rows = examples(); old = deepcopy(rows)
        shuffled = learning.permuted_positive_targets(rows)
        p.prepare(ContextTokenizer(), shuffled, position_cap=128)
        self.assertEqual(rows, old)
        for a, b in zip(rows, shuffled): self.assertEqual(a["request"], b["request"])


class LossTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_same_as_hf_shifted_response_loss(self):
        obj = backend()
        batch, _ = p.prepare(obj.tokenizer, examples(), position_cap=128)[0][0]["variants"][0]
        with torch.no_grad():
            expected = obj.loaded(**batch, use_cache=False).loss
            observed = -p.sequence_score(obj.loaded, batch)
        torch.testing.assert_close(observed, expected)

    def test_prompt_and_last_logits_are_not_scored(self):
        logits = torch.zeros((1, 5, 8), requires_grad=True)
        labels = torch.tensor([[-100, -100, -100, 4, 2]])
        p.mean_response_logp(logits, labels).backward()
        self.assertEqual(float(logits.grad[:, :2].abs().sum()), 0.0)
        self.assertEqual(float(logits.grad[:, -1].abs().sum()), 0.0)
        self.assertGreater(float(logits.grad[:, 2:4].abs().sum()), 0.0)

    def test_nonfinite_and_empty_target_fail(self):
        logits = torch.zeros((1, 3, 8)); labels = torch.tensor([[-100, 2, 3]])
        logits[0, 1, 1] = float("nan")
        with self.assertRaises(c.Invalid): p.mean_response_logp(logits, labels)
        with self.assertRaises(c.Invalid): p.mean_response_logp(torch.zeros_like(logits), torch.full_like(labels, -100))

    def test_paired_preferences_need_context_interaction(self):
        result = p.metrics([-3.0, -1.0, -3.0, -1.0])
        self.assertEqual(result["evidence_interaction"], 0.0)
        self.assertFalse(result["both_conditional_preferences_positive"])
        self.assertTrue(p.metrics([-1.0, -3.0, -3.0, -1.0])["both_conditional_preferences_positive"])

    def test_margin_pushes_against_both_unconditional_refusal_and_answer(self):
        scores = torch.tensor([-4., -1., -4., -1.], requires_grad=True)
        loss = p.part_loss(scores[0], scores[1], p.MARGIN) + p.part_loss(scores[3], scores[2], p.MARGIN)
        loss.backward()
        self.assertLess(float(scores.grad[0]), 0)
        self.assertGreater(float(scores.grad[1]), 0)
        self.assertGreater(float(scores.grad[2]), 0)
        self.assertLess(float(scores.grad[3]), 0)

    def test_ce_does_not_backpropagate_dummy_countertarget_loss(self):
        scores = torch.tensor([-4., -1.], requires_grad=True)
        p.part_loss(scores[0], scores[1], p.CE).backward()
        self.assertEqual(float(scores.grad[1]), 0.0)
        self.assertLess(float(scores.grad[0]), 0)

    def test_unknown_objective_rejected(self):
        with self.assertRaises(c.Invalid): p.part_loss(torch.tensor(-1.), torch.tensor(-2.), "guessed")


class NativePairedTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_real_pair_optimization_and_saved_reload_for_both_objectives(self):
        for objective in p.OBJECTIVES:
            with self.subTest(objective=objective), tempfile.TemporaryDirectory() as folder:
                obj = backend()
                original = learning.state_digest(obj.loaded.state_dict())
                result = learning.fit_response_adapter(obj, examples(), Path(folder)/"fit", epochs=1, loss_profile=objective)
                self.assertEqual(result["optimizer_steps"], 2)
                self.assertEqual(result["training_forwards"], 8)
                self.assertEqual(result["base_tensor_sha256"], original)
                self.assertTrue(result["base_unchanged"] and result["checkpoint_reload_equal"])
                self.assertTrue(all(not x.requires_grad for x in obj.loaded.parameters()))
                self.assertGreater(result["scored_response_tokens_processed"], result["supervised_tokens_processed"])
                self.assertEqual(result["loss_objective"]["name"], objective)
                self.assertFalse(result["production_accepted"])

    def test_diagnosis_counts_real_forwards_and_keeps_parameters(self):
        obj = backend(); before = learning.state_digest(obj.loaded.state_dict())
        with learning.count_forwards(obj.loaded.base_model) as count:
            result = p.diagnose(obj.loaded, obj.tokenizer, examples(), position_cap=128)
        self.assertEqual(count["model_calls"], 8)
        self.assertEqual(len(result), 2)
        self.assertEqual(learning.state_digest(obj.loaded.state_dict()), before)

    def test_select_rejected_before_wrap_or_output(self):
        rows = examples()
        for row in rows: row["split"] = "select"
        obj = backend()
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/"fit"
            with self.assertRaises(c.Invalid): learning.fit_response_adapter(obj, rows, out, loss_profile=p.MARGIN)
            self.assertFalse(out.exists())
            self.assertFalse(hasattr(obj.loaded, "peft_config"))

    def test_exception_retains_attempt_count_and_never_retries(self):
        obj = backend()
        original = obj.loaded.base_model.forward
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2: raise RuntimeError("fixture decoder failure")
            return original(*args, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/"fit"
            with patch.object(obj.loaded.base_model, "forward", side_effect=fail_second):
                with self.assertRaises(RuntimeError): learning.fit_response_adapter(obj, examples(), out, epochs=1, loss_profile=p.MARGIN)
            import json
            records = [json.loads(line)["record"] for line in (out/"optimizer-journal.jsonl").read_text().splitlines()]
            self.assertEqual(records[-1]["event"], "optimizer_failed_or_unknown")
            self.assertEqual(records[-1]["observed_decoder_forwards"], 2)
            self.assertFalse((out/"training-receipt.json").exists())
            self.assertEqual(len(calls), 2)
            self.assertFalse(obj.loaded.base_model._forward_pre_hooks)


class DevelopmentStudyTests(unittest.TestCase):
    def benchmark(self):
        qs = [SimpleNamespace(identity="q"+str(i), family="f"+str(i), content="Fixture?") for i in range(6)]
        class NoTargets:
            def __getitem__(self, key): raise AssertionError("target used in selection")
        return SimpleNamespace(questions=qs, families={q.family:q.family for q in qs},
            partition=lambda q: ("train" if q.identity in ("q0", "q1") else "select" if q.identity in ("q2", "q3") else "test"),
            history=lambda q:[SimpleNamespace(root=q.identity)], targets=NoTargets())

    def test_validation_selection_excludes_old_test_and_does_not_read_targets(self):
        selected, forbidden = study.choose(self.benchmark())
        self.assertEqual({q.identity for q in selected["select"]}, {"q2", "q3"})
        self.assertEqual(set(forbidden), {"f4", "f5"})
        self.assertNotIn("test", selected)

    def test_source_overlap_between_training_and_validation_fails(self):
        b = self.benchmark(); b.history = lambda q:[SimpleNamespace(root="shared")]
        with self.assertRaises(c.Invalid): study.choose(b)

    def test_readout_keeps_failure_and_missing_target(self):
        rows = [{"split":"select", "condition":"support_only", "status":"failed", "benchmark_exact_body":False},
                {"split":"select", "condition":"support_only", "status":"succeeded", "benchmark_exact_body":None}]
        report = study.aggregate(rows)[0]
        self.assertEqual(report["planned"], 2)
        self.assertEqual(report["available_targets"], 1)
        self.assertEqual(report["status_census"], {"failed":1,"succeeded":1})


if __name__ == "__main__":
    unittest.main()
