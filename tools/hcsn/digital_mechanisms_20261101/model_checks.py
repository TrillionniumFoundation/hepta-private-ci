"""Mechanism contracts and cell-only recoverability diagnostics (no efficacy gate)."""
import copy
import json
import unittest

import numpy as np
import torch

from ..digital_read_before_20261031.model import FAMILIES
from ..digital_read_before_20261031.task import initial, successor
from .models import MechanismPolicy, accumulator_features, transition_context


def fixture():
    return dict(schema="digital-read-before-public-v1", id="mechanism-fixture", deadline=6, initial_budget=3,
                duration=[.25, .5, 1., .5, .25, 1.5], reliability=[.85] * 6,
                read_price=[.02] * 6, read_delay=[2] * 6, latency_price=.01,
                repair_price=.03, failure_probability=.1,
                packets=[f"p{i}.json" for i in range(6)], packet_sha256=["0" * 64] * 6)


def belief_information(class0, class1):
    """Optimal decoder of true class under balanced prior, optionally selected."""
    a, b = np.asarray(class0), np.asarray(class1)
    weight = a + b
    total = float(weight.sum())
    if total < 1e-14:
        return None
    return dict(selected_probability=total / 2,
                optimal_accuracy=float(np.maximum(a, b).sum() / total),
                optimal_brier=float(np.divide(a * b, weight, out=np.zeros_like(weight), where=weight > 0).sum() / total))


def retention_diagnostics(fit=101):
    """One noisy READ sign, balanced hidden label; reveal only finite cell state.

    Last-symbol public features reveal the original observation directly and are
    deliberately excluded here. These are model mechanism probes, not new task
    samples or an attribution of fitted-policy utility.
    """
    result = []
    for family in ("ordinary_bank", "clocked_bank", "first_passage_bank"):
        for drive in ("sustained", "impulse"):
            policy = MechanismPolicy(family, fit, drive_mode=drive)
            with torch.no_grad():
                signs = []
                for sign in (-1., 1.):
                    mass = policy.initial_mass()
                    if drive == "impulse":
                        mass = mass @ policy.impulse_matrix(sign, .85)
                    signs.append(mass)
                for horizon, dt in ((0., 0.), (.25, .25), (.75, .5), (1.5, .75), (3., 1.5)):
                    if dt:
                        signs = [mass @ policy.transition_for_context(dict(dt=dt, symbol=sign, reliability=.85))[0]
                                 for mass, sign in zip(signs, (-1., 1.))]
                    y0, y1 = [x.numpy() for x in signs]
                    c0, c1 = .85 * y0 + .15 * y1, .15 * y0 + .85 * y1
                    reset = policy.cell.reset_distributions().numpy()
                    merged0 = np.r_[c0[:15], c0[15:].sum()]
                    merged1 = np.r_[c1[:15], c1[15:].sum()]
                    same_reset = np.repeat(reset.mean(0, keepdims=True), 2, axis=0)
                    result.append(dict(family=family, drive=drive, horizon=horizon,
                                       full_cell=belief_information(c0, c1),
                                       active_only=belief_information(c0[:15], c1[:15]),
                                       event_sign_only=belief_information(c0[15:], c1[15:]),
                                       event_sign_removed=belief_information(merged0, merged1),
                                       forced_reset=belief_information(c0[15:] @ reset, c1[15:] @ reset),
                                       equal_reset=belief_information(c0[15:] @ same_reset, c1[15:] @ same_reset),
                                       public_observation_optimal_accuracy=.85,
                                       scope="Cell-only one-observation information; finite-grid projection; no task benefit claim"))
    return result


