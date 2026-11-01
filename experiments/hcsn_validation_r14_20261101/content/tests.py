"""Behavioral checks of real causal prefixes, returns, and complete freezing."""

import copy
import unittest
import torch

from experiments.hcsn_validation_r12_20261031.content.models import FAMILIES, Model, core_configs
from .data import dataset
from .engine import ValueController, all_logits, policy_values, realized_returns, replay, online_rollout, model_hash, READ_FEE, TIME_FEE


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.configs=core_configs()
        data=dataset('recall','train')
        cls.x=torch.from_numpy(data['x'][:4]);cls.dt=torch.from_numpy(data['dt'][:4])
        cls.y=torch.from_numpy(data['y'][:4])

    def test_all_families_causal_prefixes(self):
        for family in FAMILIES:
            with self.subTest(family=family),torch.no_grad():
                model=Model('recall',family,123,self.configs[family]).eval()
                logits=all_logits(model,self.x,self.dt)
                for t in (1,5,self.x.shape[1]):
                    self.assertTrue(torch.allclose(logits[:,t],model(self.x[:,:t],self.dt[:,:t]),atol=2e-6,rtol=2e-6))
                changed=self.x.clone();changed[:,6:]=torch.randn_like(changed[:,6:])*20
                self.assertTrue(torch.equal(logits[:,:7],all_logits(model,changed,self.dt)[:,:7]))

    def test_initial_stop_never_acquires_raw(self):
        model=Model('recall','analytic',123,self.configs['analytic'])
        controller=ValueController()
        with torch.no_grad():
            for p in controller.parameters():p.zero_()
            controller.net[-1].bias[0]=10
            result=online_rollout(model,controller,torch.full_like(self.x,float('nan')),self.dt,self.y)
        self.assertEqual(result['model_calls'],0)
        self.assertEqual(result['processed_prefix_tokens'],0)
        self.assertTrue(torch.equal(result['reads'],torch.zeros(4,dtype=torch.long)))
        self.assertTrue(torch.isfinite(result['utility']).all())

    def test_always_read_uses_actual_fees_and_terminal(self):
        model=Model('recall','ordinary_dual',123,self.configs['ordinary_dual'])
        controller=ValueController()
        with torch.no_grad():
            for p in controller.parameters():p.zero_()
            controller.net[-1].bias[1]=10
            result=online_rollout(model,controller,self.x,self.dt,self.y)
            pred=model(self.x,self.dt).argmax(-1)
        self.assertTrue(torch.equal(result['prediction'],pred))
        self.assertTrue(torch.equal(result['reads'],torch.full((4,),self.x.shape[1],dtype=torch.long)))
        fee=READ_FEE*self.x.shape[1]+TIME_FEE*self.dt.sum(1)
        self.assertTrue(torch.equal(result['utility'],(pred==self.y).float()-fee))

    def test_sample_qpi_follows_actual_next_decision(self):
        logits=torch.tensor([[[2.,0.],[0.,2.],[2.,0.]]])
        values=torch.tensor([[[0.,1.],[1.,0.],[1.,0.]]])
        dt=torch.tensor([[.3,1.7]])
        targets,actions,root=realized_returns(logits,values,dt,torch.tensor([0]))
        self.assertAlmostEqual(float(targets[0,0,1]),-READ_FEE-TIME_FEE*.3,places=7)
        self.assertAlmostEqual(float(targets[0,1,1]),1-READ_FEE-TIME_FEE*1.7,places=7)
        self.assertAlmostEqual(float(root),float(targets[0,0,1]),places=7)
        self.assertEqual(actions.tolist(),[[True,False,False]])

    def test_frozen_complete_backend_and_joint_gradients(self):
        for frozen in (True,False):
            model=Model('recall','analytic',123,self.configs['analytic'])
            model.requires_grad_(not frozen)
            controller=ValueController()
            before=model_hash(model)
            params=list(controller.parameters())+[p for p in model.parameters() if p.requires_grad]
            optimizer=torch.optim.Adam(params,lr=.01)
            logits=all_logits(model,self.x,self.dt)
            values=policy_values(controller,logits,self.dt)
            loss=values.square().mean()+torch.nn.functional.cross_entropy(logits[:,-1],self.y)
            loss.backward();optimizer.step()
            self.assertEqual(model_hash(model)==before,frozen)
            for group in (model.encoder,model.core,model.readout):
                has_grad=any(p.grad is not None and bool(torch.count_nonzero(p.grad)) for p in group.parameters())
                self.assertEqual(has_grad,not frozen)

    def test_replay_matches_causal_actor(self):
        torch.manual_seed(8)
        model=Model('recall','ordinary_dual',123,self.configs['ordinary_dual'])
        controller=ValueController()
        with torch.no_grad():
            logits=all_logits(model,self.x,self.dt)
            a=replay(logits,policy_values(controller,logits,self.dt),self.dt,self.y)
            b=online_rollout(model,controller,self.x,self.dt,self.y)
        self.assertTrue(torch.equal(a['read_count'],b['reads']))
        self.assertTrue(torch.equal(a['terminal_prediction'],b['prediction']))
        self.assertTrue(torch.equal(a['value_utility'],b['utility']))


if __name__=='__main__':unittest.main()
