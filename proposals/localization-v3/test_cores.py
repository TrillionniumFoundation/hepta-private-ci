"""Causality, actual shared components and exact-event derivative checks."""

import os
import math
import unittest

import torch
from cores import CoreStudyModel, event_lif_step, explicit_hcsn_grid

TEST_GRID = {
    "active_cells": 8,
    "endpoint": 2.4,
    "phase_cells": 4,
    "refractory": 0.2,
    "tail_rate": 1.0,
    "quadrature_order": 8,
    "initial_log_std": 0.08,
}


class CommonCoreTests(unittest.TestCase):
    def test_same_frontend_and_head_across_different_constructor_rng(self):
        models = [
            CoreStudyModel(
                arm, width=4, seed=13, hcsn_grid=TEST_GRID if arm == "hcsn" else None
            )
            for arm in ("gru", "attention", "event_time_lif", "hcsn")
        ]
        self.assertEqual(len({m.initial_frontend_sha256 for m in models}), 1)
        self.assertEqual(len({m.initial_head_sha256 for m in models}), 1)
        self.assertNotEqual(
            models[0].initial_head_sha256,
            CoreStudyModel("gru", width=4, seed=17).initial_head_sha256,
        )

    def test_hcsn_requires_complete_geometry_and_accounts_for_content_state(self):
        from dataclasses import asdict

        model = CoreStudyModel("hcsn", width=4, seed=13, hcsn_grid=TEST_GRID)
        self.assertEqual(asdict(model.core.network.layers[0].grid), TEST_GRID)
        state = model.core.network.initial_state(2).layers[0]
        self.assertEqual(tuple(state.probability.shape), (2, 13))
        self.assertEqual(tuple(state.content_mass.shape), (2, 13, 4))
        self.assertEqual(
            model.core.cost_geometry["state_payload_fp64_bytes_per_sample"], 13 * 5 * 8
        )
        for invalid in (
            None,
            {"active_cells": 128},
            {**TEST_GRID, "unused": 0},
            {**TEST_GRID, "active_cells": True},
            {**TEST_GRID, "endpoint": float("nan")},
        ):
            with self.subTest(configuration=invalid), self.assertRaises(ValueError):
                explicit_hcsn_grid(invalid)
        with self.assertRaises(ValueError):
            CoreStudyModel("gru", hcsn_grid=TEST_GRID)

    def test_frozen_cache_matches_transport_and_learned_gradients_and_clears_on_restore(
        self,
    ):
        models = [
            CoreStudyModel(
                "hcsn", width=4, seed=29, hcsn_grid=TEST_GRID, cache_frozen_tables=cache
            )
            for cache in (False, True)
        ]
        generator = torch.Generator().manual_seed(41)
        features = torch.randn(2, 4, 4, generator=generator, dtype=torch.float64)
        dt = torch.tensor(
            [[0, 0.02, 0.02, 0.04], [0.02, 0.04, 0.02, 0.04]], dtype=torch.float64
        )
        outputs = []
        for model in models:
            network = model.core.network
            output = network(
                features, dt, state=network.initial_state(2), return_trace=True
            )
            (
                output.predictions.square().sum()
                + output.state.layers[0].content_mass.square().sum()
            ).backward()
            outputs.append(output)
        for left, right in zip(outputs[0].trace, outputs[1].trace):
            for name in ("probability", "content_mass", "expected_events", "channels"):
                torch.testing.assert_close(
                    left[0][name], right[0][name], rtol=0, atol=0
                )
        torch.testing.assert_close(
            outputs[0].predictions, outputs[1].predictions, rtol=0, atol=0
        )
        for (name, left), (other, right) in zip(
            models[0].named_parameters(), models[1].named_parameters()
        ):
            self.assertEqual(name, other)
            if left.requires_grad:
                # Shared frozen frontend/head are absent from this network call.
                self.assertIsNotNone(left.grad)
                torch.testing.assert_close(left.grad, right.grad, rtol=0, atol=0)
        operator = models[1].core.network.layers[0].operator
        self.assertGreater(operator.cache_receipt()["hits"], 0)
        self.assertEqual(operator.cache_receipt()["entries"], 3)
        models[1].load_state_dict(models[0].state_dict())
        self.assertEqual(operator.cache_receipt()["entries"], 0)
        self.assertEqual(operator.cache_receipt()["resident_table_tensor_bytes"], 0)
        p = models[1].core.network.layers[0].physics()

        def table(duration, mu=None):
            return operator(
                p.log_boundary,
                p.mu if mu is None else mu,
                p.sigma,
                p.absolute_reset,
                duration,
                p.discount,
            )

        table(0.02)
        table(math.nextafter(0.02, 0.03))
        self.assertEqual(operator.cache_receipt()["entries"], 2)
        table(0.02, p.mu + 0.001)
        self.assertEqual(operator.cache_receipt()["entries"], 3)
        with self.assertRaisesRegex(ValueError, "differentiable physics"):
            table(0.02, p.mu.detach().requires_grad_(True))

    def test_causal_prefix_and_connected_common_parameters(self):
        generator = torch.Generator().manual_seed(23)
        x = torch.randn(2, 5, 25, generator=generator, dtype=torch.float64)
        dt = torch.full((2, 5), 0.02, dtype=torch.float64)
        for arm in ("gru", "attention", "event_time_lif", "cfc", "snn_plif", "ssm_s4d"):
            with self.subTest(arm=arm):
                model = CoreStudyModel(
                    arm, width=4, seed=13, s4_repo=os.environ.get("HCSN_S4_REPO")
                )
                original = model(x, dt)
                changed = x.clone()
                changed[:, 3:] += 7
                torch.testing.assert_close(
                    original[:, :3], model(changed, dt)[:, :3], atol=1e-11, rtol=1e-10
                )
                original.square().sum().backward()
                self.assertTrue(
                    all(
                        p.grad is not None and bool(torch.isfinite(p.grad).all())
                        for p in model.parameters()
                        if p.requires_grad
                    )
                )

    def test_exact_lif_multiple_events_and_gradient(self):
        dtype = torch.float64
        current = torch.tensor([2.0], dtype=dtype, requires_grad=True)
        tau = torch.tensor([0.1], dtype=dtype)
        trace_tau = torch.tensor([0.3], dtype=dtype)
        duration = torch.tensor([0.24], dtype=dtype)
        voltage, trace, count = event_lif_step(
            torch.zeros_like(current),
            torch.zeros_like(current),
            current,
            duration,
            tau,
            trace_tau,
        )
        self.assertEqual(int(count), 3)
        event_times = (
            tau * torch.log(current / (current - 1)) * torch.arange(1, 4, dtype=dtype)
        )
        torch.testing.assert_close(
            trace, torch.exp(-(duration - event_times) / trace_tau).sum().reshape(1)
        )
        gradient = torch.autograd.grad(voltage + trace, current)[0]
        epsilon = 1e-6
        values = []
        for sign in (-1, 1):
            v, r, c = event_lif_step(
                torch.zeros_like(current),
                torch.zeros_like(current),
                current.detach() + sign * epsilon,
                duration,
                tau,
                trace_tau,
            )
            self.assertEqual(int(c), 3)
            values.append(v + r)
        torch.testing.assert_close(
            gradient, (values[1] - values[0]) / (2 * epsilon), atol=1e-8, rtol=1e-7
        )

    def test_exact_lif_no_spike_and_zero_interval(self):
        current = torch.tensor([0.7, 2.0], dtype=torch.float64)
        zero = torch.zeros_like(current)
        tau = torch.full_like(current, 0.1)
        for dt in (zero, torch.tensor([0.1, 0.01], dtype=torch.float64)):
            voltage, trace, count = event_lif_step(zero, zero, current, dt, tau, tau)
            torch.testing.assert_close(voltage, current * (-torch.expm1(-dt / tau)))
            torch.testing.assert_close(trace, zero)
            torch.testing.assert_close(count, zero)

    def test_exact_lif_all_smooth_parameters_and_large_current_rejection(self):
        values = tuple(
            torch.tensor([value], dtype=torch.float64, requires_grad=True)
            for value in (0.2, 0.3, 2.1, 0.25, 0.13, 0.31)
        )

        def readout(*args):
            voltage, trace, _ = event_lif_step(*args)
            return torch.cat((voltage, trace))

        self.assertTrue(
            torch.autograd.gradcheck(readout, values, eps=1e-6, atol=1e-6, rtol=1e-5)
        )
        with self.assertRaisesRegex(FloatingPointError, "declared numeric domain"):
            event_lif_step(
                values[0],
                values[1],
                torch.tensor([1e16], dtype=torch.float64),
                *values[3:],
            )

    def test_frozen_shared_weights_remain_bitwise_identical_after_update(self):
        from cores import tensor_digest

        model = CoreStudyModel("gru", width=4, seed=13)
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad], lr=0.01
        )
        x = torch.ones(1, 4, 25, dtype=torch.float64)
        dt = torch.full((1, 4), 0.02, dtype=torch.float64)
        model(x, dt).square().sum().backward()
        optimizer.step()
        self.assertEqual(tensor_digest(model.frontend), model.initial_frontend_sha256)
        self.assertEqual(tensor_digest(model.head), model.initial_head_sha256)

    def test_uniform_identity_adapter_preserves_initial_output_and_then_learns(self):
        from cores import tensor_digest

        x = torch.ones(1, 4, 25, dtype=torch.float64)
        dt = torch.full((1, 4), 0.02, dtype=torch.float64)
        identities = []
        for arm in (
            "gru",
            "cfc",
            "snn_plif",
            "event_time_lif",
            "ssm_s4d",
            "attention",
            "hcsn",
        ):
            with self.subTest(arm=arm):
                options = dict(
                    width=4,
                    seed=13,
                    s4_repo=os.environ.get("HCSN_S4_REPO"),
                    hcsn_grid=TEST_GRID if arm == "hcsn" else None,
                )
                original = CoreStudyModel(arm, **options)
                adapted = CoreStudyModel(arm, learn_core_adapter=True, **options)
                identities.append(tensor_digest(adapted.temporal_adapter))
                # The extra identity matmul can change a strided S4D output's
                # layout and hence last-bit GEMM reduction order in the head.
                torch.testing.assert_close(
                    original(x, dt), adapted(x, dt), rtol=1e-13, atol=1e-14
                )
                optimizer = torch.optim.AdamW(
                    [p for p in adapted.parameters() if p.requires_grad], lr=0.01
                )
                adapted(x, dt).square().sum().backward()
                optimizer.step()
                self.assertNotEqual(
                    tensor_digest(adapted.temporal_adapter), identities[-1]
                )
                self.assertEqual(
                    tensor_digest(adapted.frontend), adapted.initial_frontend_sha256
                )
                self.assertEqual(
                    tensor_digest(adapted.head), adapted.initial_head_sha256
                )
        self.assertEqual(len(set(identities)), 1)

    def test_effective_batch_weighted_loss_gradients_and_step_match_micro_accumulation(
        self,
    ):
        from hcsn_study_support import backward_effective_batch

        generator = torch.Generator().manual_seed(71)
        x = torch.randn(4, 4, 25, generator=generator, dtype=torch.float64)
        dt = torch.full((4, 4), 0.02, dtype=torch.float64)
        y = torch.tensor([[0, 1, 2, 2], [3, 1, 1, -1], [2, 0, -1, -1], [1, 3, 0, 1]])
        x[y < 0] = 0
        dt[y < 0] = 0
        weights = torch.linspace(0.2, 2.0, 11, dtype=torch.float64)
        for arm in ("gru", "hcsn"):
            with self.subTest(arm=arm):
                options = dict(
                    width=4,
                    seed=79,
                    learn_core_adapter=True,
                    hcsn_grid=TEST_GRID if arm == "hcsn" else None,
                    cache_frozen_tables=arm == "hcsn",
                )
                full, micro = (
                    CoreStudyModel(arm, **options),
                    CoreStudyModel(arm, **options),
                )
                optimizers = [
                    torch.optim.AdamW(
                        [p for p in m.parameters() if p.requires_grad],
                        lr=0.003,
                        weight_decay=0,
                    )
                    for m in (full, micro)
                ]
                logits = full(x, dt)
                loss = torch.nn.functional.cross_entropy(
                    logits[y >= 0], y[y >= 0], weight=weights
                )
                loss.backward()
                receipt = backward_effective_batch(
                    micro, x, dt, y, weights, micro_batch_size=2
                )
                self.assertAlmostEqual(float(loss.detach()), receipt["loss"], places=13)
                self.assertEqual(receipt["micro_forward_calls"], 2)
                for left, right in zip(full.parameters(), micro.parameters()):
                    if left.requires_grad:
                        self.assertIsNotNone(left.grad)
                        torch.testing.assert_close(
                            left.grad, right.grad, atol=1e-12, rtol=1e-10
                        )
                for model, optimizer in zip((full, micro), optimizers):
                    torch.nn.utils.clip_grad_norm_(
                        [p for p in model.parameters() if p.requires_grad], 1.0
                    )
                    optimizer.step()
                for left, right in zip(full.parameters(), micro.parameters()):
                    torch.testing.assert_close(left, right, atol=1e-11, rtol=1e-10)


if __name__ == "__main__":
    torch.set_num_threads(1)
    unittest.main()
