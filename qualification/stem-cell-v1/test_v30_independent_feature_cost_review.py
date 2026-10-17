"""Stand-alone adversarial tests; all time/counter inputs are SYNTHETIC."""
from __future__ import annotations

import copy
from pathlib import Path
import os
import tempfile
import unittest

import v30_independent_feature_cost_review as v


def fixture():
    arms=[]
    for i,profile in enumerate(v.ARM_ORDER):
        full = i in (0,3)
        vision_ns = 700 if full else 250
        text_ns = 900 + i*10
        cpu_ns = text_ns + vision_ns + 70
        arms.append({'arm':profile,'cpu_ns':cpu_ns,'wall_ns':cpu_ns + 40,
                     'text_items':320,'text_batches':20,
                     'text_cpu_ns':text_ns,'text_wall_ns':text_ns+10,
                     'items':64 if full else 21,'batches':8 if full else 3,
                     'media_bytes_read':4_000_000 if full else 1_200_000,
                     'vision_cpu_ns':vision_ns,'vision_wall_ns':vision_ns+10})
    return {'schema':v.SOURCE_SCHEMA,'authority':'DENY_ALL',
            'disposition':'HOLD_NO_CELL_OR_MODEL_SELECTION',
            'production_authorized':False,'stem_winner_verified':False,
            'frozen_route_plan_sha256':v.MINIMAL_ROUTE_SHA,
            'historical_archive_sha256':v.ORIGINAL_ARCHIVE_SHA,
            'actual_live_text_route_from_model':True,
            'cached_vision_predictions_used_for_route':False,
            'real_test_labels_opened':False,'new_training_updates':0,
            'real_original_source_case_count':64,'selected_vision_cases':21,
            'real_text_model_repo':v.GRANITE[0],
            'real_text_model_revision':v.GRANITE[1],
            'real_vision_model_repo':v.DINO[0],
            'real_vision_model_revision':v.DINO[1],
            'text_model_manifest_sha256':'a'*64,
            'vision_model_manifest_sha256':'b'*64,
            'actual_pretrained_text_and_vision_forwards':True,
            'warmup_text_batches':1,'warmup_vision_batches':1,
            'model_acquisition_and_load_wall_ns':5_000,
            'arm_traces':arms,'text_score_max_abs_drift':0.0,
            'image_feature_max_abs_drift':0.0,
            'process_peak_rss_kib_not_incremental':800_000,
            'energy_joules':None,'gpu_peak_bytes':None,
            'independent_future_windows':0,
            'full_product_end_to_end_savings_proven':False,
            'original_task_accuracy_recomputed_this_run':False,
            'physical_cpu_execution_owner':'original-frozen-granite-and-dinov2'}


