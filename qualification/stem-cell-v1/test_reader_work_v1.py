"""Exact backward scatter mathematics and independent arithmetic policy revision."""
import unittest
import torch

from reader_work_v1 import PROFILE, cost
from execution_meter import EXTENDED_POLICY_SCHEMA, CONDITIONAL_READER_POLICY_SCHEMA, WorkLedger
from transformer_work_v3 import PROFILE as PREVIOUS_PROFILE
from paired_execution import PHASES


def policy(version, profile):
    return dict(schema=version, arithmetic_profile=profile,
                mode='strict', wall_time_ns=20_000_000_000,
                max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)


class ReaderArithmeticTests(unittest.TestCase):
    def test_select_backward_really_scattered_without_floating_arithmetic(self):
        source=torch.tensor([1.,2.])
        op=torch.ops.aten.select_backward.default
        self.assertEqual(cost(op,(source,[2,2],0,1),{}),0)
        output=op(source,[2,2],0,1)
        torch.testing.assert_close(output,torch.tensor([[0.,0.],[1.,2.]]),atol=0,rtol=0)
        self.assertIsNone(cost(op,(source,[2,3],0,1),{}))

    def test_unsupported_shapes_dtype_and_indices_do_not_get_free_cost(self):
        op=torch.ops.aten.select_backward.default
        cases=((torch.ones(2,dtype=torch.float64),[2,2],0,1),
               (torch.ones(2),[2,2],0,2),
               (torch.ones(2),[2,2],2,1),
               (torch.ones(2),[2,2],True,1),
               (torch.ones(2),[2,2],0,True),
               (torch.ones(2),[2,3],0,1))
        for args in cases:
            with self.subTest(args=str(args)):
                self.assertIsNone(cost(op,args,{}))

    def test_old_V3_remains_unregistered_for_reader_backward(self):
        op=torch.ops.aten.select_backward.default
        from transformer_work_v3 import cost as old
        self.assertIsNone(old(op,(torch.ones(2),[2,2],0,1),{}))
        self.assertNotEqual(PREVIOUS_PROFILE,PROFILE)
        with self.assertRaises(ValueError):
            WorkLedger(policy(EXTENDED_POLICY_SCHEMA,PROFILE),dict.fromkeys(PHASES,1000))
        WorkLedger(policy(CONDITIONAL_READER_POLICY_SCHEMA,PROFILE),dict.fromkeys(PHASES,1000))

    def test_new_profile_counts_backward_zero_but_not_unknown_training_scope(self):
        meter=WorkLedger(policy(CONDITIONAL_READER_POLICY_SCHEMA,PROFILE),dict.fromkeys(PHASES,1000))
        with meter.scope('train','bank'):
            out=torch.ops.aten.select_backward.default(torch.ones(2),[2,2],0,1)
        data=meter.report()
        self.assertEqual(data['unknown_operators'],{})
        self.assertEqual(data['phase_flops']['train'],0)
        self.assertEqual(out.shape,(2,2))


if __name__ == '__main__':
    unittest.main()
