"""Exact-view reuse tests on real PyTorch modules, NOT pretrained efficacy."""
import copy
import unittest

import torch

from execution_meter import EXTENDED_POLICY_SCHEMA
from matrix_bank import CellBank, state_digest, train_bank
from shared_fanout import CellConsumer, measure_fanout, view_digest
from transformer_work_v3 import PROFILE


POLICY = dict(schema=EXTENDED_POLICY_SCHEMA, arithmetic_profile=PROFILE,
              mode='strict', wall_time_ns=20_000_000_000,
              max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)


def request():
    return dict(sample_id='case-001', source_group='news-1', scope='principal-a',
                state='article about news', question='Classify the same ordered options',
                options=['World','Sports','Business','Science'], available_at_ns=10)


class Encoder:
    """A genuinely executed, frozen, stable CPU linear Encoder."""
    def __init__(self, dimension=16):
        self.calls=0
        with torch.random.fork_rng():
            torch.manual_seed(4)
            self.model=torch.nn.Sequential(torch.nn.Linear(dimension,dimension),
                                           torch.nn.GELU(),torch.nn.Linear(dimension,dimension)).eval()
        self.model.requires_grad_(False)
        self.source=torch.linspace(-1.,1.,dimension)
        self.changed=False
        self.last_rows=[]

    def __call__(self,row):
        self.calls+=1
        self.last_rows.append(dict(row))
        if self.changed:
            row['question']='mutated'
        y=self.model(self.source)
        return y.detach(),8


def setup(n=7, *, dimension=16, trained=False):
    req=request()
    view=view_digest(req)
    consumers=[]
    for i in range(n):
        profile=dict(logical_cells=16,initial_logical_cells=16,split=False,ndu=False,
            resident_stem_copies=1,cell_head_budget_params=2_000_000,
            total_head_budget_params=32_000_000,active_cells_per_round_cap=2)
        with torch.random.fork_rng():
            torch.manual_seed(i+100)
            bank=CellBank(dimension,4,profile,4)
        if trained:
            x=torch.arange(4*dimension,dtype=torch.float32).reshape(4,dimension)/100.
            y=torch.tensor([(j+i)%4 for j in range(4)])
            train_bank(bank,x,y,dict(train_steps=2,batch_size=4), i+1)
        bank.eval()
        consumers.append(CellConsumer(f'task-{i}',req['scope'],view,bank))
    return req,consumers


