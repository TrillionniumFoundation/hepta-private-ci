"""Physical CPU mechanics on SYNTHETIC features, NOT pretrained model efficacy."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import numpy as np
import torch
import e1_matched_gated_head as producer
import e1_matched_gated_review as reviewer


class MatchedProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {}
        for width in (256,384,768):
            x = np.random.default_rng(7).normal(0,.2,(56,width)).astype(np.float32)
            args = (x,list(range(32)),[i%2 for i in range(32)],list(range(32,40)),
                    [i%2 for i in range(8)],list(range(40,56)))
            r,w = producer.run_probe(*args)
            cls.runs[width] = (args,r,w)

    def verify(self, r=None, w=None, args=None):
        a,report,weights = self.runs[384]
        return reviewer.verify_probe(report if r is None else r, weights if w is None else w,
                                     *(a if args is None else args))

    def test_three_widths_actual_sgd_and_independent_replay(self):
        for width,(args,r,w) in self.runs.items():
            with self.subTest(width=width):
                out=reviewer.verify_probe(r,w,*args)
                self.assertEqual(out['trial_count'],12)
                self.assertLess(out['max_weight_disagreement'],3e-5)
                self.assertLess(out['max_probability_disagreement'],3e-5)

    def test_every_parameter_has_a_real_gradient(self):
        for kind in ('gated','additive'):
            with self.subTest(kind=kind):
                head=producer.MatchedHead(kind)
                head(torch.randn(8,128)).square().mean().backward()
                self.assertEqual(sum(p.numel() for p in head.parameters()),4145)
                self.assertTrue(all(p.grad is not None and p.grad.abs().sum()>0 for p in head.parameters()))

    def test_frozen_states_unchanged_and_trained_states_different(self):
        for _,r,w in self.runs.values():
            for arm in r['arms']:
                changed=arm['initial_sha256']!=arm['final_sha256']
                self.assertEqual(changed,arm['arm'].startswith('trained_'))
                actual=sum(w[f"seed{arm['seed']}.{arm['arm']}.{k}"].size for k in reviewer.SHAPES)
                self.assertEqual(actual,arm['parameter_count'])

    def test_repeated_execution_is_weight_and_prediction_deterministic(self):
        args,r,w=self.runs[384]
        again,tensors=producer.run_probe(*args)
        for k in w: np.testing.assert_array_equal(w[k],tensors[k])
        self.assertEqual([a['blind_probabilities'] for a in r['arms']],
                         [a['blind_probabilities'] for a in again['arms']])

    def test_one_split_storage_shared_by_every_head_and_seed(self):
        args,_,_=self.runs[384]; seen={};calls=[]
        old=producer.MatchedHead.forward
        def observe(head,x):
            seen.setdefault(len(x),set()).add(x.data_ptr());calls.append(len(x))
            return old(head,x)
        with patch.object(producer.MatchedHead,'forward',observe):
            producer.run_probe(*args)
        self.assertEqual({k:len(v) for k,v in seen.items()},{32:1,8:1,16:1})
        self.assertEqual(calls.count(32),240)
        self.assertEqual(calls.count(8),12)
        self.assertEqual(calls.count(16),12)

    def test_original_feature_bank_and_global_rng_not_mutated(self):
        args,_,_=self.runs[384]; x=args[0].copy(); state=torch.get_rng_state().clone()
        threads=torch.get_num_threads(); producer.run_probe(*args)
        np.testing.assert_array_equal(x,args[0]);self.assertTrue(torch.equal(state,torch.get_rng_state()))
        self.assertEqual(torch.get_num_threads(),threads)

    def test_no_held_labels_parameter(self):
        with self.assertRaises(TypeError): producer.run_probe(*self.runs[384][0],held_labels=[1]*16)

    def test_bad_feature_matrices_refused(self):
        original=self.runs[384][0]
        matrices=[original[0].astype(np.float64),original[0][:,:128],original[0][:,0]]
        for value in (float('nan'),float('inf'),9.):
            x=original[0].copy();x[0,0]=value;matrices.append(x)
        for x in matrices:
            with self.subTest(shape=x.shape),self.assertRaises(ValueError): producer.run_probe(x,*original[1:])

    def test_duplicate_overlap_outofrange_boolean_indices_refused(self):
        a=self.runs[384][0]
        for idx in ([0]*32,[-1]+list(range(31)),[1000]+list(range(31)),[True]+list(range(1,32)),list(range(8,40))):
            with self.subTest(idx=idx[:2]),self.assertRaises(ValueError): producer.run_probe(a[0],idx,*a[2:])

    def test_bad_training_or_calibration_labels_refused(self):
        a=self.runs[384][0]
        for position,values in ((2,[0]*32),(2,[True]*32),(2,[0,1]),(4,[1]*8),(4,[0]*7+[2])):
            b=list(a);b[position]=values
            with self.subTest(position=position,values=values[:2]),self.assertRaises(ValueError): producer.run_probe(*b)

    def test_source_feature_tamper_refused(self):
        a=list(self.runs[384][0]);a[0]=a[0].copy();a[0][0,0]+=.01
        with self.assertRaises(ValueError): self.verify(args=a)

    def test_projection_tamper_refused_even_with_unchanged_budget(self):
        w=copy.deepcopy(self.runs[384][2]);w['shared_projection'][0,0]+=.01
        with self.assertRaises(ValueError): self.verify(w=w)

    def test_changed_and_rehashed_trained_weights_refused(self):
        _,r,w=self.runs[384];r=copy.deepcopy(r);w=copy.deepcopy(w)
        w['seed41.trained_gated.out.bias']+=.1
        st={k:w['seed41.trained_gated.'+k] for k in reviewer.SHAPES}
        r['arms'][3]['final_sha256']=reviewer.sha_state(st)
        with self.assertRaisesRegex(ValueError,'SGD replay'): self.verify(r,w)

    def test_wrong_original_training_labels_refused(self):
        a=list(self.runs[384][0]);a[2]=[1-y for y in a[2]]
        with self.assertRaisesRegex(ValueError,'SGD replay'): self.verify(args=a)

    def test_missing_duplicate_or_reordered_trial_refused(self):
        base=self.runs[384][1]
        for arms in (base['arms'][:-1],base['arms']+[base['arms'][0]],list(reversed(base['arms']))):
            r=copy.deepcopy(base);r['arms']=arms
            with self.assertRaises(ValueError): self.verify(r)

    def test_wrong_physical_count_or_steps_refused(self):
        for key,val in (('parameter_count',1),('optimizer_steps',0),('training_row_exposures',1)):
            r=copy.deepcopy(self.runs[384][1]);r['arms'][1][key]=val
            with self.subTest(key=key),self.assertRaises(ValueError): self.verify(r)

    def test_tampered_missing_or_nonfinite_forecast_refused(self):
        for val in ([.5], [float('nan')]*16,[.1]*16):
            r=copy.deepcopy(self.runs[384][1]);r['arms'][0]['blind_probabilities']=val
            with self.assertRaises(ValueError): self.verify(r)

    def test_unregistered_temperature_refused(self):
        r=copy.deepcopy(self.runs[384][1]);r['arms'][0]['temperature']=4.
        with self.assertRaises(ValueError): self.verify(r)

    def test_tensor_inventory_and_shape_refused(self):
        for mode in ('missing','extra','shape'):
            w=copy.deepcopy(self.runs[384][2])
            if mode=='missing':del w['seed41.frozen_gated.out.bias']
            elif mode=='extra':w['unused_padding']=np.zeros(1,dtype=np.float32)
            else:w['seed41.frozen_gated.out.bias']=np.zeros(2,dtype=np.float32)
            with self.subTest(mode=mode),self.assertRaises(ValueError): self.verify(w=w)

    def test_fabricated_free_projection_refused(self):
        for key in ('fp32_bytes','coefficient_count','linear_forward_macs','split_buffer_bytes'):
            r=copy.deepcopy(self.runs[384][1]);r['shared_projection'][key]=0
            with self.subTest(key=key),self.assertRaises(ValueError): self.verify(r)

    def test_false_success_authority_and_extra_encoder_claims_refused(self):
        for key in ('held_labels_accessed','quality_scored','model_selection_permitted',
                    'production_promotion_permitted','end_to_end_cost_equal',
                    'native_representation_preserved','timing_is_counterbalanced',
                    'physical_model_origin_independently_authenticated','genuine_deployed_nochange_baseline'):
            r=copy.deepcopy(self.runs[384][1]);r[key]=True
            with self.subTest(key=key),self.assertRaises(ValueError): self.verify(r)
        for key in ('additional_pretrained_loads','additional_encoder_forwards'):
            r=copy.deepcopy(self.runs[384][1]);r[key]=1
            with self.subTest(key=key),self.assertRaises(ValueError): self.verify(r)

    def test_reviewer_imports_neither_torch_nor_producer(self):
        done=subprocess.run([sys.executable,'-c',
            "import sys,e1_matched_gated_review; assert 'torch' not in sys.modules; assert 'e1_matched_gated_head' not in sys.modules"],
            cwd=Path(__file__).parent,capture_output=True,text=True,check=False)
        self.assertEqual(done.returncode,0,done.stderr)


if __name__=='__main__': unittest.main()
