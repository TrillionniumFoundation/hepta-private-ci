"""Actual descendant optimization, sparse dispatch, withdrawal and disk rollback."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from cell_head_training import HeadTrainingConfigV1, _state_digest, train_cell_head
from cell_router_training import RouterCellV1, RouterTrainingConfigV1, train_cell_router
from cell_evolution_snapshot import (EvolutionBudgetV1, EvolutionError, OfflineEvolutionOwnerV1,
    WithdrawalViewV1, bootstrap_snapshot, group_digest, load_snapshot, retire_snapshot, rollback_snapshot)
from cell_evolution_training import (EvolutionTrainingConfigV1, continue_snapshot,
                                     merge_snapshot, split_snapshot)
from native_latent import LightCellHead
from test_cell_router_training import IDENTITY, cohort


class Withdrawals:
    def __init__(self):
        self.view = WithdrawalViewV1(IDENTITY.scope_id)

    def __call__(self):
        return self.view

    def revoke(self, source):
        self.view = replace(self.view, epoch=self.view.epoch + 1,
                            revoked_source_digests=tuple(sorted(set(self.view.revoked_source_digests) | {source})))


class CellEvolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        cls.storage = tempfile.TemporaryDirectory()
        cls.cells = []
        for index, name in enumerate(("a", "b")):
            splits = {split: cohort(f"parent-{name}-{split}", domain=index)
                      for split in ("train", "calibration", "evaluation")}
            head = train_cell_head(splits["train"], splits["calibration"],
                {"evaluation": splits["evaluation"]}, config=HeadTrainingConfigV1(
                    task_count=2, mode="linear", steps=60, learning_rate=0.3, seed=11))
            cls.cells.append(RouterCellV1(name, head, 1.0,
                {split: value.source_group_ids for split, value in splits.items()}))
        router_cohorts = {split: cohort(f"parent-router-{split}") for split in ("train", "calibration", "evaluation")}
        cls.router_config = RouterTrainingConfigV1(steps=60, learning_rate=0.2, seed=17)
        router = train_cell_router(router_cohorts["train"], router_cohorts["calibration"],
            {"evaluation": router_cohorts["evaluation"]}, cls.cells, cls.router_config)
        cls.budget = EvolutionBudgetV1()
        cls.parent = bootstrap_snapshot(cls.cells, router,
            {name: c.source_group_ids for name, c in router_cohorts.items()},
            Path(cls.storage.name) / "parent", cls.budget, Withdrawals())
        cls.config = EvolutionTrainingConfigV1(steps=40, learning_rate=0.2)

    @classmethod
    def tearDownClass(cls):
        cls.storage.cleanup()
        torch.set_num_threads(cls.previous_threads)

    def setUp(self):
        self.directory = Path(self.storage.name) / self._testMethodName
        self.directory.mkdir()
        self.withdrawals = Withdrawals()

    def split(self, name="split", **changes):
        args = dict(parent=self.parent, parent_cell_id="a",
            children={"child_a": cohort("child-a", domain=0), "child_b": cohort("child-b", domain=1)},
            calibration=cohort("descendant-cal"), holdouts={"future": cohort("descendant-future")},
            router_train=cohort("descendant-router-train"), router_calibration=cohort("descendant-router-cal"),
            directory=self.directory / name, budget=self.budget, withdrawal_provider=self.withdrawals,
            training_config=self.config, router_config=self.router_config)
        return split_snapshot(**{**args, **changes})

    def merge(self, name="merge", **changes):
        args = dict(parent=self.parent, new_cell_id="merged", train=cohort("merge-train"),
            calibration=cohort("merge-cal"), holdouts={"future": cohort("merge-future")},
            directory=self.directory / name, budget=self.budget, withdrawal_provider=self.withdrawals,
            training_config=self.config)
        return merge_snapshot(**{**args, **changes})

    def test_real_npz_warm_start_private_children_and_atomic_dispatch(self):
        bundle = cohort("prediction").bundle
        before = self.parent.predict_task(bundle, self.withdrawals)["task_probabilities"]
        with patch("cell_evolution_training.load_snapshot", wraps=load_snapshot) as reader:
            successor = self.split()
        self.assertEqual(reader.call_count, 1)
        parent_digest = self.parent.cells[0].head.report["trained_tensor_sha256"]
        self.assertEqual({c.head.report["initial_tensor_sha256"] for c in successor.cells}, {parent_digest})
        hashes = {c.head.report["trained_tensor_sha256"] for c in successor.cells}
        self.assertEqual(len(hashes), 2)
        self.assertNotIn(parent_digest, hashes)
        pointers = [{p.data_ptr() for p in c.head._head.parameters()} for c in successor.cells]
        self.assertFalse(pointers[0] & pointers[1])
        self.assertEqual(successor.report["resident_tensor_bytes"], self.parent.report["resident_tensor_bytes"])
        self.assertTrue(all(h["model_generation"] == 2 for h in successor.report["heads"]))
        owner = OfflineEvolutionOwnerV1(self.parent, self.withdrawals)
        owner.commit(successor, expected_parent_manifest_sha256=self.parent.manifest_sha256)
        output = owner.predict_task(bundle)
        self.assertEqual(output["head_example_calls"], 32)
        self.assertEqual(output["graph_generation"], 2)
        self.assertTrue(all(set(row["actual_calls"]) <= {"child_a", "child_b"} for row in output["routes"]))
        self.assertTrue(torch.equal(before, self.parent.predict_task(bundle, self.withdrawals)["task_probabilities"]))
        for cell in self.parent.cells:
            self.assertEqual(_state_digest(cell.head._head), cell.head.report["trained_tensor_sha256"])
        json.dumps(successor.report, allow_nan=False)

    def test_snapshot_adopts_reloaded_weights_without_unaccounted_training_gradients(self):
        self.assertTrue(any(p.grad is not None for cell in self.cells for p in cell.head._head.parameters()))
        for snapshot in (self.parent, self.split()):
            modules = [c.head._head for c in snapshot.cells] + [snapshot.router._net]
            self.assertTrue(all(p.grad is None for module in modules for p in module.parameters()))
            parameter = next(snapshot.router._net.parameters())
            try:
                parameter.grad = torch.ones_like(parameter)
                with self.assertRaisesRegex(EvolutionError, "optimizer gradients"):
                    snapshot.require_current(self.withdrawals)
            finally:
                parameter.grad = None

    def test_merge_executes_real_teacher_predictions_and_updates_student(self):
        teacher_hashes = {c.head.report["trained_tensor_sha256"] for c in self.parent.cells}
        seen = []
        original = LightCellHead.forward
        def observe(module, features, state):
            if not any(p.requires_grad for p in module.parameters()) and _state_digest(module) in teacher_hashes:
                seen.append((_state_digest(module), len(features)))
            return original(module, features, state)
        with patch.object(LightCellHead, "forward", new=observe):
            merged = self.merge()
        self.assertEqual(set(seen), {(sha, 32) for sha in teacher_hashes})
        self.assertEqual(len(seen), 2)
        self.assertEqual(merged.report["operation_receipt"]["teacher_head_example_calls"], 64)
        self.assertNotEqual(merged.cells[0].head.report["initial_tensor_sha256"],
                            merged.cells[0].head.report["trained_tensor_sha256"])
        self.assertLess(merged.report["resident_tensor_bytes"], self.parent.report["resident_tensor_bytes"])
        self.assertIsNone(merged.router)
        output = merged.predict_task(cohort("merge-predict").bundle, self.withdrawals)
        self.assertTrue(all(r["actual_calls"] == ["merged"] for r in output["routes"]))
        second = self.merge("different-distillation", training_config=replace(self.config, distillation_weight=0.9))
        self.assertNotEqual(second.cells[0].head.report["trained_tensor_sha256"],
                            merged.cells[0].head.report["trained_tensor_sha256"])

    def test_static_continuation_uses_own_parent_with_exact_same_update_budget(self):
        split = self.split()
        continued = continue_snapshot(self.parent,
            {"a": cohort("child-a", domain=0), "b": cohort("child-b", domain=1)},
            cohort("descendant-cal"), {"future": cohort("descendant-future")},
            cohort("descendant-router-train"), cohort("descendant-router-cal"),
            self.directory / "continued", self.budget, self.withdrawals,
            training_config=self.config, router_config=self.router_config)
        self.assertEqual([c.cell_id for c in continued.cells], ["a", "b"])
        for original, trained in zip(self.parent.cells, continued.cells, strict=True):
            self.assertEqual(trained.head.report["initial_tensor_sha256"],
                             original.head.report["trained_tensor_sha256"])
        self.assertEqual(continued.report["operation_receipt"]["actual_usage"],
                         split.report["operation_receipt"]["actual_usage"])
        self.assertEqual(continued.report["operation_receipt"]["reservation"],
                         split.report["operation_receipt"]["reservation"])
        self.assertFalse(continued.report["operation_receipt"]["structure_changed"])
        self.assertTrue(all(h["model_generation"] == 2 for h in continued.report["heads"]))
        self.assertNotIn("transition_tensor_bytes", continued.report["operation_receipt"]["actual_usage"])
        with self.assertRaisesRegex(EvolutionError, "unchanged"):
            continue_snapshot(self.parent, {"a": cohort("unmatched")}, None, {}, None, None,
                              self.directory / "bad", self.budget, self.withdrawals)

    def test_retirement_executes_zero_calls_to_retired_cell(self):
        with patch.object(self.parent.cells[1].head, "predict_task", side_effect=AssertionError("retired ran")):
            retired = retire_snapshot(self.parent, "b", self.directory / "retired", self.budget, self.withdrawals)
            output = retired.predict_task(cohort("retired-predict").bundle, self.withdrawals)
        self.assertEqual(output["head_module_invocations"], {"a": 1})
        self.assertEqual(output["router_forward_calls"], 0)
        self.assertTrue(set(self.parent.report["source_closure"]) <= set(retired.report["source_closure"]))
        with self.assertRaises(EvolutionError):
            retire_snapshot(retired, "a", self.directory / "empty", self.budget, self.withdrawals)

    def test_rollback_reloads_original_artifacts_under_fresh_generations(self):
        split = self.split()
        merged = self.merge(parent=split)
        restored = rollback_snapshot(merged, self.parent, self.directory / "rollback", self.budget, self.withdrawals)
        self.assertEqual(restored.generation, 4)
        self.assertTrue(all(h["model_generation"] > 1 for h in restored.report["heads"]))
        bundle = cohort("rollback-predict").bundle
        self.assertTrue(torch.equal(restored.predict_task(bundle, self.withdrawals)["task_probabilities"],
                                    self.parent.predict_task(bundle, self.withdrawals)["task_probabilities"]))
        self.assertEqual((restored.directory / "head-0" / "weights.npz").read_bytes(),
                         (self.parent.directory / "head-0" / "weights.npz").read_bytes())
        self.assertEqual((restored.directory / "router" / "weights.npz").read_bytes(),
                         (self.parent.directory / "router" / "weights.npz").read_bytes())
        owner = OfflineEvolutionOwnerV1(merged, self.withdrawals)
        owner.commit(restored, expected_parent_manifest_sha256=merged.manifest_sha256)
        self.assertEqual(owner.current.manifest_sha256, restored.manifest_sha256)

    def test_ancestral_teacher_and_router_withdrawals_invalidate_whole_snapshot(self):
        split, merged = self.split(), self.merge()
        retired = retire_snapshot(self.parent, "b", self.directory / "retired", self.budget, self.withdrawals)
        sources = [self.parent.cells[1].head.report["splits"]["train"]["source_record_digests"][0],
                   self.parent.router.report["splits"]["calibration"]["source_record_digests"][0],
                   group_digest(self.parent.cells[0].head_source_groups["calibration"][0])]
        for source in sources:
            provider = Withdrawals()
            provider.revoke(source)
            for snapshot in (split, merged, retired):
                with self.subTest(source=source, operation=snapshot.report["operation"]), self.assertRaisesRegex(
                        EvolutionError, "withdrawn"):
                    snapshot.predict_task(cohort("denied").bundle, provider)
            with self.assertRaisesRegex(EvolutionError, "withdrawn"):
                rollback_snapshot(split, self.parent, self.directory / "forbidden-rollback", self.budget, provider)

    def test_clean_parent_can_recover_from_withdrawn_child_only_sources(self):
        successor = self.split()
        self.withdrawals.revoke(successor.cells[0].head.report["splits"]["train"]["source_record_digests"][0])
        with self.assertRaisesRegex(EvolutionError, "withdrawn"):
            successor.require_current(self.withdrawals)
        restored = rollback_snapshot(successor, self.parent, self.directory / "clean", self.budget, self.withdrawals)
        self.assertEqual(restored.generation, 3)
        restored.predict_task(cohort("clean-predict").bundle, self.withdrawals)
        self.assertIn(successor.manifest_sha256, restored.report["ancestor_snapshot_digests"])

    def test_rollback_never_rolls_back_current_withdrawal_frontier(self):
        self.withdrawals.view = replace(self.withdrawals.view, epoch=2)
        successor = self.split()
        stale = Withdrawals()
        with self.assertRaisesRegex(EvolutionError, "frontier rollback"):
            rollback_snapshot(successor, self.parent, self.directory / "stale-frontier",
                              self.budget, stale)

    def test_budget_denial_precedes_any_head_forward_and_leaves_parent_selected(self):
        owner = OfflineEvolutionOwnerV1(self.parent, self.withdrawals)
        for field in ("resident_tensor_bytes", "transition_tensor_bytes", "gradient_bytes",
                      "head_example_calls", "parameter_example_updates", "router_example_steps"):
            with self.subTest(field=field), patch.object(LightCellHead, "forward", side_effect=AssertionError("ran")):
                with self.assertRaisesRegex(EvolutionError, "budget"):
                    self.split(field, budget=replace(self.budget, **{field: 0}))
            self.assertFalse((self.directory / field).exists())
        with self.assertRaisesRegex(EvolutionError, "budget"):
            retire_snapshot(self.parent, "b", self.directory / "retire-budget",
                            replace(self.budget, transition_tensor_bytes=0), self.withdrawals)
        self.assertEqual(owner.current.manifest_sha256, self.parent.manifest_sha256)

    def test_leakage_and_stale_candidate_fail_closed(self):
        with self.assertRaisesRegex(EvolutionError, "leakage"):
            self.split(calibration=cohort("child-a", domain=0))
        with self.assertRaisesRegex(EvolutionError, "leakage"):
            self.split(router_train=cohort("parent-router-train"))
        successor = self.split()
        competing = retire_snapshot(self.parent, "b", self.directory / "competing", self.budget, self.withdrawals)
        owner = OfflineEvolutionOwnerV1(self.parent, self.withdrawals)
        owner.commit(successor, expected_parent_manifest_sha256=self.parent.manifest_sha256)
        with self.assertRaisesRegex(EvolutionError, "compare-and-swap"):
            owner.commit(competing, expected_parent_manifest_sha256=self.parent.manifest_sha256)

    def test_holdout_labels_do_not_change_descendant_or_router_weights(self):
        first = self.split()
        held = cohort("descendant-future")
        second = self.split("flipped", holdouts={"future": replace(held, labels=1 - held.labels)})
        for left, right in zip(first.cells, second.cells, strict=True):
            self.assertEqual(left.head.report["trained_tensor_sha256"], right.head.report["trained_tensor_sha256"])
            self.assertEqual(left.head.report["temperature"], right.head.report["temperature"])
        self.assertEqual(first.router.report["trained_tensor_sha256"], second.router.report["trained_tensor_sha256"])
        self.assertEqual(first.router.report["temperature"], second.router.report["temperature"])

    def test_npz_corruption_and_snapshot_tamper_reject_real_reload(self):
        snapshot = self.split()
        args = dict(expected_manifest_sha256=snapshot.manifest_sha256, budget=self.budget,
                    withdrawal_provider=self.withdrawals)
        replay = load_snapshot(snapshot.directory, **args)
        bundle = cohort("replayed").bundle
        self.assertTrue(torch.equal(snapshot.predict_task(bundle, self.withdrawals)["task_probabilities"],
                                    replay.predict_task(bundle, self.withdrawals)["task_probabilities"]))
        for path in (snapshot.directory / "head-0" / "weights.npz", snapshot.directory / "snapshot.json"):
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"!")
                with self.assertRaises(ValueError):
                    load_snapshot(snapshot.directory, **args)
            finally:
                path.write_bytes(original)

    def test_revocation_during_actual_prediction_discards_entire_output(self):
        source = self.parent.report["source_closure"][0]
        original = self.parent.cells[0].head.predict_task
        seen = []
        def invoke(bundle):
            seen.append(len(bundle.source_record_digests))
            result = original(bundle)
            self.withdrawals.revoke(source)
            return result
        with patch.object(self.parent.cells[0].head, "predict_task", side_effect=invoke):
            with self.assertRaisesRegex(EvolutionError, "withdrawn"):
                self.parent.predict_task(cohort("mid-revocation").bundle, self.withdrawals)
        self.assertTrue(seen)

    def test_global_optimizer_hook_cannot_mutate_parent(self):
        from torch.optim.optimizer import register_optimizer_step_pre_hook
        called = []
        hook = register_optimizer_step_pre_hook(lambda *args: called.append(True))
        try:
            with self.assertRaisesRegex(ValueError, "global.*hooks"):
                self.merge()
        finally:
            hook.remove()
        self.assertEqual(called, [])
        self.parent.require_current(self.withdrawals)


if __name__ == "__main__":
    unittest.main()
