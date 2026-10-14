"""Real sequential accounting/seals plus explicit simulated-Encoder integration."""
from decimal import Decimal, localcontext
from pathlib import Path
import math
import tempfile
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import execution as e, sequential_confirmation as s
from experiments.shared_stem_cell.sequential_evidence import PairedEvidence, log_evidence, BETS


class EvidenceTests(unittest.TestCase):
    def test_equal_mixture_matches_independent_high_precision_products(self):
        with localcontext() as ctx:
            ctx.prec = 70
            for gain, loss in ((0,0),(7,3),(18,7),(1000,300),(0,8192),(8192,0)):
                values = [((1+Decimal(b))**gain)*((1-Decimal(b))**loss) for b in BETS]
                expected = float((sum(values)/4).ln())
                self.assertAlmostEqual(log_evidence(gain,loss),expected,places=9)

    def test_optional_stopping_null_probability_by_exact_state_recursion(self):
        # Sum ALL paths up to each time, including stopped paths, not simulation.
        for pg, pl in ((.5,.5),(.15,.15),(.1,.4)):
            active, crossing = {(0,0):1.0}, 0.0
            for _ in range(40):
                next_states = {}
                for (g,l),mass in active.items():
                    for dg,dl,prob in ((1,0,pg),(0,1,pl),(0,0,1-pg-pl)):
                        pair = g+dg,l+dl
                        if log_evidence(*pair) >= math.log(20)+1e-8:
                            crossing += mass*prob
                        else:
                            next_states[pair] = next_states.get(pair,0.0)+mass*prob
                active = next_states
                self.assertLessEqual(crossing,.05+1e-12)
                self.assertAlmostEqual(sum(active.values())+crossing,1.,places=11)

    def test_ties_are_not_nonregression_evidence(self):
        st=PairedEvidence()
        report=st.update([str(i) for i in range(128)],[0]*128,[0]*128,[0]*128,[0,1]*64)
        self.assertFalse(report['all_crossed'])
        self.assertEqual([v['log_evidence'] for v in report['per_cell']],[0.,0.])

    def test_only_covered_improving_cells_stop(self):
        st=PairedEvidence()
        report=st.update([str(i) for i in range(64)],[1]*64,[0]*64,[0]*64,[0]*64)
        self.assertTrue(report['per_cell'][0]['crossed'])
        self.assertFalse(report['all_crossed'])
        with self.assertRaises(e.InputError): st.update(['next'],[1],[0],[0],[0])

    def test_late_bad_class_and_duplicate_rows_are_transactional(self):
        st=PairedEvidence();before=st.snapshot()
        for ids,labels in ((['a','b'],[0,True]),(['a','a'],[0,0])):
            with self.assertRaises(e.InputError):st.update(ids,[0,0],[0,0],labels,[0,1])
            self.assertEqual(st.snapshot(),before)
        st.update(['a'],[0],[0],[0],[0]);before=st.snapshot()
        with self.assertRaises(e.InputError):st.update(['a'],[0],[0],[0],[0])
        self.assertEqual(st.snapshot(),before)

    def test_counts_reject_bad_types_and_budget(self):
        for pair in ((True,1),(-1,2),(8193,1),(1.,2)):
            with self.assertRaises(e.InputError):log_evidence(*pair)
        for kw in ({'alpha':float('nan')},{'alpha':.2},{'cells':True},{'classes':1}):
            with self.assertRaises(e.InputError):PairedEvidence(**kw)


class StreamTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.rows=s.cohort([f'brand new text {i}' for i in range(500)],[],confirmation=256,final=16)
        self.lock={'selected':'residual_corrected','parameter_counts':
                   {'bank':100,'shared':20,'residual_corrected':60,'linear_distilled':40}}

    def tearDown(self):self.tmp.cleanup()

    def execute(self,out,kind='gain',final_label=0):
        out.mkdir();calls=[];answers=[]
        lookup={r['source_index']:r for r in self.rows}
        def forward(part):
            if part[0]['split']=='evaluation':self.assertTrue((out/'decision.json').exists())
            calls.extend(r['case_id'] for r in part)
            p={key:[] for key in s.NAMES}
            for row in part:
                for key in s.NAMES:
                    good=key=='residual_corrected' and (kind=='gain' or (kind=='cell0' and row['cell']==0))
                    p[key].append([1.,0,0,0] if good else [0.,1,0,0])
            return {'predictions':p,'encoding':{'encoder_forward_calls':math.ceil(len(part)/8),'requests':len(part)}}
        def label(index):
            row=lookup[index]
            self.assertIn(row['case_id'],calls)
            files=list(out.glob('*-predictions.json'))
            self.assertTrue(any(row['case_id'] in e.decode(p.read_bytes())['case_ids'] for p in files))
            if row['split']=='evaluation':self.assertTrue((out/'decision.json').exists())
            answers.append(index)
            return final_label if row['split']=='evaluation' else 0
        result=s.stream(out,self.rows,self.lock,forward,label)
        return result,calls,answers

    def test_real_batch_stopping_prevents_later_encoder_and_label_calls(self):
        result,calls,answers=self.execute(self.root/'run')
        self.assertEqual(result['chosen'],'residual_corrected')
        self.assertEqual(result['encoded_confirmation_rows'],64)
        self.assertEqual(result['unencoded_confirmation_rows'],192)
        self.assertEqual(len(calls),80)
        self.assertEqual(len(answers),80)
        decision=e.decode((self.root/'run/decision.json').read_bytes())
        self.assertFalse(set(calls).intersection(decision['unencoded_confirmation_ids']))

    def test_one_cell_stops_other_consumes_full_cap(self):
        result,calls,_=self.execute(self.root/'run','cell0')
        self.assertEqual(result['chosen'],'bank')
        self.assertEqual(result['encoded_confirmation_rows'],160)
        self.assertEqual(len(calls),176)

    def test_final_labels_cannot_change_confirmation(self):
        self.execute(self.root/'a',final_label=0);self.execute(self.root/'b',final_label=1)
        self.assertEqual((self.root/'a/decision.json').read_bytes(),(self.root/'b/decision.json').read_bytes())

    def test_non_saving_candidate_never_encodes_confirmation(self):
        self.lock['parameter_counts']['residual_corrected']=101
        result,calls,_=self.execute(self.root/'run')
        self.assertEqual(result['chosen'],'bank');self.assertEqual(len(calls),16)

    def test_equal_model_hits_cap_no_zero_loss_shortcut(self):
        result,calls,_=self.execute(self.root/'run','tie')
        self.assertEqual(result['encoded_confirmation_rows'],256)
        self.assertEqual(result['chosen'],'bank');self.assertEqual(len(calls),272)

    def test_exact_exclusion_and_full_pool_size_without_labels(self):
        texts=['old NEWS','old  news']+[f'text:{i}' for i in range(400)]
        rows=s.cohort(texts,['OLD news'],confirmation=128,final=32)
        self.assertEqual(len(rows),160)
        self.assertNotIn(s.f.normalized('old news'),{r['normalized_sha256'] for r in rows})
        with self.assertRaises(e.InputError):s.cohort(['same']*300,[],confirmation=128,final=32)

    def test_invalid_prediction_rejects_before_first_label(self):
        for mode in ('missing','bad'):
            out=self.root/mode;out.mkdir()
            def forward(part):
                p={k:[[1.,0,0,0] for _ in part] for k in s.NAMES}
                if mode=='missing':p.pop('bank')
                else:p['bank'][-1]=[2.,-1,0,0]
                return {'predictions':p}
            with self.assertRaises(e.InputError):
                s.stream(out,self.rows,self.lock,forward,lambda i:self.fail('premature label'))
            self.assertFalse((out/'decision.json').exists())

    def test_tampered_lock_during_forward_rejects_before_answers(self):
        out=self.root/'run';out.mkdir()
        def forward(part):
            (out/'candidate-lock.json').write_text('{}')
            return {'predictions':{k:[[1.,0,0,0] for _ in part] for k in s.NAMES}}
        with self.assertRaises(e.InputError):
            s.stream(out,self.rows,self.lock,forward,lambda i:self.fail('premature label'))

    def test_duplicate_normalized_cohort_refused_before_forward(self):
        out=self.root/'run';out.mkdir();self.rows[-1]['normalized_sha256']=self.rows[0]['normalized_sha256']
        with self.assertRaises(e.InputError):
            s.stream(out,self.rows,self.lock,lambda p:self.fail('premature forward'),lambda i:0)


    def test_actual_panel_export_to_previous_to_new_stream_without_refitting(self):
        import sys
        from types import SimpleNamespace
        from experiments.shared_stem_cell.consolidation_study import study as consolidate
        old=self.root/'original';old.mkdir()
        torch.manual_seed(17);features=torch.randn(12,8)
        records=[{'case_id':str(i),'group':str(i),'split':'train' if i<6 else
            'calibration' if i<8 else 'holdout','observed_at':None,'cell':i%2,'scope':'fixture',
            'text':f'sample:{i}','label':i%4} for i in range(12)]
        raw=b''.join(e.canonical(r) for r in records);(old/'dataset.jsonl').write_bytes(raw)
        config={'schema':'hepta.shared-stem-execution.v1','classes':4,'cells':2,'steps':2,'seed':17,
            'temporal':False,'maximum_tokens':512,'batch_size':8,'export_frozen_features':True,
            'model':{'path':'model','model_id':'jhu-clsp/mmBERT-small','revision':s.f.MODEL_REVISION},
            'dataset':{'path':'dataset.jsonl','sha256':e.sha(raw)}}
        e.write_once(old/'manifest.json',config)
        e.write_once(old/'acquisition.json',{'dataset_id':'fancyzhx/ag_news','dataset_revision':s.f.DATA_REVISION})
        class Encoder:
            simulated=True
            identity=e.sha(e.canonical(config['model']))
            calls=[]
            def __init__(self,*args):pass
            def encode(self,texts):
                self.calls.extend(texts)
                return torch.stack([features[int(t.split(':')[1])] if t.startswith('sample:')
                                    else torch.arange(8).float()/8 for t in texts])
            def close(self):pass
        with patch.object(e,'LocalEncoder',Encoder):e.run(old/'manifest.json',old/'execution')
        prod=e.sha((old/'execution/report.json').read_bytes());cons=self.root/'consolidation'
        consolidate(old/'manifest.json',old/'execution',prod,cons,ridge=True)
        cons_sha=e.sha((cons/'report.json').read_bytes())
        target=self.root/'previous';current=self.root/'current';labels=[]
        class Source:
            def __getitem__(source,key):
                if key=='text':return [f'news item {i}' for i in range(500)]
                labels.append(key);return {'text':f'news item {key}','label':key%4}
        module=SimpleNamespace(load_dataset=lambda *a,**kw:Source())
        with patch.dict(sys.modules,{'datasets':module}),patch.object(e,'LocalEncoder',Encoder), \
                patch.object(s.f,'PER_PHASE',4),patch.object(e,'fit',side_effect=AssertionError('no fitting')), \
                patch.object(torch.linalg,'svd',side_effect=AssertionError('no SVD')):
            s.f.run(old,cons,prod,cons_sha,target)
            previous_sha=e.sha((target/'report.json').read_bytes())
            old_seen=set(Encoder.calls);Encoder.calls=[];labels.clear()
            with patch.object(s,'CONFIRM',32),patch.object(s,'FINAL',8),patch.object(s,'CHUNK_PER_CELL',4):
                result=s.run(old,cons,prod,cons_sha,target,previous_sha,current)
        self.assertFalse(old_seen.intersection(Encoder.calls))
        self.assertEqual(len(labels),result['encoded_confirmation_rows']+8)
        self.assertEqual(len(Encoder.calls),len(labels))
        self.assertTrue(result['source_simulated_encoder'])
        self.assertEqual(result['extra_optimizer_steps'],0)
        self.assertEqual(result['extra_svd_calls'],0)
        panel,_,_,lock=s.f.load_panel(old,cons,prod,cons_sha)
        lock['component_manifests']=[]
        with self.assertRaises(e.InputError):s.prior_rows(target,previous_sha,lock)


if __name__=='__main__':unittest.main()
