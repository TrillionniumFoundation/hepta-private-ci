"""Actual tiny shared-cell fit/gradient/replay checks; these vectors are fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
import torch
from four_gate_common import digest
from fbsde_composition import PROFILE, make_cell, compile_batch, evaluate
from fbsde_encoder import train_and_compare
from fbsde_audit import recompute_comparison


class SharedCellTensorTests(unittest.TestCase):
    def test_same_eight_parameters_receive_gradient_across_different_tree_depths(self):
        model=make_cell(torch);identity=[id(p) for p in model.parameters()]
        formula=('or',('and',0,1),('and',2,3))
        public=[{'case_id':'x','utterance_ids':['a','b','c','d'],'target_intents':[0]*4,'formula':formula}]
        p=torch.tensor([[.8,.7,.2,.1]])
        before=model(p,compile_batch(torch,public));self.assertEqual(before.item(),.5)
        (before-1).square().backward()
        self.assertGreater(model.corners.grad.abs().sum().item(),0)
        self.assertEqual(sum(x.numel() for x in model.parameters()),8)
        self.assertEqual(identity,[id(p) for p in model.parameters()])

    def test_scalar_frozen_runtime_matches_tensor_probability(self):
        model=make_cell(torch)
        with torch.no_grad():model.corners.copy_(torch.tensor([[.1,.2,.3,.8],[.2,.7,.8,.9]]))
        formula=('and',('or',0,1),('or',2,3))
        public=[{'case_id':'x','utterance_ids':['a','b','c','d'],'target_intents':[0]*4,'formula':formula}]
        p=torch.tensor([[.4,.3,.2,.9]])
        actual=model(p,compile_batch(torch,public)).item()
        scalar=evaluate(formula,p[0].tolist(),model.corners.tolist())['probability']
        self.assertAlmostEqual(actual,scalar,places=6)

    def test_projection_preserves_bounded_probability_and_public_plan_rejects_gold(self):
        model=make_cell(torch)
        with torch.no_grad():model.corners.fill_(2.)
        model.project();self.assertLess(model.corners.max().item(),1.)
        with self.assertRaisesRegex(ValueError,'public model'):
            compile_batch(torch,[{'formula':('and',0,1),'gold':True}])


class CompositionReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.parts={};features={};torch.set_num_threads(2);torch.manual_seed(1709)
        for split in ('train','validation','calibration','test'):
            cls.parts[split]=[]
            for i in range(32):
                uid=f'{split}:{i}';label=i%4
                cls.parts[split].append({'id':uid,'intent':label,'source_sha256':digest(uid)})
                v=torch.randn(384)*.01;v[label]=2.;features[uid]=v
        cls.report=train_and_compare(torch,cls.parts,features,cls.root,104729,profile=PROFILE)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_complete_new_profile_is_arithmetically_reproducible(self):
        audit=recompute_comparison(self.root,self.parts)
        self.assertEqual(len(audit['metrics']),12)
        self.assertFalse(audit['scientific_superiority_established'])
        learned=json.loads((self.root/'composition-corners.json').read_text())
        self.assertLess(learned['final_training_bce'],learned['initial_training_bce'])
        self.assertEqual(learned['parameters'],8)

    def test_frozen_baseline_not_charged_unused_fit_and_guard_pays_fit(self):
        r=self.report
        self.assertEqual(r['adaptation_plus_inference_cpu_ns']['composition_cell']-
                         r['inference_cpu_ns']['composition_cell'],
                         r['adaptation_plus_inference_cpu_ns']['composition_guarded']-
                         r['inference_cpu_ns']['composition_guarded'])
        self.assertGreater(r['adaptation_plus_inference_cpu_ns']['composition_cell']-
                           r['inference_cpu_ns']['composition_cell'],
                           r['adaptation_plus_inference_cpu_ns']['composition_frozen']-
                           r['inference_cpu_ns']['composition_frozen'])

    def test_silently_removed_fallback_is_rejected(self):
        path=self.root/'composition_guarded-predictions.json';original=path.read_bytes()
        try:
            rows=json.loads(original);r=next(x for x in rows if x['composition']['exact_fallback'])
            r['composition']['exact_fallback']=False;path.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'fallback'):
                recompute_comparison(self.root,self.parts)
        finally:path.write_bytes(original)

    def test_corrupted_learned_corner_values_rejected(self):
        path=self.root/'composition-corners.json';original=path.read_bytes()
        try:
            values=json.loads(original);values['fitted'][0]=[.99]*4;path.write_text(json.dumps(values))
            with self.assertRaisesRegex(ValueError,'tensor bytes'):
                recompute_comparison(self.root,self.parts)
        finally:path.write_bytes(original)

    def test_full_depth_not_relabelled_as_recurrent_or_free_compute(self):
        rows=json.loads((self.root/'composition_guarded-predictions.json').read_text())
        self.assertTrue(all(r['actual_recurrent_steps']==0 and r['selected_depth']==2 for r in rows))
        self.assertTrue(all(r['composition']['guard_operator_calls']==3 for r in rows))
        self.assertTrue(all(r['cpu_ns']>0 for r in rows))

if __name__=='__main__':unittest.main()
