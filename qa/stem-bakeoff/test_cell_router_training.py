"""Real tiny supervised Heads/Router: sparse execution, isolation and replay."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from cell_head_training import HeadCohortV1, HeadTrainingConfigV1, train_cell_head
from cell_router_artifact import load_router_artifact, save_router_artifact
from cell_router_training import (RouterCellV1, RouterTrainingConfigV1,
                                  RouterTrainingError, _new_router, train_cell_router)
from feature_bundle import FeatureBundleV1, FeatureIdentityV1


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


IDENTITY = FeatureIdentityV1(digest("router-test-frozen-encoder"), "1" * 40, digest("preprocess"))


def cohort(name, domain=None, identity=IDENTITY):
    bit = torch.arange(32) % 2
    domains = (torch.arange(32) // 2) % 2 if domain is None else torch.full((32,), domain)
    features = torch.zeros(32, 4)
    features[:, 0], features[:, 1] = bit * 2 - 1, domains * 2 - 1
    missing = torch.ones(32, 5, dtype=torch.bool)
    missing[:, 0] = False
    bundle = FeatureBundleV1.from_tensors(global_features=features,
        source_record_digests=tuple(digest(f"{name}:{i}") for i in range(32)),
        identity=identity, missing_mask=missing)
    return HeadCohortV1(bundle, bit ^ domains, tuple(f"{name}-group-{i}" for i in range(32)))


class CellRouterTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        cls.cells, cls.head_cohorts = [], []
        for index, name in enumerate(("a", "b")):
            splits = {split: cohort(f"{name}-{split}", domain=index)
                      for split in ("train", "calibration", "evaluation")}
            head = train_cell_head(splits["train"], splits["calibration"],
                {"evaluation": splits["evaluation"]}, config=HeadTrainingConfigV1(
                    task_count=2, mode="linear", steps=80, learning_rate=0.3, seed=11))
            cls.cells.append(RouterCellV1(name, head, 1.0,
                {split: value.source_group_ids for split, value in splits.items()}))
            cls.head_cohorts.append(splits)
        cls.train, cls.cal = cohort("router-train"), cohort("router-calibration")
        cls.holdouts = {"future": cohort("future")}
        cls.config = RouterTrainingConfigV1(steps=200, learning_rate=0.2, seed=17)
        cls.router = train_cell_router(cls.train, cls.cal, cls.holdouts, cls.cells, cls.config)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def train_router(self, **changes):
        args = dict(train=self.train, calibration=self.cal, holdouts=self.holdouts,
                    cells=self.cells, config=self.config)
        return train_cell_router(**{**args, **changes})

    def test_real_learning_and_frozen_owners(self):
        report = self.router.report
        self.assertNotEqual(report["initial_tensor_sha256"], report["trained_tensor_sha256"])
        self.assertLess(report["last_train_loss_before_step"], report["initial_train_loss"])
        self.assertEqual(report["encoder_training_steps"], 0)
        self.assertEqual(report["cell_training_steps"], 0)
        self.assertEqual(report["splits"]["future"]["learned"]["metrics"]["accuracy"], 1.0)
        self.assertEqual(report["splits"]["future"]["fixed"]["metrics"]["accuracy"], 0.5)
        self.assertEqual(report["training_head_example_calls"], 64)
        self.assertFalse(report["production_activation_allowed"])
        json.dumps(report, allow_nan=False)
        for cell in self.cells:
            self.assertFalse(any(p.requires_grad for p in cell.head._head.parameters()))
        self.train.bundle.verify_integrity()

    def test_actual_inference_calls_match_each_selected_row(self):
        seen = {c.cell_id: [] for c in self.cells}
        originals = [c.head.predict_task for c in self.cells]
        def spy(index):
            def invoke(bundle):
                seen[self.cells[index].cell_id].extend(bundle.source_record_digests)
                return originals[index](bundle)
            return invoke
        with patch.object(self.cells[0].head, "predict_task", side_effect=spy(0)), patch.object(
                self.cells[1].head, "predict_task", side_effect=spy(1)):
            output = self.router.predict_task(self.holdouts["future"].bundle, self.cells)
        self.assertEqual(output["head_example_calls"], 32)
        self.assertEqual(output["actual_cost_units"], 32)
        for row in output["routes"]:
            self.assertEqual(len(row["candidates"]), 2)
            self.assertEqual(row["selected"], row["actual_calls"])
            self.assertLessEqual(row["actual_cost_units"], row["budget_units"])
            for cell in self.cells:
                self.assertEqual(row["source_record_digest"] in seen[cell.cell_id],
                                 cell.cell_id in row["selected"])
        json.dumps(output["routes"], allow_nan=False)

    def test_fixed_and_allowlisted_routes_skip_unselected_heads(self):
        with patch.object(self.cells[1].head, "predict_task", side_effect=AssertionError("unselected")):
            for kwargs in ({"fixed_cell_ids": ("a",)}, {"allowed_cell_ids": ("a",)}):
                output = self.router.predict_task(self.cal.bundle, self.cells, **kwargs)
                self.assertEqual(output["head_module_invocations"], {"a": 1})
                self.assertTrue(all(row["actual_calls"] == ["a"] for row in output["routes"]))

    def test_fixed_control_never_executes_learned_router(self):
        with patch.object(self.router._net, "forward", side_effect=AssertionError("Router executed")):
            output = self.router.predict_task(self.cal.bundle, self.cells, fixed_cell_ids=("a",))
        self.assertEqual(output["router_forward_calls"], 0)
        self.assertTrue(all(c["predicted_loss_cost"] is None
                            for row in output["routes"] for c in row["candidates"]))

    def test_calibration_and_evaluation_costs_are_fully_accounted(self):
        report = self.router.report
        accounting = report["execution_accounting"]
        self.assertEqual(accounting["target_collection"]["head_example_calls"], 64)
        self.assertEqual(accounting["temperature_calibration"]["head_example_calls"], 128)
        self.assertEqual(accounting["reported_evaluation"]["head_example_calls"], 192)
        self.assertEqual(accounting["total"]["head_example_calls"], 384)
        self.assertEqual(accounting["total"]["actual_cost_units"], 384)
        self.assertEqual(accounting["total"]["router_forward_calls"], self.config.steps + 4)
        for receipt in report["calibration_routes"]:
            self.assertEqual(receipt["head_example_calls"], sum(len(r["actual_calls"]) for r in receipt["routes"]))
            self.assertEqual(receipt["router_forward_calls"], int(receipt["fixed_cell_ids"] is None))

    def test_exact_nonnegative_config_and_router_factory_dtype_isolation(self):
        for key in ("cost_weight", "confidence_threshold"):
            with self.assertRaises(RouterTrainingError):
                replace(self.config, **{key: -1e-101}).validate()
        previous_dtype = torch.get_default_dtype()
        expected = _new_router(4, 2, self.config)
        try:
            torch.set_default_dtype(torch.float64)
            replay = _new_router(4, 2, self.config)
            self.assertEqual(replay(self.train.bundle.read_global()).dtype, torch.float32)
        finally:
            torch.set_default_dtype(previous_dtype)
        self.assertTrue(all(v.dtype == torch.float32 for v in replay.state_dict().values()))
        self.assertTrue(all(torch.equal(v, replay.state_dict()[k]) for k, v in expected.state_dict().items()))

    def test_holdout_labels_never_change_weights_or_calibration(self):
        changed = {name: replace(value, labels=1 - value.labels) for name, value in self.holdouts.items()}
        replay = self.train_router(holdouts=changed)
        for key in ("trained_tensor_sha256", "temperature", "fixed_cell_ids", "single_cell_temperatures"):
            self.assertEqual(self.router.report[key], replay.report[key])
        self.assertEqual(replay.report["splits"]["future"]["learned"]["metrics"]["accuracy"], 0.0)

    def test_calibration_cannot_change_weights_or_fixed_choice(self):
        replay = self.train_router(calibration=replace(self.cal, labels=1 - self.cal.labels))
        for key in ("trained_tensor_sha256", "fixed_cell_ids"):
            self.assertEqual(self.router.report[key], replay.report[key])
        self.assertNotEqual(self.router.report["temperature"], replay.report["temperature"])

    def test_leakage_and_witness_fail_before_forward(self):
        cases = [{"calibration": self.train},
                 {"calibration": replace(self.cal, source_group_ids=self.train.source_group_ids)},
                 {"train": self.head_cohorts[0]["train"]},
                 {"train": self.head_cohorts[0]["evaluation"]}]
        with patch.object(self.cells[0].head, "predict_task", side_effect=AssertionError("forward")):
            for changes in cases:
                with self.subTest(changes=tuple(changes)), self.assertRaisesRegex(RouterTrainingError, "leakage"):
                    self.train_router(**changes)
            bad = replace(self.cells[0], head_source_groups={})
            with self.assertRaisesRegex(RouterTrainingError, "witness"):
                self.train_router(cells=[bad, self.cells[1]])

    def test_identity_head_cost_and_parameter_binding(self):
        for changes in ({"generation": 2}, {"scope_id": "other"}, {"revocation_epoch": 1},
                        {"preprocess_sha256": "2" * 64}, {"encoder_sha256": "3" * 64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.router.predict_task(cohort("identity", identity=replace(IDENTITY, **changes)).bundle, self.cells)
        with self.assertRaisesRegex(RouterTrainingError, "binding"):
            self.router.predict_task(self.cal.bundle, [replace(self.cells[0], cost_units=0.5), self.cells[1]])
        with patch.dict(self.cells[0].head._report, temperature=8.0):
            with self.assertRaisesRegex(RouterTrainingError, "binding"):
                self.router.predict_task(self.cal.bundle, self.cells)
        parameter = next(self.cells[0].head._head.parameters())
        saved = parameter.detach().clone()
        try:
            with torch.no_grad():
                parameter.add_(1)
            with self.assertRaisesRegex(RouterTrainingError, "changed"):
                self.router.predict_task(self.cal.bundle, self.cells)
        finally:
            with torch.no_grad():
                parameter.copy_(saved)

    def test_budget_and_no_legal_candidate_fail_before_forward(self):
        cases = [{"allowed_cell_ids": ()}, {"budget_units": 0.5}, {"budget_units": 2},
                 {"budget_units": float("nan")}, {"fixed_cell_ids": ("a", "b")},
                 {"fixed_cell_ids": ("unknown",)}, {"allowed_cell_ids": ("a", "a")}]
        with patch.object(self.cells[0].head, "predict_task", side_effect=AssertionError("forward")):
            for kwargs in cases:
                with self.subTest(kwargs=kwargs), self.assertRaises(RouterTrainingError):
                    self.router.predict_task(self.cal.bundle, self.cells, **kwargs)

    def test_artifact_exact_replay_tamper_and_identity_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "router"
            artifact = save_router_artifact(self.router, target)
            args = dict(expected_manifest_sha256=artifact["manifest_sha256"],
                        expected_identity=IDENTITY, cells=self.cells)
            replay = load_router_artifact(target, **args)
            before = self.router.predict_task(self.cal.bundle, self.cells)
            after = replay.predict_task(self.cal.bundle, self.cells)
            self.assertTrue(torch.equal(before["task_probabilities"], after["task_probabilities"]))
            self.assertEqual(before["routes"], after["routes"])
            with self.assertRaises(RouterTrainingError):
                load_router_artifact(target, **{**args, "expected_identity": replace(IDENTITY, revocation_epoch=1)})
            for name in ("manifest.json", "weights.npz"):
                path = target / name
                original = path.read_bytes()
                path.write_bytes(original + b"!")
                with self.assertRaises(RouterTrainingError):
                    load_router_artifact(target, **args)
                path.write_bytes(original)

    def test_optimizer_global_hook_cannot_mutate_cell(self):
        from torch.optim.optimizer import register_optimizer_step_pre_hook
        called = []
        hook = register_optimizer_step_pre_hook(lambda *args: called.append(True))
        try:
            with self.assertRaisesRegex(ValueError, "global.*hooks"):
                self.train_router()
        finally:
            hook.remove()
        self.assertEqual(called, [])

    def test_top_k_and_cost_signal_are_real(self):
        two = self.train_router(config=replace(self.config, top_k=2, budget_units=2, cost_weight=0.5))
        output = two.predict_task(self.cal.bundle, self.cells)
        self.assertEqual(output["head_example_calls"], 64)
        self.assertEqual(output["actual_cost_units"], 64)
        for signal in two.report["training_signals"]:
            for cell in signal["cells"]:
                self.assertAlmostEqual(cell["target"], cell["observed_nll"] + 0.5, places=5)
        lower = two.predict_task(self.cal.bundle, self.cells, budget_units=1)
        self.assertEqual(lower["head_example_calls"], 32)


if __name__ == "__main__":
    unittest.main()
