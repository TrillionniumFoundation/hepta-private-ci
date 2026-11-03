import unittest
import math
from fair_ablation import ARMS
from factorial_evidence import estimate_mechanisms,exact_two_sided_signflip
from synthetic_ablation_pilot import design,local_value_and_slope,run_pilot
from tests.test_experiment_protocols import fake_rows

class FactorialEstimator(unittest.TestCase):
    def test_simple_additive_and_interaction_contrasts(self):
        rows=fake_rows()
        for row in rows:
            parts=set() if row['arm']=='control' else set(row['arm'].split('+'))
            call=int('call' in parts); risk=int('risk' in parts); margin=int('margin' in parts)
            row['quality']=.5+.02*call-.03*risk+.01*margin+.04*call*risk
        r=estimate_mechanisms(rows,(11,23,37,41,59))
        self.assertTrue(r['valid_exploratory_design'])
        self.assertAlmostEqual(r['contrasts']['call']['mean_effect'],.04,places=10)
        self.assertAlmostEqual(r['contrasts']['risk']['mean_effect'],-.01,places=10)
        self.assertAlmostEqual(r['contrasts']['margin']['mean_effect'],.01,places=10)
        self.assertAlmostEqual(r['contrasts']['call+risk']['mean_effect'],.02,places=10)
        self.assertAlmostEqual(r['contrasts']['call+risk+margin']['mean_effect'],0,places=10)
        self.assertGreaterEqual(r['contrasts']['call']['holm_adjusted_p'],.05)

    def test_malformed_model_design_does_not_report_effect(self):
        rows=fake_rows(); rows.pop()
        self.assertFalse(estimate_mechanisms(rows,(11,23,37,41,59))['valid_exploratory_design'])

    def test_signflip_exact_symmetry(self):
        self.assertEqual(exact_two_sided_signflip([1,1,1,1,1]),2/32)
        with self.assertRaises(ValueError):exact_two_sided_signflip([float('nan')])

class MatchedLocalSlope(unittest.TestCase):
    def test_all_eight_arm_local_slopes_equal(self):
        base_value,base_gradient=local_value_and_slope('control')
        for arm in ARMS:
            x,g=local_value_and_slope(arm)
            self.assertLess(max(abs(x-base_value)),1e-12)
            self.assertLess(max(abs(g-base_gradient)),1e-8)

    def test_real_ridge_fitting_pilot_negative_evidence_not_promoted(self):
        diag=run_pilot()
        self.assertEqual(len(diag['quality_by_arm']),8)
        self.assertEqual(diag['study_seeds'],[11,23,37,41,59])
        self.assertFalse(diag['full_feature_training_compute_matched'])
        self.assertFalse(diag['production_evidence_accepted'])
        self.assertTrue(diag['exploratory_factorial']['valid_exploratory_design'])

if __name__=='__main__':unittest.main()

class PhysicalEvidenceSeparation(unittest.TestCase):
    """Exploratory zero placeholders must NEVER qualify as physical evidence."""
    def test_zero_measurements_rejected_in_strict_mode(self):
        from fair_ablation import check_matched
        rows=fake_rows()
        for row in rows:
            row['training_joules']=0
            row['peak_rss_bytes']=0
        result=check_matched(rows,(11,23,37,41,59))
        self.assertFalse(result['metadata_comparable'])
        self.assertTrue(any('training_joules' in e for e in result['issues']))
        self.assertTrue(any('peak_rss_bytes' in e for e in result['issues']))
        self.assertFalse(result['production_evidence_accepted'])

    def test_zero_measurements_exploratory_only(self):
        from fair_ablation import check_matched
        rows=fake_rows()
        for row in rows:
            row['training_joules']=0
            row['peak_rss_bytes']=0
        result=check_matched(rows,(11,23,37,41,59),exploratory_unmeasured_physical=True)
        self.assertTrue(result['metadata_comparable'])
        self.assertTrue(result['physical_costs_unmeasured'])
        self.assertFalse(result['production_evidence_accepted'])

    def test_unmeasured_exception_does_not_permit_negative_or_nan(self):
        from fair_ablation import check_matched
        for invalid in (-1,float('nan')):
            rows=fake_rows()
            rows[0]['training_joules']=invalid
            result=check_matched(rows,(11,23,37,41,59),exploratory_unmeasured_physical=True)
            self.assertFalse(result['metadata_comparable'])
