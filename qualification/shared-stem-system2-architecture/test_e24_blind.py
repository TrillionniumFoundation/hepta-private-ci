"""E24 unlabelled real-pretrained source + SYNTHETIC target mechanism tests."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from math import exp,log
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from e14_multirc_route import read_prelabel, write_once
from e15_reader_crossfit import training_input
from e24_question_risk import (METHODS,TAU,blind_identity,fit_one,fit_group_risk,features,
                               question_groups,_weights_gradient,scales)

SRC=os.environ.get('HEPTA_E24_ORIGINAL') or os.environ.get('HEPTA_E23_ORIGINAL') or os.environ.get('HEPTA_E16_ARCHIVE')

class E24BlindContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SRC or not Path(SRC).is_file():
            raise RuntimeError('E24 requires genuine original pretrained output ZIP: never skip')
        cls.obs=read_prelabel(SRC)
        cls.rows=features(cls.obs)
        cls.blind=blind_identity(cls.obs)
        questions={}
        for r in cls.rows:
            questions.setdefault((r['group'],r['question']),[]).append(r['task_id'])
        # These are fabricated MECHANISM-TEST labels, NEVER human source facts.
        cls.synthetic_labels={task:j%2 for ids in questions.values() for j,task in enumerate(ids)}

    def test_01_exact_original_pretrained_blind_census(self):
        self.assertEqual((len(self.rows),len(self.blind['questions']),len(self.blind['original_groups'])),(33,8,4))
        self.assertEqual(sum(x['n'] for x in self.blind['questions']),33)
        self.assertFalse(self.blind['label_read'])
        self.assertEqual(self.blind['new_pretrained_forwards'],0)

    def test_02_source_reader_opens_only_prelabel_zip_members(self):
        opened=[];old=ZipFile.read
        def record(inst,name,*a,**kw):
            opened.append(name);return old(inst,name,*a,**kw)
        with patch.object(ZipFile,'read',record):read_prelabel(SRC)
        self.assertEqual(set(opened),{'multirc-native-candidate-audit/audit.json',
                                    'multirc-native-candidate-audit/COMMITTED.json'})

    def test_03_four_registered_equal_parameter_methods(self):
        self.assertEqual(METHODS,('e16_scaled_brier_5','question_softworst_tau_001',
            'question_softworst_tau_010','question_softworst_tau_050'))
        self.assertEqual(tuple(TAU.values()),(.01,.1,.5))

    def test_04_synthetic_training_only_3_passage_six_complete_questions(self):
        for fold in range(4):
            mat=training_input(self.obs,self.synthetic_labels,fold)
            labels={r['task_id']:r['label'] for r in mat['training_label_rows']}
            grouped=question_groups(self.rows,labels)
            self.assertEqual(len(grouped),6)
            self.assertEqual(sum(len(q) for q in grouped),len(labels))
            self.assertEqual(sum(r['group']==mat['held_group'] for r in self.rows)+len(labels),33)

    def test_05_actual_four_fold_synthetic_label_optimizer_updates(self):
        for fold in range(4):
            mat=training_input(self.obs,self.synthetic_labels,fold)
            out=fit_one(self.obs,mat)
            self.assertEqual(out['fold'],fold)
            self.assertFalse(out['held_human_truth_read'])
            self.assertFalse(out['future_source_family_gain'])
            self.assertEqual(out['real_pretrained_model_forwards_new'],0)
            for method in METHODS:
                self.assertEqual(len(out['weights'][method]),5)
                self.assertEqual(out['meters'][method]['optimizer_updates'],48)
                self.assertGreater(out['meters'][method]['train_cpu_ns'],0)
                self.assertEqual(out['meters'][method]['training_question_count'],6)

    def test_06_full_question_worst_loss_gradient_finite_difference(self):
        mat=training_input(self.obs,self.synthetic_labels,0)
        labels={r['task_id']:r['label'] for r in mat['training_label_rows']}
        groups=question_groups(self.rows,labels)
        w=[.2,-.3,.1,.4,-.1]
        for tau in (.01,.1,.5):
            analytical=_weights_gradient(groups,w,tau)
            def actual(theta):
                losses=[]
                for q in groups:
                    values=[]
                    for x,y in q:
                        z=sum(a*b for a,b in zip(theta,x))
                        p=1/(1+exp(-z))
                        values.append((p-y)**2)
                    peak=max(values)
                    losses.append(peak+tau*log(sum(exp((z-peak)/tau) for z in values)/len(values)))
                return sum(losses)/len(groups)
            for j in range(5):
                delta=1e-6
                a=w[:];b=w[:];a[j]+=delta;b[j]-=delta
                numeric=(actual(a)-actual(b))/(2*delta)
                self.assertAlmostEqual(analytical[j],numeric,delta=2e-8)

    def test_07_train_normalizer_does_not_use_held_unlabelled_values(self):
        mat=training_input(self.obs,self.synthetic_labels,0)
        train={r['task_id'] for r in mat['training_label_rows']}
        fixed=scales(self.rows,train)
        mutated=deepcopy(self.rows)
        for row in mutated:
            if row['group']==mat['held_group']:row['x']=(2.,3.,4.,5.)
        self.assertEqual(fixed,scales(mutated,train))

    def test_08_held_original_label_injection_rejected(self):
        mat=training_input(self.obs,self.synthetic_labels,2)
        held=next(r['task_id'] for r in self.rows if r['group']==mat['held_group'])
        mat['training_label_rows'].append({'task_id':held,'label':1})
        with self.assertRaises(ValueError):fit_one(self.obs,mat)

    def test_09_incomplete_question_or_forged_group_rejected(self):
        mat=training_input(self.obs,self.synthetic_labels,1)
        labels={r['task_id']:r['label'] for r in mat['training_label_rows']}
        labels.pop(next(iter(labels)))
        with self.assertRaises(ValueError):question_groups(self.rows,labels)
        mat2=training_input(self.obs,self.synthetic_labels,1)
        mat2['source_archive_sha256']='f'*64
        with self.assertRaises(ValueError):fit_one(self.obs,mat2)

    def test_10_boolean_labels_and_unregistered_tau_rejected(self):
        mat=training_input(self.obs,self.synthetic_labels,1)
        labels={r['task_id']:r['label'] for r in mat['training_label_rows']}
        labels[next(iter(labels))]=True
        with self.assertRaises(ValueError):question_groups(self.rows,labels)
        labels={r['task_id']:r['label'] for r in mat['training_label_rows']}
        for tau in (.025,0.0,True,'0.1'):
            with self.subTest(tau=tau),self.assertRaises(ValueError):fit_group_risk(self.rows,labels,tau)

    def test_11_create_only_and_seal_rejects_second_write(self):
        with TemporaryDirectory() as d:
            p=str(Path(d)/'blind.json')
            digest=write_once(p,self.blind)
            self.assertEqual(digest,sha256(Path(p).read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):write_once(p,self.blind)

    def test_12_shadow_denial_not_research_selection(self):
        r=fit_one(self.obs,training_input(self.obs,self.synthetic_labels,0))
        self.assertFalse(r['production_accepted'])
        self.assertFalse(r['model_selected'])
        self.assertFalse(r['incremental_system2_admitted'])
        self.assertTrue(r['temperature_grid_exploratory_after_observing_historical_family'])
        self.assertFalse(r['whole_service_cost_certified'])

if __name__=='__main__':unittest.main()
