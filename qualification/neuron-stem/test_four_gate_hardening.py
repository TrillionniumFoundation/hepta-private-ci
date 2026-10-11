"""Additional regressions on canonical #1526 V2; no alternative review schema."""
import unittest
from four_gate_common import digest
from four_gate_outcomes import review_reasoning
from four_gate_selective import clustered_metrics
from test_four_gate_controls import strong_fixture
from test_four_gate_fixtures import plan_fixture


class ValidationLeakageTests(unittest.TestCase):
    def test_training_input_cannot_reappear_under_new_source(self):
        p,e=strong_fixture(); v=e['fixed_depth_validation']
        v['rows'][0]['input_sha256']=e['training_input_sha256s'][0]
        p['reasoning']['validation_sha256']=digest(v)
        with self.assertRaisesRegex(ValueError,'training information'):
            review_reasoning(p,e)

    def test_training_source_cannot_tune_best_fixed(self):
        p,e=strong_fixture(); v=e['fixed_depth_validation']
        v['rows'][0]['source_cluster']=e['training_source_clusters'][0]
        p['reasoning']['validation_sha256']=digest(v)
        with self.assertRaisesRegex(ValueError,'training information'):
            review_reasoning(p,e)

    def test_rehashed_duplicate_input_cannot_inflate_validation(self):
        p,e=strong_fixture(); v=e['fixed_depth_validation']; h=v['rows'][0]['input_sha256']
        for row in v['rows']: row['input_sha256']=h
        p['reasoning']['validation_sha256']=digest(v)
        with self.assertRaisesRegex(ValueError,'same validation input'):
            review_reasoning(p,e)

    def test_missing_observer_cannot_pass_by_string_inequality(self):
        p,e=strong_fixture(); v=e['fixed_depth_validation'];v['rows'][0]['observer_id']=''
        p['reasoning']['validation_sha256']=digest(v)
        with self.assertRaisesRegex(ValueError,'identity required'):
            review_reasoning(p,e)


class FiniteSampleBoundaryTests(unittest.TestCase):
    def observed(self):
        p=plan_fixture();p.update(schema='hepta.four-gate.plan.v2', evidence_kind='observed',min_groups=200)
        return p

    def test_zero_errors_do_not_prove_zero_risk(self):
        rows=[(str(i),(True,True,True,False)) for i in range(200)]
        r=clustered_metrics(rows,self.observed())['accepted_error']
        self.assertEqual(r['estimate'],0);self.assertGreater(r['ucb'],0)
        self.assertTrue(r['finite_sample_guard_applied'])

    def test_correlated_cells_do_not_narrow_cluster_bound(self):
        p=self.observed()
        # Both schedules contain only two independent source clusters.
        short=clustered_metrics([('a',(True,True,True,False)),('b',(True,True,True,False))],p)
        long=clustered_metrics([('a',(True,True,True,False))]*20+[('b',(True,True,True,False))]*20,p)
        self.assertEqual(short['accepted_error']['ucb'],long['accepted_error']['ucb'])
        self.assertFalse(long['accepted_error']['enough_groups'])

    def test_reject_all_keeps_risk_undefined(self):
        r=clustered_metrics([('a',(True,True,False,False))],self.observed())
        self.assertIsNone(r['accepted_error']['estimate']);self.assertEqual(r['accepted_error']['ucb'],1.)

    def test_historical_synthetic_fixture_does_not_claim_guard(self):
        r=clustered_metrics([('a',(True,True,True,False))],plan_fixture())
        self.assertFalse(r['accepted_error']['finite_sample_guard_applied'])


if __name__=='__main__':unittest.main()
