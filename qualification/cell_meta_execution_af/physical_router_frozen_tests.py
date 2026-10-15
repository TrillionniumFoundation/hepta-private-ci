"""Synthetic/adversarial conformance of the TRUE frozen no-change counterfactual.

Fixtures are NOT new Granite model forwards or prospective outcome evidence.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import math
import tempfile
import unittest
from pathlib import Path

from qualification.cell_meta_execution_af import physical_router_trial as base
from qualification.cell_meta_execution_af import physical_router_top1 as post
from qualification.cell_meta_execution_af import physical_router_hard_train as hard_train
from qualification.cell_meta_execution_af import physical_router_frozen_baseline as producer
from qualification.cell_meta_execution_af import physical_router_frozen_review as reviewer
from qualification.cell_meta_execution_af import physical_router_hard_review as hard_reviewer
from qualification.cell_meta_execution_af import physical_router_audit as soft_reviewer

class FrozenNoChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel=base.synthetic_panel(seed=41,rule="conditional",rows=64)
        cls.soft=base.run(cls.panel,steps=5)
        cls.post=post.create_report(cls.panel,cls.soft)
        cls.hard=hard_train.produce(cls.panel,cls.soft,cls.post)
        cls.frozen=producer.produce(cls.panel,cls.soft,cls.post,cls.hard)
        cls.evidence=reviewer.replay(cls.panel,cls.soft,cls.post,cls.hard,cls.frozen)

    def rejected(self,frozen=None,*,panel=None,soft=None,posthoc=None,hard=None):
        with self.assertRaises((reviewer.FrozenReviewDenied,
                                hard_reviewer.HardReplayDenied,
                                soft_reviewer.AuditError)):
            reviewer.replay(self.panel if panel is None else panel,
                            self.soft if soft is None else soft,
                            self.post if posthoc is None else posthoc,
                            self.hard if hard is None else hard,
                            self.frozen if frozen is None else frozen)

    def test_actual_cpu_frozen_forward_and_independent_replay(self):
        self.assertEqual(self.evidence['outcome'],'FROZEN_NO_CHANGE_NUMERIC_REPLAY_NO_AUTHORITY')
        self.assertTrue(self.evidence['source_case_predictions_and_fp32_replayed'])
        self.assertFalse(self.evidence['prospective_ndu_qualified'])
        self.assertFalse(self.evidence['total_compute_matched'])
        self.assertEqual(self.frozen['production_admission'],'BLOCKED')
        self.assertEqual(self.frozen['authority_posture'],'DENY_ALL')

    def test_no_second_phase_training_and_no_router_work(self):
        met=self.frozen['meters']
        self.assertEqual(met['additional_stage2_optimizer_updates'],0)
        self.assertEqual(met['additional_stage2_train_head_rows'],0)
        self.assertEqual(met['additional_eval_router_rows'],0)
        self.assertEqual(met['additional_eval_head_rows'],256)
        self.assertEqual(met['reused_stage1_train_rows_reported'],320)
        self.assertEqual(met['frozen_head_payload_bytes_fp32'],20)

    def test_old_unsplit_nochange_is_actually_continued_learning(self):
        self.assertEqual(self.frozen['historical_no_change_semantics'],
                         'unsplit_continued_stage2_update')
        self.assertNotEqual(self.frozen['retrospective_evaluation']['future_1']['brier'],
                            self.hard['results'][0]['retrospective_evaluation']['future_1']['brier'])
        self.assertEqual(self.hard['results'][0]['meters']['optimizer_steps'],10)

    def test_real_stage1_identical_across_four_hard_arms(self):
        self.assertEqual(len({x['stage1_parent_fp32']['data_le_hex'] for x in
                              self.hard['results']}),1)
        self.assertEqual(self.frozen['stage1_parent_fp32'],
                         self.hard['results'][0]['stage1_parent_fp32'])

    def test_excludes_torch_numpy_and_producer_from_independent_reviewer(self):
        source=inspect.getsource(reviewer)
        self.assertNotIn('\nimport torch\n',source)
        self.assertNotIn('\nimport numpy\n',source)
        self.assertNotIn('import physical_router_frozen_baseline',source)
        self.assertNotIn('from qualification.cell_meta_execution_af import physical_router_hard_train',source)

    def test_frozen_is_unchanged_when_only_eval_labels_change(self):
        changed=copy.deepcopy(self.panel)
        for part in base.EVAL_PARTITIONS:
            for row in changed['partitions'][part]:row['label']=1-row['label']
        before=self.frozen['predictions']
        weights=reviewer.hard_audit.decode(self.frozen['stage1_parent_fp32'],[5])
        for part in base.EVAL_PARTITIONS:
            for row,pred in zip(changed['partitions'][part],before[part],strict=True):
                p=reviewer.sigmoid(sum(a*b for a,b in zip(row['features']+[1.0],weights,strict=True)))
                self.assertAlmostEqual(p,pred['probability'],places=6)
        self.assertNotEqual(producer.source_metrics(changed,before),
                            self.frozen['retrospective_evaluation'])

    def test_training_new_label_change_cannot_affect_stage1_parent(self):
        changed=copy.deepcopy(self.panel)
        for row in changed['partitions']['new_train']:row['label']=1-row['label']
        alt=hard_train.train_one(changed,'no_change',steps=5)
        self.assertEqual(alt['stage1_parent_fp32'],self.frozen['stage1_parent_fp32'])
        self.assertNotEqual(alt['weights_sha256'],self.hard['results'][0]['weights_sha256'])

    def test_changed_input_feature_denied_by_source_binding(self):
        changed=copy.deepcopy(self.panel)
        changed['partitions']['future_1'][0]['features'][0] += 0.01
        self.rejected(panel=changed)

    def test_forged_future_qualification_denied(self):
        t=copy.deepcopy(self.frozen)
        t['future_window_prospective']=True
        self.rejected(t)

    def test_forged_model_origin_and_ndu_denied(self):
        for field in ['original_stage1_model_origin_authenticated',
                      'independent_ndu_selection_authorized',
                      'total_compute_matched']:
            t=copy.deepcopy(self.frozen);t[field]=True
            with self.subTest(field=field):self.rejected(t)

    def test_changed_final_probability_even_with_rehash_denied(self):
        t=copy.deepcopy(self.frozen)
        t['predictions']['future_1'][0]['probability']=.789
        t['prediction_sha256']=base.digest(t['predictions'])
        self.rejected(t)

    def test_changed_weight_with_recomputed_hash_denied(self):
        t=copy.deepcopy(self.frozen)
        obj=t['stage1_parent_fp32']
        raw=bytearray.fromhex(obj['data_le_hex'])
        raw[0] ^= 1
        obj['data_le_hex']=raw.hex()
        t['stage1_parent_domain_sha256']=hashlib.sha256(
            b'hepta.true-frozen.stage1.v1\0'+raw).hexdigest()
        self.rejected(t)

    def test_divergent_stage1_across_arms_denied(self):
        h=copy.deepcopy(self.hard)
        h['results'][1]['stage1_parent_fp32']['data_le_hex']='0'*40
        self.rejected(hard=h)

    def test_extra_stage2_optimizer_updates_denied(self):
        t=copy.deepcopy(self.frozen)
        t['meters']['additional_stage2_optimizer_updates']=1
        self.rejected(t)

    def test_fake_eval_or_router_rows_denied(self):
        for field in ('additional_eval_head_rows','additional_eval_router_rows',
                      'reused_stage1_train_rows_reported'):
            t=copy.deepcopy(self.frozen);t['meters'][field]+=1
            with self.subTest(field=field):self.rejected(t)

    def test_fake_retrospective_metric_denied(self):
        t=copy.deepcopy(self.frozen)
        t['retrospective_evaluation']['future_2']['brier'] += .01
        self.rejected(t)

    def test_forged_delta_against_continued_learning_denied(self):
        t=copy.deepcopy(self.frozen)
        t['brier_minus_historical_unsplit_continued']['future_1'] += .01
        self.rejected(t)

    def test_missing_prediction_or_extra_key_denied(self):
        t=copy.deepcopy(self.frozen)
        t['predictions']['future_2'].pop()
        t['prediction_sha256']=base.digest(t['predictions'])
        self.rejected(t)
        t=copy.deepcopy(self.frozen)
        t['frozen_superiority_claimed']=True
        self.rejected(t)

    def test_nonfinite_cpu_cost_denied(self):
        t=copy.deepcopy(self.frozen)
        t['meters']['actual_inference_cpu_seconds']=float('inf')
        self.rejected(t)

    def test_zero_additional_training_does_not_mean_matched_cost(self):
        self.assertFalse(self.frozen['total_compute_matched'])
        self.assertFalse(self.evidence['total_compute_matched'])
        self.assertTrue(math.isfinite(self.frozen['meters']['actual_inference_cpu_seconds']))

if __name__=='__main__':unittest.main()
