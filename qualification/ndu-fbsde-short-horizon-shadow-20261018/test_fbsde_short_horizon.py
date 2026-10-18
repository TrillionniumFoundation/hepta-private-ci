import unittest

from cell_fast_path_actionir import canonical_digest
from fbsde_short_horizon import FBSDEProblemV1, FBSDEStepReceiptV1, append_verified_step


D, E, F, G, H, I, J = tuple(x * 64 for x in "abcdef") + ("1" * 64,)
ZERO = "0" * 64


def problem(**overrides):
    values = dict(
        problem_id="system2.fbsde.1", state_dim=8, control_dim=4, horizon_steps=3, dt_nanos=1_000_000,
        initial_state_digest=D, terminal_condition_digest=E, driver_digest=F, diffusion_digest=G,
        solver_digest=H, stem_digest=I, cell_digest=J, snapshot_id="snap-1", generation=1,
        step_contraction_ppm=100_000, max_residual_ppm=50, max_step_memory_bytes=1_000,
        max_step_latency_ns=1_000,
    )
    values.update(overrides)
    return FBSDEProblemV1(**values)


def step(p, index, parent, next_state, *, trajectory="traj-1", residual=10, status="succeeded"):
    values = dict(
        problem_digest=p.problem_digest, trajectory_id=trajectory, step_index=index,
        parent_state_digest=parent, next_state_digest=next_state if status == "succeeded" else ZERO,
        y_digest=E if status == "succeeded" else ZERO, z_digest=F if status == "succeeded" else ZERO,
        noise_digest=G, utility_lcb_milli=100, utility_ucb_milli=200, residual_ppm=residual,
        observed_memory_bytes=100 if status == "succeeded" else 0, latency_ns=100 if status == "succeeded" else 0,
        status=status, authority="DENY_ALL", effect_admitted=False,
    )
    return FBSDEStepReceiptV1(receipt_digest=canonical_digest({
        "schema": "hepta.fbsde-step-receipt.v1", **values,
    }), **values)


class FBSDEShortHorizonTests(unittest.TestCase):
    def test_contraction_certificate_is_bounded(self):
        self.assertEqual(problem().contraction_margin_ppm, 700_000)
        with self.assertRaises(ValueError):
            problem(horizon_steps=11, step_contraction_ppm=100_000)

    def test_steps_chain_forward_state_and_finish_at_horizon(self):
        p = problem()
        t = append_verified_step(p, None, step(p, 0, D, E))
        self.assertEqual(t.status, "indeterminate")
        t = append_verified_step(p, t, step(p, 1, E, F))
        t = append_verified_step(p, t, step(p, 2, F, G))
        self.assertEqual(t.status, "succeeded")
        self.assertEqual(t.terminal_state_digest, G)

    def test_parent_or_problem_drift_fails_closed(self):
        p = problem()
        first = append_verified_step(p, None, step(p, 0, D, E))
        with self.assertRaisesRegex(ValueError, "PARENT_STATE"):
            append_verified_step(p, first, step(p, 1, D, F))
        with self.assertRaisesRegex(ValueError, "PROBLEM_DIGEST"):
            append_verified_step(problem(generation=2), None, step(p, 0, D, E))

    def test_budget_and_residual_gates(self):
        p = problem(max_residual_ppm=5)
        with self.assertRaisesRegex(ValueError, "RESIDUAL"):
            append_verified_step(p, None, step(p, 0, D, E, residual=6))
        p = problem(max_step_memory_bytes=10)
        with self.assertRaisesRegex(ValueError, "MEMORY"):
            append_verified_step(p, None, step(p, 0, D, E))

    def test_failed_step_has_no_outputs_and_is_not_admitted(self):
        p = problem()
        failed = step(p, 0, D, E, status="failed")
        with self.assertRaisesRegex(ValueError, "NOT_SUCCESSFUL"):
            append_verified_step(p, None, failed)

    def test_replay_and_receipt_digest_drift_are_rejected(self):
        p = problem()
        first = step(p, 0, D, E)
        t = append_verified_step(p, None, first)
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            append_verified_step(p, t, first)
        bad = step(p, 1, E, F)
        bad = FBSDEStepReceiptV1(**{**bad.__dict__, "receipt_digest": H})
        with self.assertRaisesRegex(ValueError, "RECEIPT_DIGEST"):
            append_verified_step(p, t, bad)

    def test_prior_trajectory_digest_drift_is_rejected(self):
        p = problem()
        first = append_verified_step(p, None, step(p, 0, D, E))
        drifted = type(first)(**{**first.__dict__, "trajectory_digest": H})
        with self.assertRaisesRegex(ValueError, "TRAJECTORY_DIGEST"):
            append_verified_step(p, drifted, step(p, 1, E, F))

    def test_authority_and_effect_are_structurally_denied(self):
        p = problem()
        with self.assertRaises(ValueError):
            problem(authority="OWNER")
        with self.assertRaises(ValueError):
            FBSDEStepReceiptV1(**{**step(p, 0, D, E).__dict__, "effect_admitted": True})
