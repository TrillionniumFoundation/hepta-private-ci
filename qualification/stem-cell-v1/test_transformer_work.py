import unittest

import torch
from torch import nn

from aten_work import PROFILE as LEGACY_PROFILE
from execution_meter import BudgetStop, TRANSFORMER_POLICY_SCHEMA, WorkLedger, validate_policy
from paired_execution import PHASES
from transformer_work import PROFILE, cost
from test_execution_meter import policy


def transformer_policy(mode='strict'):
    return {**policy(mode), 'schema': TRANSFORMER_POLICY_SCHEMA, 'arithmetic_profile': PROFILE}


class TransformerWorkTests(unittest.TestCase):
    def ledger(self):
        return WorkLedger(transformer_policy(), dict.fromkeys(PHASES, 10**9))

    def test_v1_unknown_sine_is_not_silently_redefined(self):
        m = WorkLedger(policy(), dict.fromkeys(PHASES, 10**9))
        with m.scope('inference', 'encoder'): torch.ones(2).sin()
        self.assertEqual(m.report()['profile'], LEGACY_PROFILE)
        self.assertIsNone(m.report()['phase_flops']['inference'])
        m = self.ledger()
        with m.scope('inference', 'encoder'): torch.ones(2).sin()
        self.assertEqual(m.report()['phase_flops']['inference'], 2)
        self.assertEqual(m.report()['profile'], PROFILE)

    def test_layernorm_dispatch_matches_centered_variance_formula(self):
        x = torch.tensor([[1.,2.,3.],[2.,4.,8.]])
        for affine, bias, expected in ((True, True, 48), (True, False, 42), (False, False, 36)):
            layer = nn.LayerNorm(3, elementwise_affine=affine, bias=bias).eval()
            m = self.ledger()
            with m.scope('inference', 'encoder'), torch.inference_mode(): y = layer(x)
            self.assertEqual(m.report()['phase_flops']['inference'], expected)
            centered = x - x.mean(-1, keepdim=True)
            direct = centered * (centered.square().mean(-1, keepdim=True) + layer.eps).rsqrt()
            torch.testing.assert_close(y, direct)

    def test_layernorm_group_geometry_and_invalid_arguments(self):
        x = torch.ones(2, 3, 4)
        self.assertEqual(cost(torch.ops.aten.native_layer_norm.default, (x, [3,4], None, None, 1e-5), {}), 126)
        for shape, eps in (([4,3], 1e-5), ([3,4], float('nan')), ([3,4], -1)):
            self.assertIsNone(cost(torch.ops.aten.native_layer_norm.default, (x, shape, None, None, eps), {}))

    def test_rotary_elementwise_cost_and_unchanged_results(self):
        x = torch.ones(2,3)
        m = self.ledger()
        with m.scope('inference', 'encoder'): result = x.sin() * x.cos() + x.pow(2)
        self.assertEqual(m.report()['phase_flops']['inference'], 30)
        torch.testing.assert_close(result, x.sin() * x.cos() + x.pow(2))

    def test_embedding_and_boolean_mask_are_not_arithmetic_work(self):
        layer = nn.Embedding(8,4).eval(); ids = torch.tensor([[1,2,3]])
        m = self.ledger()
        with m.scope('inference', 'encoder'), torch.inference_mode():
            y = layer(ids)
            torch.ones(3,3, dtype=torch.bool).triu().logical_not()
        self.assertEqual(m.report()['phase_flops']['inference'], 0)
        self.assertEqual(tuple(y.shape), (1,3,4))
        self.assertIn('aten.embedding.default', m.report()['operators'])

    def test_budget_checks_fused_layernorm_before_dispatch(self):
        m = WorkLedger(transformer_policy(), dict.fromkeys(PHASES, 35))
        x = torch.ones(2,3)
        with self.assertRaises(BudgetStop):
            with m.scope('inference', 'encoder'):
                nn.functional.layer_norm(x, [3])
        self.assertEqual(m.report()['stopped'], 'formula_flop_budget:inference')

    def test_profile_and_schema_cannot_be_mixed(self):
        for key, value in (('schema','hepta.execution-meter-policy.v1'), ('arithmetic_profile','unknown')):
            p = transformer_policy();p[key]=value
            with self.assertRaises(ValueError): validate_policy(p)
        p = policy();p['arithmetic_profile']=PROFILE
        with self.assertRaises(ValueError): validate_policy(p)

    def test_unsupported_fused_attention_remains_unknown(self):
        q = torch.ones(1,2,3,4)
        self.assertIsNone(cost(torch.ops.aten.scaled_dot_product_attention.default, (q,q,q), {}))


if __name__ == '__main__':
    unittest.main()
