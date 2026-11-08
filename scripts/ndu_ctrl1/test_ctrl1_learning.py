"""Behavioral and numerical counterexamples for the finite learning pilot."""

from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .learning import (
    COST_UNIT,
    FEATURES,
    Learner,
    TeacherLabel,
    _continuation,
    _policy_gradient,
    _sha,
    adoption_decision,
    train_actor_critic,
    train_distilled,
)
from .model import ACTIONS, Profile, Scenario, initial_state, legal_actions
from .budget_sensitivity import run_budget_worker


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile()
        scenarios = [
            Scenario(prior=Fraction(p), deadline=3, budget=4, horizon=1) for p in (0, 1)
        ]
        self.examples = [
            (scenario, replace(initial_state(scenario), budget_left=3))
            for scenario in scenarios
        ]

    def test_actual_actor_gradient_matches_independent_finite_difference(self):
        logits, values = [0.2, -0.1, 0.7], [0.3, -0.2, 0.9]
        analytic = _policy_gradient(logits, values)

        def objective(z):
            weights = [math.exp(x) for x in z]
            return sum(w * q for w, q in zip(weights, values)) / sum(weights)

        for index, derivative in enumerate(analytic):
            plus, minus = list(logits), list(logits)
            plus[index] += 1e-6
            minus[index] -= 1e-6
            self.assertAlmostEqual(
                derivative, (objective(plus) - objective(minus)) / 2e-6, places=8
            )
        self.assertGreater(analytic[2], 0)
        self.assertLess(analytic[1], 0)

    def test_real_joint_backup_learning_distinguishes_known_success_and_failure(self):
        learner = train_actor_critic(self.examples, self.profile, seed=4, epochs=128)
        self.assertEqual(
            [learner.action(*example) for example in self.examples], ["stop", "execute"]
        )
        stats = learner.training
        self.assertGreater(stats["actor_gradient_l1"], 0)
        self.assertEqual(stats["counts"]["actor_updates"], 256)
        self.assertEqual(stats["counts"]["critic_updates"], 256)
        self.assertGreater(
            stats["counts"]["outcome_branches"], stats["counts"]["model_calls"]
        )
        self.assertTrue(any(weight != 0 for weight in learner.critic))

    def test_seeded_replay_and_checkpoint_preserve_actions_and_parameters(self):
        first = train_actor_critic(self.examples, self.profile, seed=17, epochs=4)
        second = train_actor_critic(self.examples, self.profile, seed=17, epochs=4)
        record = json.loads(json.dumps(first.record(), allow_nan=False))
        restored = Learner.from_record(record)
        self.assertEqual(restored.record(), record)
        self.assertEqual(
            first.record()["parameters_sha256"], second.record()["parameters_sha256"]
        )
        self.assertEqual(
            first.training["update_order_sha256"],
            second.training["update_order_sha256"],
        )
        self.assertEqual(
            [first.action(*row) for row in self.examples],
            [restored.action(*row) for row in self.examples],
        )
        changed = deepcopy(record)
        changed["actor"][0][0] += 0.01
        with self.assertRaises(ValueError):
            Learner.from_record(changed)
        changed = deepcopy(record)
        changed["critic"][0] = math.nan
        with self.assertRaises(ValueError):
            Learner.from_record(changed)

    def test_distillation_retains_all_labels_and_extra_teacher_work(self):
        seen = []

        def teacher(scenario, state):
            seen.append((scenario, state))
            return TeacherLabel("stop", model_calls=7, expanded_nodes=11)

        distilled = train_distilled(
            self.examples, teacher, self.profile, seed=12, epochs=5
        )
        actor = train_actor_critic(self.examples, self.profile, seed=12, epochs=5)
        self.assertEqual(seen, self.examples)
        self.assertEqual(distilled.training["teacher_model_calls"], 14)
        self.assertEqual(distilled.training["teacher_expanded_nodes"], 22)
        self.assertEqual(len(distilled.training["teacher_labels"]), len(self.examples))
        for key in ("initial_parameters_sha256", "update_order_sha256"):
            self.assertEqual(actor.training[key], distilled.training[key])
        self.assertEqual(
            actor.training["counts"]["actor_updates"],
            distilled.training["counts"]["actor_updates"],
        )
        self.assertFalse(distilled.training["matched_total_compute_claim"])
        unknown = train_distilled(
            self.examples, lambda s, b: "stop", self.profile, epochs=1
        )
        self.assertIsNone(unknown.training["teacher_model_calls"])
        with self.assertRaises(ValueError):
            train_distilled(
                self.examples, lambda s, b: "fabricated", self.profile, epochs=1
            )

    def test_inference_hard_mask_overrides_adverse_actor_weights(self):
        learner = train_actor_critic(self.examples, self.profile, epochs=1)
        learner.actor = [[-8.0] * len(FEATURES) for _ in ACTIONS]
        learner.actor[ACTIONS.index("repair")] = [8.0] * len(FEATURES)
        scenario, state = self.examples[0]
        exhausted = replace(state, steps_left=0)
        self.assertEqual(legal_actions(scenario, exhausted), ("stop",))
        self.assertEqual(learner.action(scenario, exhausted), "stop")

    def test_known_boundary_and_future_compute_charge_prevent_false_continuation(self):
        scenario = Scenario()
        state = replace(
            initial_state(scenario), time_left=1, budget_left=2, steps_left=2
        )
        # With the next base credit charged, every non-STOP support is illegal.
        self.assertEqual(
            legal_actions(scenario, replace(state, budget_left=1)), ("stop",)
        )
        value, kind = _continuation(
            [8.0] * len(FEATURES), scenario, state, self.profile
        )
        self.assertAlmostEqual(
            value, scenario.stop_reward - self.profile.resource_weight
        )
        self.assertEqual(kind, "charged_stop")
        for exhausted in (replace(state, steps_left=0), replace(state, budget_left=0)):
            self.assertEqual(
                _continuation([8.0] * len(FEATURES), scenario, exhausted, self.profile),
                (scenario.stop_reward, "emergency_stop"),
            )

    def test_training_bounds_reject_before_creating_a_candidate(self):
        for examples, epochs in (
            ([], 1),
            (self.examples, 0),
            (self.examples, 513),
            ([self.examples[0]] * 4097, 1),
        ):
            with self.assertRaises(ValueError):
                train_actor_critic(examples, self.profile, epochs=epochs)

    def test_cpu_stop_rolls_back_partial_epoch_but_retains_its_actual_cost(self):
        ticks = iter(i / 100 for i in range(1, 1000))
        with patch(
            "ndu_ctrl1.learning.time.process_time", side_effect=lambda: next(ticks)
        ):
            stopped = train_actor_critic(
                self.examples, self.profile, seed=9, epochs=20, cpu_budget_seconds=0.065
            )
        completed = stopped.training["completed_epochs"]
        self.assertGreater(completed, 0)
        self.assertLess(completed, 20)
        self.assertGreater(
            stopped.training["actual_actor_updates"],
            stopped.training["retained_actor_updates"],
        )
        reference = train_actor_critic(
            self.examples, self.profile, seed=9, epochs=completed
        )
        self.assertEqual(
            stopped.record()["parameters_sha256"],
            reference.record()["parameters_sha256"],
        )

    def test_teacher_budget_exhaustion_has_no_candidate_or_filtered_label_subset(self):
        clock = [0.0]

        def expensive_teacher(scenario, state):
            clock[0] = 2.0
            return TeacherLabel("stop", 7, 9)

        with patch(
            "ndu_ctrl1.learning.time.process_time", side_effect=lambda: clock[0]
        ):
            stopped = train_distilled(
                self.examples,
                expensive_teacher,
                self.profile,
                epochs=2,
                cpu_budget_seconds=1.0,
            )
        self.assertFalse(stopped.training["candidate_available"])
        self.assertFalse(stopped.training["teacher_complete"])
        self.assertEqual(stopped.training["actual_actor_updates"], 0)
        self.assertEqual(len(stopped.training["teacher_labels"]), 1)


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "evaluation": "exact_environment",
            "scenario_ids": ["development-a", "development-b"],
            "values": [0.4, 0.5],
            "costs": [2.0, 3.0],
            "budget_violations": 0,
            "profile_sha256": _sha(asdict(Profile())),
            "cost_unit": COST_UNIT,
        }
        self.candidate = {**self.base, "values": [0.5, 0.6]}

    def test_gain_with_costs_passes_but_ties_and_extra_cost_do_not(self):
        decision = adoption_decision(self.base, self.candidate, split="development")
        self.assertEqual(decision["decision"], "Candidate")
        self.assertAlmostEqual(decision["mean_gain"], 0.1)
        self.assertEqual(
            adoption_decision(self.base, self.base, split="development")["decision"],
            "NoUpdate",
        )
        costly = {**self.candidate, "costs": [3.0, 4.0]}
        self.assertEqual(
            adoption_decision(self.base, costly, split="development")["decision"],
            "NoUpdate",
        )

    def test_test_split_missing_nonfinite_unpaired_and_budget_evidence_reject(self):
        cases = [
            {**self.candidate, "values": [math.nan, 0.6]},
            {**self.candidate, "costs": None},
            {**self.candidate, "budget_violations": 1},
            {**self.candidate, "scenario_ids": ["other-a", "other-b"]},
            {**self.candidate, "evaluation": "teacher_agreement"},
        ]
        for candidate in cases:
            self.assertEqual(
                adoption_decision(self.base, candidate, split="development")[
                    "decision"
                ],
                "NoUpdate",
            )
        self.assertEqual(
            adoption_decision(self.base, self.candidate, split="test")["decision"],
            "NoUpdate",
        )

    def test_profile_drift_units_missing_identity_and_unknown_fields_reject(self):
        cases = [
            {**self.candidate, "profile_sha256": _sha(asdict(Profile(risk=1.0)))},
            {**self.candidate, "cost_unit": "physical_joule"},
            {**self.candidate, "profile_sha256": "g" * 64},
            {**self.candidate, "profile_sha256": "ab" * 31},
            {**self.candidate, "profile_sha256": None},
            {**self.candidate, "profile_sha256": "AB" * 32},
            {**self.candidate, "discount_override": 0.5},
            {
                key: value
                for key, value in self.candidate.items()
                if key != "profile_sha256"
            },
        ]
        for candidate in cases:
            self.assertEqual(
                adoption_decision(self.base, candidate, split="development")[
                    "decision"
                ],
                "NoUpdate",
            )


