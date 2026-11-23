import unittest

import torch

from .adapt import (
    FitConfig, IncumbentFailure, data_arrays, fit_arm, nonlinear_screen,
    predict, screen_target_pair, solve_readout, training_diagnostics,
)


class ConditionalComparison(unittest.TestCase):
    def setUp(self):
        self.x = torch.linspace(-1.5, 1.5, 18, dtype=torch.float64)
        self.y = torch.stack((self.x.sin(), self.x ** 2, self.x.tanh()), 1)
        self.train = {"targets": self.y, "x": self.x}
        self.dev = {"targets": self.y.clone(), "x": self.x.clone()}
        self.theta = torch.tensor([0.21, -0.08], dtype=torch.float64)
        self.cfg = FitConfig(steps=3)

    @staticmethod
    def feats(theta, batch):
        x = batch["x"]
        return torch.stack(((x * (1 + theta[0])).tanh(), (x - theta[1]) ** 2), 1)

    def score(self, t, head):
        pred = predict(self.feats(t, self.dev), head)
        return -float((pred - self.y).square().mean()), True

    def test_centered_solution_and_profiled_gradient(self):
        def cost(theta):
            h, y, w = data_arrays(self.feats(theta, self.train), self.train)
            head, _ = solve_readout(h.detach(), y, w, self.cfg.ridge)
            residual = predict(h, head) - y
            self.assertTrue(torch.allclose(w @ residual, torch.zeros_like(y[0]), atol=1e-14))
            self.assertTrue(torch.allclose(h.detach().T @ (w[:, None] * residual.detach()) +
                                          self.cfg.ridge * head[:-1], torch.zeros_like(head[:-1]), atol=1e-14))
            return w @ residual.square().sum(1) + self.cfg.ridge * head[:-1].square().sum()

        x = self.theta.detach().requires_grad_()
        gradient = torch.autograd.grad(cost(x), x)[0]
        for i in range(len(x)):
            delta = torch.zeros_like(x)
            delta[i] = 1e-5
            fd = (cost(x.detach() + delta) - cost(x.detach() - delta)) / (2 * delta[i])
            self.assertAlmostEqual(float(fd), float(gradient[i]), places=8)

    def test_bp_counters_and_radius(self):
        result = fit_arm("bp", self.theta, self.feats, self.train, self.dev,
                         config=self.cfg, score=self.score)
        self.assertEqual(len(result.report["attempts"]), 4)
        self.assertEqual(result.report["cost"]["backward_calls"], 3)
        self.assertEqual(result.report["cost"]["dev_score_calls"], 4)
        self.assertLessEqual(max(r["edit_norm"] for r in result.report["attempts"]), self.cfg.radius + 1e-12)

    def test_editor_refit_and_keep_on_tie_or_rejection(self):
        def edits(t, d):
            self.assertFalse(torch.is_grad_enabled())
            self.assertEqual(d["split"], "TRAIN")
            self.assertNotIn("dev", d)
            return [
                dict(name="tie", theta=t + .01, rationale="same utility"),
                dict(name="rejected", theta=t + .03, rationale="fails retention"),
                dict(name="radius", theta=t + 2, rationale="invalid parameter change"),
            ]

        def score(t, h):
            return (4, False) if torch.max(t - self.theta) > 0.02 else (1, True)

        out = fit_arm("wsp", self.theta, self.feats, self.train, self.dev,
                      score=score, config=self.cfg, editor=edits)
        self.assertEqual(out.report["selected_index"], 0)
        self.assertEqual(out.report["cost"]["backward_calls"], 0)
        self.assertEqual(out.report["cost"]["dev_score_calls"], 3)
        self.assertEqual(len(out.report["errors"]), 1)

    def test_forward_probes_have_separate_budget_and_no_backward(self):
        seen = []
        def builder(theta, diag, probe):
            self.assertFalse(torch.is_grad_enabled())
            self.assertEqual(diag["rows"]["scores"].shape, self.y.shape)
            for j in range(2):
                v = theta.clone()
                v[j] += 0.1
                measured = probe(v)
                self.assertEqual(measured["scores"].shape, self.y.shape)
                self.assertFalse(measured["scores"].requires_grad)
                seen.append(v)
            return [dict(name="assembled", theta=(seen[0]+seen[1])/2, rationale="joint proposed edit")]

        builder.uses_train_probes = True
        out = fit_arm("wsp", self.theta, self.feats, self.train, self.dev,
                      score=self.score, config=self.cfg, editor=builder)
        self.assertEqual(out.report["errors"], [])
        self.assertEqual(len(out.report["editor_probes"]), 2)
        self.assertEqual(out.report["cost"]["train_feature_calls"], 5)
        self.assertEqual(out.report["cost"]["dev_score_calls"], 2)
        self.assertEqual(out.report["cost"]["backward_calls"], 0)
        self.assertEqual(out.report["editor_probes"][0]["score_matrix_shape"], [18,3])

    def test_terminal_wait_exclusion_from_train_rank_screen(self):
        s = {"targets": torch.tensor([[0., 0., 1.], [0., 0., -1.]], dtype=torch.float64),
             "dt": torch.ones((2,1)), "x": torch.tensor([-1., 1.], dtype=torch.float64)}
        d = training_diagnostics(self.theta, self.feats, s)
        self.assertIsNone(d["target_pair"])

    def test_bad_incumbent_records_failure(self):
        def broken(t, h):
            raise ValueError("unavailable development utility")
        with self.assertRaises(IncumbentFailure) as raised:
            fit_arm("bp", self.theta, self.feats, self.train, self.dev, score=broken)
        self.assertEqual(raised.exception.report["cost"]["dev_score_calls"], 1)
        self.assertIn("unavailable", raised.exception.report["errors"][0])

    def test_exact_and_local_obstructions_are_distinct(self):
        h = torch.tensor([[1.], [1.]], dtype=torch.float64)
        y = torch.tensor([[1., 0.], [0., 1.]], dtype=torch.float64)
        score = torch.zeros_like(y)
        strict = screen_target_pair(h, y, score, (0, 1, 0, 1))
        self.assertTrue(strict["head_only_structural_contradiction"])
        near = screen_target_pair(h + torch.tensor([[0.], [0.001]]), y, score,
                                  (0, 1, 0, 1), margin=0.1, head_radius=1.)
        self.assertTrue(near["excluded_at_supplied_readout_radius"])
        self.assertFalse(near["head_only_structural_contradiction"])
        t = torch.zeros(1, dtype=torch.float64)
        split = {"targets": y, "complete_input_prefix_ids": ["L", "R"]}
        # At theta=0 the local derivative vanishes although some nonzero edits separate the rows.
        screen = nonlinear_screen(t, lambda v, _: h + v[0]**2 * h.new_tensor([[1.], [-1.]]), split)
        self.assertTrue(screen["pair"]["head_only_structural_contradiction"])
        self.assertEqual(screen["local_fixed_head_contrast_jacobian"], [0.])
        self.assertFalse(screen["identical_complete_input_prefix"])

    def test_costed_diagnostics_are_train_only(self):
        diag = training_diagnostics(self.theta, self.feats, self.train)
        self.assertEqual(diag["target_rows"], 18)
        self.assertEqual(diag["dimensions"], 2)
        self.assertEqual(diag["vjp_calls"], 0)
        self.assertEqual(diag["feature_calls"], 1)


if __name__ == "__main__":
    unittest.main()
