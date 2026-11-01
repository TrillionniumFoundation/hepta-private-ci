"""Independent development-only sequence-gradient and execution audit.

The finite differences use a separate scalar CE/Q-pi objective and hold actual
world continuation targets fixed. No formal training or confirmation seeds are
used. Run this module with --audit-output to retain the measured checks.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.linalg import expm
from scipy.special import xlogy

from ..unified_cell_r12_20261031.cell import Cell
from ..unified_cell_r12_20261031.task_value import ACTIONS, ExactBeliefDP
from .models import GenericHMM, HXEstimator, ORDINARY_KINDS, RecurrentEstimator, restore, task_loss
from .qpi import encode, policy_alpha
from .task import TaskModel


DEVELOPMENT_SEED = 990173
CE_WEIGHT, Q_WEIGHT = .7, 1.3


def independent_loss(probabilities, teacher, alpha, legal, ce=CE_WEIGHT, q=Q_WEIGHT):
    """Separate scalar summation, avoiding the implementation's einsum loss."""
    total = -ce * float(np.sum(xlogy(teacher, probabilities))) / np.prod(teacher.shape[:-1])
    squared = 0.
    for batch in range(len(probabilities)):
        for time in range(probabilities.shape[1]):
            difference = probabilities[batch, time] - teacher[batch, time]
            for action in np.flatnonzero(legal[batch, time]):
                error = float(np.dot(difference, alpha[batch, time, action]))
                squared += error * error
    return total + q * squared / np.count_nonzero(legal)


