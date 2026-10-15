"""Original-human-only E2 source/census/tamper tests, synthetic fixtures only."""
import copy
import hashlib
import json
import math
import unittest
import numpy as np

import e1_matched_gated_head as fit
import e1_matched_gated_review as replay
from e2_seal_blind_predictions import seal, sha, MODELS, SEEDS, ARMS
from e2_original_human_score import score

SHA='6'*40
RUN=12345678


class E2SealedOriginalScore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng=np.random.default_rng(19)
        x=rng.normal(0,.2,(64,384)).astype(np.float32)
        tr=list(range(32));ca=list(range(32,40));held=list(range(40,64))
        args=(x,tr,[i%2 for i in range(32)],ca,[i%2 for i in range(8)],held)
        r,params=fit.run_probe(*args)
        numeric=replay.verify_probe(r,params,*args)
        blind={'cases':[]}
        labels={}
        # Exactly eight independent original passages, three cases per passage
        # and a distinct no-evidence control case with NO human label.
        for i in range(24):
            row={'case_id':'id%02d'%i,'view_sha256':hashlib.sha256(str(i).encode()).hexdigest(),
                 'source_group':'group%d'%(i//3),'condition':'original' if i%3<2 else 'no_evidence'}
            blind['cases'].append(row)
            if row['condition']=='original': labels[row['case_id']]=i%2
        cls.blind=blind;cls.labels=labels
        cls.source={m:{'original-model-report':m} for m in MODELS}
        cls.numeric={}
        cls.seals={}
        cls.probes={}
        for m in MODELS:
            report=copy.deepcopy(r)
            report.update({'model':m,'blind_case_ids':[c['case_id'] for c in blind['cases']],
                           'original_blind_sha256':sha(blind),
                           'original_report_sha256':sha(cls.source[m]),
                           'probe_safetensors_sha256':'a'*64})
            cls.probes[m]=report
            reviewed=dict(numeric)
            reviewed.update({'reviewed_probe_report_sha256':sha(report),
                             'reviewed_probe_weights_sha256':report['probe_safetensors_sha256'],
                             'reviewed_original_p0_report_sha256':report['original_report_sha256'],
                             'reviewed_blind_material_sha256':sha(blind),
                             'reviewed_model':m})
            cls.numeric[m]=reviewed
            cls.seals[m]=seal(blind,report,reviewed,m,SHA,RUN)

    def valid(self,**patch):
        return score(patch.get('blind',self.blind),patch.get('labels',self.labels),
                     patch.get('p0',self.source),patch.get('numeric',self.numeric),patch.get('seals',self.seals),
                     patch.get('probes',self.probes),
                     original_p0_scored=patch.get('p0_ok',True),
                     current_candidate_sha=patch.get('sha',SHA),
                     current_run_id=patch.get('run',RUN))

    def test_all_models_all_seeds_human_only(self):
        out=self.valid()
        self.assertEqual(set(out['models']),set(MODELS))
        self.assertEqual(out['original_human_cases'],16)
        self.assertEqual(out['original_human_source_groups'],8)
        for m in MODELS:
            self.assertEqual(set(out['models'][m]['seeds']),{'41','47','53'})
            for s in SEEDS:
                x=out['models'][m]['seeds'][str(s)]
                self.assertEqual(set(x['arms']),set(ARMS))
                self.assertEqual(x['arms']['trained_gated']['original_rows'],16)
                self.assertEqual(len(x['paired']['trained']['per_original_source_group_gains']),8)
        self.assertTrue(all(z['reconstructed_exact_original_prelabel_forecasts']
                            for z in out['models'].values()))
        self.assertFalse(out['model_or_head_winner_selected'])
        self.assertFalse(out['production_promotion_permitted'])

    def test_blind_seal_contains_no_train_or_held_labels(self):
        for s in self.seals.values():
            self.assertEqual(len(s['forecasts']),12)
            self.assertFalse(s['original_human_labels_included'])
            self.assertFalse(any('labels' in k and k != 'original_human_labels_included' for k in s))
            self.assertNotIn('blind_logits',json.dumps(s))
            self.assertNotIn('tensor',json.dumps(s))

    def test_missing_model_and_numeric_precheck_refused(self):
        s=dict(self.seals);del s[MODELS[0]]
        with self.assertRaises(ValueError):self.valid(seals=s)
        with self.assertRaises(ValueError):self.valid(p0_ok=False)

    def test_wrong_source_candidate_run_or_original_report_refused(self):
        for variant in (dict(sha='7'*40),dict(run=RUN+1),dict(p0={m:{'different':m} for m in MODELS})):
            with self.subTest(variant=variant),self.assertRaises(ValueError):self.valid(**variant)

    def test_changed_independent_numeric_review_refused(self):
        new=copy.deepcopy(self.numeric)
        new[MODELS[0]]['max_probability_disagreement']+=0.00001
        with self.assertRaisesRegex(ValueError,'numeric-only review'):
            self.valid(numeric=new)

    def test_missing_numeric_review_arm_refused(self):
        new=dict(self.numeric);new.pop(MODELS[0])
        with self.assertRaises(ValueError):self.valid(numeric=new)

    def test_swapped_blind_or_original_case_refused(self):
        altered=copy.deepcopy(self.blind)
        altered['cases'][1],altered['cases'][0]=altered['cases'][0],altered['cases'][1]
        with self.assertRaises(ValueError):self.valid(blind=altered)
        altered=copy.deepcopy(self.blind);altered['cases'][0]['view_sha256']='f'*64
        with self.assertRaises(ValueError):self.valid(blind=altered)

    def test_missing_duplicate_or_invalid_source_refused(self):
        for how in ('remove','duplicate','condition','group'):
            altered=copy.deepcopy(self.blind)
            if how=='remove':altered['cases'].pop()
            if how=='duplicate':altered['cases'][0]['case_id']=altered['cases'][1]['case_id']
            if how=='condition':altered['cases'][0]['condition']='invented'
            if how=='group':altered['cases'][0]['source_group']=99
            with self.subTest(how=how),self.assertRaises(ValueError):self.valid(blind=altered)

    def test_missing_or_forged_human_label_refused(self):
        for change in ('missing','extra','bool','other'):
            labels=dict(self.labels)
            if change=='missing':labels.pop(next(iter(labels)))
            elif change=='extra':labels['no-human-label']=1
            elif change=='bool':labels[next(iter(labels))]=True
            else:labels[next(iter(labels))]=2
            with self.subTest(change=change),self.assertRaises(ValueError):self.valid(labels=labels)

    def test_truncated_or_reordered_seed_grid_refused(self):
        for mutate in ('remove','duplicate','reorder'):
            seals=copy.deepcopy(self.seals);f=seals[MODELS[0]]['forecasts']
            if mutate=='remove':f.pop()
            if mutate=='duplicate':f.append(copy.deepcopy(f[-1]))
            if mutate=='reorder':f[0],f[1]=f[1],f[0]
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.valid(seals=seals)

    def test_swapped_changed_nonfinite_or_incomplete_prediction_refused(self):
        for how in ('too-short','nan','inf','outside','not-number'):
            seals=copy.deepcopy(self.seals);p=seals[MODELS[0]]['forecasts'][0]['probabilities']
            if how=='too-short':p.pop()
            if how=='nan':p[0]=float('nan')
            if how=='inf':p[0]=float('inf')
            if how=='outside':p[0]=1.2
            if how=='not-number':p[0]='wrong'
            with self.subTest(how=how),self.assertRaises(ValueError):self.valid(seals=seals)

    def test_false_authority_and_source_origin_claims_refused(self):
        for field in ('original_human_labels_included','original_future_windows_verified',
                      'independently_signed','source_origin_authenticated',
                      'production_promotion_permitted'):
            seals=copy.deepcopy(self.seals);seals[MODELS[0]][field]=True
            with self.subTest(field=field),self.assertRaises(ValueError):self.valid(seals=seals)
        seals=copy.deepcopy(self.seals);seals[MODELS[0]]['authority']='GRANTED'
        with self.assertRaises(ValueError):self.valid(seals=seals)

    def test_incorrect_parent_model_source_sha_refused(self):
        for key in ('p0_source_sha','p0_run_id','blind_material_sha256','original_report_sha256'):
            seals=copy.deepcopy(self.seals);seals[MODELS[0]][key]='wrong'
            with self.subTest(key=key),self.assertRaises(ValueError):self.valid(seals=seals)

    def test_valid_length_probability_forgery_is_refused(self):
        # This is the critical E2 v2 regression: v1 accepted this mutation.
        fake=copy.deepcopy(self.seals)
        p=fake[MODELS[0]]['forecasts'][7]['probabilities']
        p[0]=0.99 if p[0]<0.5 else 0.01
        with self.assertRaisesRegex(ValueError,'producer output'):
            self.valid(seals=fake)

    def test_matching_bogus_probe_report_sha_still_refused(self):
        forged=copy.deepcopy(self.seals)
        report=copy.deepcopy(self.probes)
        report[MODELS[0]]['arms'][3]['blind_probabilities'][4]=0.999
        # Attacker updates report hash and copied probabilities but does not
        # possess a matching independently verified training+numeric receipt.
        forged[MODELS[0]]['probe_report_sha256']=sha(report[MODELS[0]])
        forged[MODELS[0]]['forecasts'][3]['probabilities'][4]=0.999
        with self.assertRaisesRegex(ValueError,'independently replayed'):
            self.valid(seals=forged,probes=report)

    def test_independent_numeric_review_does_not_authenticate_forged_report(self):
        numeric=copy.deepcopy(self.numeric)
        numeric[MODELS[0]]['reviewed_probe_report_sha256']='0'*64
        with self.assertRaises(ValueError):self.valid(numeric=numeric)

    def test_seal_requires_original_numeric_replay_digest(self):
        report=self.probes[MODELS[0]]
        doc=copy.deepcopy(self.numeric[MODELS[0]])
        doc['reviewed_probe_report_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'independently replayed'):
            seal(self.blind,report,doc,MODELS[0],SHA,RUN)

    def test_original_probe_report_required_and_same_model(self):
        missing=dict(self.probes)
        missing.pop(MODELS[0])
        with self.assertRaises(ValueError):self.valid(probes=missing)
        substituted=copy.deepcopy(self.probes)
        substituted[MODELS[0]]=substituted[MODELS[1]]
        with self.assertRaises(ValueError):self.valid(probes=substituted)

    def test_core_score_does_not_import_trainer_or_torch(self):
        import subprocess,sys
        done=subprocess.run([sys.executable,'-c',
            "import sys,e2_original_human_score; assert 'torch' not in sys.modules; assert 'e1_matched_gated_head' not in sys.modules"],
            capture_output=True,text=True)
        self.assertEqual(done.returncode,0,done.stderr)

    def test_no_label_or_model_source_in_seal_module(self):
        import inspect,e2_seal_blind_predictions
        self.assertNotIn('original_label_audit',inspect.getsource(e2_seal_blind_predictions))
        self.assertNotIn('original_rows(',inspect.getsource(e2_seal_blind_predictions))

    def test_seal_refuses_failed_numeric_and_unregistered_model(self):
        with self.assertRaises(ValueError):
            seal(self.blind,{}, {},'ModernBERT',SHA,RUN)
        args=self.blind; base={}; reviewer={'schema':'bad'}
        with self.assertRaises(ValueError):
            seal(args,base,reviewer,MODELS[0],SHA,RUN)
        bad=copy.deepcopy(self.seals[MODELS[0]]);
        for r in bad['forecasts']:
            self.assertEqual(len(r['probabilities']),24)
        self.assertIsNone(bad.get('labels'))


if __name__=='__main__':unittest.main()
