"""Finite reference, evidence denial, Cell and masked-logit research tests."""
import unittest

import numpy as np
import torch

from portfolio import (Budget, CellAsset, PortfolioRejected, cvar90,
                       continuous_direction_step, masked_logit_step,
                       select_shadow_portfolio, verify_shadow_receipt)


def make_asset(name, losses, utility, *, fixed=0., variable=0., cap=4,
               protocol='latent_velocity_v1', domain='frozen-condition-1', payload=None):
    return CellAsset(name, payload or f'payload-{name}', protocol, domain,
                     tuple(losses), utility, variable, fixed, cap)


def solve(base, cells, budget=Budget()):
    return select_shadow_portfolio(base, cells, budget,
                                   calibration_digest='train-calibration-v1',
                                   objective_digest='objective-immutable-v1')


class PortfolioMechanismTests(unittest.TestCase):
    def test_nochange_is_explicit_and_zero_cell_parity(self):
        r = solve([2, 3, 4, 3], [], Budget(grid=4))
        self.assertEqual(r['no_change_ticks'], 4)
        self.assertEqual(r['allocations'], [])
        self.assertEqual(r['authority'], 'DENY_ALL')

    def test_negative_standalone_hedge_can_improve_joint_risk(self):
        a = make_asset('a', [0, 4, 0, 4], .70, cap=2)
        b = make_asset('b', [4, 0, 4, 0], -.05, cap=2)
        base = [3, 3, 3, 3]
        setting = Budget(grid=4, risk_aversion=1., cvar90_limit=5.)
        first = solve(base, [a], setting)
        both = solve(base, [b, a], setting)
        self.assertIn('b', [x['id'] for x in both['allocations']])
        self.assertGreater(both['score'], first['score'])
        self.assertLess(both['variance'], first['variance'])

    def test_fixed_activation_charge_not_scaled_by_tiny_weight(self):
        a = make_asset('a', [2] * 4, .5, fixed=.20, cap=1)
        r = solve([3] * 4, [a], Budget(grid=4, risk_aversion=0))
        self.assertEqual(r['no_change_ticks'], 4)
        self.assertEqual(r['allocations'], [])

    def test_budget_and_tail_constraints_are_hard(self):
        a = make_asset('a', [7] * 4, 5., fixed=.3)
        r = solve([1] * 4, [a], Budget(cost_limit=.15, cvar90_limit=1.5))
        self.assertEqual(r['allocations'], [])
        with self.assertRaises(PortfolioRejected):
            solve([5] * 4, [a], Budget(cvar90_limit=.1))

    def test_reorder_invariant_and_receipt_tamper_rejected(self):
        a = make_asset('a', [0, 4, 0, 4], .7)
        b = make_asset('b', [4, 0, 4, 0], -.05)
        xs = [a, b]
        r = solve([3] * 4, xs)
        self.assertEqual(r, solve([3] * 4, list(reversed(xs))))
        self.assertTrue(verify_shadow_receipt(r, [3] * 4, xs, Budget(),
                                             calibration_digest='train-calibration-v1',
                                             objective_digest='objective-immutable-v1'))
        r['no_change_ticks'] += 1
        with self.assertRaises(PortfolioRejected):
            verify_shadow_receipt(r, [3] * 4, xs, Budget(),
                                  calibration_digest='train-calibration-v1',
                                  objective_digest='objective-immutable-v1')

    def test_duplicate_payload_must_not_fake_diversification(self):
        a = make_asset('a', [0] * 4, 1., payload='identical')
        b = make_asset('other_name', [0] * 4, 1., payload='identical')
        with self.assertRaisesRegex(PortfolioRejected, 'duplicate'):
            solve([2] * 4, [a, b])

    def test_cross_protocol_domain_and_missing_support_rejected(self):
        a = make_asset('a', [0] * 4, 1.)
        b = make_asset('b', [0] * 4, 1., protocol='masked_logits_v1')
        c = make_asset('c', [0] * 4, 1., domain='other-domain')
        for extra in (b, c):
            with self.assertRaises(PortfolioRejected):
                solve([2] * 4, [a, extra])
        with self.assertRaises(PortfolioRejected):
            solve([2] * 4, [make_asset('a', [0] * 3, 1.)])
        with self.assertRaises(PortfolioRejected):
            solve([2] * 4, [a], Budget(grid=0))

    def test_empirical_proxy_not_universally_valid_after_decode(self):
        # Squared error of a mixed latent can differ from the weighted average
        # of standalone squared errors. Never promote proxy risk to raw output.
        y, a, b = 1., 0., 2.
        scalar_proxy = .5 * (a - y) ** 2 + .5 * (b - y) ** 2
        actual_loss = (.5 * a + .5 * b - y) ** 2
        self.assertNotAlmostEqual(scalar_proxy, actual_loss)

    def test_independent_grid_oracle_over_variable_profiles(self):
        # Independent scalar implementation: no call into portfolio._evaluate.
        from itertools import product
        for seed in range(30):
            rng = np.random.default_rng(seed)
            base = rng.uniform(.5, 3, size=9)
            a = make_asset('a', rng.uniform(.2, 4, size=9),
                           float(rng.uniform(-.4, 2)),
                           fixed=.04, variable=.08, cap=2)
            b = make_asset('b', rng.uniform(.2, 4, size=9),
                           float(rng.uniform(-.4, 2)),
                           fixed=.12, variable=.05, cap=3)
            budget = Budget(grid=4, max_cells=2, cost_limit=.55,
                            cvar90_limit=4.5, risk_aversion=float(rng.uniform(0, 2)),
                            cvar_price=float(rng.uniform(0, .2)))
            got = solve(base, [a, b], budget)
            oracle = []
            for ta, tb in product(range(3), range(4)):
                if ta + tb > 4:
                    continue
                w1, w2 = ta/4, tb/4
                mixed = (1-w1-w2)*base + w1*np.array(a.scenario_losses) + w2*np.array(b.scenario_losses)
                cost = .08*w1 + .05*w2 + (.04 if ta else 0) + (.12 if tb else 0)
                tail = float(np.sort(mixed)[-1])  # 9 calibration scenarios -> worst 1.
                if cost > .55 + 1e-12 or tail > 4.5 + 1e-12:
                    continue
                gain = w1*a.conditional_utility_delta + w2*b.conditional_utility_delta
                mean = sum(float(x) for x in mixed)/len(mixed)
                var = sum((float(x)-mean)**2 for x in mixed)/len(mixed)
                value = gain - cost - budget.risk_aversion*var/2 - budget.cvar_price*tail
                oracle.append((value, (ta, tb)))
            assert oracle
            peak = max(x[0] for x in oracle)
            self.assertAlmostEqual(got['score'], peak, places=11)

    def test_baseline_semantic_loss_not_assumed_risk_free(self):
        baseline = [0., 1., 0., 5.]
        r = solve(baseline, [], Budget(grid=4, cvar90_limit=6.))
        self.assertAlmostEqual(r['variance'], np.var(baseline))
        self.assertEqual(r['tail'], 5.)

    def test_cvar_tail_uses_worst_ceil_ten_percent(self):
        self.assertEqual(cvar90(np.arange(20)), 18.5)


