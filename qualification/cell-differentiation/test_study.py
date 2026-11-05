"""Behavioral controls for leakage, missing populations, fabricated evidence and failures."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import run_study as runner
import study_model
from study_cost import total_cost
from study_data import ARMS, Batch, FrozenRun, Plan, canonical_bytes, digest, make_data, validate_isolation
from study_evidence import audit_observation
from study_gate import adjudicate, audit_study
from study_model import LinearModel, Model, evaluate, fit, snapshot_and_check, summarize


class StudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = Plan(seeds=(7, 17), pretrain_per_task=96, train_per_task=64,
                        validation_per_task=16, test_per_task=16, monitor_per_task_per_window=16)
        cls.report = runner.run_study(cls.plan)

    def fresh_run(self, scenario="helpful_specialization"):
        return copy.deepcopy(next(r for r in self.report["runs"] if r["scenario"] == scenario))

    def decision(self, run):
        return adjudicate(run, self.plan, self.report["source_digest"])

    def assert_invalid(self, run, text):
        decision = self.decision(run)
        self.assertEqual(decision["decision"], "HOLD")
        self.assertTrue(any("invalid_evidence:" in r and text in r for r in decision["reasons"]),
                        decision["reasons"])

    def test_real_serialization_roundtrip_is_auditable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study.json"
            path.write_bytes(canonical_bytes(self.report))
            restored = json.loads(path.read_text())
            audit_study(restored, self.plan)
            self.assertEqual(restored["summary"], self.report["summary"])

    def test_holdout_training_is_rejected_even_after_relabeling(self):
        data = make_data(self.plan, 7, "helpful_specialization")
        frozen = FrozenRun.freeze(self.plan, data, self.report["source_digest"])
        for leaked in (data["test"], replace(data["test"], split="train")):
            with self.subTest(split=leaked.split), self.assertRaises(ValueError):
                fit(leaked, np.ones(len(leaked.ids), dtype=bool), LinearModel("shared", np.zeros(6)),
                    frozen, self.plan, [], "leak_attempt")

    def test_fresh_ids_do_not_hide_copied_training_rows(self):
        train = make_data(self.plan, 7, "helpful_specialization")["train"]
        copied = Batch("test", tuple(f"fresh/{i}" for i in range(len(train.ids))),
                       train.x.copy(), train.y.copy(), train.task.copy(), train.window.copy())
        with self.assertRaisesRegex(ValueError, "contents leaked"):
            validate_isolation({"train": train, "test": copied})

    def test_policy_change_after_freeze_is_rejected(self):
        data = make_data(self.plan, 7, "helpful_specialization")
        frozen = FrozenRun.freeze(self.plan, data, self.report["source_digest"])
        changed = replace(self.plan, policy=replace(self.plan.policy, minimum_mse_gain=0.002))
        with self.assertRaisesRegex(ValueError, "changed after preregistration"):
            fit(data["train"], data["train"].task == 1, LinearModel("shared", np.zeros(6)),
                frozen, changed, [], "changed_policy")

    def test_zero_gain_and_zero_resource_limits_are_not_valid_policies(self):
        for field in ("minimum_mse_gain", "maximum_float_ops_ratio_to_continued", "maximum_parameter_bytes"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(self.plan, policy=replace(self.plan.policy, **{field: 0})).validate()

    def test_missing_fixed_expert_control_is_rejected(self):
        run = self.fresh_run()
        del run["arms"]["fixed_experts"]
        self.assert_invalid(run, "comparison arm")

    def test_dropping_a_trial_cannot_improve_the_aggregate(self):
        report = copy.deepcopy(self.report)
        report["runs"].pop()
        with self.assertRaisesRegex(ValueError, "trial denominator"):
            audit_study(report, self.plan)

    def test_perfect_reported_predictions_must_come_from_the_committed_model(self):
        run = self.fresh_run()
        observation = run["arms"]["demand_specialization"]["test"]
        for row in observation["records"]:
            row["prediction"] = row["target"]
            row["squared_error"] = 0.0
        self.resummarize(observation)
        self.assert_invalid(run, "not produced by the committed model")

    def test_fabricating_positive_demand_booleans_is_rejected(self):
        for field in ("persistent_demand", "negative_transfer_observed", "propose_child"):
            run = self.fresh_run("redundant_specialization")
            run["demand_evidence"][field] = True
            with self.subTest(field=field):
                self.assert_invalid(run, "demand diagnosis")

    def test_monitoring_windows_keep_their_original_requests(self):
        run = self.fresh_run()
        observation = run["demand_evidence"]["before"]
        observation["records"].pop()
        self.resummarize(observation)
        self.assert_invalid(run, "request denominator")

    def test_migration_flag_cannot_hide_changed_post_migration_outputs(self):
        run = self.fresh_run()
        arm = run["arms"]["demand_specialization"]
        migration = arm["migration"]
        payload = copy.deepcopy(arm["model"])
        payload["experts"][0]["weights"][0] += 4.0
        model = Model.restore(payload)
        data = make_data(self.plan, run["seed"], run["scenario"])
        migration["roundtrip_model"] = payload
        migration["roundtrip_digest"] = model.identity()
        migration["after"] = evaluate(data["validation"], model, [], "counterexample")
        migration["exact_validation_behavior"] = True
        self.assert_invalid(run, "migration conclusion")
        migration["exact_validation_behavior"] = False
        self.assertIn("migration_behavior_mismatch:demand_specialization", self.decision(run)["reasons"])

    def test_migration_cannot_drop_a_validation_request(self):
        run = self.fresh_run()
        migration = run["arms"]["demand_specialization"]["migration"]
        migration["after"]["records"].pop()
        self.resummarize(migration["after"])
        self.assert_invalid(run, "request denominator")

    def test_removing_one_training_stage_is_detected_even_with_other_training_costs(self):
        run = self.fresh_run()
        arm = run["arms"]["demand_specialization"]
        arm["ledger"] = [e for e in arm["ledger"] if e["stage"] != "negative_transfer_one_step_probe"]
        arm["cost"] = total_cost(run["shared_ledger"] + arm["ledger"])
        self.assert_invalid(run, "planned cost stage")

    def test_removing_validation_cost_is_detected_even_with_other_evaluation_costs(self):
        run = self.fresh_run()
        arm = run["arms"]["demand_specialization"]
        arm["ledger"] = [e for e in arm["ledger"] if (e["phase"], e["stage"]) != ("eval", "validation")]
        arm["cost"] = total_cost(run["shared_ledger"] + arm["ledger"])
        self.assert_invalid(run, "planned cost stage")

    def test_reducing_reported_training_work_and_recomputing_totals_is_rejected(self):
        run = self.fresh_run()
        arm = run["arms"]["continued_parent"]
        event = next(e for e in arm["ledger"] if e["phase"] == "train")
        event["estimated_float_ops"] //= 2
        arm["cost"] = total_cost(run["shared_ledger"] + arm["ledger"])
        self.assert_invalid(run, "frozen steps/dimensions")

    def test_failed_prediction_keeps_the_request_in_the_denominator(self):
        data = make_data(self.plan, 7, "helpful_specialization")
        model = Model.restore(self.fresh_run()["arms"]["continued_parent"]["model"])
        original = study_model.predict_routed

        def nonfinite(batch, committed, assignments):
            predictions, ops = original(batch, committed, assignments)
            predictions[0] = np.nan
            return predictions, ops

        with patch.object(study_model, "predict_routed", side_effect=nonfinite):
            observation = evaluate(data["test"], model, [], "failed_prediction")
        self.assertEqual(observation["summary"]["requested"], len(data["test"].ids))
        self.assertEqual(observation["summary"]["failed"], 1)
        self.assertIsNone(observation["summary"]["mse"])
        audit_observation(observation, data["test"].manifest())
        observation["records"] = observation["records"][1:]
        self.resummarize(observation)
        with self.assertRaisesRegex(ValueError, "request denominator"):
            audit_observation(observation, data["test"].manifest())

    def test_one_learner_failure_preserves_other_arms_and_unknown_costs(self):
        original = runner.fit

        def fail_expanded(*args, **kwargs):
            if args[-1] == "expanded_monolith_fit":
                raise RuntimeError("injected learner failure")
            return original(*args, **kwargs)

        plan = replace(self.plan, seeds=(7,))
        with patch.object(runner, "fit", side_effect=fail_expanded):
            report = runner.run_study(plan)
        audit_study(report, plan)
        for run in report["runs"]:
            arm = run["arms"]["expanded_monolith"]
            self.assertIn("injected learner failure", arm["failure"])
            self.assertEqual(arm["test"]["summary"]["incomplete"], 2 * plan.test_per_task)
            self.assertEqual(arm["validation"]["summary"]["incomplete"], 2 * plan.validation_per_task)
            self.assertIsNone(arm["cost"]["estimated_float_ops"])
            self.assertFalse(arm["cost"]["complete"])
            self.assertEqual(run["arms"]["fixed_experts"]["test"]["summary"]["completed"], 2 * plan.test_per_task)
            self.assertEqual(run["decision"]["decision"], "HOLD")

    def test_incumbent_training_failure_preserves_every_trial_and_arm(self):
        original = runner.fit

        def fail_pretrain(*args, **kwargs):
            if args[-1] == "incumbent_pretrain":
                raise RuntimeError("injected incumbent failure")
            return original(*args, **kwargs)

        plan = replace(self.plan, seeds=(7,))
        with patch.object(runner, "fit", side_effect=fail_pretrain):
            report = runner.run_study(plan)
        audit_study(report, plan)
        self.assertEqual(len(report["runs"]), len(plan.scenarios))
        for run in report["runs"]:
            self.assertEqual(set(run["arms"]), set(ARMS))
            for arm in run["arms"].values():
                self.assertEqual(arm["test"]["summary"]["incomplete"], 2 * plan.test_per_task)
                self.assertIsNone(arm["test"]["summary"]["mse"])
                self.assertIsNone(arm["cost"]["estimated_float_ops"])
            self.assertEqual(run["decision"]["decision"], "HOLD")

    def test_corrupted_child_is_rejected_using_actual_predictions(self):
        run = self.fresh_run()
        self.assertTrue(run["demand_evidence"]["propose_child"])
        arm = run["arms"]["demand_specialization"]
        payload = copy.deepcopy(arm["model"])
        payload["experts"][1]["weights"] = [10 * w for w in payload["experts"][1]["weights"]]
        model = Model.restore(payload)
        data = make_data(self.plan, run["seed"], run["scenario"])
        post_training = {"validation", "candidate_snapshot", "deserialize_snapshot", "migration_validation", "test"}
        ledger = [e for e in arm["ledger"] if e["stage"] not in post_training]
        observation = evaluate(data["validation"], model, ledger, "validation")
        migration = snapshot_and_check(model, data["validation"], observation, ledger)
        test = evaluate(data["test"], model, ledger, "test")
        arm.update({"model": payload, "model_digest": model.identity(), "validation": observation,
                    "migration": migration, "test": test, "ledger": ledger,
                    "cost": total_cost(run["shared_ledger"] + ledger)})
        self.assertIn("insufficient_gain_over:frozen_incumbent", self.decision(run)["reasons"])

    def test_differentiation_cannot_overwrite_the_parent_to_hide_old_task_regression(self):
        run = self.fresh_run()
        arm = run["arms"]["demand_specialization"]
        arm["model"]["experts"][0]["weights"][1] *= -1
        arm["model_digest"] = digest(arm["model"])
        self.assert_invalid(run, "compatible parent")

    def test_demand_changes_structure_only_in_the_conflicting_task_scenario(self):
        helpful = self.fresh_run()
        redundant = self.fresh_run("redundant_specialization")
        self.assertTrue(helpful["demand_evidence"]["propose_child"])
        self.assertFalse(redundant["demand_evidence"]["propose_child"])
        specialized = helpful["arms"]["demand_specialization"]["test"]["summary"]["mse"]
        frozen = helpful["arms"]["frozen_incumbent"]["test"]["summary"]["mse"]
        self.assertLess(specialized, frozen / 2)
        self.assertEqual(redundant["arms"]["demand_specialization"]["model"],
                         redundant["arms"]["frozen_incumbent"]["model"])

    def test_self_consistent_source_map_still_must_match_executed_files(self):
        report = copy.deepcopy(self.report)
        report["source_files"]["study_model.py"] = "0" * 64
        report["source_digest"] = digest(report["source_files"])
        with self.assertRaisesRegex(ValueError, "executed local files"):
            audit_study(report, self.plan)

    @staticmethod
    def resummarize(observation):
        rows = observation["records"]
        observation["summary"] = summarize(rows)
        observation["old_task"] = summarize([r for r in rows if r["task"] == 0])
        observation["new_task"] = summarize([r for r in rows if r["task"] == 1])


if __name__ == "__main__":
    unittest.main()
