"""Engineering checks only; generated tensors are not real-task evidence."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from .real_predictor import (
    Observation,
    Opportunity,
    PredictiveModel,
    digest,
    fit_predictive,
    parameter_digest,
    conditional_stop_loss,
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


class PredictiveContracts(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(17)

    def test_actual_hepta_and_ordinary_ablation_are_parameter_matched(self):
        ordinary = PredictiveModel(4, width=4, core="ordinary")
        hepta = PredictiveModel(4, width=4, core="hepta")
        hepta.load_state_dict(ordinary.state_dict())
        self.assertEqual(
            sum(p.numel() for p in ordinary.parameters()),
            sum(p.numel() for p in hepta.parameters()),
        )
        self.assertEqual(hepta.core.mode, "dual")
        features = torch.tensor([observed().features()])
        self.assertFalse(torch.equal(ordinary.hidden(features), hepta.hidden(features)))
        loss = hepta.hidden(features).square().sum()
        loss.backward()
        self.assertGreater(
            sum(
                float(p.grad.abs().sum())
                for p in hepta.core.parameters()
                if p.grad is not None
            ),
            0,
        )

    def test_stop_critic_targets_conditional_ce_not_mean_log_outcomes(self):
        outcomes = torch.tensor([0.0, 1.0], dtype=torch.float64)
        gamma = 2.0
        optimum = -torch.log(torch.exp(-gamma * outcomes).mean()) / gamma
        prediction = optimum.clone().requires_grad_()
        conditional_stop_loss(
            prediction.expand_as(outcomes), outcomes, gamma
        ).backward()
        self.assertLess(abs(prediction.grad.item()), 1e-12)
        mean = outcomes.mean().requires_grad_()
        conditional_stop_loss(mean.expand_as(outcomes), outcomes, gamma).backward()
        self.assertGreater(mean.grad.item(), 0.1)
        self.assertLess(optimum.item(), outcomes.mean().item())

    def test_fitting_preserves_frozen_core_and_updates_joint_core(self):
        for regime in ("frozen", "joint"):
            with self.subTest(regime=regime), tempfile.TemporaryDirectory() as folder:
                model = PredictiveModel(4, width=4, core="hepta")
                before = parameter_digest(model.core)
                report = fit_predictive(
                    model,
                    [transition()],
                    PLAN,
                    allowed_sources={"unit-fixture-source"},
                    regime=regime,
                    seed=17,
                    output=Path(folder) / "fit",
                )
                self.assertEqual(report["status"], "completed")
                self.assertEqual(report["updates"], 2)
                self.assertEqual(
                    parameter_digest(model.core) == before, regime == "frozen"
                )
                self.assertEqual(report["claim_status"], "HOLD")
                self.assertGreater(report["wall_seconds"], 0)
                saved = torch.load(Path(folder) / "fit/model.pt", weights_only=True)
                restored = PredictiveModel(**saved["config"])
                restored.load_state_dict(saved["state_dict"])
                self.assertEqual(parameter_digest(restored), report["model_digest"])

    def test_confirmation_labels_and_unregistered_sources_cannot_fit(self):
        for changed in ({"split": "confirmation"}, {"source_group": "unregistered"}):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "fit"
                with self.assertRaises(ValueError):
                    fit_predictive(
                        PredictiveModel(4, width=4),
                        [{**transition(), **changed}],
                        PLAN,
                        allowed_sources={"unit-fixture-source"},
                        regime="joint",
                        seed=1,
                        output=path,
                    )
                receipt = json.loads((path / "fit.json").read_text())
                self.assertEqual(receipt["status"], "failed")
                self.assertGreater(receipt["wall_seconds"], 0)
                self.assertFalse((path / "model.pt").exists())

    def test_duplicate_physical_transition_is_not_more_training_data(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            self.assertRaisesRegex(ValueError, "duplicate physical"),
        ):
            fit_predictive(
                PredictiveModel(4, width=4),
                [transition(), transition()],
                PLAN,
                allowed_sources={"unit-fixture-source"},
                regime="joint",
                seed=1,
                output=Path(folder) / "fit",
            )

    def test_capacity_limit_fails_with_retained_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fit"
            with self.assertRaisesRegex(ValueError, "parameter opportunity"):
                fit_predictive(
                    PredictiveModel(4, width=4),
                    [transition()],
                    replace(PLAN, max_parameters=1),
                    allowed_sources={"unit-fixture-source"},
                    regime="joint",
                    seed=1,
                    output=path,
                )
            self.assertEqual(
                json.loads((path / "fit.json").read_text())["status"], "failed"
            )


if __name__ == "__main__":
    unittest.main()
