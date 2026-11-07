"""Engineering checks only; generated tensors are not real-task evidence."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from .real_controllers import (
    ACTIONS,
    Controller,
    Observation,
    Opportunity,
    PlanningExhausted,
    PredictiveModel,
    check_equal_opportunity,
    digest,
    fit_predictive,
    parameter_digest,
)


PLAN = Opportunity(10000, 16, 2, 3, 20, 500)


def observed(steps=2):
    return Observation((0.1, 0.2, -0.1, 0.3), False, False, 10.0, 20.0, steps)


def transition(index=0):
    before = observed()
    after = replace(
        before,
        has_text=True,
        remaining_steps=1,
        remaining_cost=9.0,
        remaining_seconds=19.0,
    )
    return dict(
        split="train",
        source_group="unit-fixture-source",
        episode_group="unit-fixture-episode",
        observation=asdict(before),
        next_observation=asdict(after),
        action="text",
        utility=0.1,
        next_utility=0.7,
        cost=1.0,
        seconds=1.0,
        execution_receipt=digest(["unit-fixture-execution", index]),
        evaluator_receipt=digest(["unit-fixture-evaluator", index]),
        encoding_digest=digest("unit-fixture-encoding"),
    )


def controller(model, strategy="light", plan=PLAN):
    return Controller(
        model,
        strategy,
        plan,
        fixed=("text", "draft", "stop"),
        gamma=2.0,
        cost_weight=0.02,
        failure_score=0.0,
        allow_unfitted=True,
    )


class ControllerContracts(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(17)

    def test_actor_rejects_private_fields_and_untyped_payloads(self):
        payload = asdict(observed())
        for name in ("target", "future", "source_id", "family", "split", "reference"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "forbidden"),
            ):
                Observation.parse({**payload, name: "hidden"})
        with self.assertRaises(ValueError):
            controller(PredictiveModel(4, width=4)).choose(payload)

    def test_unfitted_predictor_requires_explicit_engineering_mode(self):
        with self.assertRaisesRegex(ValueError, "completed physical fit"):
            Controller(
                PredictiveModel(4, width=4),
                "mpc",
                PLAN,
                fixed=("stop",),
                gamma=2.0,
                cost_weight=0.02,
                failure_score=0.0,
            )
        self.assertEqual(
            controller(PredictiveModel(4, width=4)).identity["fit_status"],
            "unfitted_engineering_only",
        )

    def test_voi_mpc_and_ndu_use_only_a_frozen_learned_model(self):
        model = PredictiveModel(4, width=4)
        for strategy in ("initial", "tuned_fixed", "light", "ndu", "voi", "mpc"):
            with self.subTest(strategy=strategy):
                actor = controller(model, strategy)
                choice = actor.choose(observed())
                self.assertIn(choice, observed().legal())
                self.assertEqual(actor.decisions[-1]["status"], "completed")
                self.assertLessEqual(
                    actor.decisions[-1]["model_nodes"], PLAN.planner_nodes
                )
                self.assertEqual(
                    actor.identity["core_role"], "public_content_state_for_control"
                )

    def test_planning_cap_is_a_recorded_failure_not_silent_exact_search(self):
        actor = controller(
            PredictiveModel(4, width=4), "mpc", replace(PLAN, planner_nodes=1)
        )
        with self.assertRaises(PlanningExhausted):
            actor.choose(observed())
        self.assertEqual(actor.decisions[-1]["status"], "failed")
        self.assertGreater(actor.decisions[-1]["wall_seconds"], 0)

    def test_policy_opportunities_and_objective_cannot_differ(self):
        model = PredictiveModel(4, width=4)
        actors = [
            controller(model, strategy)
            for strategy in ("light", "ndu", "voi", "mpc", "tuned_fixed")
        ]
        self.assertTrue(check_equal_opportunity(actors)["equal_opportunity"])
        other = controller(model, "mpc", replace(PLAN, search_trials=4))
        with self.assertRaises(ValueError):
            check_equal_opportunity([actors[0], other])
        other.cost_weight = 0.04
        with self.assertRaises(ValueError):
            check_equal_opportunity([actors[0], other])

    def test_changed_model_cannot_be_deployed_under_old_identity(self):
        model = PredictiveModel(4, width=4)
        actor = controller(model)
        with torch.no_grad():
            next(model.parameters()).add_(0.01)
        with self.assertRaisesRegex(ValueError, "changed"):
            actor.choose(observed())
        self.assertEqual(actor.decisions[-1]["status"], "failed")

    def test_same_data_comparison_rejects_different_fitting_records(self):
        models = [PredictiveModel(4, width=4) for _ in range(2)]
        for index, model in enumerate(models):
            model.fit_receipt = {
                "input_digest": digest(["engineering-fixture", index]),
                "status": "completed",
                "supported_actions": list(ACTIONS[:-1]),
            }
        actors = [controller(model) for model in models]
        with self.assertRaises(ValueError):
            check_equal_opportunity(actors)
        models[0].fit_receipt["input_digest"] = digest("changed")
        with self.assertRaisesRegex(ValueError, "provenance changed"):
            actors[0].choose(observed())

    def test_unobserved_actions_cannot_be_extrapolated_into_deployment(self):
        model = PredictiveModel(4, width=4)
        model.fit_receipt = {
            "input_digest": digest("fixture"),
            "status": "completed",
            "supported_actions": ["text"],
        }
        with self.assertRaisesRegex(ValueError, "absent"):
            controller(model, "mpc")

    def test_deployment_risk_cannot_change_fitted_critic_target(self):
        with self.assertRaisesRegex(ValueError, "risk"):
            controller(PredictiveModel(4, width=4, gamma=0.0))


if __name__ == "__main__":
    unittest.main()
