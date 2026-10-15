"""Falsification-focused P5 research scaling checks with synthetic receipts only."""
from __future__ import annotations

import copy
import math
import tempfile
import unittest
from pathlib import Path

from scaling_frontier import (SCHEMA, ScalingDenied, load, one_axis_sweeps,
                              validate_series)


def trial(scale: int, *, seed: int = 41, arm: str = 'shared_sparse') -> dict:
    return {
        'trial_id': f'{seed}-{arm}-{scale}', 'arm': arm, 'seed': seed,
        'source_sha256': 'a'*64, 'held_label_sha256': 'b'*64,
        'evaluator_sha256': 'c'*64, 'stem_sha256': 'd'*64,
        'logical_cells': scale, 'active_cells': 8,
        'reasoning_depth': 2, 'train_rows': 128,
        'compute_budget_ns': 1000000,
        'correct': {64:11,256:12,1024:13,4096:13}[scale], 'total': 16,
        'training_cpu_ns': 2000 + scale, 'inference_cpu_ns': 1000 + scale,
        'encoder_forwards': 16, 'peak_rss_bytes': 1000000 + scale,
        'independent_source_groups': 4, 'physical_work_observed': True,
        'independent_score_receipt': True,
    }


def fixture() -> dict:
    return {'schema': SCHEMA, 'authority_posture':'DENY_ALL',
            'production_accepted':False, 'teacher_equivalence_certified':False,
            'rows':[trial(i) for i in (64,256,1024,4096)]}


class TestScaleFrontier(unittest.TestCase):
    def test_four_scale_holdout_is_descriptive_only(self):
        result=one_axis_sweeps(fixture())
        self.assertEqual(len(result['matched_one_axis_sweeps']),1)
        review=result['matched_one_axis_sweeps'][0]
        self.assertEqual(review['levels'],[64,256,1024,4096])
        self.assertEqual(review['held_level'],4096)
        self.assertGreaterEqual(review['held_level_absolute_error'],0)
        for k in ('task_quality_winner_certified', 'complete_cost_pareto_certified',
                  'model_or_teacher_equivalence_certified',
                  'can_extrapolate_to_unmeasured_10t_100t', 'production_accepted'):
            self.assertIs(result[k],False)

    def test_wilson_interval_and_plateau_not_certified(self):
        result=one_axis_sweeps(fixture())
        review=result['matched_one_axis_sweeps'][0]
        lo,hi=review['held_level_wilson95_iid_only']
        self.assertLess(lo,hi)
        self.assertLessEqual(lo,review['held_level_quality'])
        self.assertLessEqual(review['held_level_quality'],hi)
        self.assertIs(review['held_level_wilson_independence_established'],False)
        self.assertIs(review['plateau_claim_admitted'],False)
        self.assertEqual(review['gain_over_previous_level'],0)

    def test_extreme_extrapolation_keeps_raw_bad_prediction(self):
        x=fixture()
        # Intentionally extreme held data in an underpowered toy panel.
        # A fit can violate the valid probability interval, but must not be
        # silently clipped and reported as a credible scaling forecast.
        for i,r in enumerate(x['rows']):
            r['correct']=(0,0,16,16)[i]
        review=one_axis_sweeps(x)['matched_one_axis_sweeps'][0]
        self.assertIsInstance(review['prediction_outside_unit_interval'],bool)
        self.assertIs(review['plateau_claim_admitted'],False)

    def test_valid_one_axis_pair_within_arm_seed(self):
        x=fixture()
        x['rows'] += [trial(s,seed=47) for s in (64,256,1024,4096)]
        result=one_axis_sweeps(x)
        self.assertEqual(len(result['matched_one_axis_sweeps']),2)
        self.assertEqual([r['seed'] for r in result['matched_one_axis_sweeps']],[41,47])

    def test_other_axes_do_not_get_pooled_to_fake_scaling(self):
        for change in ({'active_cells':4},{'reasoning_depth':4},
                       {'compute_budget_ns':2000000},{'train_rows':256},
                       {'source_sha256':'f'*64},{'evaluator_sha256':'e'*64}):
            x=fixture();x['rows'][2].update(change)
            with self.subTest(change=change):
                result=one_axis_sweeps(x)
                self.assertEqual(len(result['matched_one_axis_sweeps']),0)

    def test_all_five_single_axis_designs_can_be_scored_without_pooling(self):
        from scaling_frontier import LEVELS
        for axis,values in LEVELS.items():
            rows=[]
            for index,v in enumerate(values):
                r=trial(1024)
                r['trial_id']=f'{axis}-{v}'
                r[axis]=v
                r['correct']=11+index
                rows.append(r)
            x=fixture(); x['rows']=rows
            with self.subTest(axis=axis):
                result=one_axis_sweeps(x)
                self.assertEqual(len(result['matched_one_axis_sweeps']),1)
                self.assertEqual(result['matched_one_axis_sweeps'][0]['swept_axis'],axis)
                self.assertEqual(result['matched_one_axis_sweeps'][0]['levels'],list(values))

    def test_duplicate_trial_and_duplicate_scale_refused(self):
        x=fixture(); x['rows'][1]['trial_id']=x['rows'][0]['trial_id']
        with self.assertRaises(ScalingDenied): one_axis_sweeps(x)
        x=fixture();x['rows'][1]['logical_cells']=64
        with self.assertRaises(ScalingDenied): one_axis_sweeps(x)

    def test_malformed_inflated_or_forged_cost_rejected(self):
        for field,value in (('logical_cells',10**13),('active_cells',5000),
                            ('correct',17),('total',0),('training_cpu_ns',-1),
                            ('inference_cpu_ns',False),('peak_rss_bytes',0),
                            ('independent_source_groups',17),('physical_work_observed',False),
                            ('independent_score_receipt',False),('encoder_forwards',-1),
                            ('stem_sha256','0'*64)):
            x=fixture();x['rows'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ScalingDenied): one_axis_sweeps(x)

    def test_false_production_or_large_teacher_claim_denied(self):
        for field, value in (('production_accepted',True),
                             ('teacher_equivalence_certified',True),
                             ('authority_posture','ALLOW')):
            x=fixture();x[field]=value
            with self.subTest(field=field),self.assertRaises(ScalingDenied): one_axis_sweeps(x)

    def test_missing_provenance_field_and_extra_field_denied(self):
        for edit in ('delete','inject'):
            x=fixture()
            if edit=='delete': del x['rows'][0]['held_label_sha256']
            else: x['rows'][0]['self_certifies_independence']=True
            with self.subTest(edit=edit),self.assertRaises(ScalingDenied): one_axis_sweeps(x)

    def test_strict_json_duplicate_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'in.json'
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
                p.write_bytes(raw)
                with self.assertRaises(ScalingDenied): load(p)

    def test_zero_physical_cost_or_bad_boolean_identity(self):
        x=fixture();x['rows'][0]['training_cpu_ns']=0;x['rows'][0]['inference_cpu_ns']=0
        with self.assertRaises(ScalingDenied): one_axis_sweeps(x)
        x=fixture();x['rows'][0]['seed']=True
        with self.assertRaises(ScalingDenied): one_axis_sweeps(x)


if __name__=='__main__':
    unittest.main()
