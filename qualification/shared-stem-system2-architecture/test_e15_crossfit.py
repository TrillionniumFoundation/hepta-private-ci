"""E15 actual frozen logits + original-ID source checks; labels are synthetic ONLY here."""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from e14_multirc_route import ARCHIVE_SHA, read_prelabel, positive, write_once, strict_json
import e15_reader_crossfit as fit
import e15_independent_score as score

ARCHIVE = os.environ.get('HEPTA_E15_ARCHIVE')


class E15(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = ARCHIVE if ARCHIVE and Path(ARCHIVE).is_file() else None

    def original(self):
        if not self.archive:
            self.skipTest('real original ModernBERT/Reader ZIP unavailable for local optional tests')
        return read_prelabel(self.archive)

    def synthetic_labels(self,obs):
        # Deliberately NOT original human truth, never count as real efficacy.
        byquestion={}
        for r in obs['rows']:
            byquestion.setdefault((r['source_group'],r['question_slot']),[]).append(r['task_id'])
        return {task:int(index%2) for ids in byquestion.values() for index,task in enumerate(ids)}

    def test_01_real_pretrained_observation_is_strictly_pinned(self):
        o=self.original()
        self.assertEqual(sha256(Path(self.archive).read_bytes()).hexdigest(), ARCHIVE_SHA)
        self.assertEqual((len(o['rows']),len(fit.groups(o))),(33,4))

    def test_02_labelblind_question_geometry(self):
        o=self.original()
        rows=fit.observations(o)
        self.assertEqual(len(rows),33)
        self.assertEqual(len(rows[0]['probs']),4)
        self.assertEqual(len(rows[0]['raw']),5)
        self.assertEqual(len(rows[0]['gate']),3)

    def test_03_exact_real_reader_answer_insensitivity(self):
        diag=fit.answer_signal_gate(self.original())
        self.assertEqual((diag['conditioned_near_invariant_count'],
                          diag['conditioned_exact_tie_count']), (8,4))
        self.assertFalse(diag['system2_full_fbsde_admitted'])

    def test_04_all_four_train_folds_exclude_held_labels(self):
        obs=self.original();labels=self.synthetic_labels(obs)
        for i in range(4):
            with self.subTest(i=i):
                t=fit.training_input(obs,labels,i)
                self.assertEqual(len(fit.verify_train(obs,t)),33-len([r for r in obs['rows'] if r['source_group']==t['held_group']]))
                self.assertTrue(set(fit.verify_train(obs,t)).isdisjoint({r['task_id'] for r in obs['rows'] if r['source_group']==t['held_group']}))
                self.assertFalse(t['held_labels_exposed'])

    def test_05_material_rejects_missing_real_ids_and_types(self):
        o=self.original();labels=self.synthetic_labels(o)
        for broken in ({},{k:v for k,v in labels.items() if k!=o['rows'][0]['task_id']},
                       {**labels,o['rows'][0]['task_id']:True}):
            with self.assertRaises(ValueError):fit.training_input(o,broken,0)
        for badfold in (-1,4,True,'0'):
            with self.assertRaises(ValueError):fit.training_input(o,labels,badfold)

    def test_06_training_material_fails_on_held_label_insertion(self):
        o=self.original();t=fit.training_input(o,self.synthetic_labels(o),0)
        leak=copy.deepcopy(t)
        held=next(r['task_id'] for r in o['rows'] if r['source_group']==t['held_group'])
        leak['training_label_rows'].append({'task_id':held,'label':1})
        with self.assertRaises(ValueError):fit.verify_train(o,leak)

    def test_07_training_material_fails_on_foreign_revision_or_source(self):
        o=self.original();t=fit.training_input(o,self.synthetic_labels(o),1)
        for name,value in [('source_archive_sha256','a'*64),
                           ('original_validation_human_label_source_sha256','b'*64),
                           ('held_group','not-original'),('authority','ALLOW'),
                           ('held_labels_exposed',True),('future_observation_window',True)]:
            bad={**t,name:value}
            with self.subTest(name=name),self.assertRaises(ValueError):fit.verify_train(o,bad)

    def test_08_actual_tiny_sgd_updates_with_synthetic_labels(self):
        o=self.original();t=fit.training_input(o,self.synthetic_labels(o),2)
        a=fit.train_one(o,t)
        self.assertEqual(len(a['predictions']),10)
        self.assertEqual([len(a['weights'][v]) for v in fit.PARAMS], [5,3])
        self.assertTrue(all(any(abs(w)>1e-8 for w in a['weights'][v]) for v in fit.PARAMS))
        self.assertFalse(a['causal_improvement_established'])

    def test_09_independent_parameter_and_prediction_reconstruction(self):
        o=self.original();t=fit.training_input(o,self.synthetic_labels(o),3)
        a=fit.train_one(o,t)
        data=score.independent_features(o)
        original=fit.observations(o)
        for method in fit.PARAMS:
            x,_=fit.fit(original,fit.verify_train(o,t),method)
            y=score.independently_fit(data,fit.verify_train(o,t),method)
            self.assertLess(max(abs(u-v) for u,v in zip(x,y,strict=True)),2e-12)
            for row in a['predictions']:
                d=next(v for v in data if v['task_id']==row['task_id'])
                self.assertAlmostEqual(row['probs'][method],score.independent_probability(d,y,method),delta=2e-12)

    def test_10_training_cpu_is_paid_and_model_calls_not_fabricated(self):
        o=self.original();a=fit.train_one(o,fit.training_input(o,self.synthetic_labels(o),0))
        self.assertEqual(a['new_pretrained_forwards'],0)
        self.assertFalse(a['full_training_cost_included'])
        self.assertTrue(all(x['train_cpu_ns']>0 and x['held_cpu_ns']>0 for x in a['meters'].values()))

    def test_11_labelblind_training_does_not_read_zip_score_members(self):
        o=self.original();t=fit.training_input(o,self.synthetic_labels(o),0)
        seen=[]
        original=ZipFile.read
        def spy(inst,n,*a,**kw):
            seen.append(n)
            return original(inst,n,*a,**kw)
        with patch.object(ZipFile,'read',spy):
            obs=read_prelabel(self.archive);fit.train_one(obs,t)
        self.assertEqual(set(seen),{'multirc-native-candidate-audit/audit.json',
                                    'multirc-native-candidate-audit/COMMITTED.json'})

    def test_12_source_fingerprints_cannot_be_posthoc_changed(self):
        o=self.original();t=fit.training_input(o,self.synthetic_labels(o),0)
        a=fit.train_one(o,t)
        self.assertEqual(a['train_only_label_input_sha256'],fit.digest(t))
        altered={**t,'training_label_rows':copy.deepcopy(t['training_label_rows'])}
        altered['training_label_rows'][0]['label']^=1
        self.assertNotEqual(a['train_only_label_input_sha256'],fit.digest(altered))

    def test_13_independent_4fold_replay_on_SYNTHETIC_labels_not_human(self):
        o=self.original();labels=self.synthetic_labels(o)
        # Isolation test: independent reviewer is patched with explicitly fake
        # human data. These numbers must NEVER be reported as real MultiRC.
        with TemporaryDirectory() as td:
            files=[];hashes=[]
            for i in range(4):
                t=fit.training_input(o,labels,i)
                a=fit.train_one(o,t)
                p=str(Path(td)/f'fold{i}.json')
                h=write_once(p,a)
                files.append(p);hashes.append(h)
            baseline={}
            feat=score.independent_features(o)
            for j,arm in enumerate(score.ARMS):
                correct=sum((r['p'][j]>=.5)==bool(labels[r['task_id']]) for r in feat)
                brier=sum(2*(r['p'][j]-labels[r['task_id']])**2 for r in feat)/33
                baseline[arm]={'correct':correct,'brier':brier}
            with patch.object(score,'read_validation',return_value=[{'synthetic':True}]), \
                 patch.object(score,'original_labels',return_value=labels), \
                 patch.object(score,'historical_owner_score',return_value={'results':baseline}):
                result=score.verify_score(self.archive,'fake.parquet',files,hashes)
            self.assertEqual(result['original_candidate_count'],33)
            self.assertEqual(result['conditioned_exact_tie_question_count'],4)
            self.assertFalse(result['trained_cell_head_production_admitted'])

    def test_14_forged_learned_params_fail_independent_replay(self):
        o=self.original();labels=self.synthetic_labels(o)
        with TemporaryDirectory() as td:
            files=[]; hashes=[]
            for i in range(4):
                rec=fit.train_one(o,fit.training_input(o,labels,i))
                if i==0:rec['weights']['learned_gated_3'][0]+=1
                p=str(Path(td)/f'f{i}.json')
                hashes.append(write_once(p,rec));files.append(p)
            feat=score.independent_features(o)
            baseline={}
            for j,arm in enumerate(score.ARMS):
                baseline[arm]={'correct':sum((r['p'][j]>=.5)==bool(labels[r['task_id']]) for r in feat),
                               'brier':sum(2*(r['p'][j]-labels[r['task_id']])**2 for r in feat)/33}
            with patch.object(score,'read_validation',return_value=[{'synthetic':True}]), \
                 patch.object(score,'original_labels',return_value=labels), \
                 patch.object(score,'historical_owner_score',return_value={'results':baseline}), \
                 self.assertRaisesRegex(ValueError,'forged learned'):
                score.verify_score(self.archive,'fake.parquet',files,hashes)

    def test_15_unsealed_mutation_rejected(self):
        o=self.original();a=fit.train_one(o,fit.training_input(o,self.synthetic_labels(o),0))
        with TemporaryDirectory() as td:
            p=str(Path(td)/'out.json')
            h=write_once(p,a)
            self.assertEqual(sha256(Path(p).read_bytes()).hexdigest(),h)
            self.assertRaises(FileExistsError,write_once,p,a)
            b=json.loads(Path(p).read_text());b['production_accepted']=True
            Path(p).write_text(json.dumps(b))
            self.assertNotEqual(h,sha256(Path(p).read_bytes()).hexdigest())

    def test_16_folds_require_original_exclusive_group(self):
        o=self.original();t=fit.training_input(o,self.synthetic_labels(o),0)
        bad=copy.deepcopy(t)
        bad['held_group']=fit.groups(o)[2]
        with self.assertRaises(ValueError):fit.train_one(o,bad)

    def test_17_legacy_system2_gate_stays_off_without_semantic_evidence(self):
        diag=fit.answer_signal_gate(self.original())
        self.assertFalse(diag['system2_full_fbsde_admitted'])
        self.assertTrue(diag['uncalibrated_variance_does_not_prove_semantic_reasoning'])

    def test_18_no_math_model_uses_held_original_truth(self):
        o=self.original()
        a=fit.train_one(o,fit.training_input(o,self.synthetic_labels(o),1))
        for p in a['predictions']:
            self.assertEqual(set(p),{'task_id','source_group','question_slot','candidate_id','probs'})
        self.assertFalse(a['held_original_human_labels_accessed'])

if __name__=='__main__':unittest.main()
