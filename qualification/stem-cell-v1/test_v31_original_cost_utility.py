"""No real pretrained forward in these tests: synthetic V25 and V30 contracts."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import v30_independent_feature_cost_review as parent
import v31_original_cost_utility as v
from test_v30_independent_feature_cost_review import fixture as physical_fixture


ARMS = {
    'text_only':(17,0,0),'image_masked':(17,0,0),
    'calibrated_fusion':(17,0,0), 'bridge_image_only':(21,16,12),
    'bridge_equal_fusion':(16,5,6), 'rotated_equal_fusion':(19,7,5),
    'unaligned_equal_fusion':(10,5,12), 'train_gate':(24,14,7),
}


def historical_fixture():
    arms={}
    for name,(correct,rescue,harm) in ARMS.items():
        arms[name]={'original_historical_correct':correct,
                    'paired_rescues_vs_text':rescue,
                    'paired_harms_vs_text':harm,
                    'paired_exact_mcnemar_p':v.exact_p(rescue,harm),
                    'original_historical_brier_4class':0.18,
                    'original_historical_nll':1.3}
    return {'schema':'hepta.stem.v25.original-publisher-historical-rejudge.v1',
            'decision':'HISTORICAL_PUBLISHER_LABEL_RECOUNT_ONLY_NO_PROMOTION',
            'authority_posture':'DENY_ALL',
            'original_historical_archive_sha256':v.cost.ORIGINAL_ARCHIVE_SHA,
            'original_source_sha256':v.ORIGINAL_SOURCE,
            'original_prediction_sha256':v.ORIGINAL_PREDICTIONS,
            'publisher_revision':v.V25_SOURCE_REV,
            'original_publisher_dataset':'lmms-lab/ScienceQA-IMG',
            'original_publisher_labels_independently_rescored':True,
            'original_test_label_file_sha256_original_matched':True,
            'source_file_sha256_original_matched':True,
            'original_model_recomputed_in_this_run':False,
            'original_source_custody_independent_from_upstream_release':False,
            'future_independent_source_windows':0,
            'new_encoder_forwards':0,'new_training_updates':0,
            'scientific_promotion_authorized':False,
            'stem_winner_verified':False,'production_authorized':False,
            'external_independent_human_visual_necessity_annotated':False,
            'all_original_arms':arms,
            'precommitted_v24_label_blind_route':{
                'historical_correct':17,'historical_accuracy':17/64,
                'historical_rescues_vs_text':5,'historical_harms_vs_text':5,
                'historical_exact_mcnemar_p':1.0,'threshold':0.005,
                'conditional_image_calls_planned':21,'changed_top1_vs_text':19,
                'archived_vision_features_were_computed_for_all_64':True,
                'actual_conditional_encoder_forward_count':None,
                'actual_conditional_cpu_or_energy_cost':None,
                'actual_conditional_service_latency_ms':None}}


class Contract(unittest.TestCase):
    def joined(self,change=None):
        p=historical_fixture();e=physical_fixture()
        if change:change(p,e)
        return v.join(p,parent.canonical(e))

    def rejected(self,mutate):
        with self.assertRaises((v.Rejected,parent.Rejected)):
            self.joined(mutate)

    def test_normal_exact_same_source_yields_nogo(self):
        d=self.joined()
        self.assertEqual(d['decision'],'NO_GO_RESOURCE_ONLY_NO_UTILITY_UPLIFT')
        self.assertEqual(d['historical_no_change_correct'],17)
        self.assertEqual(d['historical_conditional_correct'],17)
        self.assertEqual((d['historical_rescues'],d['historical_harms']),(5,5))
        self.assertEqual(d['selected_vision_cases'],21)
        self.assertTrue(d['feature_only_resource_gain_descriptive'])
        self.assertFalse(d['case_level_joint_prediction_replay_authenticated'])
        self.assertFalse(d['ndu_net_utility_improvement_verified'])
        self.assertFalse(d['production_authorized'])
        self.assertIsNone(d['ndu_net_benefit'])

    def test_negative_cpu_outcome_is_reported_not_gamed(self):
        def mutate(_,phys):
            for i in (1,2):
                phys['arm_traces'][i]['cpu_ns']+=1000
                phys['arm_traces'][i]['wall_ns']+=1000
        d=self.joined(mutate)
        self.assertFalse(d['feature_only_resource_gain_descriptive'])
        self.assertLess(d['observed_two_encoder_feature_cpu_reduction_fraction'],0)
        self.assertEqual(d['decision'],'NO_GO_RESOURCE_ONLY_NO_UTILITY_UPLIFT')

    def test_v25_did_not_reopen_labels(self):
        self.rejected(lambda p,_:p.update(original_publisher_labels_independently_rescored=False))
        self.rejected(lambda p,_:p.update(original_test_label_file_sha256_original_matched=False))

    def test_v25_revision_fence(self):
        self.rejected(lambda p,_:p.update(publisher_revision='0'*40))
        self.rejected(lambda p,_:p.update(original_source_sha256='0'*64))
        self.rejected(lambda p,_:p.update(original_historical_archive_sha256='0'*64))

    def test_mismatched_original_cohort(self):
        self.rejected(lambda p,_:p.update(original_prediction_sha256='f'*64))
        self.rejected(lambda p,_:p.update(original_publisher_dataset='synthetic-dataset'))

    def test_forbidden_promotion_or_future(self):
        for key,value in [('production_authorized',True),('stem_winner_verified',True),
                          ('scientific_promotion_authorized',True),
                          ('future_independent_source_windows',1),
                          ('new_training_updates',1),
                          ('external_independent_human_visual_necessity_annotated',True)]:
            with self.subTest(key=key):self.rejected(lambda p,_,k=key,x=value:p.update({k:x}))

    def test_original_arm_rescue_harm_recount(self):
        self.rejected(lambda p,_:p['all_original_arms']['train_gate'].update(paired_harms_vs_text=2))
        self.rejected(lambda p,_:p['all_original_arms']['bridge_image_only'].update(original_historical_correct=51))
        self.rejected(lambda p,_:p['all_original_arms']['bridge_equal_fusion'].update(paired_exact_mcnemar_p=0.12))

    def test_original_arm_inventory_and_masked_control(self):
        self.rejected(lambda p,_:p['all_original_arms'].pop('train_gate'))
        self.rejected(lambda p,_:p['all_original_arms']['image_masked'].update(original_historical_correct=18))

    def test_frozen_route_cannot_be_retuned(self):
        self.rejected(lambda p,_:p['precommitted_v24_label_blind_route'].update(threshold=0.01))
        self.rejected(lambda p,_:p['precommitted_v24_label_blind_route'].update(conditional_image_calls_planned=64))

    def test_frozen_route_no_accuracy_lift(self):
        self.rejected(lambda p,_:p['precommitted_v24_label_blind_route'].update(historical_correct=25))
        self.rejected(lambda p,_:p['precommitted_v24_label_blind_route'].update(historical_rescues_vs_text=20))

    def test_boolean_and_nan_primary_rejected(self):
        self.rejected(lambda p,_:p['precommitted_v24_label_blind_route'].update(historical_correct=True))
        self.rejected(lambda p,_:p['all_original_arms']['text_only'].update(original_historical_nll=float('nan')))

    def test_v30_clock_collision_refused(self):
        self.rejected(lambda _,p:p['arm_traces'][0].update(cpu_ns=p['arm_traces'][0]['vision_cpu_ns']))
        self.rejected(lambda _,p:p['arm_traces'][0].pop('vision_cpu_ns'))

    def test_v30_model_substitution_refused(self):
        self.rejected(lambda _,p:p.update(real_vision_model_revision='a'*40))
        self.rejected(lambda _,p:p.update(real_text_model_revision='a'*40))

    def test_v30_unauthorized_or_made_up_utility(self):
        self.rejected(lambda _,p:p.update(production_authorized=True))
        self.rejected(lambda _,p:p.update(independent_future_windows=3))

    def test_two_sources_must_match_original_19_21(self):
        self.rejected(lambda p,_:p['precommitted_v24_label_blind_route'].update(changed_top1_vs_text=21))
        self.rejected(lambda _,p:p.update(selected_vision_cases=22))

    def test_different_original_source_is_blocked(self):
        self.rejected(lambda _,p:p.update(historical_archive_sha256='a'*64))

    def test_bogus_feature_cpu_unit_refused(self):
        self.rejected(lambda _,p:p['arm_traces'][1].update(cpu_ns=1))
        self.rejected(lambda _,p:p['arm_traces'][0].update(text_batches=0))

    def test_same_dataset_not_per_case_current_predictions(self):
        d=self.joined()
        self.assertFalse(d['case_level_joint_prediction_replay_authenticated'])
        self.assertFalse(d['original_test_cases']==0)
        self.assertIsNone(d['resource_break_even_with_head_and_recovery'])

    def test_exact_zip_and_reject_missing_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fake.zip'
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('original.json',b'{}\n')
            raw=path.read_bytes()
            self.assertEqual(v.exact_artifact(path,v.sha(raw),{'original.json':v.sha(b'{}\n')}),
                             {'original.json':b'{}\n'})
            with self.assertRaises(v.Rejected):v.exact_artifact(path,'a'*64,{'original.json':v.sha(b'{}\n')})
            with self.assertRaises(v.Rejected):v.exact_artifact(path,v.sha(raw),{'other.json':v.sha(b'{}\n')})
            with self.assertRaises(v.Rejected):v.exact_artifact(path,v.sha(raw),{'original.json':'f'*64})

    def test_zip_extra_file_and_traversal_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'evil.zip'
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('safe.json',b'{}\n');z.writestr('../bad.json',b'{}\n')
            raw=path.read_bytes()
            with self.assertRaises(v.Rejected):v.exact_artifact(path,v.sha(raw),{'safe.json':v.sha(b'{}\n'),'../bad.json':v.sha(b'{}\n')})
            with self.assertRaises(v.Rejected):v.exact_artifact(path,v.sha(raw),{'safe.json':v.sha(b'{}\n')})

    def test_duplicate_json_keys_and_nonfinite_denied(self):
        for content in [b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}']:
            with self.subTest(content=content),self.assertRaises(v.Rejected):
                v.strict_source_json(content)

    def test_create_only_no_symlinks_or_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sealed.json'
            d=self.joined()
            v.safe_write(path,d)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(v.Rejected):v.safe_write(path,d)
            self.assertEqual(json.loads(path.read_bytes())['decision'],d['decision'])

    def test_independent_synthetic_drift_not_production(self):
        d=self.joined()
        self.assertEqual(d['independent_future_windows'],0)
        self.assertFalse(d['whole_product_lifecycle_cost_qualified'])
        self.assertFalse(d['no_change_baseline_production_trace_witnessed'])
        self.assertFalse(d['source_independent_human_modal_necessity_adjudicated'])

    def test_checked_in_original_readout_is_nogo_and_source_bound(self):
        p=Path(__file__).resolve().parent/'STEM_V31_ORIGINAL_SAME_SOURCE_NO_GO_20261017.json'
        raw=p.read_bytes()
        published=json.loads(raw)
        self.assertEqual(raw,parent.canonical(published))
        self.assertEqual(published['decision'],'NO_GO_RESOURCE_ONLY_NO_UTILITY_UPLIFT')
        self.assertEqual(published['original_test_cases'],64)
        self.assertEqual(published['selected_vision_cases'],21)
        self.assertEqual(published['historical_no_change_correct'],17)
        self.assertEqual(published['historical_conditional_correct'],17)
        self.assertFalse(published['case_level_joint_prediction_replay_authenticated'])
        self.assertIsNone(published['ndu_net_benefit'])
        self.assertFalse(published['production_authorized'])
        self.assertEqual(published['physical_producer_report_sha256'],v.V30_MEMBER_SHA)

    def test_workflow_guards_exact_material_and_no_model_run(self):
        wf=Path(__file__).resolve().parents[2]/'.github/workflows/hepta-stem-v31-cost-utility-join.yml'
        content=wf.read_text()
        for keyword in (str(v.V25_ARTIFACT),str(v.V30_ARTIFACT),v.V25_ZIP_SHA,v.V30_ZIP_SHA,
                        'original-source-qualification','push',
                        "github.event_name == 'push'",'DENY_ALL','sha256sum -c -'):
            self.assertIn(keyword,content)
        self.assertIn('cmp "$RUNNER_TEMP/v31-same-original-source-nogo.json" qualification/stem-cell-v1/STEM_V31_ORIGINAL_SAME_SOURCE_NO_GO_20261017.json',content)
        self.assertNotIn('trust_remote_code=True',content)
        self.assertNotIn('model.safetensors',content)


if __name__=='__main__':unittest.main()