class _BurningTeacher:
    def __init__(self, profile):
        pass

    def __call__(self, scenario, state):
        while True:
            pass


@unittest.skipUnless(
    hasattr(os, "fork") and hasattr(os, "wait4"), "POSIX CPU-mode qualification only"
)
class BudgetWorkerTests(unittest.TestCase):
    def test_hard_cpu_limit_retains_failed_attempt_and_inclusive_cpu(self):
        scenario = Scenario(deadline=3, budget=4, horizon=1)
        examples = [(scenario, replace(initial_state(scenario), budget_left=3))]
        with tempfile.TemporaryDirectory() as temporary:
            with patch("ndu_ctrl1.run.Teacher", _BurningTeacher):
                receipt = run_budget_worker(
                    examples,
                    Profile(),
                    3,
                    "distillation",
                    1,
                    Path(temporary) / "hard-limit",
                )
            self.assertEqual(receipt["candidate_status"], "NoCandidate")
            self.assertLess(receipt["worker_exit_code"], 0)
            self.assertGreater(receipt["worker_inclusive_cpu_seconds"], 0.5)
            self.assertLess(receipt["worker_inclusive_cpu_seconds"], 1.5)
            self.assertIsNone(receipt["actual_actor_updates"])
            self.assertEqual(receipt["retained_actor_updates"], 0)
            self.assertTrue((Path(temporary) / "hard-limit" / "RECEIPT.json").exists())


if __name__ == "__main__":
    unittest.main()
