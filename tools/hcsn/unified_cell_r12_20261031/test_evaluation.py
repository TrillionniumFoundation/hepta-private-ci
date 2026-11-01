"""Development-only execution, information-boundary and freeze audit.

Tiny fixtures use independently named development tapes and temporary mock fit
records. They do not read, alter or evaluate the campaign's selected models or
confirmation namespaces. Timing comparisons are intentionally not asserted.
"""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import campaign, evaluate
from .cell import Cell
from .data import EpisodeOwner, generate_episode_tapes, generate_sequences
from .estimators import HXFilter, restore_model
from .recurrent import RecurrentEstimator
from .task_value import ExactBeliefDP


def scientific_episode(record):
    return {key: record[key] for key in ("utility", "reward", "cost", "correct", "label", "state",
                                         "elapsed", "steps", "counts", "actions", "channels",
                                         "final_estimated_bit_probability")}


def fake_fit_directory(root, seed=73, ordinary_scores=(.7, .4)):
    """Minimal completed *mock* records for testing validation-only selection."""
    run = root / "run"
    per_seed = run / str(seed)
    per_seed.mkdir(parents=True)
    for kind, score, irrelevant_test in zip(campaign.KINDS, (.01, *ordinary_scores), (100., 0., 100.)):
        value = dict(status="completed", seed=seed, kind=kind, budget_cpu_seconds=20.,
                     selected_validation_joint_ce=score, test_metric_must_not_select=irrelevant_test)
        (per_seed / (kind + ".json")).write_text(json.dumps(value))
    (per_seed / "data_manifest.json").write_text("{}")
    (per_seed / "job_costs.json").write_text("{}")
    (run / "training_manifest.json").write_text("{}")
    np.savez(per_seed / "common_data.npz", development_only=np.arange(3))
    source = root / "audited_source.py"
    source.write_text("VALUE = 1\n")
    return run, source


class EvaluationBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hx = HXFilter(seed=741)
        cls.fitted = cls.hx.build_cell()
        cls.world = Cell()
        cls.tapes = generate_episode_tapes(321741, 2, horizon=3, intervals=(.15, .45))
        cls.ordinary = RecurrentEstimator("gru", seed=742)

    def test_all_four_arms_execute_serialize_and_share_one_controller(self):
        assignments = {"A": (self.ordinary.export(), "fixed_read"),
                       "B": (self.ordinary.export(), "finite_horizon_value"),
                       "C": (self.hx.export(), "fixed_read"),
                       "D": (self.hx.export(), "finite_horizon_value")}
        expected_identity = ExactBeliefDP(self.fitted).model_identity
        for name, (payload, control) in assignments.items():
            with self.subTest(arm=name):
                result = evaluate.execute_arm(payload, self.fitted, self.world, self.tapes, control)
                self.assertEqual(result["controller_identity"], expected_identity)
                self.assertEqual(len(result["episodes"]), 2)
                self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
                self.assertAlmostEqual(result["online_cpu_per_episode"] * 2, result["online_cpu_seconds"])
                self.assertGreaterEqual(result["online_cpu_seconds"], result["setup_cpu_seconds"])
                self.assertGreaterEqual(result["online_cpu_seconds"] + 1e-9,
                                        sum(result["component_cpu_seconds"].values()))
                for tape, episode in zip(self.tapes, result["episodes"]):
                    self.assertLessEqual(episode["counts"]["READ"], 2)
                    self.assertEqual(sum(episode["counts"].values()), episode["steps"])
                    self.assertEqual(len(episode["actions"]), episode["steps"] + 1)
                    self.assertTrue(episode["actions"][-1].startswith("STOP"))
                    self.assertLessEqual(episode["steps"], 3)
                    # Independently replay the *executed* actions through an
                    # owner; no model is allowed to supply the scoring state.
                    owner = EpisodeOwner(self.world, tape)
                    for action in episode["actions"][:-1]:
                        owner.advance(action)
                    replay = owner.finish(int(episode["actions"][-1][-1]))
                    for key in replay:
                        self.assertEqual(replay[key], episode[key])

    def test_actual_actor_interface_has_shared_prior_and_raw_observations_only(self):
        observed_priors, observed_inputs, closed = [], [], []
        real_restore = restore_model
        real_owner = EpisodeOwner

        class AuditedActor:
            def __init__(self, payload):
                self.model = real_restore(payload)

            def start(self, prior):
                observed_priors.append(np.array(prior, copy=True))
                return self.model.start(prior)

            def step(self, value):
                self_outer.assertEqual(np.asarray(value).shape, (10,))
                self_outer.assertFalse(closed[-1])
                self_outer.assertIn(value[7], (0., 1.))
                self_outer.assertIn(value[9], (0., 1.))
                observed_inputs.append(np.array(value, copy=True))
                return self.model.step(value)

        class AuditedOwner(real_owner):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                closed.append(False)

            def advance(self, action):
                result = super().advance(action)
                self_outer.assertEqual(set(result), {"input", "token", "dt", "reset", "observed"})
                self_outer.assertNotIn("cost", result)
                self_outer.assertNotIn("state", result)
                self_outer.assertNotIn("label", result)
                return result

            def finish(self, answer):
                closed[-1] = True
                return super().finish(answer)

        self_outer = self
        with patch.object(evaluate, "restore_model", side_effect=AuditedActor), patch.object(evaluate, "EpisodeOwner", AuditedOwner):
            for payload in (self.hx.export(), self.ordinary.export()):
                evaluate.execute_arm(payload, self.fitted, self.world, self.tapes, "fixed_read")
        self.assertEqual(len(observed_priors), 4)
        self.assertEqual(len(observed_inputs), 8)
        for prior in observed_priors:
            np.testing.assert_array_equal(prior, self.fitted.prior)
        self.assertTrue(all(closed))

    def test_unread_future_does_not_change_fixed_read_execution(self):
        changed = [replace(tape,
                           transition_uniform=(*tape.transition_uniform[:2], .999),
                           observation_uniform=(*tape.observation_uniform[:2], .001)) for tape in self.tapes]
        for payload in (self.hx.export(), self.ordinary.export()):
            first = evaluate.execute_arm(payload, self.fitted, self.world, self.tapes, "fixed_read")
            second = evaluate.execute_arm(payload, self.fitted, self.world, changed, "fixed_read")
            self.assertEqual([scientific_episode(r) for r in first["episodes"]],
                             [scientific_episode(r) for r in second["episodes"]])

    def test_structural_hmm_reference_and_unknown_control(self):
        data = generate_sequences(self.fitted, 321743, 2, length=4)
        predicted = restore_model(self.hx.export()).forward(data["inputs"])
        independent = evaluate.generic_hmm(self.fitted, data["inputs"])
        np.testing.assert_allclose(predicted, independent, rtol=4e-13, atol=2e-14)
        with self.assertRaises(ValueError):
            evaluate.execute_arm(self.hx.export(), self.fitted, self.world, self.tapes, "typo_control")

    def test_freeze_selects_ordinary_from_validation_and_detects_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, source = fake_fit_directory(root)
            with patch.dict(campaign.PROTOCOL, {"seeds": [73]}), patch.object(campaign, "ROOT", root), patch.object(campaign, "source_paths", return_value=[source]):
                value = campaign.freeze(run, "a" * 40)
                # The tempting test metric favors GRU; validation favors SSM.
                self.assertEqual(value["selection"]["73"]["kind"], "continuous_diagonal_ssm")
                frozen, identity = campaign.verify_freeze(run)
                self.assertEqual(identity, value["freeze_sha256"])
                self.assertFalse(frozen["confirmation_generated"])
                self.assertIn("73/common_data.npz", frozen["training_data_files"])
                data_file = run / "73" / "common_data.npz"
                original_data = data_file.read_bytes()
                data_file.write_bytes(original_data + b"tampered")
                with self.assertRaisesRegex(ValueError, "Common training data changed"):
                    campaign.verify_freeze(run)
                data_file.write_bytes(original_data)
                source.write_text("VALUE = 2\n")
                with self.assertRaisesRegex(ValueError, "Source changed"):
                    campaign.verify_freeze(run)
                source.write_text("VALUE = 1\n")
                fit = run / "73" / "gru.json"
                fit.write_text(fit.read_text() + " ")
                with self.assertRaisesRegex(ValueError, "Training artifact changed"):
                    campaign.verify_freeze(run)

    def test_cannot_create_new_freeze_after_confirmation_was_opened(self):
        for marker in ("CONFIRMATION_STARTED.json", "CONFIRMATION_FAILED.json", "73/confirmation_iid.json"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run, source = fake_fit_directory(root)
                (run / marker).write_text("{}")
                with patch.dict(campaign.PROTOCOL, {"seeds": [73]}), patch.object(campaign, "ROOT", root), patch.object(campaign, "source_paths", return_value=[source]):
                    with self.assertRaises((ValueError, FileExistsError)):
                        campaign.freeze(run, "a" * 40)


if __name__ == "__main__":
    unittest.main()
