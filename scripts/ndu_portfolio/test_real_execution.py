"""Actual artifact I/O with explicit fixture backends; never model-quality evidence."""

from dataclasses import replace
import json
import hashlib
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
from PIL import Image
import torch

from .real_controllers import Controller, Opportunity, PredictiveModel
from .real_execution import execute, load_predictor
from .real_predictor import fit_predictive
from .test_real_predictor import transition


BINDING = dict(
    task_id="private-task",
    source_group="private-source",
    episode_group="private-episode",
    fit_id="private-fit",
    native_request_id="not-native-authenticated",
    incumbent_checkpoint_digest="a" * 64,
)
PLAN = Opportunity(10000, 16, 2, 3, 20, 500)


class ArtifactFixture:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def identity(self):
        return {"evidence_kind": "synthetic_fixture", "claim": "transport_test_only"}

    def describe(self, image_path, prompt):
        self.calls.append(("describe", prompt))
        if self.fail:
            raise RuntimeError("physical fixture failure")
        return "Fixture output; no semantic acceptance."

    def draw(self, prompt, output_path, seed, initial_image=None):
        self.calls.append(("draw", prompt))
        Image.new("RGB", (8, 8), "blue").save(output_path)

    def synchronize(self):
        pass


class PublicRecordingEncoder:
    def __init__(self):
        self.calls = []

    def contract_digest(self):
        return hashlib.sha256(b"explicit-unit-fixture-encoding").hexdigest()

    def __call__(self, public, current):
        self.calls.append((set(public), set(current)))
        if set(public) != {"text", "image_rgb"} or set(current) != {
            "plan",
            "text",
            "image_rgb",
            "critique",
            "history",
        }:
            raise AssertionError("private data leaked to encoder")
        return (0.1, 0.2, -0.1, 0.3)


