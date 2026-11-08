"""Finite-v4 planner contracts; the full training/native entry is diagnostic.py."""

from dataclasses import replace
import unittest

import torch

from scripts.joint_generation_v4_codecs import commit_mean, flush_mean
from scripts.joint_generation_v4_gradients import fixture, frozen_copy
from scripts.joint_generation_v4_ndu import choose, live_state, loss_terms


class FiniteV4Tests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.generator, self.public, self.owner = fixture()

    def test_fair_cap_budget_and_repeatability(self):
        with torch.no_grad():
            state = live_state(self.generator, self.public)
            first = choose(self.generator, state, self.owner, self.public)
            second = choose(self.generator, state, self.owner, self.public)
            torch.testing.assert_close(first.scores, second.scores, rtol=0, atol=0)
            self.assertEqual(
                (first.action, first.trace_sha256), (second.action, second.trace_sha256)
            )
            self.assertTrue(all(first.scored))
            self.assertLessEqual(first.forecasts, 32)
            self.assertTrue(first.exhausted)
            with self.assertRaisesRegex(ValueError, "No affordable"):
                choose(
                    self.generator,
                    state,
                    replace(self.owner, budget_remaining=999),
                    self.public,
                )
            bounded = choose(
                self.generator,
                state,
                replace(self.owner, budget_remaining=1000),
                self.public,
            )
            self.assertEqual(bounded.forecasts, 7)
            self.assertTrue(all(bounded.scored))

    def test_stop_flushes_required_and_started_optional(self):
        with torch.no_grad():
            state = live_state(self.generator, self.public)
            owner = replace(self.owner, required_mask=8, optional_mask=1)
            state, owner, _ = commit_mean(self.generator, state, owner, 0, 1)
            stopped = self.generator.advance(state, "stop", self.public)
            stopped, final, _ = flush_mean(self.generator, stopped, owner)
            self.assertEqual(final.cursors, (16, 0, 0, 128))
            self.assertEqual(stopped.text_units, 128)
            self.assertEqual(len(final.committed[3].decode("utf-8")), 128)

    def test_frozen_evaluator_retains_live_core_and_text_gradients(self):
        reference = frozen_copy(self.generator)
        terms, _ = loss_terms(self.generator, reference, self.public, self.owner)
        parameters = (
            self.generator.core.layers[0].drift_bias,
            self.generator.text_recurrent.weight,
            self.generator.token_encoder.weight,
        )
        for name in ("recursive", "policy"):
            derivatives = torch.autograd.grad(
                terms[name], parameters, retain_graph=True
            )
            self.assertTrue(
                all(
                    bool(torch.isfinite(value).all())
                    and float(value.abs().max()) > 1e-12
                    for value in derivatives
                )
            )
        self.assertTrue(
            all(
                parameter.grad is None and not parameter.requires_grad
                for parameter in reference.parameters()
            )
        )


if __name__ == "__main__":
    unittest.main()