class Review(unittest.TestCase):
    def good(self):return v.review(v.canonical(fixture()))
    def deny(self,change):
        model=fixture()
        change(model)
        with self.assertRaises(v.Rejected):v.review(v.canonical(model))

    def test_complete_arms_and_independent_cpu_math(self):
        d=self.good()
        self.assertEqual(d['text_batched_forwards_by_arm'],[20]*4)
        self.assertEqual(d['vision_batched_forwards_by_arm'],[8,3,3,8])
        self.assertEqual(d['full_feature_cpu_ns_by_arm'],[1670,1230,1240,1700])
        self.assertEqual(d['paired_total_feature_cpu_deltas_ns'],[440,460])
        self.assertAlmostEqual(d['combined_total_feature_cpu_reduction_fraction_descriptive'],1-2470/3370)
        self.assertFalse(d['producer_counters_independently_hardware_attested'])
        self.assertFalse(d['production_authorized'])
        self.assertEqual(d['decision'],'HOLD_RESEARCH_FEATURE_CPU_ONLY_NO_PROMOTION')

    def test_no_positive_cost_claim_required(self):
        m=fixture()
        for i in (1,2):
            m['arm_traces'][i]['cpu_ns'] += 1000
            m['arm_traces'][i]['wall_ns'] += 1000
        d=v.review(v.canonical(m))
        self.assertLess(d['combined_total_feature_cpu_reduction_fraction_descriptive'],0)
        self.assertFalse(d['stem_winner_verified'])

    def test_v30_previous_clock_collision_is_rejected(self):
        self.deny(lambda d:d['arm_traces'][0].update(cpu_ns=d['arm_traces'][0]['vision_cpu_ns'],
                                                     wall_ns=d['arm_traces'][0]['vision_wall_ns']))

    def test_text_phase_required_for_every_arm(self):
        self.deny(lambda d:d['arm_traces'][1].__setitem__('text_cpu_ns',d['arm_traces'][1]['cpu_ns']))

    def test_vision_phase_required_for_every_arm(self):
        self.deny(lambda d:d['arm_traces'][1].__setitem__('vision_wall_ns',d['arm_traces'][1]['wall_ns']))

    def test_wrong_count_and_batch_rejected(self):
        self.deny(lambda d:d['arm_traces'][1].__setitem__('batches',8))
        self.deny(lambda d:d['arm_traces'][0].__setitem__('text_batches',0))
        self.deny(lambda d:d['arm_traces'][2].__setitem__('text_items',319))

    def test_wrong_arm_order_rejected(self):
        self.deny(lambda d:d['arm_traces'].__setitem__(slice(0,2),[d['arm_traces'][1],d['arm_traces'][0]]))
        self.deny(lambda d:d['arm_traces'].pop())

    def test_dropped_phase_clock_is_rejected(self):
        self.deny(lambda d:d['arm_traces'][0].pop('vision_cpu_ns'))
        self.deny(lambda d:d['arm_traces'][0].pop('text_cpu_ns'))

    def test_wrong_repeated_media_bytes_rejected(self):
        self.deny(lambda d:d['arm_traces'][0].__setitem__('media_bytes_read',42))

    def test_wrong_original_model_revision_rejected(self):
        self.deny(lambda d:d.__setitem__('real_text_model_revision','0'*40))
        self.deny(lambda d:d.__setitem__('real_vision_model_revision','0'*40))

    def test_model_manifest_identity_rejected(self):
        self.deny(lambda d:d.__setitem__('text_model_manifest_sha256','no verification'))
        self.deny(lambda d:d.__setitem__('vision_model_manifest_sha256','a'*64))

    def test_wrong_source_or_route_rejected(self):
        self.deny(lambda d:d.__setitem__('historical_archive_sha256','f'*64))
        self.deny(lambda d:d.__setitem__('frozen_route_plan_sha256','f'*64))

    def test_missing_or_forged_labeled_outcome_rejected(self):
        self.deny(lambda d:d.__setitem__('real_test_labels_opened',True))
        self.deny(lambda d:d.__setitem__('cached_vision_predictions_used_for_route',True))
        self.deny(lambda d:d.__setitem__('independent_future_windows',1))
        self.deny(lambda d:d.__setitem__('original_task_accuracy_recomputed_this_run',True))

    def test_authority_and_physical_claim_veto(self):
        self.deny(lambda d:d.__setitem__('authority','GRANTED'))
        self.deny(lambda d:d.__setitem__('production_authorized',True))
        self.deny(lambda d:d.__setitem__('full_product_end_to_end_savings_proven',True))
        self.deny(lambda d:d.__setitem__('actual_pretrained_text_and_vision_forwards',False))

    def test_boolean_counter_is_not_one(self):
        self.deny(lambda d:d.__setitem__('warmup_text_batches',True))
        self.deny(lambda d:d['arm_traces'][0].__setitem__('text_batches',True))

    def test_unknown_authority_field_rejected(self):
        self.deny(lambda d:d.__setitem__('FinalUseGranted',True))
        self.deny(lambda d:d['arm_traces'][0].__setitem__('token', 'secret'))

    def test_nonfinite_and_overflow_rejected(self):
        for x in (float('nan'),float('inf'),True,-1):
            try: raw=v.canonical(dict(fixture(),text_score_max_abs_drift=x))
            except ValueError:continue
            with self.assertRaises(v.Rejected):v.review(raw)
        self.deny(lambda d:d['arm_traces'][0].__setitem__('cpu_ns',10**35))

    def test_duplicate_json_field_denied(self):
        raw=v.canonical(fixture())
        altered=raw.replace(b'"authority":"DENY_ALL"',
                            b'"authority":"DENY_ALL","authority":"GRANTED"')
        with self.assertRaises(v.Rejected):v.review(altered)

    def test_noncanoical_and_oversize_denied(self):
        raw=v.canonical(fixture())
        for payload in (raw[:-1],b' '+raw, raw+b' ',b'{}\n',b'x'*v.MAX_REPORT_BYTES+b'\n'):
            with self.subTest(size=len(payload)),self.assertRaises(v.Rejected):v.review(payload)

    def test_strict_create_only_output(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'readonly-review.json'
            d=self.good()
            v.write_create_only(p,d)
            self.assertEqual(p.read_bytes(),v.canonical(d))
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):v.write_create_only(p,d)

    def test_yaml_separate_review_consumer(self):
        root=Path(__file__).resolve().parents[2]
        wf=(root/'.github/workflows/hepta-stem-v30-live-text-vision.yml').read_text()
        self.assertIn('  independent-feature-cost-review:',wf)
        self.assertIn('needs: original-physical-live-text-vision',wf)
        self.assertIn('download-artifact@v4',wf)
        self.assertIn('v30_independent_feature_cost_review.py',wf)
        self.assertIn('producer',wf)
        self.assertIn('DENY_ALL',wf)
        self.assertIn('stem-v30-live-text-vision-cost-hold-${{ github.sha }}',wf)

if __name__=='__main__':unittest.main()
