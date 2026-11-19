"""Original pretrained ModernBERT Reader archive + SYNTHETIC LABEL mechanism tests.

Never claim actual MultiRC learning or independent outcome efficacy here. The
real original human labels enter a separate hosted post-seal scoring job.
"""
from __future__ import annotations

import copy
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from e14_multirc_route import read_prelabel, write_once, ARCHIVE_SHA
from e15_reader_crossfit import training_input, groups, observations
import e16_answer_centered as learner
import e16_independent_score as reviewer

ZIP = os.environ.get('HEPTA_E16_ARCHIVE')


class E16(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ZIP or not Path(ZIP).is_file():
            raise RuntimeError('E16 requires original real pretrained ZIP, never silently skip')
        cls.raw = read_prelabel(ZIP)
        cls.records = learner.features(cls.raw)
        cls.labels = cls.synthetic_labels(cls.raw)

    @staticmethod
    def synthetic_labels(obs):
        grouped = {}
        for row in obs['rows']:
            grouped.setdefault((row['source_group'], row['question_slot']), []).append(row['task_id'])
        return {item: idx % 2 for ids in grouped.values() for idx, item in enumerate(ids)}

    def test_01_archive_byte_identity(self):
        self.assertEqual(sha256(Path(ZIP).read_bytes()).hexdigest(), ARCHIVE_SHA)
        self.assertEqual(len(self.records), 33)

    def test_02_four_source_eight_question_slate(self):
        self.assertEqual(len(groups(self.raw)), 4)
        self.assertEqual(len({(r['group'], r['question']) for r in self.records}), 8)

    def test_03_centering_zero_sum_per_original_question(self):
        per = {}
        for row in self.records:
            per.setdefault((row['group'], row['question']), []).append(row)
        for key, rows in per.items():
            for j in (0, 1, 2):
                with self.subTest(key=key,j=j):
                    self.assertLess(abs(sum(r['x'][j] for r in rows)), 1e-12)

    def test_04_no_query_reader_is_exactly_answer_invariant(self):
        orig = observations(self.raw)
        per = {}
        for row in orig:
            per.setdefault((row['source_group'], row['question_slot']), []).append(row['raw'][4])
        self.assertTrue(all(max(x) == min(x) for x in per.values()))

    def test_05_real_conditioned_information_signal_small(self):
        per = {}
        for row in self.records:
            per.setdefault((row['group'],row['question']), []).append(row['x'][0])
        self.assertEqual(len(per),8)
        self.assertTrue(all(max(x)-min(x)<1e-3 for x in per.values()))

    def test_06_train_only_scaler_and_shapes(self):
        for fold in range(4):
            with self.subTest(fold=fold):
                mat = training_input(self.raw,self.labels,fold)
                train = {r['task_id'] for r in mat['training_label_rows']}
                units = learner.scales(self.records,train)
                self.assertEqual(len(units),4)
                self.assertTrue(all(isinstance(v,float) and v>=1e-5 for v in units))
                self.assertEqual(len(train)+sum(r['group']==mat['held_group'] for r in self.records),33)

    def test_07_normalizer_must_not_use_held_source(self):
        mat=training_input(self.raw,self.labels,0)
        train={r['task_id'] for r in mat['training_label_rows']}
        units=learner.scales(self.records,train)
        changed=copy.deepcopy(self.records)
        for row in changed:
            if row['group']==mat['held_group']:
                row['x']=(100.,100.,100.,100.)
        self.assertEqual(units,learner.scales(changed,train))

    def test_08_real_sgd_five_parameters_48_steps(self):
        material=training_input(self.raw,self.labels,1)
        output=learner.train_fold(self.raw,material)
        self.assertEqual(len(output['predictions']),len([r for r in self.records if r['group']==material['held_group']]))
        for method in learner.METHODS:
            self.assertEqual(len(output['weights'][method]),5)
            self.assertTrue(any(abs(x)>1e-8 for x in output['weights'][method]))
            self.assertEqual(output['meters'][method]['steps'],48)
            self.assertGreater(output['meters'][method]['train_cpu_ns'],0)
            self.assertGreater(output['meters'][method]['held_cpu_ns'],0)

    def test_09_full_independent_weight_and_probability_replay(self):
        for fold in range(4):
            mat=training_input(self.raw,self.labels,fold)
            output=learner.train_fold(self.raw,mat)
            independent=reviewer.separate_geometry(self.raw)
            train={r['task_id']:r['label'] for r in mat['training_label_rows']}
            for method in learner.METHODS:
                weight,norm,_=reviewer.fit_independent(independent,train,method)
                self.assertLess(max(abs(a-b) for a,b in zip(weight,output['weights'][method],strict=True)),2e-12)
                self.assertLess(max(abs(a-b) for a,b in zip(norm,output['train_only_scaling'],strict=True)),1e-12)
                for item in output['predictions']:
                    row=next(r for r in independent if r['task_id']==item['task_id'])
                    self.assertAlmostEqual(item['probabilities'][method],reviewer.probability(row,method,weight,norm),delta=2e-12)

    def test_10_incomplete_or_bad_train_reject(self):
        mat=training_input(self.raw,self.labels,2)
        for op in ('missing','held','bad-label','wrong-source'):
            candidate=copy.deepcopy(mat)
            if op=='missing':candidate['training_label_rows'].pop()
            elif op=='held':candidate['training_label_rows'].append({'task_id':next(r['task_id'] for r in self.raw['rows'] if r['source_group']==candidate['held_group']),'label':1})
            elif op=='bad-label':candidate['training_label_rows'][0]['label']=True
            else:candidate['source_archive_sha256']='f'*64
            with self.subTest(op=op),self.assertRaises(ValueError):learner.train_fold(self.raw,candidate)

    def test_11_original_zip_score_members_not_read_for_blind_fit(self):
        mat=training_input(self.raw,self.labels,1)
        seen=[]
        original=ZipFile.read
        def logzip(inst,name,*a,**kwargs):
            seen.append(name)
            return original(inst,name,*a,**kwargs)
        with patch.object(ZipFile,'read',logzip):
            a=read_prelabel(ZIP)
            learner.train_fold(a,mat)
        self.assertEqual(set(seen),{'multirc-native-candidate-audit/audit.json',
                                    'multirc-native-candidate-audit/COMMITTED.json'})

    def test_12_no_held_truth_or_model_invocation(self):
        r=learner.train_fold(self.raw,training_input(self.raw,self.labels,0))
        self.assertFalse(r['held_human_labels_accessed'])
        self.assertEqual(r['original_model_forwards_new'],0)
        self.assertFalse(r['total_service_cost_measured'])
        self.assertEqual(set(r['predictions'][0]),{'task_id','source_group','question_slot','candidate_id','probabilities'})

    def test_13_src_only_outputs_differ_between_scaled_and_raw_heads(self):
        r=learner.train_fold(self.raw,training_input(self.raw,self.labels,3))
        self.assertTrue(any(abs(p['probabilities'][learner.METHODS[0]]-p['probabilities'][learner.METHODS[1]])>1e-7 for p in r['predictions']))

    def test_14_exact_create_once_and_changed_sha_reject(self):
        r=learner.train_fold(self.raw,training_input(self.raw,self.labels,0))
        with TemporaryDirectory() as td:
            dest=str(Path(td)/'first.json')
            digest=write_once(dest,r)
            self.assertEqual(digest,sha256(Path(dest).read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):write_once(dest,r)
            Path(dest).write_text(Path(dest).read_text()+'\n')
            self.assertNotEqual(digest,sha256(Path(dest).read_bytes()).hexdigest())

    def _synthetic_reviewer(self,files,hashes):
        baseline=reviewer.independent_features(self.raw)
        controls={}
        for j,arm in enumerate(reviewer.ARMS):
            ys=[int((r['p'][j]>=.5)==bool(self.labels[r['task_id']])) for r in baseline]
            brier=sum(2*(r['p'][j]-self.labels[r['task_id']])**2 for r in baseline)/33
            controls[arm]={'correct':sum(ys),'brier':brier}
        with patch.object(reviewer,'read_validation',return_value=[{'synthetic':True}]),\
             patch.object(reviewer,'original_labels',return_value=self.labels),\
             patch.object(reviewer,'historical_owner_score',return_value={'results':controls}):
            return reviewer.evaluate(ZIP,'FAKE-SYNTHETIC-NOT-ORIGINAL-HUMAN',files,hashes)

    def _folds(self,td,mutator=None):
        files=[];hashes=[]
        for i in range(4):
            rec=learner.train_fold(self.raw,training_input(self.raw,self.labels,i))
            if mutator is not None: mutator(i,rec)
            path=str(Path(td)/f'fold{i}.json')
            hashes.append(write_once(path,rec));files.append(path)
        return files,hashes

    def test_15_fourfold_independent_score_with_only_SYNTHETIC_labels(self):
        with TemporaryDirectory() as td:
            files,hashes=self._folds(td)
            result=self._synthetic_reviewer(files,hashes)
        self.assertEqual((result['original_human_candidate_count'],result['original_passage_count']),(33,4))
        self.assertFalse(result['prospective_future_time_gain_established'])
        self.assertTrue(result['E15_retrospective_parent_head_source_replayed_not_E15_hosted_receipt'])
        self.assertIn(learner.METHODS[0],result['results'])
        self.assertEqual(len(result['folds']),4)

    def test_16_forged_student_weights_rejected(self):
        def mutate(i,r):
            if i==0:r['weights'][learner.METHODS[0]][1]+=0.2
        with TemporaryDirectory() as td:
            files,hashes=self._folds(td,mutate)
            with self.assertRaisesRegex(ValueError,'weight replay'):self._synthetic_reviewer(files,hashes)

    def test_17_held_predictions_corruption_rejected(self):
        def mutate(i,r):
            if i==0:r['predictions'][0]['probabilities'][learner.METHODS[1]]-=0.1
        with TemporaryDirectory() as td:
            files,hashes=self._folds(td,mutate)
            with self.assertRaisesRegex(ValueError,'probability'):self._synthetic_reviewer(files,hashes)

    def test_18_fake_training_only_scale_rejected(self):
        def mutate(i,r):
            if i==0:r['train_only_scaling'][1]*=2
        with TemporaryDirectory() as td:
            files,hashes=self._folds(td,mutate)
            with self.assertRaisesRegex(ValueError,'scaler'):self._synthetic_reviewer(files,hashes)

    def test_19_modified_authority_rejected(self):
        def mutate(i,r):
            if i==1:r['production_accepted']=True
        with TemporaryDirectory() as td:
            files,hashes=self._folds(td,mutate)
            with self.assertRaises(ValueError):self._synthetic_reviewer(files,hashes)

    def test_20_missing_fold_or_duplicate_id_rejected(self):
        with TemporaryDirectory() as td:
            files,hashes=self._folds(td)
            with self.assertRaises(ValueError):self._synthetic_reviewer(files[:3],hashes[:3])
            with self.assertRaises(ValueError):self._synthetic_reviewer(files,hashes[:3]+[hashes[0]])

    def test_21_original_scored_group_count_cannot_be_fabricated(self):
        with TemporaryDirectory() as td:
            files,hashes=self._folds(td)
            res=self._synthetic_reviewer(files,hashes)
            self.assertEqual({k:sum(v['source_passage_total'].values()) for k,v in res['results'].items()},
                             {k:33 for k in res['results']})

    def test_22_no_general_fbsde_permission_from_numeric_result(self):
        with TemporaryDirectory() as td:
            files,hashes=self._folds(td)
            res=self._synthetic_reviewer(files,hashes)
            self.assertFalse(res['pretrained_model_or_head_selected'])
            self.assertFalse(res['production_accepted'])
            self.assertFalse(res['prospective_future_time_gain_established'])


if __name__ == '__main__':
    unittest.main()
