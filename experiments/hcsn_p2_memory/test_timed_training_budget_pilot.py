"""Focused contract checks; not proof of training efficacy or GPU fairness."""
import unittest

import numpy as np
import torch

from experiments.hcsn_hx_unified_v3.renewal_spike_sampler import SpikeStream
from .event_content import (TrainableEventContent, default_spec, example,
                            make_batch, model_digest,UnresolvedContent)
from .timed_fire_content import timed_content_step
from .timed_training_budget_pilot import (physical_dataset, timed_forward,execute,
                                           ARMS,TASKS,CPU_BUDGET,MAX_STEPS)


class PhysicalTrainPilotContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_sampled_clocks_and_original_aggregate_data_match(self):
        for task in TASKS:
            with self.subTest(task=task):
                a=physical_dataset(task,n=8,length=16,seed=200)
                b=make_batch(task,n=8,length=16,seed=200)
                for k in ('x','y','mask','dt','count'):
                    self.assertTrue(torch.equal(a[k],b[k]),k)
                self.assertEqual(a['total_events'],b['total_events'])
                self.assertEqual(a['multi_fire_streams'],b['multi_fire_streams'])
                self.assertTrue(torch.all(a['count']==a['event_valid'].sum(-1)))
                self.assertTrue(torch.allclose(a['event_gap'].sum(-1),a['dt'],atol=1e-6))

    def test_batched_timed_forward_matches_exact_per_event_step(self):
        model=TrainableEventContent(32).eval()
        torch.manual_seed(310)
        for task in TASKS:
            data=physical_dataset(task,n=2,length=16,seed=200)
            y=timed_forward(model,data)
            for actor in range(2):
                x,_,_,_,times=example(task,length=16,seed=200*100000+actor)
                stream=SpikeStream(default_spec(),seed=200*100000+actor,
                                   stream_id=f'{task}-200-{actor}')
                h=torch.zeros(1,model.hidden)
                prev=0.
                for t in range(16):
                    ev=stream.advance_to(times[t])
                    with torch.no_grad():
                        h,logit=timed_content_step(model,
                          torch.from_numpy(x[t].copy())[None],prev,times[t],ev,h)
                    self.assertTrue(torch.allclose(logit,y[actor,t],atol=2e-6,rtol=2e-6),
                                    (task,actor,t,float(logit),float(y[actor,t])))
                    prev=times[t]

    def test_autograd_reaches_all_trainable_blocks(self):
        torch.manual_seed(17)
        data=physical_dataset('copy',n=8,length=16,seed=201)
        model=TrainableEventContent(32)
        logits=timed_forward(model,data)
        loss=torch.nn.functional.binary_cross_entropy_with_logits(logits[:,-1],data['y'][:,-1])
        loss.backward()
        for name,p in model.named_parameters():
            self.assertIsNotNone(p.grad,name)
            self.assertTrue(bool(torch.isfinite(p.grad).all()),name)
            self.assertGreater(float(p.grad.abs().sum()),1e-10,name)

    def test_fixed_data_and_weight_initialization_digest(self):
        a=physical_dataset('mqar4',n=8,length=32,seed=300)
        b=physical_dataset('mqar4',n=8,length=32,seed=300)
        self.assertEqual(a['data_sha256'],b['data_sha256'])
        for k in ('event_gap','event_valid','x','count','dt','y','mask'):
            self.assertTrue(torch.equal(a[k],b[k]))
        torch.manual_seed(400)
        m=TrainableEventContent(32)
        torch.manual_seed(400)
        n=TrainableEventContent(32)
        self.assertEqual(model_digest(m),model_digest(n))
        self.assertEqual(sum(p.numel() for p in m.parameters()),5186)

    def test_reject_unregistered_arm_task_and_budget(self):
        data=physical_dataset('copy',n=2,length=16,seed=201)
        with self.assertRaises(UnresolvedContent):physical_dataset('invalid',n=2,length=16,seed=201)
        with self.assertRaises(UnresolvedContent):physical_dataset('copy',n=0,length=16,seed=201)
        model=TrainableEventContent(32)
        bad=dict(data);bad['event_valid']=data['event_valid'][:,:-1]
        with self.assertRaises(UnresolvedContent):timed_forward(model,bad)
        with self.assertRaises(UnresolvedContent):execute('invalid',0,'aggregate_count',smoke=True)
        with self.assertRaises(UnresolvedContent):execute('copy',0,'none',smoke=True)
        with self.assertRaises(UnresolvedContent):execute('copy',0,'aggregate_count',budget=1, max_steps=1)
        self.assertEqual(CPU_BUDGET,25.0)
        self.assertEqual(MAX_STEPS,2000)

    def test_focused_differentiable_training_smoke_not_a_scientific_gate(self):
        records=[execute('copy',0,a,budget=2.0,max_steps=3,train_n=8,
                         test_n=8,smoke=True) for a in ARMS]
        self.assertEqual([r['optimizer_updates'] for r in records],[3,3])
        self.assertEqual(records[0]['initial_model_sha256'],records[1]['initial_model_sha256'])
        self.assertEqual(records[0]['train_data_sha256'],records[1]['train_data_sha256'])
        self.assertEqual(records[0]['params'],records[1]['params'])
        self.assertEqual(records[0]['id']['data_sha256'],records[1]['id']['data_sha256'])
        for r in records:
            self.assertFalse(r['all_scientific_blockers_closed'])
            self.assertFalse(r['production_activation'])
            self.assertEqual(r['id']['queries'],8)
            self.assertEqual(r['ood']['queries'],8)


if __name__=='__main__':unittest.main()