def development_fixture():
    histories = (
        (("READ", .15, 0), ("WAIT", .37, None), ("READ", .22, 7),
         ("RESET", .31, None), ("READ", .45, 6), ("READ", .20, 3)),
        (("READ", .21, 7), ("RESET", .12, None), ("READ", .44, 5),
         ("WAIT", .17, None), ("READ", .32, 6), ("READ", .19, 1)),
        (("READ", .18, 2), ("READ", .27, 4), ("WAIT", .33, None),
         ("READ", .36, 6), ("RESET", .13, None), ("READ", .29, 7)),
    )
    world = TaskModel()
    fitted = TaskModel(Cell([.255, .015, 1.3]))
    planner = ExactBeliefDP(fitted, reset_cost=fitted.reset_cost, latency_price=fitted.latency_price)
    inputs = np.zeros((3, 7, 11))
    teacher = np.zeros((3, 7, 40))
    alpha = np.zeros((3, 7, 5, 40))
    legal = np.zeros((3, 7, 5), dtype=bool)
    for batch, history in enumerate(histories):
        actor = GenericHMM(fitted)
        actor.start()
        for time in range(7):
            if time:
                action, duration, token = history[time - 1]
                inputs[batch, time] = encode(token, duration, action == "RESET")
                actor.step(inputs[batch, time])
            teacher[batch, time] = world.posterior(history[:time])
            schedule = () if time == 6 else (.23, .41)
            reads = 0 if time == 4 else 2
            vectors = policy_alpha(world, actor, planner, schedule, reads)
            for action, vector in vectors.items():
                index = ACTIONS.index(action)
                legal[batch, time, index] = True
                alpha[batch, time, index] = vector
    return inputs, teacher, alpha, legal


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_start = hashlib.sha256(Path(__file__).with_name("models.py").read_bytes()).hexdigest()
        cls.inputs, cls.teacher, cls.alpha, cls.legal = development_fixture()
        cls.audit = {"schema": "hcsn-r14-model-gradient-audit-v1",
                     "purpose": "development-only independent correctness checks; not efficacy confirmation",
                     "development_seed": DEVELOPMENT_SEED, "gradient_coordinates": [],
                     "sequence_parity": {}, "fixture": {}}
        for name in ("inputs", "teacher", "alpha", "legal"):
            value = getattr(cls, name)
            cls.audit["fixture"][name] = {"shape": list(value.shape), "sha256": hashlib.sha256(value.tobytes()).hexdigest()}

    def make_model(self, kind):
        if kind == "hx_distribution":
            return HXEstimator(seed=DEVELOPMENT_SEED)
        model = RecurrentEstimator(kind, seed=DEVELOPMENT_SEED, gate_slope=1.7)
        # Nonzero biases make the initial dummy update observable and exercise
        # recurrent/reset-gate derivatives beyond initialization symmetries.
        rng = np.random.default_rng(DEVELOPMENT_SEED + 1)
        for key in model.params:
            if key.startswith("b"):
                model.params[key][:] = rng.normal(0, .06, model.params[key].shape)
        return model

    def check_coordinates(self, model, coordinates, ce=CE_WEIGHT, q=Q_WEIGHT):
        loss, gradient = model.loss_grad(self.inputs, self.teacher, self.alpha, self.legal, ce, q)
        expected = independent_loss(model.forward(self.inputs), self.teacher, self.alpha, self.legal, ce, q)
        self.assertAlmostEqual(loss, expected, places=12)
        for key, index in coordinates:
            parameter = model.params[key]
            original = float(parameter[index])
            step = 1e-5
            try:
                parameter[index] = original + step
                plus = independent_loss(model.forward(self.inputs), self.teacher, self.alpha, self.legal, ce, q)
                parameter[index] = original - step
                minus = independent_loss(model.forward(self.inputs), self.teacher, self.alpha, self.legal, ce, q)
            finally:
                parameter[index] = original
            numerical = (plus - minus) / (2 * step)
            analytical = float(gradient[key][index])
            error = abs(analytical - numerical)
            self.audit["gradient_coordinates"].append(dict(kind=model.kind, parameter=key,
                coordinate=list(index), analytic=analytical, central=numerical, absolute_error=error,
                ce_weight=ce, q_weight=q))
            with self.subTest(kind=model.kind, parameter=key, coordinate=index, ce=ce, q=q):
                self.assertLess(error, 2e-7 + 2e-5 * abs(numerical))

    @staticmethod
    def representative_coordinates(model, names):
        result = []
        for name in names:
            shape = model.params[name].shape
            result.append((name, tuple(0 for _ in shape)))
            result.append((name, tuple(size - 1 for size in shape)))
        return result

    def test_probability_loss_matches_independent_formula(self):
        p = self.make_model("gru").forward(self.inputs)
        loss, _ = task_loss(p, self.teacher, self.alpha, self.legal, CE_WEIGHT, Q_WEIGHT)
        self.assertAlmostEqual(loss, independent_loss(p, self.teacher, self.alpha, self.legal), places=13)

    def test_probability_loss_has_simplex_directional_derivative(self):
        p = self.make_model("gru").forward(self.inputs)
        _, gradient = task_loss(p, self.teacher, self.alpha, self.legal, CE_WEIGHT, Q_WEIGHT)
        direction = np.random.default_rng(DEVELOPMENT_SEED + 2).normal(size=p.shape)
        direction -= direction.mean(-1, keepdims=True)
        step = 1e-6
        numerical = (independent_loss(p + step * direction, self.teacher, self.alpha, self.legal)
                     - independent_loss(p - step * direction, self.teacher, self.alpha, self.legal)) / (2 * step)
        self.assertAlmostEqual(float(np.sum(gradient * direction)), numerical, places=7)

    def test_illegal_action_vectors_do_not_change_loss_or_score(self):
        p = self.make_model("continuous_ssm").forward(self.inputs)
        original = task_loss(p, self.teacher, self.alpha, self.legal, CE_WEIGHT, Q_WEIGHT)
        altered = self.alpha.copy()
        altered[~self.legal] = 10000. * np.arange(40)
        actual = task_loss(p, self.teacher, altered, self.legal, CE_WEIGHT, Q_WEIGHT)
        self.assertEqual(actual[0], original[0])
        np.testing.assert_array_equal(actual[1], original[1])

    def test_q_only_loss_has_finite_disjoint_support_value(self):
        p, target = np.zeros((1, 1, 40)), np.zeros((1, 1, 40))
        p[0, 0, 0], target[0, 0, 1] = 1., 1.
        alpha = np.zeros((1, 1, 2, 40))
        alpha[0, 0, 0, 0], alpha[0, 0, 1, 1] = 1., 1.
        loss, gradient = task_loss(p, target, alpha, np.ones((1, 1, 2)), 0., Q_WEIGHT)
        self.assertAlmostEqual(loss, Q_WEIGHT, places=14)
        np.testing.assert_array_equal(gradient, Q_WEIGHT * (p - target))

    def test_hx_whole_sequence_physical_gradients(self):
        self.check_coordinates(self.make_model("hx_distribution"), [("physical_raw", (i,)) for i in range(2)])

    def test_hx_whole_sequence_emission_row_zero_gradients(self):
        self.check_coordinates(self.make_model("hx_distribution"), [("emission_logits", (0, i)) for i in range(6)])

    def test_hx_whole_sequence_emission_row_one_gradients(self):
        self.check_coordinates(self.make_model("hx_distribution"), [("emission_logits", (1, i)) for i in range(6)])

    def test_hx_emission_row_gauge_derivative_is_zero(self):
        model = self.make_model("hx_distribution")
        _, gradient = model.loss_grad(self.inputs, self.teacher, self.alpha, self.legal, CE_WEIGHT, Q_WEIGHT)
        before = model.forward(self.inputs)
        model.params["emission_logits"] += np.array([[2.3], [-1.7]])
        np.testing.assert_allclose(model.forward(self.inputs), before, atol=1e-13, rtol=0)
        np.testing.assert_allclose(gradient["emission_logits"].sum(1), 0., atol=1e-13, rtol=0)

    def check_stream(self, model):
        expected = model.forward(self.inputs)
        actual = np.empty_like(expected)
        for batch, sequence in enumerate(self.inputs):
            actual[batch, 0] = model.start()
            for time, item in enumerate(sequence[1:], 1):
                actual[batch, time] = model.step(item)
        error = float(np.max(abs(actual - expected)))
        self.audit["sequence_parity"][model.kind] = error
        np.testing.assert_allclose(actual, expected, atol=2e-13, rtol=0)

    def test_hx_start_and_incremental_execution_match_forward(self):
        self.check_stream(self.make_model("hx_distribution"))

    def test_hx_start_refreshes_updated_parameters(self):
        model = self.make_model("hx_distribution")
        model.build_cell()
        model.params["physical_raw"][0] += .2
        actual = model.start()
        expected = model.forward(np.zeros((1, 1, 11)))[0, 0]
        error = float(np.max(abs(actual - expected)))
        self.audit["post_update_start_error"] = error
        np.testing.assert_allclose(actual, expected, atol=1e-13, rtol=0)

    def test_hx_and_generic_hmm_share_matrix_filter(self):
        model = self.make_model("hx_distribution")
        expected = model.forward(self.inputs)
        hmm = GenericHMM(model.cell)
        actual = np.empty_like(expected)
        for batch, sequence in enumerate(self.inputs):
            actual[batch, 0] = hmm.start()
            for time, item in enumerate(sequence[1:], 1):
                actual[batch, time] = hmm.step(item)
        np.testing.assert_allclose(actual, expected, atol=2e-13, rtol=0)
        self.audit["hx_generic_hmm_max_abs_error"] = float(np.max(abs(actual - expected)))

    def test_all_eight_observation_symbols_cover_valid_task_states(self):
        model = self.make_model("hx_distribution")
        inputs = np.zeros((8, 2, 11))
        for token in range(8):
            inputs[token, 1] = encode(token, .29)
        output = model.forward(inputs)
        task = model.cell
        transition = expm(.29 * task.Q)
        independent = np.empty((8, 40))
        for token in range(8):
            row = (task.prior @ transition) * task.E[:, token]
            independent[token] = row / row.sum()
        np.testing.assert_allclose(output[:, 1], independent, atol=2e-13, rtol=0)
        np.testing.assert_allclose(output.sum(-1), 1., atol=1e-13, rtol=0)
        recovery = np.arange(40) % 20 >= 16
        self.assertAlmostEqual(float(output[6, 1, recovery].sum()), 1., places=13)
        self.assertGreater(float(output[7, 1, 20:].sum()), task.fault_probability)

    def test_gru_input_and_recurrent_matrix_gradients(self):
        model = self.make_model("gru")
        self.check_coordinates(model, self.representative_coordinates(model, ["Wz", "Uz", "Wr", "Ur", "Wn", "Un"]))

    def test_gru_output_and_bias_gradients(self):
        model = self.make_model("gru")
        self.check_coordinates(model, self.representative_coordinates(model, ["Wo", "bo", "bz", "br", "bn"]))

    def test_continuous_ssm_all_parameter_families(self):
        model = self.make_model("continuous_ssm")
        self.check_coordinates(model, self.representative_coordinates(model, model.params))

    def test_dual_head_all_parameter_families(self):
        model = self.make_model("dual_head")
        self.check_coordinates(model, self.representative_coordinates(model, model.params))
        self.check_coordinates(model, [("Wo", (3, 20)), ("bo", (20,))])

    def test_matched_slope_all_parameter_families(self):
        model = self.make_model("matched_slope")
        self.check_coordinates(model, self.representative_coordinates(model, model.params))

    def test_all_ordinary_initial_and_incremental_states_match_forward(self):
        for kind in ORDINARY_KINDS:
            with self.subTest(kind=kind):
                self.check_stream(self.make_model(kind))

    def test_export_restore_keeps_predictions(self):
        for kind in ("hx_distribution", *ORDINARY_KINDS):
            model = self.make_model(kind)
            prediction = model.forward(self.inputs)
            np.testing.assert_array_equal(restore(model.export()).forward(self.inputs), prediction)

    def test_models_cannot_read_future_inputs(self):
        changed = self.inputs.copy()
        changed[:, 4:] = encode(7, .51)
        for kind in ("hx_distribution", *ORDINARY_KINDS):
            model = self.make_model(kind)
            expected = model.forward(self.inputs)[:, :4]
            np.testing.assert_array_equal(model.forward(changed)[:, :4], expected)
            np.testing.assert_array_equal(model.forward(self.inputs[:, :4]), expected)

    def test_dual_head_always_factorizes_phase_regime_and_bit(self):
        probability = self.make_model("dual_head").forward(self.inputs).reshape(3, 7, 20, 2)
        factored = probability.sum(-1)[..., :, None] * probability.sum(-2)[..., None, :]
        np.testing.assert_allclose(probability, factored, atol=1e-15, rtol=0)
        self.audit["dual_head_factorization_max_error"] = float(np.max(abs(probability - factored)))

    def test_factorization_loses_same_marginal_correlations(self):
        first, second = np.zeros((20, 2)), np.zeros((20, 2))
        first[0, 0] = first[1, 1] = .5
        second[0, 1] = second[1, 0] = .5
        projection = lambda x: x.sum(1)[:, None] * x.sum(0)[None, :]
        np.testing.assert_array_equal(projection(first), projection(second))
        payoff = np.zeros((20, 2))
        payoff[0, 0] = payoff[1, 1] = 1.
        actual_gap = float(np.sum((first - second) * payoff))
        projected_gap = float(np.sum((projection(first) - projection(second)) * payoff))
        self.assertEqual((actual_gap, projected_gap), (1., 0.))
        self.audit["correlation_witness"] = dict(actual_value_gap=actual_gap, factorized_value_gap=projected_gap,
            scope="Representation witness only; not a task efficacy measurement. The dual-head output cannot retain phase/regime-bit correlation.")

    def test_ce_only_and_qpi_only_sequence_gradients(self):
        for ce, q in ((1., 0.), (0., 1.)):
            self.check_coordinates(self.make_model("hx_distribution"), [("physical_raw", (0,)), ("emission_logits", (1, 3))], ce, q)
            self.check_coordinates(self.make_model("gru"), [("Wo", (2, 7)), ("Wn", (9, 3))], ce, q)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-output", type=Path)
    arguments = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ModelTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = ModelTests.audit
    root = Path(__file__).resolve().parents[3]
    source = [Path(__file__).resolve(), *(Path(__file__).with_name(name) for name in ("models.py", "task.py", "qpi.py"))]
    report["source_sha256"] = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source}
    report["models_source_stable_during_audit"] = ModelTests.source_start == hashlib.sha256(Path(__file__).with_name("models.py").read_bytes()).hexdigest()
    report["tests"] = dict(run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                           success=result.wasSuccessful(), failure_details=[dict(test=str(test), traceback=trace) for test, trace in result.failures + result.errors])
    report["gradient_coordinate_count"] = len(report["gradient_coordinates"])
    report["gradient_max_absolute_error"] = max(row["absolute_error"] for row in report["gradient_coordinates"])
    if arguments.audit_output:
        arguments.audit_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.audit_output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    sys.exit(0 if result.wasSuccessful() and report["models_source_stable_during_audit"] else 1)


if __name__ == "__main__":
    main()
