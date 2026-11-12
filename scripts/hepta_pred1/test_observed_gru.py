"""Risk checks on declared synthetic histories; no owner or policy-gain evidence."""

import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .models import Model
from .observed_gru import ObservedGRU, _continuous_loss_grad, fit_observed_gru
from .observed_models import _canonical, _digest
from .test_observed_models import row


def records():
    return [row(i, "fast" if i % 2 else "slow", history=[[float(i), 1.0]] * (1 + i % 3)
                + [[float(i), 0.0]]) for i in range(8)]


def fit(rows, **changes):
    options = dict(feature_names=["x", "stage"], action_ids=["fast", "slow", "unseen"],
                   success_definition="fixture success", cost_unit="fixture credits",
                   hidden_size=4, seed=17, epochs=8, learning_rate=0.02)
    options.update(changes)
    return fit_observed_gru(rows, **options)


class ObservedGRUTests(unittest.TestCase):
    def test_variable_length_gradient_matches_finite_difference_and_single_rows(self):
        kernel = Model("gru", 2, 2, 3, 2, 19)
        histories = [np.array([[0.1, 0.2]]), np.array([[0.3, 0.4], [-0.1, 0.2], [0.5, 0.6]]),
                     np.array([[-0.4, 0.2], [0.3, -0.8]])]
        actions, targets = np.array([[1., 0.], [0., 1.], [1., 0.]]), np.array([[0., .2, .1], [1., .8, .3], [0., .5, .2]])
        loss, analytic = _continuous_loss_grad(kernel, histories, actions, targets)
        singles = [_continuous_loss_grad(kernel, [h], actions[i:i+1], targets[i:i+1]) for i, h in enumerate(histories)]
        self.assertAlmostEqual(loss, np.mean([pair[0] for pair in singles]))
        for name, values in kernel.params.items():
            np.testing.assert_allclose(analytic[name], np.mean([pair[1][name] for pair in singles], axis=0), atol=1e-15)
            numerical = np.empty_like(values)
            for index in np.ndindex(values.shape):
                original = values[index]
                values[index] = original + 1e-6
                plus = _continuous_loss_grad(kernel, histories, actions, targets)[0]
                values[index] = original - 1e-6
                minus = _continuous_loss_grad(kernel, histories, actions, targets)[0]
                values[index] = original
                numerical[index] = (plus - minus) / 2e-6
            np.testing.assert_allclose(analytic[name], numerical, rtol=2e-5, atol=2e-10)

    def test_history_learning_order_and_stateless_candidate_inference(self):
        rows = [row(i, features=[0., 0.], history=[[float(2 * (i % 2) - 1), 0.]] + [[0., 0.]] * (1 + i // 2),
                    outcome_quality=i % 2) for i in range(8)]
        model = fit(rows, epochs=140, hidden_size=6, learning_rate=0.03)
        yes, no = [[1., 0.], [0., 0.]], [[-1., 0.], [0., 0.]]
        self.assertGreater(model.predict(yes, "fast")["success_probability"], .95)
        self.assertLess(model.predict(no, "fast")["success_probability"], .05)
        self.assertLess(model.loss_history[-1], model.loss_history[0] / 3)
        original = copy.deepcopy(yes)
        before = {k: v.copy() for k, v in model.kernel.params.items()}
        model.predict(yes, "fast")
        self.assertEqual(yes, original)
        for name, value in before.items():
            np.testing.assert_array_equal(model.kernel.params[name], value)
        x, action = model._inputs([[1., 0.], [-1., 0.], [0., 0.]], "fast")
        self.assertFalse(np.array_equal(model.kernel.forward(x[None], action[None]),
                                        model.kernel.forward(x[[1, 0, 2]][None], action[None])))

    def test_unknowns_remain_committed_and_do_not_fit_or_normalize(self):
        rows = records()
        excluded = row(99, features=[99999., 0.], history=[[99999., 0.]], outcome_status="right_censored",
                       time_status="unobserved", cost_status="unknown", outcome_quality=None,
                       duration_seconds=None, action_cost=None)
        model, baseline = fit(rows + [excluded]), fit(rows)
        self.assertEqual(model.predict(rows[0]["history"], "slow"), baseline.predict(rows[0]["history"], "slow"))
        self.assertEqual(model.metadata["training"]["excluded_rows"], 1)
        self.assertEqual(model.metadata["training"]["source_counts"], {"fixture": 9})
        np.testing.assert_allclose(model.center, np.concatenate([r["history"] for r in rows]).mean(axis=0))
        self.assertNotEqual(model.metadata["training"]["input_sha256"], baseline.metadata["training"]["input_sha256"])
        invalid = [None, [], [[0., 0.]] * 257, [[0.]], [[True, 0.]], [[float("nan"), 0.]], [[0., 9.]]]
        for history in invalid:
            changed = copy.deepcopy(rows)
            changed[0]["history"] = history
            with self.subTest(history=str(history)[:40]), self.assertRaises(ValueError):
                fit(changed)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            model.predict(rows[0]["history"], "unseen")

    def test_checkpoint_exact_readback_and_resume(self):
        rows = records()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gru.json"
            model = fit(rows, epochs=7)
            digest = model.save(path)
            restored = ObservedGRU.load(path, expected_sha256=digest)
            self.assertEqual(restored.save(path.with_name("copy.json")), digest)
            self.assertEqual(restored.predict(rows[0]["history"], "slow"), model.predict(rows[0]["history"], "slow"))
            with self.assertRaises(FileExistsError):
                model.save(path)
            with self.assertRaisesRegex(ValueError, "SHA256"):
                ObservedGRU.load(path, expected_sha256="0" * 64)
            with self.assertRaisesRegex(ValueError, "identity differs"):
                restored.continue_fit(list(reversed(rows)), epochs=1)
            restored.continue_fit(rows, epochs=9)
            whole = fit(rows, epochs=16)
            for state in ("params", "m", "v"):
                for key, value in getattr(whole.kernel, state).items():
                    np.testing.assert_array_equal(value, getattr(restored.kernel, state)[key])
            self.assertEqual(restored.loss_history, whole.loss_history)
            self.assertEqual(restored.predict(rows[0]["history"], "slow"), whole.predict(rows[0]["history"], "slow"))
            self.assertEqual(restored.metadata["history_step_presentations"], 16 * sum(len(r["history"]) for r in rows))

    def test_rehashed_corruption_cannot_bypass_shapes_sources_and_ledgers(self):
        mutations = [(("metadata", "learning_rate"), 0), (("metadata", "optimizer_calls"), 1),
                     (("metadata", "sample_presentations"), 1), (("metadata", "history_step_presentations"), 1),
                     (("metadata", "training", "complete_case_rows"), 7),
                     (("metadata", "training", "input_rows"), 9),
                     (("metadata", "training", "input_history_steps"), 999),
                     (("metadata", "training", "history_length_counts"), {"1": 8}),
                     (("metadata", "training", "task_groups_sha256"), "0" * 64),
                     (("metadata", "training", "input_sha256"), "not-a-digest"),
                     (("metadata", "training", "exclusion_reason_counts"), {"cost_unknown": 1}),
                     (("metadata", "training", "missingness_bias_corrected"), True),
                     (("metadata", "provenance_authenticated"), True),
                     (("metadata", "source_sha256", "models.py"), "0" * 64),
                     (("parameters", "Wz"), [[0.]]), (("parameters", "by"), ["nan", 0., 0.]),
                     (("optimizer", "v", "by"), [-1., 0., 0.]), (("residuals", "fast"), [])]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gru.json"
            fit(records(), epochs=2).save(path)
            original = json.loads(path.read_bytes())
            for index, (keys, value) in enumerate(mutations):
                data = copy.deepcopy(original)
                target = data["payload"]
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                data["payload_sha256"] = _digest(data["payload"])
                encoded = _canonical(data)
                broken = path.with_name(f"corrupt-{index}.json")
                broken.write_bytes(encoded)
                with self.subTest(keys=keys), self.assertRaises(ValueError):
                    ObservedGRU.load(broken, expected_sha256=sha256(encoded).hexdigest())
