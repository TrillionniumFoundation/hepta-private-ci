"""Negative/independent scorer tests; never download external archives in unit tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from e7_second_opinion import (ARMS, agree, archive, canonical, independent_score,
                               json_load, model_predictions, group_labels)


def source():
    # Three sealed artificial outcomes, not archived pretrained observations.
    return ({'a':('scope_a','sha_a',1),'b':('scope_b','sha_b',0),
             'c':('scope_c','sha_c',1)},
            {'granite97':{'a':(.9,11),'b':(.2,12),'c':(.45,13)},
             'mmbert_small':{'a':(.1,21),'b':(.1,22),'c':(.8,23)}})


def primary_for(second):
    return {'schema':'hepta.e7.real-two-stem-routed-retrospective-score.v1',
            'authority':'DENY_ALL','production_accepted':False,
            'actual_on_demand_encoder_calls_executed':0,
            'arms':{name:dict(row) for name,row in second['arms'].items()}}


class IndependentRetrospectiveSecondOpinion(unittest.TestCase):
    def test_literal_thresholds_frozen(self):
        self.assertEqual(ARMS,{'granite_only':None,'mmbert_only':None,
                               'gate_conf_075':.75,'gate_conf_090':.90,
                               'gate_conf_098':.98})

    def test_no_models_loaded_count_exact_complements(self):
        labels,models=source()
        result=independent_score(labels,models)
        self.assertEqual(result['paired_correctness']['at_least_one_right'],3)
        self.assertEqual(result['paired_correctness']['oracle_extra_correct_over_granite'],1)
        self.assertEqual(result['arms']['granite_only']['correct'],2)
        self.assertEqual(result['arms']['mmbert_only']['correct'],2)
        self.assertTrue(result['paired_correctness']['oracle_uses_future_labels_is_not_an_admissible_policy'])

    def test_confidence_075_switches_only_third_source(self):
        labels,models=source()
        result=independent_score(labels,models)
        arm=result['arms']['gate_conf_075']
        self.assertEqual(arm['hypothetical_secondary_model_calls'],1)
        self.assertEqual(arm['archived_per_case_wall_proxy_ns_sum'],11+12+(13+23))
        self.assertEqual(arm['correct'],3)

    def test_five_policy_means_are_recomputed_not_trusted(self):
        labels,models=source()
        score=independent_score(labels,models)
        p=primary_for(score)
        agree(p,score)
        self.assertAlmostEqual(score['arms']['granite_only']['accuracy'],2/3)
        self.assertEqual(score['arms']['granite_only']['archived_per_case_wall_proxy_ns_sum'],36)

    def test_wrong_primary_correctness_fails(self):
        labels,models=source()
        value=independent_score(labels,models)
        p=primary_for(value);p['arms']['gate_conf_075']['correct']+=1
        with self.assertRaisesRegex(ValueError,'disagreement'):
            agree(p,value)

    def test_wrong_primary_cost_or_calls_fails(self):
        labels,models=source()
        value=independent_score(labels,models)
        for field in ('archived_per_case_wall_proxy_ns_sum','hypothetical_secondary_model_calls'):
            p=primary_for(value);p['arms']['gate_conf_075'][field]+=1
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'disagreement'):
                agree(p,value)

    def test_mutated_brier_fails_with_strict_float_tolerance(self):
        labels,models=source();score=independent_score(labels,models)
        p=primary_for(score);p['arms']['granite_only']['brier']+=1e-6
        with self.assertRaises(ValueError):agree(p,score)

    def test_non_denied_primary_fails_even_when_metric_equal(self):
        labels,models=source();score=independent_score(labels,models)
        for field,value in [('authority','ALLOW'),('production_accepted',True),
                            ('actual_on_demand_encoder_calls_executed',1)]:
            p=primary_for(score);p[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):agree(p,score)

    def test_duplicate_keys_nan_or_infinity_json_reject(self):
        for invalid in (b'{"a":0,"a":1}',b'{"a":NaN}',b'{"a":Infinity}'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):json_load(invalid)

    def test_fake_zip_rejected_before_any_zip_parse(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'fake.zip';path.write_bytes(b'fake registered historical zip')
            with self.assertRaisesRegex(ValueError,'exact registered original ZIP'):
                archive(path,'e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d')

    def test_original_label_panel_absent_or_tampered_reject(self):
        with self.assertRaises(KeyError):group_labels({})
        with self.assertRaises(ValueError):group_labels({'stem-agnews-new-source-panel.json':canonical({'fake':1})})

    def test_pretrained_model_report_absent_reject(self):
        with self.assertRaises(ValueError):model_predictions({},source()[0])


if __name__=='__main__':unittest.main()
