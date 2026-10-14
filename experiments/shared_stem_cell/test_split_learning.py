"""Actual train-only routing, inheritance controls and sealed scoring regressions."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import execution as e, controls as c
from experiments.shared_stem_cell.control_evaluation import evaluate_controls
from experiments.shared_stem_cell.split_learning import TrainingPartition, InheritedUnsplit
from experiments.shared_stem_cell.split_study import recommend, ARMS, cohort


class SplitLearningTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(73)
            self.x = torch.randn(24, 4)
            self.y = (self.x[:, 0] > 0).long()
            self.parent = e.Head(5, 2, "linear", 4).eval()
        self.partition, self.router_cost = TrainingPartition.fit(self.x)
        self.routed = self.partition.append_route(self.x)

    def trial(self):
        return c.split_trial(self.routed, self.y, self.routed[:4], classes=2,
                             steps=3, extra=(self.routed[4:8], self.y[4:8]), matched_inheritance=True)

    def test_router_is_fitted_without_labels_and_preserves_inputs_rng(self):
        state, x = torch.get_rng_state().clone(), self.x.clone()
        r, cost = TrainingPartition.fit(self.x)
        self.assertTrue(torch.equal(state, torch.get_rng_state()))
        self.assertTrue(torch.equal(x, self.x))
        self.assertEqual(sum(cost["training_route_counts"]), len(x))
        self.assertFalse(cost["labels_consumed"])
        self.assertTrue(torch.equal(r.assign(x), self.partition.assign(x)))
        with self.assertRaises(TypeError):
            TrainingPartition.fit(x, labels=self.y)

    def test_router_owns_centroids_and_no_inference_updates(self):
        source = torch.tensor([[-1., 0.], [1., 0.]])
        r = TrainingPartition(source)
        source.zero_()
        before = r.centers.clone()
        self.assertEqual(r.assign(torch.tensor([[-2., 0.], [2., 0.], [0., 0.]])).tolist(), [0, 1, 0])
        self.assertTrue(torch.equal(before, r.centers))

    def test_degenerate_router_does_not_invent_specialization(self):
        r, cost = TrainingPartition.fit(torch.ones(8, 4))
        self.assertTrue(cost["empty_child"])
        self.assertEqual(r.assign(torch.ones(8, 4)).tolist(), [0] * 8)

    def test_invalid_router_inputs_rejected(self):
        for x in (self.x.double(), self.x[:0], torch.full_like(self.x, float("nan")),
                  torch.full_like(self.x, 1e10), torch.zeros(2, 769)):
            with self.assertRaises(e.InputError):
                TrainingPartition.fit(x)
        with self.assertRaises(e.InputError):
            self.partition.assign(torch.ones(2, 3))

    def test_modernbert_768d_offline_routing_does_not_relax_native_profile(self):
        # Offline FP32 training-only centroid owner may consume 768d features.
        # It neither emits Q24 native ticks nor authorizes a production model.
        torch.manual_seed(73)
        features = torch.randn(16, 768, dtype=torch.float32)
        snapshot = features.clone()
        state = torch.get_rng_state().clone()
        route, cost = TrainingPartition.fit(features)
        self.assertTrue(torch.equal(state, torch.get_rng_state()))
        self.assertTrue(torch.equal(snapshot, features))
        self.assertEqual(route.centers.shape, (2, 768))
        self.assertEqual(cost["centroid_bytes"], 2 * 768 * 4)
        self.assertEqual(sum(cost["training_route_counts"]), len(features))
        self.assertFalse(cost["labels_consumed"])
        self.assertEqual(route.append_route(features).shape, (16, 769))
        with self.assertRaises(e.InputError):
            TrainingPartition.fit(torch.zeros(2, 769, dtype=torch.float32))
        with self.assertRaises(e.InputError):
            route.assign(torch.zeros(2, 512, dtype=torch.float32))

    def test_unsplit_capacity_preserves_parent_function_and_capped_parameters(self):
        count = e.parameters(self.parent)["parameters"]
        larger = InheritedUnsplit(self.parent, 2 * count)
        self.assertLessEqual(e.parameters(larger)["parameters"], 2 * count)
        self.assertGreater(e.parameters(larger)["parameters"], count)
        self.assertTrue(torch.equal(larger(self.routed), self.parent(self.routed)))
        before = e.parameters(self.parent)
        fitted, _ = e.fit(larger, self.routed, self.y, steps=3)
        self.assertNotEqual(e.parameters(fitted), e.parameters(larger))
        self.assertEqual(e.parameters(self.parent), before)

    def test_split_profile_preserves_rng_minibatches_and_work(self):
        state = torch.get_rng_state().clone()
        actual_steps = []
        original_step = torch.optim.AdamW.step
        def tracked_step(optimizer, *args, **kwargs):
            actual_steps.append(1)
            return original_step(optimizer, *args, **kwargs)
        with patch.object(torch.optim.AdamW, "step", tracked_step):
            result = self.trial()
        self.assertEqual(result["executed_training_work"]["optimizer_steps"], len(actual_steps))
        self.assertTrue(torch.equal(state, torch.get_rng_state()))
        self.assertEqual(set(result["predictions"]), set(ARMS))
        hashes = [result["costs"][arm]["minibatch_sha256"] for arm in
                  ("parent_continued", "inherited_split", "inherited_unsplit")]
        self.assertEqual(len(set(hashes)), 1)
        for arm in ARMS:
            work = result["per_arm_training_work"][arm]
            self.assertEqual(work["optimizer_steps"], 3 if arm == "parent_no_change" else 6)
        self.assertFalse(result["per_arm_training_work"]["larger_unsplit"]["parent_training_included"])
        self.assertFalse(result["topology_activation"])

    def test_extra_data_and_late_route_errors_precede_first_fit(self):
        broken = self.routed[:4].clone()
        broken[-1, -1] = 0.5
        with patch.object(c, "fit") as fit:
            for extra in ((broken, self.y[:4]), (self.routed[:4], None), (self.routed[:4], torch.ones(4).long()*3)):
                with self.assertRaises(e.InputError):
                    c.split_trial(self.routed, self.y, self.routed[:4], classes=2, extra=extra)
            with self.assertRaises(e.InputError):
                c.split_trial(self.routed, self.y, broken, classes=2)
            fit.assert_not_called()

    def evaluate(self, result):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "controls.json"
            seq = self.x.unsqueeze(1)
            value = {"split": result, "system2": c.recurrent_trial(seq, self.y, seq, self.y, seq[:4],
                       classes=2, steps=2), "holdout_case_ids": [str(i) for i in range(4)]}
            cases = [e.Case(str(i), str(i), "holdout", None, 0, "scope", str(i)) for i in range(4)]
            labels = {str(i): int(self.y[i]) for i in range(4)}
            return evaluate_controls(path, e.write_once(path, value), labels, cases, classes=2)

    def test_matched_control_is_scored_after_seal(self):
        result = self.evaluate(self.trial())
        self.assertEqual(set(result["split"]["scores"]), set(ARMS))
        self.assertFalse(result["independent_future_evidence"])

    def test_missing_matched_control_never_silently_reverts_to_legacy(self):
        result = self.trial()
        result["predictions"].pop("inherited_unsplit")
        with self.assertRaises(e.InputError):
            self.evaluate(result)

    def test_rehashed_work_budget_or_sampling_corruption_rejected(self):
        original = self.trial()
        for mode in ("work", "budget", "sampling"):
            r = deepcopy(original)
            if mode == "work":
                r["per_arm_training_work"]["larger_unsplit"]["optimizer_steps"] += 3
            elif mode == "budget":
                r["costs"]["inherited_unsplit"]["parameters"] = r["split_parameter_budget"] + 1
            else:
                r["costs"]["inherited_split"]["minibatch_sha256"] = "0" * 64
            with self.assertRaises(e.InputError):
                self.evaluate(r)

    def test_calibration_rule_keeps_no_change_on_exact_ties(self):
        predictions = {arm: [[1., 0.], [0., 1.]] for arm in ARMS}
        costs = {arm: {"parameters": 10} for arm in ARMS}
        r = recommend(predictions, [0, 1], costs, classes=2)
        self.assertEqual(r["recommended_arm"], "parent_no_change")
        self.assertFalse(r["holdout_labels_used"])
        self.assertFalse(r["independent_acceptance"])

    def test_calibration_requires_all_arms(self):
        with self.assertRaises(e.InputError):
            recommend({ARMS[0]: [[1., 0.]]}, [0], {}, classes=2)

    def test_pixel_partition_preserves_duplicates(self):
        pixels = torch.arange(24).reshape(3, 8)
        identities, split = cohort(torch.cat((pixels, pixels[:1])))
        self.assertEqual((identities[0], split[0]), (identities[-1], split[-1]))

    def test_existing_model_entrypoint_learns_router_from_train_only(self):
        class Encoder:
            identity, simulated, calls = "a" * 64, True, 0
            def __init__(self, *args):
                pass
            def encode(self, texts):
                Encoder.calls += 1
                return torch.tensor([[float(t[-1]), 1.] for t in texts])
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            splits = ("train", "train", "train", "train", "calibration", "calibration", "holdout", "holdout")
            rows = [{"case_id": str(i), "group": str(i), "split": s, "observed_at": None,
                     "cell": i%2, "scope": "test-only", "text": f"row-{i}", "label": i%2}
                    for i,s in enumerate(splits)]
            raw = b"".join(e.canonical(r) for r in rows)
            (root/"data.jsonl").write_bytes(raw)
            manifest = {"schema": "hepta.shared-stem-execution.v1", "classes": 2, "cells": 2,
                "steps": 2, "run_controls": True, "split_routing": "train_two_means",
                "dataset": {"path": "data.jsonl", "sha256": e.sha(raw)}, "model": {"path": "test-only"}}
            e.write_once(root/"manifest.json", manifest)
            with patch.object(e, "LocalEncoder", Encoder):
                report = e.run(root/"manifest.json", root/"result")
            saved = e.decode((root/"result/controls.json").read_bytes())
            self.assertEqual(Encoder.calls, 1)
            self.assertEqual(saved["split"]["routing"]["train_rows"], 4)
            self.assertIn("inherited_unsplit", report["control_scores"]["split"]["scores"])


if __name__ == "__main__":
    unittest.main()
