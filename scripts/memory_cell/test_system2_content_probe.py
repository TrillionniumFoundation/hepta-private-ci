"""Hermetic interventions, not native model or independent human observations."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from torch import nn

from system2_ablation import Continuation, BudgetExceeded, model_digest
from system2_content_probe import (
    evaluate,
    fit,
    gate,
    matched_opportunities,
    pair_at,
    run_content_probe,
)
from test_system2_learning_probe import inputs


class ContentTests(unittest.TestCase):
    def test_all_pairs_same_nonzero_cardinality_one_replacement(self):
        rows, cut = inputs()
        items, disposition = matched_opportunities(rows, cut, 4)
        self.assertTrue(all(d["eligible"] for d in disposition))
        for item in items:
            for pos, neg in item.pairs:
                self.assertEqual(len(pos), len(neg))
                self.assertGreater(len(pos), 0)
                self.assertEqual(len(set(pos) ^ set(neg)), 2)
                self.assertIn(0, pos)
                self.assertNotIn(0, neg)

    def test_pair_schedule_cycles_per_question(self):
        rows, cut = inputs()
        items, _ = matched_opportunities(rows, cut, 4)
        pairs = items[0].pairs
        self.assertEqual([len(pair_at(pairs, i)[0]) for i in range(4)], [1, 2, 1, 2])
        self.assertNotEqual(pair_at(pairs, 0), pair_at(pairs, 2))

    def test_late_unadmitted_row_precedes_label_access(self):
        rows, cut = inputs()

        class ForbiddenLabel:
            features = rows[0].features

            @property
            def positive_indices(self):
                raise AssertionError("early label access")

        cut.question_ids.remove(rows[-1].features.question_id)
        with self.assertRaises(ValueError):
            matched_opportunities((ForbiddenLabel(), *rows[1:]), cut, 4)

    def test_no_same_size_negative_not_relabelled_null(self):
        rows, cut = inputs()
        for r in rows:
            r.positive_indices = (0, 1, 2)
        model = Continuation(4, hidden=4)
        before = model_digest(model)
        result = fit(model, rows, cut)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["updates"], 0)
        self.assertEqual(model_digest(model), before)

    def test_no_positive_is_not_trained_as_unanswerability(self):
        rows, cut = inputs()
        for r in rows:
            r.positive_indices = ()
        report = run_content_probe(rows, cut, 4, steps=4)
        self.assertTrue(
            all(m["status"] == "unavailable" for m in report["methods"].values())
        )
        self.assertFalse(report["paired_shapes_calls_updates_matched"])
        self.assertEqual(
            report["next_gate"], "stop_incomplete_or_no_matched_opportunity"
        )

    def test_actual_updates_exact_work_and_labels_matched(self):
        rows, cut = inputs()
        a = fit(Continuation(4, hidden=4), rows, cut, method="content", steps=16)
        b = fit(Continuation(4, hidden=4), rows, cut, method="content_erased", steps=16)
        self.assertNotEqual(a["before"], a["after"])
        self.assertEqual(a["before"], b["before"])
        self.assertEqual(
            a["costs"]["attempted_operations"], b["costs"]["attempted_operations"]
        )
        for x, y in zip(a["records"], b["records"], strict=True):
            self.assertEqual(x["paths"], y["paths"])
            self.assertEqual(x["targets"], y["targets"])
            self.assertEqual(y["predictions"][0], y["predictions"][1])

    def test_erased_control_cannot_rank_equal_size_pairs(self):
        rows, cut = inputs()
        model = Continuation(4, hidden=4)
        fit(model, rows, cut, method="content_erased", steps=16)
        items, _ = matched_opportunities(rows, cut, 4)
        result = evaluate(model, items, "content_erased")
        self.assertEqual(result["matched_pair_question_macro"], 0.5)
        self.assertTrue(
            all(r["max_absolute_pair_margin"] == 0 for r in result["records"])
        )

    def test_length_only_predictor_cannot_win_matched_pairs(self):
        rows, cut = inputs()
        items, _ = matched_opportunities(rows, cut, 4)

        class CountOnly(nn.Module):
            dimension = 4
            quarantined = False
            encoder_identity = None
            roots = frozenset()

            def forward(self, paired):
                return torch.tensor(0.1 + 0.2 * len(paired))

        result = evaluate(CountOnly(), items, "content")
        self.assertEqual(result["matched_pair_question_macro"], 0.5)
        self.assertTrue(
            all(r["max_absolute_pair_margin"] == 0 for r in result["records"])
        )

    def test_collapsed_model_free_argmax_still_selects_empty(self):
        rows, cut = inputs()
        items, _ = matched_opportunities(rows, cut, 4)
        model = Continuation(4, hidden=4)
        with torch.no_grad():
            for p in model.parameters():
                p.zero_()
        result = evaluate(model, items, "content")
        self.assertEqual(result["empty_choices"], len(rows))
        self.assertEqual(result["weak_support_hits"], 0)

    def test_eval_does_not_mutate_shared_features_or_weights(self):
        rows, cut = inputs()
        items, _ = matched_opportunities(rows, cut, 4)
        stamps = [r.features.seal() for r in rows]
        model = Continuation(4, hidden=4)
        before = model_digest(model)
        evaluate(model, items, "content_erased")
        self.assertEqual(before, model_digest(model))
        self.assertEqual(stamps, [r.features.seal() for r in rows])

    def test_budget_failure_recorded_quarantines_no_completed_update(self):
        rows, cut = inputs()
        model = Continuation(4, hidden=4)
        with self.assertRaises(BudgetExceeded):
            fit(model, rows, cut, operation_ceiling=1)
        self.assertTrue(model.quarantined)
        self.assertEqual(model.last_content_failure["completed_updates"], 0)
        self.assertEqual(len(model.last_content_failure["records"]), 1)

    def test_revocation_and_encoder_drift_before_update(self):
        rows, cut = inputs()
        for case in ("root", "encoder"):
            model = Continuation(4, hidden=4)
            if case == "root":
                model.roots = frozenset({"withdrawn"})
            else:
                model.encoder_identity = "different"
            before = model_digest(model)
            with self.assertRaises(ValueError):
                fit(model, rows, cut, revoked=frozenset({"withdrawn"}))
            self.assertEqual(before, model_digest(model))

    def test_invalid_method_label_or_steps_rejects(self):
        rows, cut = inputs()
        for kw in (dict(method="unknown"), dict(steps=True), dict(steps=0)):
            with self.assertRaises(ValueError):
                fit(Continuation(4), rows, cut, **kw)
        rows[-1].positive_indices = (True,)
        with self.assertRaises(ValueError):
            fit(Continuation(4), rows, cut)

    def test_local_grad_enable_and_inference_rejection(self):
        rows, cut = inputs()
        with torch.no_grad():
            r = fit(Continuation(4, hidden=4), rows, cut, steps=2)
        self.assertEqual(r["updates"], 2)
        with torch.inference_mode(), self.assertRaises(ValueError):
            fit(Continuation(4), rows, cut, steps=2)

    def test_source_family_macro_not_raw_pair_count(self):
        rows, cut = inputs()
        items, _ = matched_opportunities(rows, cut, 4)
        r = evaluate(Continuation(4), items, "content")
        self.assertEqual(r["planned_questions"], 4)
        self.assertEqual(r["eligible_families"], 1)
        self.assertTrue(r["paired_comparisons_are_not_independent_samples"])

    def test_exact_safetensors_reloads_and_explicit_nonclaims(self):
        rows, cut = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "probe"
            r = run_content_probe(rows, cut, 4, steps=4, output=out)
            self.assertEqual(set(r["snapshots"]), {"content", "content_erased"})
            self.assertTrue(
                all(s["reload_tensor_parity"] for s in r["snapshots"].values())
            )
            self.assertTrue((out / "train-features.safetensors").is_file())
            self.assertEqual(r["actual_reader_calls"], 0)
            self.assertFalse(r["reader_adequacy_established"])
            self.assertFalse(r["superiority_claim"])
            self.assertFalse(r["production_accepted"])

    def test_gate_requires_beating_frozen_and_erased_not_only_initial(self):
        initial = dict(
            content=dict(matched_pair_question_macro=0.25, weak_support_hits=0)
        )
        results = {
            "content": dict(
                status="succeeded",
                after=dict(
                    matched_pair_question_macro=0.6,
                    frozen_max_score_question_macro=0.7,
                    weak_support_hits=1,
                ),
            ),
            "content_erased": dict(
                status="succeeded", after=dict(matched_pair_question_macro=0.5)
            ),
        }
        self.assertEqual(
            gate(initial, results), "stop_no_content_gain_over_all_train_controls"
        )
        results["content"]["after"]["matched_pair_question_macro"] = 0.8
        self.assertEqual(
            gate(initial, results), "fresh_confirmation_and_reader_controls_required"
        )
        results["content"]["after"]["weak_support_hits"] = 0
        self.assertEqual(gate(initial, results), "stop_no_free_choice_training_gain")

    def test_failed_method_not_discarded(self):
        rows, cut = inputs()
        with patch("system2_content_probe.fit", side_effect=RuntimeError("injected")):
            r = run_content_probe(rows, cut, 4, steps=4)
        self.assertTrue(all(x["status"] == "failed" for x in r["methods"].values()))
        self.assertEqual(r["next_gate"], "stop_incomplete_or_no_matched_opportunity")


if __name__ == "__main__":
    unittest.main()
