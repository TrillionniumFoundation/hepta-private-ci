"""Actual paired bounds, label ordering and frozen-panel reuse; no model downloads."""
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import execution as e, fresh_confirmation as f
from experiments.shared_stem_cell.retention_confirmation import upper_binomial, paired_confirmation


class BoundTests(unittest.TestCase):
    def test_closed_form_endpoints(self):
        for n in (1,16,256,8192):
            self.assertAlmostEqual(upper_binomial(0,n,.0125),1-.0125**(1/n),places=10)
            self.assertEqual(upper_binomial(n,n,.0125),1)

    def test_inverts_independent_direct_binomial_sum(self):
        for n in (4,16,32):
            for k in range(1,n):
                p=upper_binomial(k,n,.0125)
                actual=math.fsum(math.comb(n,j)*p**j*(1-p)**(n-j) for j in range(k+1))
                self.assertAlmostEqual(actual,.0125,places=9)

    def test_exact_small_sample_coverage_enumeration(self):
        # No Monte Carlo success-rate claim: enumerate every possible binomial count.
        for n in (3,8,16):
            for p in (.02,.2,.5,.8,.98):
                failed=math.fsum(math.comb(n,k)*p**k*(1-p)**(n-k) for k in range(n+1)
                                 if upper_binomial(k,n,.025)<p)
                self.assertLessEqual(failed,.025+1e-12)

    def test_invalid_counts_never_compute_a_bound(self):
        for args in ((True,4,.01),(1,0,.01),(5,4,.01),(1,4,float('nan')),(1,4,.8)):
            with self.assertRaises(e.InputError):upper_binomial(*args)

    def test_zero_observed_losses_does_not_prove_zero_risk(self):
        r=paired_confirmation([0]*32,[0]*32,[0]*32,[0,1]*16,cells=2,classes=2)
        self.assertFalse(r['supported_under_iid'])
        self.assertTrue(all(v['excess_error_upper']>0 for v in r['per_cell']))

    def test_large_unambiguous_paired_gain_is_detectable(self):
        r=paired_confirmation([1]*128,[0]*128,[0]*128,[0,1]*64,cells=2,classes=2)
        self.assertTrue(r['supported_under_iid'])
        self.assertEqual(r['tail_per_bound'],.0125)
        self.assertFalse(r['retention_certified'])

    def test_missing_cell_blocks_and_one_regression_blocks(self):
        for routes,candidate in (([0]*128,[0]*128),([0,1]*64,[0,1]*64)):
            r=paired_confirmation([1,0]*64,candidate,[0]*128,routes,cells=2,classes=2)
            self.assertFalse(r['supported_under_iid'])

    def test_pairing_rejects_late_bad_class_and_lengths(self):
        for candidate in ([0,True],[0,3],[0]):
            with self.assertRaises(e.InputError):
                paired_confirmation([0,0],candidate,[0,0],[0,1],cells=2,classes=2)


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.rows=f.cohort([f'unseen news {i}' for i in range(20)],[],per_phase=4)
        self.lock={'selected':'residual_corrected','parameter_counts':
                   {'bank':100,'shared':20,'residual_corrected':60,'linear_distilled':40}}

    def tearDown(self):self.temp.cleanup()

    def seal(self,directory,probabilities=None):
        directory.mkdir()
        e.write_once(directory/'candidate-lock.json',self.lock)
        cohort=e.write_once(directory/'cohort.json',self.rows)
        p=probabilities or {name:[[1.,0,0,0] for _ in self.rows]
                           for name in ('bank','shared',*f.rc.MODES)}
        return e.write_once(directory/'predictions.json',{'case_ids':[r['case_id'] for r in self.rows],
            'candidate_lock_sha256':e.sha(e.canonical(self.lock)),'cohort_sha256':cohort,'predictions':p})

    def test_exact_normalized_exclusion_and_balanced_disjoint_phases(self):
        texts=['Old  NEWS','old news','old\tnews']+[f'unseen {i}' for i in range(20)]
        rows=f.cohort(texts,['OLD news'],per_phase=4)
        self.assertEqual(len(rows),8)
        self.assertEqual(len({r['normalized_sha256'] for r in rows}),8)
        self.assertNotIn(f.normalized('old news'),{r['normalized_sha256'] for r in rows})
        for phase in ('confirmation','evaluation'):
            self.assertEqual([r['cell'] for r in rows if r['split']==phase],[0,1,0,1])

    def test_selection_has_no_answer_accessor_and_never_shrinks(self):
        class TextOnly:
            def __iter__(self):return iter([f'text {i}' for i in range(8)])
            def __getitem__(self,key):raise AssertionError('no label-bearing row access')
        self.assertEqual(len(f.cohort(TextOnly(),[],per_phase=4)),8)
        with self.assertRaises(e.InputError):f.cohort(['same']*100,[],per_phase=4)

    def test_predictions_precede_labels_and_confirmation_precedes_evaluation(self):
        out=self.root/'run'; seal=self.seal(out); calls=[]
        positions={r['source_index']:r for r in self.rows}
        def label(index):
            self.assertTrue((out/'predictions.json').exists())
            if positions[index]['split']=='evaluation':self.assertTrue((out/'confirmation.json').exists())
            calls.append(index); return 0
        result=f.evaluate_sealed(out,seal,self.lock,self.rows,label)
        self.assertEqual(calls,[r['source_index'] for r in self.rows])
        self.assertEqual(result['chosen'],'bank')

    def test_evaluation_labels_cannot_change_confirmation(self):
        decisions=[]
        for number in (0,1):
            out=self.root/str(number);seal=self.seal(out)
            test={r['source_index'] for r in self.rows if r['split']=='evaluation'}
            f.evaluate_sealed(out,seal,self.lock,self.rows,lambda i:number if i in test else 0)
            decisions.append((out/'confirmation.json').read_bytes())
        self.assertEqual(*decisions)

    def test_best_other_arm_cannot_replace_frozen_proposal(self):
        p={name:[[0.,1,0,0] for _ in self.rows] for name in ('bank','shared',*f.rc.MODES)}
        p['shared']=[[1.,0,0,0] for _ in self.rows]
        out=self.root/'run';seal=self.seal(out,p)
        result=f.evaluate_sealed(out,seal,self.lock,self.rows,lambda i:0)
        self.assertEqual(result['chosen'],'bank')
        self.assertEqual(result['scores']['shared']['correct'],4)

    def test_tampered_lock_or_cohort_rejected_before_labels(self):
        for file in ('candidate-lock.json','cohort.json'):
            out=self.root/file;seal=self.seal(out)
            (out/file).write_text('{}')
            with patch.object(f,'paired_confirmation') as score,self.assertRaises(e.InputError):
                f.evaluate_sealed(out,seal,self.lock,self.rows,lambda i:self.fail('premature labels'))
            score.assert_not_called()

    def test_missing_or_nonfinite_arm_rejects_before_labels(self):
        for bad in (None,float('nan')):
            out=self.root/str(bad);seal=self.seal(out)
            doc=e.decode((out/'predictions.json').read_bytes())
            if bad is None:doc['predictions'].pop('shared')
            else:doc['predictions']['shared'][-1]=[2.,-1.,0,0]
            (out/'predictions.json').unlink();seal=e.write_once(out/'predictions.json',doc)
            with self.assertRaises(e.InputError):
                f.evaluate_sealed(out,seal,self.lock,self.rows,lambda i:self.fail('premature labels'))

    def test_original_panel_to_fresh_execution_with_explicit_synthetic_encoder(self):
        from experiments.shared_stem_cell.consolidation_study import study as consolidate
        old=self.root/'original';old.mkdir();output=self.root/'fresh'
        torch.manual_seed(17);features=torch.randn(12,8)
        rows=[{'case_id':str(i),'group':str(i),'split':'train' if i<6 else
               'calibration' if i<8 else 'holdout','observed_at':None,'cell':i%2,
               'scope':'fixture','text':f'sample:{i}','label':i%4} for i in range(12)]
        raw=b''.join(e.canonical(r) for r in rows);(old/'dataset.jsonl').write_bytes(raw)
        config={'schema':'hepta.shared-stem-execution.v1','classes':4,'cells':2,'steps':2,
            'seed':17,'temporal':False,'maximum_tokens':512,'batch_size':8,'export_frozen_features':True,
            'model':{'path':'model','model_id':'jhu-clsp/mmBERT-small','revision':f.MODEL_REVISION},
            'dataset':{'path':'dataset.jsonl','sha256':e.sha(raw)}}
        e.write_once(old/'manifest.json',config)
        e.write_once(old/'acquisition.json',{'dataset_id':'fancyzhx/ag_news','dataset_revision':f.DATA_REVISION})
        class Encoder:
            simulated=True
            identity=e.sha(e.canonical(config['model']))
            def __init__(self,*args):pass
            def encode(self,texts):
                return torch.stack([features[int(t.split(':')[1])] if t.startswith('sample:')
                                    else torch.arange(8).float()/8 for t in texts])
            def close(self):pass
        with patch.object(e,'LocalEncoder',Encoder):e.run(old/'manifest.json',old/'execution')
        producer_sha=e.sha((old/'execution/report.json').read_bytes())
        target=self.root/'consolidation'
        consolidate(old/'manifest.json',old/'execution',producer_sha,target,ridge=True)
        consolidation_sha=e.sha((target/'report.json').read_bytes())
        calls=[]
        class Source:
            def __getitem__(source,key):
                if key=='text':return [f'fresh news {i}' for i in range(20)]
                self.assertTrue((output/'predictions.json').is_file())
                calls.append(key);return {'text':f'fresh news {key}','label':key%4}
        module=SimpleNamespace(load_dataset=lambda *a,**kw:Source())
        with patch.dict(sys.modules,{'datasets':module}),patch.object(e,'LocalEncoder',Encoder), \
                patch.object(f,'PER_PHASE',4),patch.object(e,'fit',side_effect=AssertionError('no refit')), \
                patch.object(torch.linalg,'svd',side_effect=AssertionError('no new solve')):
            result=f.run(old,target,producer_sha,consolidation_sha,output)
        self.assertEqual(result['encoding']['encoder_forward_calls'],1)
        self.assertEqual(result['extra_optimizer_steps'],0)
        self.assertEqual(len(calls),8)
        self.assertEqual(result['chosen_score']['cases'],4)
        self.assertFalse(result['retention_certified'])


if __name__=='__main__':unittest.main()
