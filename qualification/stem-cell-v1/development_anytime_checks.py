"""Actual gradient, parameter-equivalence and frozen-input tests."""

import unittest
import torch
from development_ablation import RecurrentClassifier, fit_candidate
from development_anytime import fit_anytime_candidate
from development_tensors import parameter_digest


class AnytimeTests(unittest.TestCase):
    def setUp(self):
        self.rng = torch.random.fork_rng(devices=[])
        self.rng.__enter__()
        self.threads = torch.get_num_threads()
        torch.set_num_threads(1)
        torch.manual_seed(1404)
        self.model = RecurrentClassifier(4,2,depth=4)
        self.x = torch.randn(16,3,4,requires_grad=True)
        self.y = (self.x[:,:,0].sum(1)>0).long()

    def tearDown(self):
        torch.set_num_threads(self.threads)
        self.rng.__exit__(None,None,None)

    def test_shared_parameters_and_real_backward_without_frozen_source_mutation(self):
        identity = parameter_digest(self.model)
        out,r = fit_anytime_candidate(self.model,self.x,self.y,steps=20)
        self.assertEqual(identity,parameter_digest(self.model))
        self.assertNotEqual(identity,parameter_digest(out))
        self.assertEqual(sum(p.numel() for p in out.parameters()),sum(p.numel() for p in self.model.parameters()))
        self.assertIsNone(self.x.grad)
        self.assertEqual(r['cell_transitions'],1280)
        self.assertEqual(r['readout_rows'],1280)
        self.assertFalse(r['equal_actual_training_compute_claimed'])

    def test_terminal_only_weight_matches_existing_fitter(self):
        terminal,_ = fit_candidate(self.model,self.x,self.y,steps=3,seed=15,lr=.02)
        candidate,report = fit_anytime_candidate(self.model,self.x,self.y,steps=3,seed=15,
                                                depth_weights=(0,0,0,1))
        for key,value in terminal.state_dict().items():
            torch.testing.assert_close(candidate.state_dict()[key],value,rtol=0,atol=1e-8)
        self.assertEqual(report['readout_rows'],48)
        self.assertEqual(report['supervised_depths'],[4])

    def test_all_supervised_exits_improve_training_loss(self):
        _,r = fit_anytime_candidate(self.model,self.x,self.y,steps=100)
        self.assertTrue(all(b<a for a,b in zip(r['initial_losses'],r['last_losses'])))

    def test_invalid_weights_steps_and_labels_fail(self):
        for w in ((0,0,0,0),(1,1,1),(1,1,float('nan'),1),(True,1,1,1)):
            with self.assertRaises(ValueError):
                fit_anytime_candidate(self.model,self.x,self.y,depth_weights=w)
        with self.assertRaises(ValueError):
            fit_anytime_candidate(self.model,self.x,self.y,steps=True)
        with self.assertRaises(ValueError):
            fit_anytime_candidate(self.model,self.x,torch.full((16,),2,dtype=torch.long))


if __name__ == '__main__':
    unittest.main()