class GenerativeMechanismTests(unittest.TestCase):
    def test_zero_delta_equals_base_flow_and_gradients_reach_cells(self):
        z = torch.zeros(5, 7, requires_grad=True)
        c = torch.zeros(5, 32)
        class Base(torch.nn.Module):
            def forward(self, z, t, context):
                return z * 0 + 1
        class Cell(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.p = torch.nn.Parameter(torch.tensor(.5))
            def forward(self, z, context):
                return torch.ones_like(z) * self.p
        cell = Cell()
        base = continuous_direction_step(Base(), z, c, .0, .2, [], [])
        zero = continuous_direction_step(Base(), z, c, .0, .2, [cell], [0.])
        self.assertTrue(torch.equal(base, zero))
        changed = continuous_direction_step(Base(), z, c, .0, .2, [cell], [.25])
        changed.square().mean().backward()
        self.assertIsNotNone(cell.p.grad)
        self.assertGreater(abs(float(cell.p.grad)), 0)

    def test_masked_logits_only_choose_masked_positions(self):
        logits = torch.tensor([[[0., 4.], [3., 0.], [0., 0.]]])
        mask = torch.tensor([[True, False, True]])
        delta = torch.zeros_like(logits)
        tokens, selected = masked_logit_step(logits, [delta], [.5], mask, 1)
        self.assertEqual(selected.sum().item(), 1)
        self.assertTrue(selected[0, 0])
        self.assertFalse(selected[0, 1])
        self.assertEqual(tokens.shape, mask.shape)
        with self.assertRaises(PortfolioRejected):
            masked_logit_step(logits, [delta[..., :1]], [1.], mask, 1)


if __name__ == '__main__':
    unittest.main()
