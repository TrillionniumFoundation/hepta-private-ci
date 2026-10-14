"""Actual tensor training + blind labeled material; no mocked predictions."""
import copy
import json
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from multirc_materials import (prepare_panels,validate_panel_bundles,load_parquet,
                               _group_inputs)
from multirc_reader_study import (train_then_predict,score_sealed,publish,check_seal,_features,ARMS)
from next_round_matrix import _digest


def fixture_rows(count=9,split='train'):
    output=[]
    for p in range(count):
        for q in range(2):
            for a in range(2):
                output.append(dict(idx=dict(paragraph=p,question=q,answer=a),
                    paragraph=f'{split} passage {p}. River level is {p%2}. Price rises {p%3}.',
                    question=['Is the river high?','Did the price rise?'][q],
                    answer=['affirmative','negative'][a],label=(p+q+a)%2))
    return output


def panels():
    return prepare_panels(fixture_rows(),fixture_rows(7,'val'),seed=7347,
                          train_passages=5,val_passages=4,
                          dataset_sha256_train='a'*64,dataset_sha256_val='b'*64)


class DummyEncoder:
    def __init__(self):
        self.trained=False
        self.calls=[]
    def __call__(self,text):
        self.calls.append(('evidence',text,self.trained))
        p=torch.tensor([float(sum(ord(x) for x in text)%7),float(len(text)%11),1.,2.])
        return torch.stack([p,p,p]) / 10.
    def query(self,text):
        self.calls.append(('query',text,self.trained))
        if 'river' in text.lower():return torch.tensor([1.,0.,.3,.2])
        return torch.tensor([0.,1.,.1,.4])


