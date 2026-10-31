"""Narrow independent audit of critic gradients, training isolation and execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .controller import (ARMS, choose, design, loss_and_gradient, normalization,
                         parameter_hash, parameters, train_controller)
from .dataset import collect, state_record
from .task import ACTIONS, ContentAdapter, Owner, score_terminal


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.adapter = ContentAdapter()
        cls.confusion = [[.9, .1], [.1, .9]]
        data_protocol = dict(data_seed_base=1730000000, deadlines=[6], read_budgets=[2],
                             packet_reliabilities=[.7, .9], packet_prices=[.05, .2],
                             step_durations=[.2, .5], packet_length=32,
                             behavior_action_weights=[0., 0., 1., 0.])
        cls.train_data = collect(cls.root / "train", "train", 903, 2, data_protocol,
                                 cls.adapter, cls.confusion, 1., .05)
        cls.validation_data = collect(cls.root / "validation", "validation", 903, 1,
                                      data_protocol, cls.adapter, cls.confusion, 1., .05)
        cls.train = cls.train_data["rows"]
        cls.validation = cls.validation_data["rows"]
        cls.norm = normalization(cls.train)
        cls.cell = np.zeros(11)
        cls.seed = 7
        cls.protocol = dict(critic_init_seed_base=70, critic_width=4,
                            batch_seed_base=80, critic_updates=6, batch_size=4,
                            critic_l2=.003, gradient_clip=2., learning_rate=.004,
                            checkpoint_updates=[2, 4, 6])
        cls.fitted = {}
        for arm in ARMS:
            family, mode = arm.split("_")
            cls.fitted[arm] = train_controller(family, mode, cls.seed, cls.train,
                cls.validation, cls.cell, cls.norm, cls.protocol)

    def test_masked_mse_gradient_two_independent_random_directions(self):
        rng = np.random.default_rng(491)
        weights = parameters(43, 5, 3)
        x, target = rng.normal(size=(6, 5)), rng.normal(size=(6, 4))
        mask = np.array([[1, 0, 1, 1], [1, 0, 0, 1], [1, 1, 1, 0],
                         [1, 1, 0, 0], [1, 0, 1, 0], [1, 0, 0, 0]], bool)
        l2 = .037

        def independent_objective(candidate):
            prediction = np.tanh(x @ candidate["w"]+candidate["b"]) @ candidate["v"]+candidate["c"]
            legal_errors = (prediction-target)[mask]
            penalty = sum(float(np.vdot(value, value)) for value in candidate.values())
            return float(np.mean(legal_errors**2)+l2*penalty)

        loss, gradients = loss_and_gradient(weights, x, target, mask, l2)
        self.assertAlmostEqual(loss, independent_objective(weights), places=14)
        for direction_seed in (131, 977):
            direction_rng = np.random.default_rng(direction_seed)
            direction = {key: direction_rng.normal(size=value.shape) for key, value in weights.items()}
            length = np.sqrt(sum(np.vdot(value, value) for value in direction.values()))
            direction = {key:value/length for key, value in direction.items()}
            step = 1e-6
            positive = {key:weights[key]+step*direction[key] for key in weights}
            negative = {key:weights[key]-step*direction[key] for key in weights}
            finite_difference = (independent_objective(positive)-independent_objective(negative))/(2*step)
            derivative = sum(float(np.vdot(gradients[key], direction[key])) for key in weights)
            np.testing.assert_allclose(derivative, finite_difference, rtol=2e-7, atol=2e-9)
        altered_target = target.copy()
        altered_target[~mask] = 1e8
        altered_loss, altered_gradient = loss_and_gradient(weights, x, altered_target, mask, l2)
        self.assertEqual(loss, altered_loss)
        for key in weights:
            np.testing.assert_array_equal(gradients[key], altered_gradient[key])
        penalty_loss, penalty_gradient = loss_and_gradient(weights, x, target, np.zeros_like(mask), l2)
        self.assertAlmostEqual(penalty_loss, l2*sum(np.vdot(v, v) for v in weights.values()), places=14)
        for key in weights:
            np.testing.assert_allclose(penalty_gradient[key], 2*l2*weights[key], atol=0.)

    def test_four_arms_share_initial_parameters_and_every_minibatch(self):
        receipts = [result[1] for result in self.fitted.values()]
        self.assertEqual(len({r["initial_sha256"] for r in receipts}), 1)
        self.assertEqual(len({r["minibatch_sha256"] for r in receipts}), 1)
        self.assertEqual(len({r["parameter_count"] for r in receipts}), 1)
        width = len(self.norm["mean"])+5
        expected_initial = parameter_hash(parameters(self.seed+self.protocol["critic_init_seed_base"],
                                                      width, self.protocol["critic_width"]))
        rng = np.random.default_rng(self.seed+self.protocol["batch_seed_base"])
        batches = [rng.integers(0, len(self.train), self.protocol["batch_size"])
                   for _ in range(self.protocol["critic_updates"])]
        expected_batches = hashlib.sha256(b"".join(b.astype("<i8").tobytes() for b in batches)).hexdigest()
        for receipt in receipts:
            self.assertEqual(receipt["initial_sha256"], expected_initial)
            self.assertEqual(receipt["minibatch_sha256"], expected_batches)
            self.assertEqual(receipt["updates"], self.protocol["critic_updates"])
            self.assertEqual(receipt["target"], "q" if receipt["mode"] == "value" else "q_myopic")

    def test_training_normalization_and_updates_ignore_validation_distribution(self):
        before = json.dumps(self.norm, sort_keys=True)
        raw = np.asarray([r["features"] for r in self.train])
        np.testing.assert_array_equal(self.norm["mean"], raw.mean(0))
        expected_scale = raw.std(0)
        expected_scale[expected_scale < 1e-8] = 1.
        np.testing.assert_array_equal(self.norm["scale"], expected_scale)
        self.assertEqual(self.norm["split"], "TRAIN only")
        perturbed = copy.deepcopy(self.validation)
        for row in perturbed:
            row["features"] = (np.asarray(row["features"])*-11.+1e5).tolist()
            row["q"] = [1000., -999., 500., 300.]
        _, receipt = train_controller("ordinary", "value", self.seed, self.train,
                                       perturbed, self.cell, self.norm, self.protocol)
        original = self.fitted["ordinary_value"][1]
        self.assertEqual([c["parameter_sha256"] for c in receipt["candidates"]],
                         [c["parameter_sha256"] for c in original["candidates"]])
        self.assertEqual(receipt["losses"], original["losses"])
        self.assertEqual(json.dumps(self.norm, sort_keys=True), before)
        encoded = design(self.train, "ordinary", self.cell, self.norm)
        np.testing.assert_allclose(encoded[:, :raw.shape[1]],
                                   (raw-np.asarray(self.norm["mean"]))/expected_scale, atol=0.)

    def test_selected_weights_and_receipts_are_finite_and_executable(self):
        session = self.validation_data["cohort"]["records"][0]
        for arm, (weights, receipt) in self.fitted.items():
            family, _ = arm.split("_")
            self.assertEqual(set(weights), {"w", "b", "v", "c"})
            self.assertTrue(all(np.all(np.isfinite(value)) for value in weights.values()))
            self.assertEqual(parameter_hash(weights), receipt["selected_sha256"])
            self.assertTrue(np.all(np.isfinite(receipt["losses"])))
            self.assertTrue(np.isfinite(receipt["selected_validation_regret"]))
            self.assertIn(receipt["selected_update"], self.protocol["checkpoint_updates"])
            self.assertEqual(len(receipt["losses"]), self.protocol["critic_updates"])
            json.dumps(receipt, allow_nan=False)
            owner = Owner(session["folder"], self.adapter, self.confusion, 1., .05)
            history, steps = [], 0
            while not owner.terminal:
                record = state_record(owner, history)
                action, predicted_q = choose(weights, family, self.cell, self.norm, record)
                self.assertTrue(record["feasible"][action])
                self.assertTrue(np.all(np.isfinite(predicted_q)))
                event = owner.act(ACTIONS[action])
                history.append(dict(driver=record["driver"], duration=event["duration"],
                                    reset=event["action"] == "FIRE"))
                steps += 1
                self.assertLessEqual(steps, owner.meta["deadline"]+1)
            self.assertTrue(np.isfinite(score_terminal(owner)["utility"]))


if __name__ == "__main__":
    unittest.main()
