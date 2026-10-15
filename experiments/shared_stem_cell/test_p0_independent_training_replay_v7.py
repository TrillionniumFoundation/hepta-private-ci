"""V7 adversarial independent optimizer replay; inputs are synthetic Q24-like features.

The test does not load Granite/mmBERT/Gemma weights or open held labels.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from safetensors.numpy import load_file, save_file

from p0_multirc_semantic_material import Invalid,canonical,sha,validate
from p0_physical_replay_v5 import (MODEL_WIDTHS,export_original_replay,
    independent_numeric_replay,_hash_bytes)
from p0_cold_encoder_replay_v6 import checked_probe
from p0_independent_training_replay_v7 import (
    independently_refit, _proper_training_groups, _calibration_loss,SCHEMA,
    MAX_TRAINED_DIFFERENCE)
import test_p0_physical_replay_v5 as replay_fixture

REVISIONS={
    'granite_97m_r2':'835ad14087e140460703cf0fae09f97d469d65c2',
    'mmbert_small':'0eb3d056ec1d6333cf4e19b0966dfde342a41a3a',
    'embeddinggemma_2_text':'914f7f89142e33e77833254d9c9b90c3cef7303b'}


class IndependentOriginalOptimizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        replay_fixture.OriginalTensorReplayTests.setUpClass()
        cls.fit,cls.blind=replay_fixture.OriginalTensorReplayTests.fit,replay_fixture.OriginalTensorReplayTests.blind
        cls.templates=replay_fixture.OriginalTensorReplayTests.template
        cls.count=len(cls.fit['cases'])+len(cls.blind['cases'])
        cls.fake_head={'schema':'hepta.p0.three-pretrained-head-numeric-replay.v1',
                       'authority':'DENY_ALL','production_promotion_permitted':False,
                       'models':{m: {'model':m,'source_case_count':cls.count,
                                    'replayed_original_and_question_head_predictions':192,
                                    'max_probability_disagreement':1e-7,'tolerance':3e-5,
                                    'authority':'DENY_ALL','production_promotion_permitted':False}
                                 for m in MODEL_WIDTHS}}
        cls.fake_cold={'schema':'hepta.p0.three-real-cold-encoder-replay.v1',
                       'authority':'DENY_ALL','production_promotion_permitted':False,
                       'new_original_human_labels_accessed':False,
                       'models':{m: {'model':m,'revision':REVISIONS[m],
                                    'cold_probed_case_count':12,
                                    'selection_protocol':'sha256-panel-source-pair-2-groups-per-split-v1',
                                    'registered_max_q24_difference':2,
                                    'max_q24_disagreement':0,
                                    'source_distinct_pairs_per_split':2,
                                    'actual_original_checkpoint_loader_invoked_in_second_process':True,
                                    'original_human_held_labels_accessed':False,
                                    'authority':'DENY_ALL','production_promotion_permitted':False}
                                 for m in MODEL_WIDTHS}}

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model='granite_97m_r2'
        self.path=Path(self.tmp.name)/'pretrained.replay'
        v,weights,report=self.templates[self.model]
        self.report=copy.deepcopy(report)
        export_original_replay(self.path,self.fit,self.blind,self.report,self.model,v,weights)
        self.head=copy.deepcopy(self.fake_head)
        self.cold=copy.deepcopy(self.fake_cold)

    def _verify(self):
        return independently_refit(self.fit,self.blind,self.report,self.model,
                                  self.path,self.head,self.cold)

    def test_independent_replay_genuine_two_40step_updates_384(self):
        out=self._verify()
        self.assertEqual(out['schema'],SCHEMA)
        self.assertEqual(out['stored_training_updates_replayed'],80)
        self.assertEqual(set(out['arms']),{'evidence','question_only'})
        self.assertEqual(out['arms']['evidence']['max_original_final_head_parameter_difference'],0.)
        self.assertEqual(out['arms']['question_only']['max_original_final_head_parameter_difference'],0.)
        self.assertFalse(out['held_original_human_labels_opened'])
        self.assertFalse(out['full_pretrained_effectiveness_proven'])
        self.assertFalse(out['production_promotion_permitted'])

    def test_independent_replay_three_distinct_pretrained_feature_widths(self):
        for m in ('mmbert_small','embeddinggemma_2_text'):
            v,weights,report=self.templates[m]
            out=Path(self.tmp.name)/f'{m}.replay'
            export_original_replay(out,self.fit,self.blind,report,m,v,weights)
            result=independently_refit(self.fit,self.blind,report,m,out,self.head,self.cold)
            self.assertEqual(result['original_feature_count'],self.count)
            self.assertEqual(result['stored_training_updates_replayed'],80)

    def test_old_v5_can_miss_training_only_feature_corruption_v7_catches(self):
        probe={r['case_id'] for r in checked_probe(self.fit,self.blind)}
        original=[i for i,r in enumerate(self.fit['cases'])
                  if r['split']=='train' and r['condition']=='original' and r['case_id'] not in probe]
        self.assertTrue(original)
        path=self.path/'features.safetensors'
        vectors=load_file(str(path))
        vectors['features_q24_fp32'][original[0],0]+=np.float32(.7)
        save_file(vectors,str(path))
        m=json.loads((self.path/'COMMITTED.json').read_text())
        m['features_safetensors_sha256']=_hash_bytes(path.read_bytes())
        (self.path/'COMMITTED.json').write_bytes(canonical(m)+b'\n')
        # Held predictions and the source-disjoint 12-case cold selection are unchanged.
        independent_numeric_replay(self.path,self.fit,self.blind,self.report,model=self.model)
        with self.assertRaisesRegex(Invalid,'not reproducible'):
            self._verify()

    def test_reject_unequal_future_train_source_inventory(self):
        self.report['training']['fit_train_case_ids_sha256']='d'*64
        with self.assertRaises(Invalid):self._verify()

    def test_reject_forged_question_train_ids(self):
        self.report['matched_question_only_control']['train_question_case_ids_sha256']='d'*64
        with self.assertRaises(Invalid):self._verify()

    def test_reject_forged_calibration_ids(self):
        self.report['training']['calibration_case_ids_sha256']='d'*64
        with self.assertRaises(Invalid):self._verify()

    def test_reject_missing_original_optimizer_report(self):
        self.report.pop('training')
        with self.assertRaises(Invalid):self._verify()

    def test_reject_missing_independent_upstream_head_gate(self):
        self.head['models'].pop('mmbert_small')
        with self.assertRaises(Invalid):self._verify()

    def test_reject_empty_old_head_replay_score(self):
        self.head['models'][self.model]['replayed_original_and_question_head_predictions']=0
        with self.assertRaises(Invalid):self._verify()

    def test_reject_false_numeric_replay_pretrained_accuracy(self):
        self.head['models'][self.model]['max_probability_disagreement']=.1
        with self.assertRaises(Invalid):self._verify()

    def test_reject_missing_real_cold_model(self):
        self.cold['models'].pop(self.model)
        with self.assertRaises(Invalid):self._verify()

    def test_reject_forged_cold_physical_loader(self):
        self.cold['models'][self.model]['actual_original_checkpoint_loader_invoked_in_second_process']=False
        with self.assertRaises(Invalid):self._verify()

    def test_reject_changed_cold_sample_protocol(self):
        self.cold['models'][self.model]['selection_protocol']='posthoc'
        with self.assertRaises(Invalid):self._verify()

    def test_reject_cold_more_than_two_q24_units(self):
        self.cold['models'][self.model]['max_q24_disagreement']=3
        with self.assertRaises(Invalid):self._verify()

    def test_reject_cold_report_inventing_new_held_labels(self):
        self.cold['new_original_human_labels_accessed']=True
        with self.assertRaises(Invalid):self._verify()

    def test_reject_original_report_authority_rewrite(self):
        self.report['authority']='ALLOW_ALL'
        with self.assertRaises(Invalid):self._verify()

    def test_reject_sneaking_held_evaluation_label_into_blind_material(self):
        blind=copy.deepcopy(self.blind)
        blind['cases'][0]['label']=1
        with self.assertRaises(Invalid):
            independently_refit(self.fit,blind,self.report,self.model,self.path,self.head,self.cold)

    def test_independent_group_selection_has_matching_human_targets(self):
        e,q,ids=_proper_training_groups(self.fit,self.blind)
        self.assertEqual(len(ids),self.count)
        for split in ('train','calibration'):
            self.assertEqual(e[split][1],q[split][1])
            self.assertEqual(len(e[split][0]),len(q[split][0]))
            self.assertNotEqual(e[split][0],q[split][0])

    def test_strict_registered_calibration_loss(self):
        x=np.zeros((2,384),dtype=np.float32)
        y=np.array([0,1],dtype=np.int64)
        w=np.zeros((2,384),dtype=np.float32)
        b=np.zeros(2,dtype=np.float32)
        self.assertAlmostEqual(_calibration_loss(x,y,w,b,1.0),float(np.log(2)))

    def test_optimizer_calibration_uses_training_original_only(self):
        out=self._verify()
        for result in out['arms'].values():
            self.assertEqual(result['steps_replayed'],40)
            self.assertEqual(result['training_case_count'],48)
            self.assertEqual(result['calibration_case_count'],16)
            self.assertGreater(result['replay_train_wall_ms'],0)


if __name__=='__main__':unittest.main()