class MaterialTests(unittest.TestCase):
    def test_admit_genuine_nested_multi_question_schema(self):
        tr,ev,l=panels()
        self.assertTrue(validate_panel_bundles(tr,ev))
        self.assertEqual((len(tr['rows']),len(ev['rows']),len(l['labels'])),(5,4,8))
        self.assertEqual(sum(len(v['questions']) for v in tr['rows']),10)
        self.assertTrue(all('label' not in q for r in ev['rows'] for q in r['questions']))
        self.assertTrue(all('label' in q for r in tr['rows'] for q in r['questions']))
        self.assertFalse(tr['training_data_license_approved'])

    def test_selection_is_label_blind_and_does_not_depend_on_row_order(self):
        tr,ev,lb=panels()
        a=fixture_rows();b=fixture_rows(7,'val')
        for row in a+b:row['label']=1-row['label']
        for rows in (a,b):rows.reverse()
        alt_tr,alt_ev,alt_label=prepare_panels(a,b,seed=7347,train_passages=5,val_passages=4,
                    dataset_sha256_train='a'*64,dataset_sha256_val='b'*64)
        self.assertEqual(ev['rows'],alt_ev['rows'])
        self.assertEqual([[q['task_id'] for q in r['questions']] for r in tr['rows']],
                         [[q['task_id'] for q in r['questions']] for r in alt_tr['rows']])
        self.assertNotEqual(lb['labels'],alt_label['labels'])

    def test_mixed_source_or_duplicate_content_rejected(self):
        a=fixture_rows();b=fixture_rows(7,'val')
        b[0]['paragraph']=a[0]['paragraph']
        with self.assertRaisesRegex(ValueError,'conflicting evidence text'):
            prepare_panels(a,b,seed=7,train_passages=5,val_passages=4,
                           dataset_sha256_train='a'*64,dataset_sha256_val='b'*64)

    def test_missing_question_rejected_before_any_training(self):
        a=fixture_rows(count=3)
        a[:]=[r for r in a if r['idx']['question']==0]
        with self.assertRaisesRegex(ValueError,'insufficient eligible'):
            prepare_panels(a,fixture_rows(7,'val'),seed=7,train_passages=2,val_passages=4,
                           dataset_sha256_train='a'*64,dataset_sha256_val='b'*64)

    def test_duplicates_future_eval_labels_wrong_header_and_mutation_rejected(self):
        tr,ev,_=panels()
        for how in ('label','cross_group','missing','changed','wrong_sha'):
            t,e=copy.deepcopy(tr),copy.deepcopy(ev)
            if how=='label':e['rows'][0]['questions'][0]['label']=1
            elif how=='cross_group':e['rows'][0]['source_group']=t['rows'][0]['source_group']
            elif how=='missing':e['rows'].pop()
            elif how=='changed':e['rows'][0]['evidence']='test content replaced'
            else:e['source_sha256_train']='b'*64
            with self.subTest(how=how),self.assertRaises(ValueError):
                validate_panel_bundles(t,e)

    def test_invalid_types_and_bool_labels_rejected(self):
        for how in ('label_bool','idx_bool','duplicate_answer','bad_rows'):
            a=fixture_rows();b=fixture_rows(7,'val')
            if how=='label_bool':a[0]['label']=True
            if how=='idx_bool':a[0]['idx']['question']=True
            if how=='duplicate_answer':a.append(copy.deepcopy(a[0]))
            if how=='bad_rows':a[0]['unrecognized']=1
            with self.subTest(how=how),self.assertRaises(ValueError):
                prepare_panels(a,b,seed=7,train_passages=5,val_passages=4,
                               dataset_sha256_train='a'*64,dataset_sha256_val='b'*64)

    def test_content_digest_before_parquet_import(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'pretend.parquet';p.write_bytes(b'not a parquet file')
            with self.assertRaisesRegex(ValueError,'externally pinned checksum'):
                load_parquet(p,expected_sha256='0'*64)


class ExtendedSourceMaterialTests(unittest.TestCase):
    def test_duplicate_passage_text_not_counted_as_independent_source(self):
        train=fixture_rows(9)
        first=next(r['paragraph'] for r in train if r['idx']['paragraph']==0)
        for row in train:
            if row['idx']['paragraph']==1:
                row['paragraph']=first
        tr,ev,_=prepare_panels(train,fixture_rows(7,'val'),seed=7347,
            train_passages=5,val_passages=4,dataset_sha256_train='a'*64,
            dataset_sha256_val='b'*64)
        self.assertEqual(len({r['evidence'].casefold() for r in tr['rows']}),5)
        self.assertTrue(validate_panel_bundles(tr,ev))
        bad=copy.deepcopy(tr)
        bad['rows'][1]['evidence']=bad['rows'][0]['evidence']
        with self.assertRaisesRegex(ValueError,'duplicate source evidence'):
            validate_panel_bundles(bad,ev)

    def test_material_provenance_downgrade_rejected(self):
        tr,ev,_=panels()
        for name, value in (('revision','main'),('repo','other/source'),
                            ('training_data_license_approved',True),
                            ('pretraining_contamination_ruled_out',True)):
            a,b=copy.deepcopy(tr),copy.deepcopy(ev)
            a[name]=value;b[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):
                validate_panel_bundles(a,b)


class ModelAndScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train,cls.evaluation,cls.labels=panels()
        cls.encoder=DummyEncoder()
        cls.loader_called=[]
        def load():
            cls.loader_called.append(True)
            # Assert after all four Reader fits via a patch in caller tests.
            return copy.deepcopy(cls.evaluation)
        cls.observation,cls.readers=train_then_predict(cls.train,load,
            encoder=cls.encoder,question_encoder=cls.encoder.query,
            checkpoint_sha256='c'*64,seed=7347,steps=8)

    def test_actual_four_optimizations_and_complete_predictions(self):
        o=self.observation
        self.assertEqual((o['train_passages'],o['eval_passages']), (5,4))
        self.assertEqual((o['actual_train_encoder_calls'],o['actual_eval_encoder_calls']),(5,4))
        self.assertEqual(len(self.loader_called),1)
        self.assertEqual(set(o['predictions']),{'conditioned','mean_pool_query_fused','no_evidence','no_query'})
        self.assertTrue(all(len(v)==8 for v in o['predictions'].values()))
        self.assertEqual(len(set(o['arm_parameter_counts'].values())),1)
        self.assertTrue(all(o['training'][arm]['steps']==8 for arm in o['training']))
        self.assertFalse(o['trained_reader_generalization_established'])

    def test_per_passage_feature_storage_is_shared_not_duplicated(self):
        tr,ev,_=panels()
        encoder=DummyEncoder()
        obs,_=train_then_predict(tr,lambda:ev,encoder=encoder,
            question_encoder=encoder.query,checkpoint_sha256='c'*64,
            steps=1,max_cache_bytes=800)
        # (5 training + 4 heldout) passages; each 3x4 float32 evidence
        # tensor occurs ONCE and the two 4-vector queries occur separately.
        self.assertEqual(obs['retained_feature_bytes'],9*(3*4*4+2*4*4))
        self.assertEqual(obs['actual_train_encoder_calls']+obs['actual_eval_encoder_calls'],9)
        with self.assertRaisesRegex(ValueError,'retained token/query feature'):
            train_then_predict(tr,lambda:ev,encoder=DummyEncoder(),
                question_encoder=DummyEncoder().query,checkpoint_sha256='c'*64,
                steps=1,max_cache_bytes=719)

    def test_complete_paired_controls_count_lost_and_recovered_per_passage(self):
        result=score_sealed(self.observation,self.labels,
            expected_observation_id=self.observation['observation_id'],
            expected_label_sha256=_digest(self.labels))
        self.assertEqual(set(result['paired_controls']),set(ARMS)-{'conditioned'})
        for control, comparison in result['paired_controls'].items():
            self.assertEqual(sum(r['total'] for r in comparison['by_passage'].values()),8)
            self.assertEqual(sum(r['conditioned_recovered'] for r in comparison['by_passage'].values()),
                             comparison['recovered'])
            self.assertEqual(sum(r['conditioned_lost'] for r in comparison['by_passage'].values()),
                             comparison['lost'])
            self.assertEqual(comparison['recovered']-comparison['lost'],
                             result['results']['conditioned']['correct']-result['results'][control]['correct'])
        self.assertTrue(result['repeated_answer_rows_not_independent_passages'])
        self.assertFalse(result['real_world_qa_established'])

    def test_source_text_was_materialized_after_all_trained_reader_calls(self):
        tr,ev,_=panels()
        import multirc_reader_study as study
        counter=[]
        original=study.fit_reader
        def tracked(*a,**k):
            counter.append('fit')
            return original(*a,**k)
        def loader():
            self.assertEqual(counter,['fit']*4)
            counter.append('eval_input')
            return copy.deepcopy(ev)
        with patch.object(study,'fit_reader',side_effect=tracked):
            train_then_predict(tr,loader,encoder=DummyEncoder(),
                question_encoder=DummyEncoder().query,checkpoint_sha256='c'*64,
                steps=2)
        self.assertEqual(counter[-1],'eval_input')

    def test_mean_pool_still_uses_question_and_no_evidence_keeps_query(self):
        states=torch.tensor([[1.,2.,3.,4.],[5.,6.,7.,8.]])
        q=torch.tensor([1.,2.,3.,4.])
        pooled,_=_features(states,q,'mean_pool_query_fused')
        changed,_=_features(states,q*2,'mean_pool_query_fused')
        self.assertFalse(torch.equal(pooled,changed))
        absent,_=_features(states,q,'no_evidence')
        self.assertTrue(torch.equal(absent,q.unsqueeze(0)))
        no_q,z=_features(states,q,'no_query')
        self.assertTrue(torch.equal(no_q,states))
        self.assertTrue(torch.equal(z,torch.zeros_like(q)))

    def test_cli_model_failure_is_retained_without_successful_seal(self):
        from multirc_reader_study import main
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            tr=root/'train.json';tr.write_text(json.dumps(self.train))
            candidate=root/'failed-model'
            args=['tool','run','--train-bundle',str(tr),'--blind-eval-bundle',str(root/'eval.json'),
                  '--snapshot',str(root/'missing-model'),'--output',str(candidate)]
            with patch.object(sys,'argv',args), patch('multirc_reader_study.safe_encoder',side_effect=ValueError('no pinned checkpoint')):
                with self.assertRaisesRegex(ValueError,'no pinned checkpoint'):
                    main()
            failure=json.loads((candidate/'FAILED.json').read_text())
            self.assertEqual(failure['error_type'],'ValueError')
            self.assertFalse(failure['production_authorized'])
            self.assertFalse((candidate/'COMMITTED.json').exists())

    def test_actual_after_seal_scoring_does_not_fit(self):
        o=self.observation;l=self.labels
        with patch('multirc_reader_study.fit_reader',side_effect=AssertionError('scoring retrained')):
            result=score_sealed(o,l,expected_observation_id=o['observation_id'],
                                expected_label_sha256=_digest(l))
        self.assertEqual(result['schema'],'hepta.multirc.real-question-evaluation.v1')
        self.assertTrue(all(r['total']==8 and len(r['passage_groups'])==4 for r in result['results'].values()))
        self.assertFalse(result['resource_efficiency_established'])
        self.assertFalse(result['model_selected'])

    def test_label_changes_only_affect_scores_not_frozen_predictions(self):
        o=copy.deepcopy(self.observation);l=copy.deepcopy(self.labels)
        before=o['observation_id']
        result1=score_sealed(o,l,expected_observation_id=before,expected_label_sha256=_digest(l))
        key=next(iter(l['labels']))
        l['labels'][key]=1-l['labels'][key]
        result2=score_sealed(o,l,expected_observation_id=before,expected_label_sha256=_digest(l))
        self.assertNotEqual(result1['label_sha256'],result2['label_sha256'])
        self.assertEqual(before,o['observation_id'])

    def test_missing_label_reordered_predictions_wrong_weights_and_tampered_receipt_reject(self):
        o=self.observation;l=self.labels
        for how in ('missing','reordered','weights','changed_obs','panel'):
            co=copy.deepcopy(o);cl=copy.deepcopy(l)
            if how=='missing':cl['labels'].pop(next(iter(cl['labels'])))
            if how=='reordered':co['predictions']['conditioned'].reverse()
            if how=='weights':co['predictions']['conditioned'][0]['weights_sha256']='a'*64
            if how=='changed_obs':co['seed']=2
            if how=='panel':cl['panel_id']='a'*64
            with self.subTest(how=how),self.assertRaises(ValueError):
                score_sealed(co,cl,expected_observation_id=o['observation_id'],
                            expected_label_sha256=_digest(cl))

    def test_exclusive_seal_and_weight_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run'
            seal=publish(root,self.observation,self.readers)
            self.assertEqual(check_seal(root,seal['seal_id'])['observation_id'],self.observation['observation_id'])
            with self.assertRaises(FileExistsError):publish(root,self.observation,self.readers)
            bank=root/'conditioned.safetensors';bank.write_bytes(bank.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'sealed bank'):
                check_seal(root,seal['seal_id'])

    def test_future_eval_labels_must_never_be_in_model_load(self):
        train,evaluation,_=panels()
        evaluation['rows'][0]['questions'][0]['label']=1
        with self.assertRaises(ValueError):
            train_then_predict(train,lambda:evaluation,encoder=DummyEncoder(),
                question_encoder=DummyEncoder().query,checkpoint_sha256='c'*64,steps=1)

    def test_incomplete_encoder_feature_or_bad_evaluator_never_pass(self):
        train,_,_=panels()
        encoder=DummyEncoder()
        def bad(_):return torch.ones(1),8
        with self.assertRaises(ValueError):
            train_then_predict(train,lambda:self.evaluation,encoder=bad,
                question_encoder=encoder.query,checkpoint_sha256='c'*64,steps=1)

    def test_training_work_is_not_inferred_from_matching_step_count(self):
        o=self.observation
        work=[o['training'][a]['observed_training_aten_formula_flops'] for a in o['training']]
        self.assertTrue(all(type(v) is int and v>0 for v in work))
        self.assertGreater(len(set(work)),1)
        self.assertEqual(o['encoding_work']['unknown_operators'],{})


if __name__=='__main__':unittest.main()
