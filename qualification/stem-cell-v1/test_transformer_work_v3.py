import copy
import unittest

import torch

from execution_meter import BudgetStop, EXTENDED_POLICY_SCHEMA, WorkLedger, validate_policy
from paired_execution import PHASES
from transformer_work import PROFILE as PREVIOUS_PROFILE, cost as previous_cost
from transformer_work_v3 import PROFILE, cost, matmul_work
from test_execution_meter import policy
from work_record import validate_work_record


def expanded_policy(mode='strict'):
    return {**policy(mode), 'schema': EXTENDED_POLICY_SCHEMA, 'arithmetic_profile': PROFILE}


class ExpandedWorkTests(unittest.TestCase):
    def ledger(self, mode='strict', cap=10**9):
        return WorkLedger(expanded_policy(mode), dict.fromkeys(PHASES, cap))

    def test_vector_matrix_and_broadcast_geometry_agree_with_actual_results(self):
        cases = [((3,), (3,), (), 6), ((2,3),(3,4),(2,4),48),
                 ((3,),(3,4),(4,),24), ((2,3),(3,),(2,),12),
                 ((5,2,3),(3,),(5,2),60), ((3,),(5,3,4),(5,4),120),
                 ((2,1,3,4),(7,4,5),(2,7,3,5),1680),
                 ((2,3),(5,3,4),(5,2,4),240), ((5,2,3),(3,4),(5,2,4),240)]
        for ashape,bshape,shape,expected in cases:
            a,b=torch.ones(ashape),torch.ones(bshape)
            with self.subTest(a=ashape,b=bshape):
                result=torch.matmul(a,b)
                self.assertEqual(tuple(result.shape),shape)
                self.assertEqual(matmul_work(a,b),expected)
                self.assertEqual(cost(torch.ops.aten.matmul.default, (), {'self':a,'other':b}),expected)
                torch.testing.assert_close(result,torch.full(shape,float(ashape[-1])))

    def test_empty_contraction_output_and_zero_batch_have_no_arithmetic(self):
        for ashape,bshape in [((0,),(0,)),((2,0),(0,4)),((0,3),(3,4)),
                              ((2,3),(3,0)),((0,2,3),(1,3,4))]:
            a,b=torch.empty(ashape),torch.empty(bshape)
            with self.subTest(a=ashape,b=bshape):
                result=torch.matmul(a,b)
                self.assertEqual(matmul_work(a,b),0)
                self.assertTrue(torch.isfinite(result).all().item())

    def test_noncontiguous_and_expanded_views_charge_output_not_storage(self):
        a=torch.ones(3,2).T.expand(7,2,3)
        b=torch.ones(4,3).T
        self.assertFalse(a.is_contiguous())
        self.assertEqual(matmul_work(a,b),336)
        self.assertEqual(a.untyped_storage().nbytes(),24)
        torch.testing.assert_close(a@b,torch.full((7,2,4),3.))

    def test_invalid_geometry_is_unknown_instead_of_zero(self):
        for a,b in [(torch.ones(()),torch.ones(2)),(torch.ones(2,3),torch.ones(4,2)),
                    (torch.ones(2,2,3),torch.ones(4,3,2))]:
            with self.subTest(a=a.shape,b=b.shape):
                self.assertIsNone(matmul_work(a,b))
                with self.assertRaises(RuntimeError):torch.matmul(a,b)

    def test_unsupported_tensor_profiles_remain_unknown(self):
        a,b=torch.ones(2,3),torch.ones(3,4)
        for x,y in [(a.double(),b.double()),(a.long(),b.long()),
                    (a.to_sparse(),b),(a.to('meta'),b.to('meta'))]:
            with self.subTest(dtype=x.dtype,layout=x.layout,device=x.device):
                self.assertIsNone(matmul_work(x,y))

    def test_no_out_overload_or_extra_argument_whitelist(self):
        a,b=torch.ones(2,3),torch.ones(3,4)
        self.assertIsNone(cost(torch.ops.aten.matmul.out,(a,b),{'out':torch.empty(2,4)}))
        self.assertIsNone(cost(torch.ops.aten.matmul.default,(a,b),{'other':b}))
        self.assertIsNone(cost(torch.ops.aten.matmul.default,(a,b),{'ignore':True}))

    def test_live_matmul_is_charged_once_and_matches_explicit_bmm(self):
        a,b=torch.ones(2,3,4),torch.ones(2,4,5)
        observations=[]
        for operator in (torch.ops.aten.matmul.default,torch.ops.aten.bmm.default):
            meter=self.ledger()
            with meter.scope('inference','encoder'),torch.inference_mode():result=operator(a,b)
            record=meter.report();validate_work_record(record)
            observations.append(record['phase_flops']['inference'])
            self.assertEqual(record['unknown_operators'],{})
            torch.testing.assert_close(result,torch.full((2,3,5),4.))
        self.assertEqual(observations,[240,240])

    def test_new_matmul_budget_refuses_before_followup_operations(self):
        a,b=torch.ones(2,3,4),torch.ones(2,4,5); meter=self.ledger(cap=239)
        with self.assertRaisesRegex(BudgetStop,'formula_flop_budget:inference'):
            with meter.scope('inference','encoder'),torch.inference_mode():
                torch.ops.aten.matmul.default(a,b)
                self.fail('should stop before returning the matrix product')
        record=meter.report();validate_work_record(record)
        self.assertEqual(record['scopes'][0]['formula_flops'],0)
        self.assertIsNone(record['phase_flops']['inference'])

    def test_live_conversion_copy_and_transpose_have_real_effects_without_arithmetic(self):
        x=torch.arange(6,dtype=torch.long).reshape(2,3);meter=self.ledger()
        with meter.scope('inference','encoder'),torch.inference_mode():
            a=torch.ops.aten.to.dtype(x,torch.float32,False,True)
            b=torch.ops.aten.to.dtype_layout(a,dtype=torch.float32,device=torch.device('cpu'),copy=True)
            c=torch.ops.aten.numpy_T.default(b)
        self.assertEqual(a.dtype,torch.float32)
        self.assertNotEqual(a.data_ptr(),b.data_ptr())
        self.assertEqual(c.data_ptr(),b.data_ptr())
        torch.testing.assert_close(c,x.float().T)
        record=meter.report();validate_work_record(record)
        self.assertEqual(record['phase_flops']['inference'],0)
        self.assertEqual(record['unknown_operators'],{})
        self.assertFalse(record['hardware_instruction_count'])

    def test_cast_binding_including_positional_dtype_and_memory_format(self):
        x=torch.ones(2,3,4,5)
        self.assertEqual(cost(torch.ops.aten.to.dtype,(x,torch.float32,False,True),{}),0)
        self.assertEqual(cost(torch.ops.aten.to.dtype_layout,(x,),{'memory_format':torch.channels_last}),0)
        self.assertIsNone(cost(torch.ops.aten.to.dtype,(x,),{}))
        self.assertIsNone(cost(torch.ops.aten.to.dtype,(x,torch.float32),{'dtype':torch.float32}))
        self.assertIsNone(cost(torch.ops.aten.to.dtype_layout,(x,torch.float32),{}))

    def test_cast_rejects_unregistered_precision_device_layout_and_options(self):
        x=torch.ones(2,3)
        for options in [dict(dtype=torch.float64),dict(dtype=torch.float16),dict(device='meta'),
                        dict(device='cuda'),dict(layout=torch.sparse_coo),dict(pin_memory=True),
                        dict(copy=1),dict(memory_format=torch.channels_last),dict(unknown=0)]:
            with self.subTest(options=options):
                self.assertIsNone(cost(torch.ops.aten.to.dtype_layout,(x,),options))
        self.assertIsNone(cost(torch.ops.aten.to.dtype,(x,torch.float64),{}))
        self.assertIsNone(cost(torch.ops.aten.to.dtype,(x,None),{}))

    def test_strict_rejects_cast_destination_before_creating_meta_output(self):
        x=torch.ones(2,3);meter=self.ledger()
        with self.assertRaisesRegex(BudgetStop,'unsupported_operator'):
            with meter.scope('inference','encoder'),torch.inference_mode():
                torch.ops.aten.to.dtype_layout(x,device=torch.device('meta'))
        self.assertEqual(x.device.type,'cpu')
        self.assertEqual(x.tolist(),[[1.]*3]*2)
        self.assertIsNone(meter.report()['phase_flops']['inference'])

    def test_previous_profile_remains_unknown_on_exact_new_overloads(self):
        a,b=torch.ones(2,3),torch.ones(3,4)
        for operator,args in [(torch.ops.aten.matmul.default,(a,b)),(torch.ops.aten.numpy_T.default,(a,)),
                              (torch.ops.aten.to.dtype,(a,torch.float32)),(torch.ops.aten.to.dtype_layout,(a,))]:
            with self.subTest(operator=str(operator)):
                self.assertIsNone(previous_cost(operator,args,{}))
                self.assertIsNotNone(cost(operator,args,{}))

    def test_schema_and_profile_cannot_be_cross_labeled(self):
        policy=expanded_policy();validate_policy(policy)
        for key,value in [('schema','hepta.execution-meter-policy.v2'),('arithmetic_profile',PREVIOUS_PROFILE)]:
            bad={**policy,key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):validate_policy(bad)

    def test_unknown_unrelated_operator_still_blocks_complete_accounting(self):
        meter=self.ledger('observe');x=torch.ones(3)
        with meter.scope('inference','encoder'):x.acos()
        record=meter.report();validate_work_record(record)
        self.assertIn('aten.acos.default',record['unknown_operators'])
        self.assertIsNone(record['phase_flops']['inference'])

    def test_meter_does_not_change_outputs_input_or_rng(self):
        a,b=torch.randn(2,1,3,4),torch.randn(5,4,2)
        a0,b0=a.clone(),b.clone();state=torch.random.get_rng_state();meter=self.ledger()
        with meter.scope('inference','encoder'),torch.inference_mode():result=a@b
        torch.testing.assert_close(result,a0@b0,rtol=0,atol=0)
        torch.testing.assert_close(a,a0,rtol=0,atol=0)
        torch.testing.assert_close(b,b0,rtol=0,atol=0)
        self.assertTrue(torch.equal(state,torch.random.get_rng_state()))


if __name__=='__main__':unittest.main()