class SharedFanoutTests(unittest.TestCase):
    def test_one_real_encoder_forward_serves_seven_real_banks_and_112_cells(self):
        req,consumers=setup(7,trained=True)
        encoder=Encoder()
        before=[state_digest(c.bank) for c in consumers]
        report=measure_fanout(encoder,req,consumers,policy=POLICY)
        self.assertEqual(report['logical_cells'],112)
        self.assertEqual(report['shared_encoder_calls'],1)
        self.assertEqual(report['standalone_encoder_calls'],7)
        self.assertEqual(encoder.calls,8)
        self.assertEqual(report['max_logit_abs_difference'],0)
        self.assertEqual(len(report['results']['shared']['logits']),7)
        self.assertEqual(before,[state_digest(c.bank) for c in consumers])
        self.assertGreater(report['bank_unique_weight_bytes'],0)
        self.assertTrue(report['encoder_reuse_validated_for_identical_request_only'])
        self.assertFalse(report['independent_task_learning_established'])
        self.assertFalse(report['production_authorized'])

    def test_actual_encoder_arithmetic_saved_and_head_work_still_charged(self):
        req,consumers=setup(7)
        result=measure_fanout(Encoder(),req,consumers,policy=POLICY)
        a=result['results']['shared']; b=result['results']['repeated']
        self.assertGreater(a['formula_flops'],0)
        self.assertGreater(b['formula_flops'],a['formula_flops'])
        self.assertGreater(result['formula_work_reduction'],0)
        self.assertGreater(result['formula_work_reduction_fraction'],0)
        # Seven Banks execute in BOTH modes: reduction is only their six
        # duplicated Encoder forwards, not the 112 Cell heads themselves.
        banks_a=sum(s['calls'] for s in a['work_observation']['scopes'] if s['component']=='bank')
        banks_b=sum(s['calls'] for s in b['work_observation']['scopes'] if s['component']=='bank')
        self.assertEqual((banks_a,banks_b),(7,7))

    def test_one_consumer_means_no_reuse_savings(self):
        req,consumers=setup(1)
        report=measure_fanout(Encoder(),req,consumers,policy=POLICY)
        self.assertEqual(report['formula_work_reduction'],0)
        self.assertEqual(report['shared_encoder_calls'],1)
        self.assertEqual(report['standalone_encoder_calls'],1)

    def test_different_question_options_sample_time_or_scope_rejected(self):
        req,consumers=setup(2)
        for field,value in (('question','other question'),('options',['a','b','c','d']),
                            ('sample_id','different'),('available_at_ns',11),('scope','principal-b')):
            changed=copy.deepcopy(req); changed[field]=value
            encoder=Encoder()
            with self.subTest(field=field), self.assertRaises(ValueError):
                measure_fanout(encoder,changed,consumers,policy=POLICY)
            self.assertEqual(encoder.calls,0)

    def test_different_declared_consumer_scope_and_view_rejected_early(self):
        req,consumers=setup(2)
        for bad in (CellConsumer('task-0','different-scope',consumers[0].view_sha256,consumers[0].bank),
                    CellConsumer('task-0',req['scope'],'f'*64,consumers[0].bank)):
            encoder=Encoder()
            with self.assertRaises(ValueError):
                measure_fanout(encoder,req,[bad,consumers[1]],policy=POLICY)
            self.assertEqual(encoder.calls,0)

    def test_duplicate_task_id_bank_object_and_training_mode_rejected(self):
        req,consumers=setup(2)
        for altered in ([consumers[0],CellConsumer('task-0',req['scope'],consumers[1].view_sha256,consumers[1].bank)],
                        [consumers[0],CellConsumer('other',req['scope'],consumers[0].view_sha256,consumers[0].bank)]):
            with self.assertRaises(ValueError):
                measure_fanout(Encoder(),req,altered,policy=POLICY)
        consumers[0].bank.train()
        with self.assertRaises(ValueError):
            measure_fanout(Encoder(),req,consumers,policy=POLICY)

    def test_exact_row_contract_rejects_unknown_labels_and_missing_fields(self):
        req,consumers=setup(1)
        for mutation in ('label','missing','empty_options','bool_time'):
            row=copy.deepcopy(req)
            if mutation=='label':row['label']=1
            elif mutation=='missing':del row['scope']
            elif mutation=='empty_options':row['options']=[]
            else:row['available_at_ns']=True
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                measure_fanout(Encoder(),row,consumers,policy=POLICY)

    def test_insufficient_cell_and_feature_caps_rejected(self):
        req,consumers=setup(7)
        with self.assertRaises(ValueError):
            measure_fanout(Encoder(),req,consumers,policy=POLICY,max_total_cells=111)
        encoder=Encoder()
        with self.assertRaises(ValueError):
            measure_fanout(encoder,req,consumers,policy=POLICY,max_feature_bytes=4)
        self.assertEqual(encoder.calls,1)

    def test_uncovered_formula_keeps_unknown_not_fake_zero(self):
        req,consumers=setup(2)
        p=dict(POLICY,mode='observe')
        class Unknown(Encoder):
            def __call__(self,row):
                feature, n=super().__call__(row)
                return torch.atan(feature),n
        report=measure_fanout(Unknown(),req,consumers,policy=p)
        self.assertIsNone(report['results']['shared']['formula_flops'])
        self.assertIsNone(report['formula_work_reduction'])
        self.assertTrue(report['results']['shared']['work_observation']['unknown_operators'])

    def test_budget_stop_fails_without_success_record(self):
        req,consumers=setup(2)
        caps=dict.fromkeys(('train','search','evaluation','inference','migration'),1)
        encoder=Encoder()
        with self.assertRaisesRegex(RuntimeError,'formula_flop_budget'):
            measure_fanout(encoder,req,consumers,policy=POLICY,caps=caps)
        self.assertEqual(encoder.calls,1)

    def test_nondeterministic_encoder_cannot_pass_parity(self):
        req,consumers=setup(2)
        class Changing(Encoder):
            def __call__(self,row):
                y,n=super().__call__(row)
                return y + self.calls * 0.25,n
        with self.assertRaisesRegex(ValueError,'changed task logits'):
            measure_fanout(Changing(),req,consumers,policy=POLICY)

    def test_storage_views_charge_underlying_feature_allocation(self):
        req,consumers=setup(1)
        class LargeStorage(Encoder):
            def __call__(self,row):
                self.calls+=1
                return torch.ones(16384)[:16],8
        encoder=LargeStorage()
        with self.assertRaisesRegex(ValueError,'unsafe or over-budget'):
            measure_fanout(encoder,req,consumers,policy=POLICY,max_feature_bytes=1024)

    def test_unexpected_mutation_of_model_parameters_is_rejected(self):
        req,consumers=setup(2)
        class Corrupting(Encoder):
            def __call__(self,row):
                result=super().__call__(row)
                with torch.no_grad():
                    consumers[1].bank.gate.bias[0].add_(1.)
                return result
        with self.assertRaisesRegex(ValueError,'parameters changed'):
            measure_fanout(Corrupting(),req,consumers,policy=POLICY)


if __name__=='__main__':
    unittest.main()
