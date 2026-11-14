import hashlib
from dataclasses import replace
import unittest

import torch
from torch import nn

from multirc_data import ReaderCase
from token_campaign_utils import (DeletedDataset, choose_threshold, evaluate_panel,
                                  evidence_deltas, infer, summarize_panel)
from token_reader_training import TokenBatch


def cases_fixture():
    return tuple(ReaderCase("p", str(index // 2), str(index % 2), "Which fact?", str(index),
        ("The evidence is present.",), int(index % 2 == 0), "train", "1" * 64)
        for index in range(4))


class FakeBank:
    def __init__(self):
        self.physical_calls = []

    def batch(self, cases):
        self.physical_calls.append([case.case_id for case in cases])
        size = len(cases)
        return TokenBatch(facts=torch.ones(size, 1, 1, 8), question=torch.ones(size, 1, 8),
            candidate=torch.tensor([float(case.candidate) - 1.5 for case in cases])[:, None, None].expand(-1, 1, 8),
            fact_mask=torch.ones(size, 1, 1, dtype=torch.bool),
            question_mask=torch.ones(size, 1, dtype=torch.bool),
            candidate_mask=torch.ones(size, 1, dtype=torch.bool),
            targets=torch.tensor([case.label for case in cases]),
            source_groups=tuple(case.source_hash for case in cases))

    def public(self, case, deleted=False):
        return dict(feature_sha256=hashlib.sha256((case.case_id + str(deleted)).encode()).hexdigest())


class FakeReader(nn.Module):
    def __init__(self):
        super().__init__()
        self.eval()
        self.max_hops = 8
        self.argument_counts = []

    def forward(self, *features, steps, reset_state=False):
        self.argument_counts.append(len(features))
        facts, question, candidate, fact_mask, question_mask, candidate_mask = features
        value = candidate[:, 0, 0] + (facts * fact_mask.unsqueeze(-1)).sum((1, 2, 3)) / 8
        return torch.stack((torch.zeros_like(value), value), -1)


class TokenCampaignUtilityTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.cases = cases_fixture()

    def test_threshold_uses_all_candidate_f1_and_question_exact_match(self):
        selected = choose_threshold(self.cases, [.8, .7, .6, .1])
        self.assertEqual(selected["threshold"], .5)
        self.assertEqual(len(selected["candidates"]), 19)
        self.assertEqual(selected["candidates"][9]["metrics"]["questions"], 2)
        self.assertEqual(selected["candidates"][9]["metrics"]["f1_a"], .8)
        self.assertEqual(selected["candidates"][9]["metrics"]["exact_match"], .5)
        self.assertFalse(selected["final_outcomes_used"])
        with self.assertRaises(ValueError):
            choose_threshold(self.cases, [.1])
        for invalid in (float("nan"), float("inf"), -0.1, 1.1):
            with self.assertRaises(ValueError):
                choose_threshold(self.cases, [.1, .2, .3, invalid])

    def test_actual_physical_batch_receipts_are_counted_once(self):
        bank, model = FakeBank(), FakeReader()
        probability, batches = infer(model, self.cases, bank, batch_size=2, depth=3)
        self.assertEqual(len(probability), 4)
        self.assertEqual(bank.physical_calls, [row["case_ids"] for row in batches])
        self.assertEqual([len(row["case_ids"]) for row in batches], [2, 2])
        self.assertEqual([row["proposal_steps"] for row in batches], [6, 6])
        self.assertEqual(model.argument_counts, [6, 6])
        by_case = {case_id: batch["batch_id"] for batch in batches for case_id in batch["case_ids"]}
        rows = [dict(case_id=case.case_id, batch_id=by_case[case.case_id],
                     prediction=int(p > .5), raw_argmax=int(p > .5))
                for case, p in zip(self.cases, probability)]
        summary = summarize_panel(self.cases, rows, batches)
        self.assertEqual(summary["physical_batches"], 2)
        self.assertEqual(summary["cpu_ns"], sum(row["cpu_ns"] for row in batches))
        self.assertEqual(summary["wall_ns"], sum(row["wall_ns"] for row in batches))
        self.assertEqual(summary["proposal_steps"], 12)
        self.assertGreater(summary["cpu_ns"], 0)
        self.assertFalse(summary["per_answer_latency_measured"])
        with self.assertRaisesRegex(ValueError, "physical"):
            summarize_panel(self.cases, rows, batches + batches)

    def test_query_control_deletes_evidence_in_both_cohorts_and_pairs_outputs(self):
        bank = FakeBank()
        models = {name: FakeReader() for name in ("token", "query_only")}
        protocol = dict(expected_cohorts=["full", "deleted"], expected_arms=list(models),
            arm_input_transforms={"query_only": "delete_evidence"},
            arm_depths={"token": 3, "query_only": 1}, arm_thresholds=dict.fromkeys(models, .5),
            arm_model_sha256=dict.fromkeys(models, "2" * 64))
        rows, receipts, summaries = evaluate_panel(models, self.cases, bank, protocol, prefix="test")
        self.assertEqual(len(rows), 16)
        self.assertEqual(len(receipts), 4)
        self.assertEqual(len({row["batch_id"] for row in receipts}), 4)
        self.assertEqual(sum(row["cpu_ns"] for row in receipts),
                         sum(summary["cpu_ns"] for summary in summaries.values()))
        delta = evidence_deltas(rows)
        self.assertEqual(delta["query_only"]["mean_absolute_probability_shift"], 0)
        self.assertGreater(delta["token"]["mean_absolute_probability_shift"], 0)
        with self.assertRaisesRegex(ValueError, "both cohorts"):
            evidence_deltas([row for row in rows if row["cohort"] == "full"])

    def test_query_only_training_preserves_targets_and_removes_annotations(self):
        batch = FakeBank().batch(self.cases)
        batch = replace(batch, evidence_targets=torch.ones(4, 1),
                        evidence_supervision=torch.ones(4, dtype=torch.bool))
        data = DeletedDataset(batch)
        data.validate(8)
        deleted = data.take([0, 1])
        self.assertEqual(deleted.targets.tolist(), [1, 0])
        self.assertFalse(deleted.facts.any())
        self.assertFalse(deleted.fact_mask.any())
        self.assertIsNone(deleted.evidence_targets)
        self.assertIsNone(deleted.evidence_supervision)


if __name__ == "__main__":
    unittest.main()