class ModelChecks(unittest.TestCase):
    def test_structured_head_pairing_and_terminal_order(self):
        x = torch.randn(13, 48, dtype=torch.float64, generator=torch.Generator().manual_seed(12))
        for family in FAMILIES:
            free = MechanismPolicy(family, 101, terminal_mode="free")
            structured = MechanismPolicy(family, 101)
            a, b = free(x), structured(x)
            self.assertTrue(torch.equal(free.linear1.weight, structured.linear1.weight))
            self.assertTrue(torch.equal(free.linear2.weight[[1, 2, 3, 6]], structured.linear2.weight))
            self.assertTrue(torch.allclose(a[:, [1, 2, 3, 6]], b[:, [1, 2, 3, 6]], atol=2e-15, rtol=0))
            self.assertTrue(torch.equal(b[:, 0], torch.zeros(13, dtype=torch.float64)))
            self.assertTrue(torch.equal(b[:, 4], -b[:, 5]))
            self.assertTrue(torch.equal(b[:, 5], 2 * torch.sigmoid(b[:, 6]) - 1))
            self.assertTrue(torch.equal(b[:, [4, 5]].argmax(-1), (b[:, 6] > 0).long()))

    def test_terminal_extremes_and_belief_gradient(self):
        p = MechanismPolicy("raw_history", 103)
        x = torch.zeros(1, 48, dtype=torch.float64)
        for logit in (-1000., -1., 0., 1., 1000.):
            with torch.no_grad():
                p.linear2.weight[3].zero_()
                p.linear2.bias[3] = logit
            output = p(x)[0]
            self.assertTrue(bool(torch.isfinite(output).all()))
            self.assertGreaterEqual(float(output[4:6].max().detach()), 0.)
        with torch.no_grad():
            p.linear2.bias[3] = .7
        p.zero_grad()
        p(x)[0, 5].backward()
        expected = 2 * torch.sigmoid(torch.tensor(.7)) * (1 - torch.sigmoid(torch.tensor(.7)))
        self.assertAlmostEqual(float(p.linear2.bias.grad[3]), float(expected), places=7)

    def test_completion_injects_once_after_delayed_read(self):
        public = fixture()
        s0 = initial(public)
        s1 = successor(public, s0, 2)
        s2 = successor(public, s1, 1, dict(observation=1))
        s3 = successor(public, s2, 1)
        contexts = [transition_context(public, a, b) for a, b in ((s0, s1), (s1, s2), (s2, s3))]
        self.assertEqual([c["injection_symbol"] for c in contexts], [0., 1., 0.])
        failed = successor(public, s1, 1, dict(failure=True))
        self.assertEqual(transition_context(public, s1, failed)["injection_symbol"], 0.)
        with self.assertRaises(ValueError):
            transition_context(public, s0, s2)

    def test_wait_does_not_repeat_impulse_evidence(self):
        neutral = dict(dt=.75, symbol=0., reliability=.5)
        remembered = dict(dt=.75, symbol=1., reliability=.85)
        for family in ("ordinary_bank", "clocked_bank", "first_passage_bank"):
            pulse = MechanismPolicy(family, 107, drive_mode="impulse")
            old = MechanismPolicy(family, 107, drive_mode="sustained")
            self.assertTrue(torch.equal(pulse.transition_for_context(neutral)[0], pulse.transition_for_context(remembered)[0]))
            self.assertGreater(float((old.transition_for_context(neutral)[0] - old.transition_for_context(remembered)[0]).detach().abs().max()), .01)
            t, _ = pulse.transition_for_context(dict(**remembered, injection_symbol=1., injection_reliability=.85))
            self.assertGreater(float((t - pulse.transition_for_context(remembered)[0]).detach().abs().max()), .01)

    def test_impulse_mass_and_refractory_semantics(self):
        p = MechanismPolicy("first_passage_bank", 109, drive_mode="impulse")
        matrix = p.impulse_matrix(1., .85)
        self.assertTrue(torch.allclose(matrix.sum(1), torch.ones(17, dtype=torch.float64), atol=2e-15, rtol=0))
        self.assertGreaterEqual(float(matrix.min().detach()), 0.)
        self.assertTrue(torch.equal(matrix[15:], torch.eye(17, dtype=torch.float64)[15:]))
        positive = p.initial_mass() @ matrix
        self.assertGreater(float((positive[:15] * p.cell.centers_normalized).detach().sum()), 0.)
        before = p.initial_mass() @ p.impulse_matrix(-1., .85)
        self.assertLess(float((before[:15] * p.cell.centers_normalized).detach().sum()), 0.)

    def test_construction_preserves_external_rng(self):
        before = torch.get_rng_state().clone()
        MechanismPolicy("first_passage_bank", 110)
        self.assertTrue(torch.equal(before, torch.get_rng_state()))

    def test_complete_prefix_and_physical_derivative(self):
        p = MechanismPolicy("clocked_bank", 113, drive_mode="impulse")
        prefix = [dict(dt=.25, symbol=0., reliability=.5, injection_symbol=1., injection_reliability=.85),
                  dict(dt=.5, symbol=1., reliability=.85)]
        mass = p.prefix_mass(prefix)
        manual = p.initial_mass()
        for context in prefix:
            manual = manual @ p.transition_for_context(context)[0]
        self.assertTrue(torch.equal(mass, manual))
        payoff = torch.linspace(-1, 1, 17, dtype=torch.float64)
        objective = (mass * payoff).sum()
        gradient = torch.autograd.grad(objective, p.cell.raw)[0][2].item()
        with torch.no_grad():
            raw = p.cell.raw[2].item()
            values = []
            for shift in (-1e-5, 1e-5):
                p.cell.raw[2] = raw + shift
                values.append(float((p.prefix_mass(prefix) * payoff).sum()))
            p.cell.raw[2] = raw
        self.assertAlmostEqual(gradient, (values[1] - values[0]) / 2e-5, places=8)

    def test_accumulator_is_causal_and_time_explicit(self):
        public = fixture()
        state = initial(public)
        p = MechanismPolicy("evidence_accumulator", 127, drive_mode="accumulator")
        before = p.latent_inputs(public, state)
        private = copy.deepcopy(state)
        private["unread_label"] = 1
        self.assertTrue(torch.equal(before, p.latent_inputs(public, private)))
        later = copy.deepcopy(state)
        later["elapsed"] = 2.
        self.assertFalse(np.array_equal(accumulator_features(state), accumulator_features(later)))
        read = copy.deepcopy(state)
        read["history"] = [dict(source_tick=0, observation=1, reliability=.85)]
        self.assertNotEqual(accumulator_features(read)[0], accumulator_features(state)[0])
        self.assertEqual(p.prefix_mass([]).tolist(), [1.])

    def test_ordinary_inactive_input_weights_are_really_zero_gradient(self):
        p = MechanismPolicy("ordinary_bank", 131)
        public, state = fixture(), initial(fixture())
        output = p.latent_outputs(public, state)[:15]
        output.square().sum().backward()
        self.assertTrue(torch.equal(p.linear1.weight.grad[:, 46:], torch.zeros(32, 2, dtype=torch.float64)))
        self.assertEqual(p.capacity_report()["unreachable_refractory_input_weights"], p.linear1.weight.grad[:, 46:].numel())

    def test_export_roundtrip_preserves_outputs_and_transition(self):
        for family, drive in (("first_passage_bank", "impulse"), ("ordinary_bank", "sustained"),
                              ("raw_history", "sustained"), ("evidence_accumulator", "accumulator")):
            p = MechanismPolicy(family, 137, drive_mode=drive)
            restored = MechanismPolicy.from_export(json.loads(json.dumps(p.export())))
            public, state = fixture(), initial(fixture())
            self.assertTrue(torch.equal(p.latent_outputs(public, state), restored.latent_outputs(public, state)))
            context = dict(dt=.5, symbol=-1., reliability=.85, injection_symbol=1., injection_reliability=.65)
            self.assertTrue(torch.equal(p.transition_for_context(context)[0], restored.transition_for_context(context)[0]))

    def test_cell_information_cannot_exceed_observed_information(self):
        for row in retention_diagnostics():
            self.assertLessEqual(row["full_cell"]["optimal_accuracy"], .85 + 1e-12)
            self.assertLessEqual(row["event_sign_removed"]["optimal_accuracy"], row["full_cell"]["optimal_accuracy"] + 1e-12)
            if row["forced_reset"] is not None:
                self.assertLessEqual(row["equal_reset"]["optimal_accuracy"], row["event_sign_only"]["optimal_accuracy"] + 1e-12)


if __name__ == "__main__":
    unittest.main()
