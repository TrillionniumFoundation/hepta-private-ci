import json
import unittest

import torch

from aten_work import cost
from execution_meter import BudgetStop, POLICY_SCHEMA, WorkLedger, validate_policy
from host_counters import rapl_delta, rapl_snapshot
from paired_execution import PHASES


def policy(mode='observe'):
    return {'schema': POLICY_SCHEMA, 'mode': mode, 'wall_time_ns': 20_000_000_000,
            'max_process_rss_bytes': None, 'rapl_zone': None, 'rapl_max_power_watts': None}


class MeterTests(unittest.TestCase):
    def ledger(self, mode='observe', **kwargs):
        return WorkLedger(policy(mode), dict.fromkeys(PHASES, 10**9), **kwargs)

    def test_matrix_formula_counts_and_phase_separation(self):
        x, y = torch.ones(2, 3), torch.ones(3, 4)
        m = self.ledger()
        with m.scope('train', 'bank'):
            result = x @ y
        with m.scope('inference', 'bank'):
            result = x @ y + 1
        report = m.report()
        self.assertEqual(report['phase_flops']['train'], 48)
        self.assertEqual(report['phase_flops']['inference'], 56)
        self.assertEqual(result.tolist(), [[4.] * 4] * 2)
        self.assertIsNone(report['phase_flops']['evaluation'])
        self.assertFalse(report['hardware_instruction_count'])

    def test_linear_fused_and_decomposed_paths_have_same_profile_charge(self):
        x, w, b = torch.ones(2, 3), torch.ones(4, 3), torch.ones(4)
        fused = cost(torch.ops.aten.linear.default, (x, w, b), {})
        expanded = cost(torch.ops.aten.addmm.default, (b, x, w.T), {})
        self.assertEqual(fused, expanded)
        self.assertEqual(fused, 56)

    def test_broadcast_reduction_and_softmax_formulas(self):
        x = torch.ones(2, 3)
        self.assertEqual(cost(torch.ops.aten.mul.Tensor, (x, torch.ones(3)), {}), 6)
        self.assertEqual(cost(torch.ops.aten.sum.dim_IntList, (x, [1], True), {}), 4)
        self.assertEqual(cost(torch.ops.aten.mean.dim, (x, [1], True), {}), 6)
        self.assertEqual(cost(torch.ops.aten._softmax.default, (x, 1, False), {}), 22)
        self.assertEqual(cost(torch.ops.aten._log_softmax.default, (x, 1, False), {}), 24)
        self.assertEqual(cost(torch.ops.aten._softmax_backward_data.default, (x, x, 1, torch.float32), {}), 22)
        self.assertEqual(cost(torch.ops.aten._log_softmax_backward_data.default, (x, x, 1, torch.float32), {}), 22)

    def test_fused_activations_optimizer_and_scatter_formulas(self):
        x = torch.ones(2, 3)
        self.assertEqual(cost(torch.ops.aten.gelu.default, (x,), {}), 30)
        self.assertEqual(cost(torch.ops.aten.gelu_backward.default, (x, x), {}), 78)
        self.assertIsNone(cost(torch.ops.aten.gelu.default, (x,), {'approximate': 'tanh'}))
        self.assertEqual(cost(torch.ops.aten.addcdiv_.default, (x, x, x), {'value': .3}), 18)
        self.assertEqual(cost(torch.ops.aten.lerp_.Scalar, (x, x, .1), {}), 18)
        self.assertEqual(cost(torch.ops.aten.index_add.default, (x, 0, torch.tensor([0, 1]), x), {}), 6)
        self.assertEqual(cost(torch.ops.aten.rsqrt.default, (x,), {}), 12)

    def test_budget_refuses_before_known_inplace_operation(self):
        m = WorkLedger(policy('strict'), dict.fromkeys(PHASES, 3))
        x = torch.ones(4)
        with self.assertRaisesRegex(BudgetStop, 'formula_flop_budget'):
            with m.scope('train', 'bank'):
                x.add_(1)
        self.assertEqual(x.tolist(), [1.] * 4)
        with self.assertRaises(BudgetStop):
            m.call('inference', 'bank', lambda: self.fail('must not execute'))

    def test_observe_records_unknown_instead_of_assuming_zero(self):
        m = self.ledger()
        x = torch.ones(3)
        with m.scope('train', 'bank'):
            result = torch.sin(x)
        report = m.report()
        self.assertIn('aten.sin.default', report['unknown_operators'])
        self.assertIsNone(report['phase_flops']['train'])
        torch.testing.assert_close(result, torch.sin(x))

    def test_strict_refuses_unknown_without_mutation(self):
        m = self.ledger('strict')
        x = torch.ones(3)
        with self.assertRaisesRegex(BudgetStop, 'unsupported_operator'):
            with m.scope('train', 'bank'):
                x.sin_()
        self.assertEqual(x.tolist(), [1.] * 3)
        self.assertIsNotNone(m.report()['stopped'])

    def test_failed_operator_keeps_reservation_and_unknown_work(self):
        m = self.ledger()
        x, y = torch.ones(2, 3), torch.ones(4, 2)
        with self.assertRaises(RuntimeError):
            with m.scope('train', 'bank'):
                x @ y
        r = m.report()
        self.assertEqual(r['aborted_formula_reservations'], 24)
        self.assertIsNone(r['phase_flops']['train'])
        self.assertEqual(r['stopped'], 'operator_execution_failed')

    def test_python_callback_failure_retained(self):
        m = self.ledger()
        def fails():
            raise OSError('provider failed')
        with self.assertRaises(OSError):
            m.call('inference', 'encoder', fails)
        self.assertEqual(m.report()['scopes'][0]['failed_calls'], 1)
        self.assertIsNone(m.report()['phase_flops']['inference'])

    def test_wall_budget_checked_before_callback(self):
        now = [0]
        m = self.ledger(monotonic=lambda: now[0])
        now[0] = policy()['wall_time_ns']
        with self.assertRaisesRegex(BudgetStop, 'wall_time_budget'):
            m.call('train', 'bank', lambda: self.fail('must not execute'))

    def test_memory_budget_missing_or_excess_is_not_a_zero_reading(self):
        p = policy(); p['max_process_rss_bytes'] = 100
        for reading in (None, 101):
            with self.subTest(reading=reading):
                m = WorkLedger(p, dict.fromkeys(PHASES, 10**9), peak_reader=lambda: reading)
                with self.assertRaises(BudgetStop):
                    m.call('train', 'bank', lambda: self.fail('must not execute'))

    def test_scope_nested_or_after_seal_rejected(self):
        m = self.ledger()
        with m.scope('train', 'bank'):
            with self.assertRaises(ValueError):
                with m.scope('inference', 'bank'):
                    pass
        first = m.report()
        self.assertEqual(m.report(), first)
        with self.assertRaises(ValueError):
            with m.scope('train', 'bank'):
                pass

    def test_validated_policy_no_boolean_budget_or_unknown_override(self):
        for key, val in (('wall_time_ns', True), ('mode', 'ignore'), ('extra', 1),
                         ('max_process_rss_bytes', -1), ('rapl_zone', '/etc/passwd'),
                         ('rapl_max_power_watts', float('inf'))):
            p = policy(); p[key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_policy(p)

    def test_observations_are_json_safe_and_memory_scope_is_explicit(self):
        m = self.ledger(peak_reader=lambda: 4096)
        with m.scope('inference', 'bank'):
            torch.ones(2).add(1)
        r = json.loads(json.dumps(m.report(), allow_nan=False))
        self.assertEqual(r['peak_rss_after_bytes'], 4096)
        self.assertEqual(r['peak_rss_scope'], 'process_lifetime_not_request_peak')
        self.assertIsNone(r['zone_energy']['joules'])


class CounterTests(unittest.TestCase):
    def reading(self, value=10):
        return {'zone': '/sys/test-zone', 'name': 'package-0', 'range_uj': 1000, 'energy_uj': value}

    def test_missing_counter_is_explicit(self):
        self.assertIsNone(rapl_snapshot(None))
        self.assertIsNone(rapl_snapshot('/etc'))
        self.assertIsNone(rapl_delta(None, None, 100, None)['joules'])

    def test_positive_delta_and_wrap_use_same_declared_domain(self):
        delta = rapl_delta(self.reading(10), self.reading(20), 20000, 1)
        self.assertEqual(delta['joules'], 10e-6)
        self.assertFalse(delta['process_attribution_established'])
        wrapped = rapl_delta(self.reading(990), self.reading(5), 20000, 1)
        self.assertEqual(wrapped['joules'], 15e-6)

    def test_missing_power_bound_counter_reset_or_multiple_wrap_rejects(self):
        for start, end, duration, power, reason in (
            (10, 20, 20000, None, 'power_bound_unavailable'),
            (10, 20, 1000000, 1, 'multiple_wrap_ambiguity'),
            (100, 0, 20000, 1, 'power_bound_or_counter_reset')):
            r = rapl_delta(self.reading(start), self.reading(end), duration, power)
            self.assertIsNone(r['joules'])
            self.assertEqual(r['reason'], reason)

    def test_domain_identity_change_rejects(self):
        after = self.reading(); after['name'] = 'core-subzone'
        self.assertEqual(rapl_delta(self.reading(), after, 10, 1)['reason'], 'counter_identity_changed')


if __name__ == '__main__':
    unittest.main()
