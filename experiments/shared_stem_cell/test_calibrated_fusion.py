"""Actual connector arithmetic and cohort exclusion, not pretrained effectiveness."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import calibrated_fusion as f, controls, execution as e, media_execution as m
from experiments.shared_stem_cell import public_media as p
from experiments.shared_stem_cell.test_public_media import Tokenizer, public_rows
from experiments.shared_stem_cell.test_media_execution import FixtureTowers


def features(n=8):
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(81)
        return {k: (torch.randn(n, 2, 4), torch.ones(n, 2, dtype=torch.bool),
                    torch.arange(2, dtype=torch.long).expand(n, -1).clone()) for k in ("image", "text")}


class CalibratedFusionTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.train, self.cal = features(), features(6)
        self.labels, self.cal_labels = torch.arange(8) % 2, torch.arange(6) % 2

    def fit(self, **kw):
        return f.fit_calibrated(self.train, self.labels, self.cal, self.cal_labels,
                                classes=2, steps=3, seed=17, **kw)

    def test_actual_final_models_equal_unchanged_legacy_training(self):
        models, plan = self.fit()
        new = f.execute_calibrated(models, plan, self.cal, ["test"] * 6)
        old = controls.modality_trial(self.train, self.labels, self.cal, classes=2, steps=3, seed=17)
        for name in old["predictions"]:
            self.assertEqual(new["predictions"][name], old["predictions"][name])
            self.assertEqual(new["frozen_predictions"][name], old["frozen_predictions"][name])

    def test_each_legacy_arm_trains_once_without_extra_search_updates(self):
        original, calls = torch.optim.AdamW.step, []
        def count(optimizer, *args, **kwargs):
            calls.append(1)
            return original(optimizer, *args, **kwargs)
        with patch.object(torch.optim.AdamW, "step", count):
            _, plan = self.fit()
        self.assertEqual(len(calls), 9)
        self.assertEqual(plan["costs"]["actual_optimizer_steps"], 9)
        self.assertEqual([c["calibration_forward_calls"] for c in plan["costs"]["arms"].values()], [4, 4, 4])

    def test_selected_checkpoint_satisfies_calibration_rule_including_no_change(self):
        _, plan = self.fit()
        for trace in plan["traces"].values():
            winner = min(trace["checkpoints"], key=lambda r: (-r["correct"], r["nll"], r["step"]))
            self.assertEqual(winner["step"], trace["selected_step"])
            self.assertIn(0, [r["step"] for r in trace["checkpoints"]])

    def test_mixture_includes_pure_endpoints_and_same_joint_control(self):
        _, plan = self.fit()
        candidates = plan["mixtures"]
        self.assertEqual(len(candidates), 6)
        self.assertTrue(all(any(c["components"] == [(name, 1.0)] for c in candidates)
                            for name in ("image", "text", "image+text")))
        winner = candidates[plan["selected_mixture"]]
        self.assertEqual(winner["correct"], max(c["correct"] for c in candidates))

    def test_same_source_identity_is_executed_only_once(self):
        models, plan = self.fit()
        result = f.execute_calibrated(models, plan, self.cal, ["test"] * 6)
        ids = {v for roles in plan["model_identities"].values() for v in roles.values()}
        self.assertEqual(set(result["costs"]["unique_model_forwards"]), ids)
        self.assertEqual(len(result["predictions"]), 7)
        self.assertEqual(result["predictions"].keys(), result["frozen_predictions"].keys())

    def test_validation_selection_has_no_dependency_on_test_inputs(self):
        models, plan = self.fit()
        before = e.canonical(plan)
        f.execute_calibrated(models, plan, self.cal, ["test"] * 6)
        changed = deepcopy(self.cal)
        changed["image"][0].add_(10)
        f.execute_calibrated(models, plan, changed, ["test"] * 6)
        self.assertEqual(before, e.canonical(plan))

    def test_model_identity_change_refuses_before_prediction(self):
        models, plan = self.fit()
        with torch.no_grad():
            next(models["image"]["selected"].parameters()).add_(1)
        with patch.object(controls.FusionHead, "forward", side_effect=AssertionError("late guard")):
            with self.assertRaises(e.InputError):
                f.execute_calibrated(models, plan, self.cal, ["test"] * 6)

    def test_invalid_frozen_mixture_and_partitions_refuse_before_arithmetic(self):
        models, plan = self.fit()
        for change in ("index", "negative", "sum", "partitions"):
            broken, partitions = deepcopy(plan), ["test"] * 6
            if change == "index": broken["selected_mixture"] = True
            if change == "negative": broken["mixtures"][broken["selected_mixture"]]["components"] = [("image", -1.0)]
            if change == "sum": broken["mixtures"][broken["selected_mixture"]]["components"] = [("image", 0.2)]
            if change == "partitions": partitions.pop()
            with patch.object(controls.FusionHead, "forward", side_effect=AssertionError("late guard")):
                with self.assertRaises(e.InputError):
                    f.execute_calibrated(models, broken, self.cal, partitions)

    def test_late_invalid_calibration_rejects_before_optimizer_or_candidate(self):
        for defect in ("nan", "width", "label", "time"):
            cal, target = deepcopy(self.cal), self.cal_labels.clone()
            if defect == "nan": cal["text"][0][0, 0, 0] = float("nan")
            if defect == "width": cal["text"] = (torch.ones(6, 2, 3), *cal["text"][1:])
            if defect == "label": target[-1] = 2
            if defect == "time": cal["text"][2][0] = torch.tensor([1, 0])
            with patch.object(torch.optim, "AdamW", side_effect=AssertionError("allocated")):
                with self.assertRaises(e.InputError):
                    f.fit_calibrated(self.train, self.labels, cal, target, classes=2)

    def test_training_preserves_features_gradients_and_global_rng(self):
        for item in self.train.values(): item[0].requires_grad_(True)
        before = {k: [e.tensor_digest(t) for t in item] for k, item in self.train.items()}
        rng = torch.get_rng_state().clone()
        models, _ = self.fit()
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertEqual(before, {k: [e.tensor_digest(t) for t in item] for k, item in self.train.items()})
        self.assertTrue(all(item[0].grad is None for item in self.train.values()))
        self.assertTrue(all(not q.requires_grad for roles in models.values() for mod in roles.values() for q in mod.parameters()))

    def test_single_modality_has_no_duplicate_training_or_fabricated_partner(self):
        with patch.object(torch.optim.AdamW, "step", autospec=True) as step:
            models, plan = f.fit_calibrated({"image": self.train["image"]}, self.labels,
                {"image": self.cal["image"]}, self.cal_labels, classes=2, steps=2)
        self.assertEqual(step.call_count, 2)
        self.assertEqual(set(models), {"image"})
        self.assertEqual(plan["mixtures"][0]["components"], [("image", 1.0)])


class FreshCohortTests(unittest.TestCase):
    def test_excludes_previous_pixel_and_text_inputs_across_every_fold(self):
        public = public_rows()
        old = p.choose(public, Tokenizer(), sizes={k: 1 for k in p.SIZES})
        excluded = tuple(row for group in old.values() for row in group)
        fresh = p.choose(public, Tokenizer(), sizes={k: 2 for k in p.SIZES}, excluded=excluded)
        self.assertFalse({r["pixel_sha256"] for r in excluded} & {r["pixel_sha256"] for g in fresh.values() for r in g})
        self.assertFalse({r["text"] for r in excluded} & {r["text"] for g in fresh.values() for r in g})

    def test_cannot_reduce_requested_sample_count_when_exclusions_exhaust_fold(self):
        public = public_rows()
        old = p.choose(public, Tokenizer(), sizes={k: 4 for k in p.SIZES})
        with self.assertRaisesRegex(e.InputError, "insufficient"):
            p.choose(public, Tokenizer(), sizes={k: 1 for k in p.SIZES},
                     excluded=tuple(row for group in old.values() for row in group))

    def test_fresh_cohort_is_sealed_before_first_label_and_not_reselected(self):
        public = public_rows()
        old = p.choose(public, Tokenizer(), sizes={k: 1 for k in p.SIZES})
        with tempfile.TemporaryDirectory() as td:
            root, calls = Path(td), []
            def answer(split, index):
                self.assertTrue((root / "cohort-before-labels.json").exists())
                calls.append((split, index))
                return 0
            desc, _ = p.stage_cases(root, public, answer, Tokenizer(), sizes={k: 2 for k in p.SIZES},
                                   excluded=tuple(row for group in old.values() for row in group))
            self.assertEqual(len(calls), 6)
            # Actual file/tower/connector entrypoint; only tower features are synthetic.
            e.write_once(root / "manifest.json", {"schema": "hepta.shared-stem-media.v1",
                "classes": 4, "steps": 2, "models": {}, "dataset": desc,
                "fusion_profile": "calibrated_checkpoints_v1"})
            original = f.execute_calibrated
            def guarded(models, plan, inputs, partitions):
                self.assertTrue((root / "result/calibration-selection.json").exists())
                self.assertEqual(len(plan["binding"]["calibration_ids"]), 2)
                return original(models, plan, inputs, partitions)
            with patch.object(f, "execute_calibrated", guarded):
                report = m.run(root / "manifest.json", root / "result", _tower_factory=FixtureTowers)
            self.assertEqual(len(report["scores"]), 7)
            self.assertEqual(report["calibration_selection_sha256"], e.sha((root / "result/calibration-selection.json").read_bytes()))
            self.assertEqual(report["tower_forward_calls"], {"fixture": 12})


if __name__ == "__main__":
    unittest.main()