class ExecutionContracts(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(11)
        self.public = {
            "text": "Describe the visible item.",
            "image_rgb": np.zeros((8, 8, 3), dtype=np.uint8),
        }

    def actor(self, schedule, strategy="tuned_fixed"):
        return Controller(
            PredictiveModel(4, width=4),
            strategy,
            PLAN,
            fixed=schedule,
            gamma=2.0,
            cost_weight=0.02,
            failure_score=0.0,
        )

    def run_episode(self, folder, actor, backend=None, encoder=None, **overrides):
        values = dict(
            binding=BINDING,
            seed=17,
            horizon=6,
            cost_budget=100.0,
            wall_budget=100.0,
            cpu_tariff=0.0,
            wall_tariff=1.0,
            required_modalities=("text", "image"),
        )
        values.update(overrides)
        return execute(
            self.public,
            backend or ArtifactFixture(),
            actor,
            encoder or PublicRecordingEncoder(),
            Path(folder) / "episode",
            **values,
        )

    def test_actual_artifacts_are_bound_without_claiming_native_or_scoring(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_episode(folder, self.actor(("text", "draft", "stop")))
            self.assertEqual(
                report["status"], "candidate_complete_pending_native_owner"
            )
            self.assertEqual(
                {item["kind"] for item in report["selected"]}, {"text", "image"}
            )
            self.assertFalse(report["native_owner_verified"])
            self.assertEqual(
                report["semantic_acceptance"], "pending_independent_evaluation"
            )
            self.assertGreater(report["total_cost"], 0)
            self.assertEqual(
                [
                    r["status"]
                    for r in report["events"]
                    if r["category"] == "synchronization"
                ],
                ["completed", "completed", "completed"],
            )
            self.assertEqual(
                json.loads((Path(folder) / "episode/episode.json").read_text()), report
            )

    def test_private_binding_does_not_enter_encoder_or_generator_prompts(self):
        backend, encoder = ArtifactFixture(), PublicRecordingEncoder()
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_episode(
                folder,
                self.actor(("text", "draft", "stop")),
                backend,
                encoder,
                collect_transition_features=True,
            )
            self.assertTrue(encoder.calls)
            self.assertTrue(
                all(
                    row["suitable_for_predictive_fitting"]
                    for row in report["observations"]
                )
            )
            for _, prompt in backend.calls:
                self.assertFalse(any(value in prompt for value in BINDING.values()))

    def test_fixed_does_not_burn_unused_encoder_work(self):
        encoder = PublicRecordingEncoder()
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_episode(
                folder, self.actor(("text", "draft", "stop")), encoder=encoder
            )
            self.assertEqual(encoder.calls, [])
            self.assertTrue(
                all(
                    not row["suitable_for_predictive_fitting"]
                    for row in report["observations"]
                )
            )

    def test_registered_initial_text_delivery_and_optional_image(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_episode(
                folder,
                self.actor(("stop",), "initial"),
                initial_actions=("text",),
                required_modalities=("text",),
            )
            self.assertEqual(
                report["status"], "candidate_complete_pending_native_owner"
            )
            self.assertEqual([item["kind"] for item in report["selected"]], ["text"])
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            self.run_episode(folder, self.actor(("stop",), "initial"))

    def test_plan_revision_invalidates_previous_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_episode(
                folder, self.actor(("text", "draft", "revise", "stop"))
            )
            self.assertEqual(report["status"], "abstained")
            self.assertEqual(report["selected"], [])
            self.assertEqual(len(report["artifacts"]), 3)

    def test_failure_is_retained_with_cost_and_cannot_deliver(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_episode(
                folder,
                self.actor(("text", "draft", "stop")),
                ArtifactFixture(fail=True),
            )
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["selected"], [])
            self.assertGreater(report["wall_seconds"], 0)
            self.assertEqual(report["events"][-1]["category"], "failure")

    def test_actual_budget_exhaustion_does_not_return_a_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self.run_episode(
                folder, self.actor(("text", "draft", "stop")), cost_budget=1e-12
            )
            self.assertEqual(report["status"], "timeout")
            self.assertEqual(report["selected"], [])
            self.assertGreater(report["total_cost"], 1e-12)

    def test_failed_barrier_is_metered_and_revokes_delivery(self):
        class FailedBarrier(ArtifactFixture):
            def synchronize(self):
                time.sleep(0.002)
                raise RuntimeError("explicit fixture barrier failure")

        with tempfile.TemporaryDirectory() as folder:
            report = self.run_episode(
                folder,
                self.actor(("text", "stop")),
                FailedBarrier(),
                required_modalities=("text",),
            )
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["selected"], [])
            barriers = [
                r for r in report["events"] if r["category"] == "synchronization"
            ]
            self.assertEqual(len(barriers), 1)
            self.assertEqual(barriers[0]["status"], "failed")
            self.assertGreaterEqual(barriers[0]["wall_seconds"], 0.002)
            self.assertAlmostEqual(
                report["total_cost"], sum(r["cost"] for r in report["events"])
            )

    def test_hidden_reference_in_material_input_is_rejected(self):
        self.public["reference"] = "private answer"
        with (
            tempfile.TemporaryDirectory() as folder,
            self.assertRaisesRegex(ValueError, "only public"),
        ):
            self.run_episode(folder, self.actor(("stop",)))

    def test_checkpoint_bound_fit_provenance_cannot_be_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fit"
            fit_predictive(
                PredictiveModel(4, width=4),
                [transition()],
                replace(PLAN, updates=1),
                allowed_sources={"unit-fixture-source"},
                regime="frozen",
                seed=17,
                output=path,
            )
            checkpoint = path / "model.pt"
            sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            original = json.loads((path / "fit.json").read_text())
            self.assertEqual(
                load_predictor(checkpoint, sha).fit_receipt["regime"], "frozen"
            )
            for key, value in (
                ("input_digest", "b" * 64),
                ("source_groups", ["substituted"]),
                ("regime", "joint"),
            ):
                with self.subTest(key=key):
                    (path / "fit.json").write_text(json.dumps({**original, key: value}))
                    with self.assertRaisesRegex(ValueError, "rewrites"):
                        load_predictor(checkpoint, sha)


if __name__ == "__main__":
    unittest.main()
