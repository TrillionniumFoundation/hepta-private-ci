"""Hermetic mechanics, not pretrained-model or independent human evidence."""

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from system2_ablation import BudgetExceeded, Continuation, model_digest
from system2_learning_probe import cycle_path, fit_paired, inspect, prepare, run_probe
from test_system2_ablation import fixture


def inputs(count=4):
    rows = tuple(
        SimpleNamespace(
            features=fixture(seed=719 + i, qid=f"train-{i}", family="train"),
            positive_indices=(0,),
        )
        for i in range(count)
    )
    cut = SimpleNamespace(
        question_ids={r.features.question_id for r in rows},
        families={"train"},
        allowed_roots=frozenset({"fixture-root"}),
        forbidden_roots=frozenset(),
        admission_digest="fixture-cut",
    )
    return rows, cut


class PairedOpportunityTests(unittest.TestCase):
    def test_whole_cut_validated_before_any_annotation(self):
        rows, cut = inputs()

        class NoLabelAccess:
            features = rows[0].features

            @property
            def positive_indices(self):
                raise AssertionError("annotation accessed before admission")

        cut.question_ids.remove(rows[-1].features.question_id)
        with self.assertRaises(ValueError):
            prepare((NoLabelAccess(), *rows[1:]), cut, 4)

    def test_every_visited_question_has_both_labels_not_global_alias(self):
        rows, cut = inputs()
        m = Continuation(4, hidden=4)
        before = model_digest(m)
        result = fit_paired(m, rows, cut, steps=16)
        self.assertEqual(result["updates"], 16)
        self.assertEqual(set(result["visits"].values()), {4})
        self.assertNotEqual(before, model_digest(m))
        self.assertEqual(result["costs"]["attempted_operations"]["critic_forward"], 32)
        for qid in cut.question_ids:
            events = [e for e in result["records"] if e["question_id"] == qid]
            self.assertTrue(
                all(
                    0 in e["positive_indices"] and 0 not in e["negative_indices"]
                    for e in events
                )
            )
            self.assertGreater(len({len(e["positive_indices"]) for e in events}), 1)
            self.assertTrue(any(not e["negative_indices"] for e in events))

    def test_random_control_matches_each_path_length_and_updates(self):
        rows, cut = inputs()
        a = fit_paired(Continuation(4, hidden=4), rows, cut, steps=16)
        b = fit_paired(
            Continuation(4, hidden=4),
            rows,
            cut,
            steps=16,
            sampling="shape_matched_random",
        )
        self.assertEqual(
            a["costs"]["attempted_operations"], b["costs"]["attempted_operations"]
        )
        for x, y in zip(a["records"], b["records"], strict=True):
            self.assertEqual(x["question_id"], y["question_id"])
            self.assertEqual([len(p) for p in x["paths"]], [len(p) for p in y["paths"]])
            self.assertEqual(y["targets"], [float(0 in p) for p in y["paths"]])

    def test_cardinality_cycles_with_local_visits(self):
        paths = ((), (1,), (2,), (1, 2))
        self.assertEqual(
            [len(cycle_path(paths, v)) for v in range(6)], [0, 1, 2, 0, 1, 2]
        )
        self.assertNotEqual(cycle_path(paths, 1), cycle_path(paths, 4))

    def test_no_positive_is_unavailable_not_null_supervision(self):
        rows, cut = inputs()
        rows = tuple(
            SimpleNamespace(features=r.features, positive_indices=()) for r in rows
        )
        m = Continuation(4, hidden=4)
        before = model_digest(m)
        report = fit_paired(m, rows, cut)
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["updates"], 0)
        self.assertEqual(before, model_digest(m))
        self.assertTrue(all(not r["eligible"] for r in report["disposition"]))

    def test_probe_does_not_force_nonempty_selection(self):
        rows, cut = inputs()
        opportunities, _ = prepare(rows, cut, 4)
        m = Continuation(4, hidden=4)
        for p in m.parameters():
            p.data.zero_()
        result = inspect(m, opportunities)
        self.assertEqual(result["empty_choices"], len(rows))
        self.assertEqual(result["weak_support_hits"], 0)

    def test_failure_keeps_work_and_quarantines(self):
        rows, cut = inputs()
        m = Continuation(4, hidden=4)
        with self.assertRaises(BudgetExceeded):
            fit_paired(m, rows, cut, operation_ceiling=1)
        self.assertTrue(m.quarantined)
        self.assertEqual(m.last_probe_failure["completed_updates"], 0)
        self.assertEqual(len(m.last_probe_failure["records"]), 1)
        self.assertGreater(
            sum(m.last_probe_failure["costs"]["attempted_operations"].values()), 1
        )

    def test_invalid_second_label_rejects_without_updates(self):
        rows, cut = inputs()
        rows[1].positive_indices = (True,)
        m = Continuation(4, hidden=4)
        before = model_digest(m)
        with self.assertRaises(ValueError):
            fit_paired(m, rows, cut)
        self.assertEqual(model_digest(m), before)

    def test_source_revocation_before_probe_or_training(self):
        rows, cut = inputs()
        m = Continuation(4, hidden=4)
        with self.assertRaises(ValueError):
            fit_paired(m, rows, cut, revoked=frozenset({"fixture-root"}))
        m.roots = frozenset({"other-withdrawn"})
        with self.assertRaises(ValueError):
            fit_paired(m, rows, cut, revoked=m.roots)

    def test_mixed_encoder_or_duplicate_census_refused(self):
        rows, cut = inputs()
        with self.assertRaises(ValueError):
            prepare((*rows, rows[0]), cut, 4)
        rows[1].features = replace(rows[1].features, encoder_identity="other")
        with self.assertRaises(ValueError):
            prepare(rows, cut, 4)

    def test_grad_context_and_inference_mode(self):
        rows, cut = inputs()
        with torch.no_grad():
            report = fit_paired(Continuation(4, hidden=4), rows, cut, steps=4)
        self.assertEqual(report["updates"], 4)
        with torch.inference_mode(), self.assertRaises(ValueError):
            fit_paired(Continuation(4, hidden=4), rows, cut, steps=4)

    def test_gate_does_not_advance_when_random_control_wins(self):
        rows, cut = inputs()
        initial = dict(model_digest=model_digest(Continuation(4)), weak_support_hits=0)
        learned = dict(
            status="succeeded", costs=dict(attempted_operations={"critic_forward": 32})
        )
        with (
            patch(
                "system2_learning_probe.inspect",
                side_effect=[
                    initial,
                    dict(weak_support_hits=0),
                    dict(weak_support_hits=4),
                    dict(weak_support_hits=2),
                ],
            ),
            patch("system2_learning_probe.train_continuation", return_value={}),
            patch("system2_learning_probe.fit_paired", return_value=learned),
        ):
            report = run_probe(rows, cut, 4, steps=16)
        self.assertTrue(report["observed_training_decision_gain"])
        self.assertFalse(report["paired_over_random_training_decision_gain"])
        self.assertEqual(report["next_gate"], "stop_no_gain_over_matched_random")

    def test_comparison_keeps_equal_initialization_and_no_task_claim(self):
        rows, cut = inputs()
        report = run_probe(rows, cut, 4, steps=16)
        initial = report["initial"]["model_digest"]
        self.assertEqual(report["methods"]["legacy"]["training"]["before"], initial)
        self.assertEqual(report["methods"]["paired"]["training"]["before"], initial)
        self.assertEqual(report["actual_reader_calls"], 0)
        self.assertTrue(report["paired_random_neural_shapes_and_calls_matched"])
        self.assertFalse(report["matched_training_compute"])
        self.assertFalse(report["reader_adequacy_established"])
        self.assertFalse(report["production_accepted"])


if __name__ == "__main__":
    unittest.main()
