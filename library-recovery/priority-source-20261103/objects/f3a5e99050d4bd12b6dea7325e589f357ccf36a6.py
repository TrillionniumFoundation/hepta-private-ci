import unittest
from hx_gradient_domain import domain_sweep,boundary_gradient_crosscheck

class CoupledHXAdditionalStress(unittest.TestCase):
    def test_four_boundary_sensitivities_independent_numerical(self):
        rows=boundary_gradient_crosscheck()
        self.assertEqual(len(rows),4)
        for r in rows:
            self.assertLess(r['disagreement'],.002)
            self.assertLess(r['analytic_step_halving_change'],.001)

    def test_parameter_stress_records_invalid_regimes_separately(self):
        result=domain_sweep(n=48)
        self.assertEqual(result['attempted'],48)
        self.assertEqual(result['attempted'],result['regime_refused']+
                         result['numeric_refused']+result['admissible_numeric_compared'])
        self.assertGreater(result['admissible_numeric_compared'],0)
        self.assertGreater(result['regime_refused'],0)
        self.assertFalse('PASS' in result.get('scope',''))

    def test_bad_stress_size_rejected(self):
        with self.assertRaises(ValueError):domain_sweep(0)

if __name__=='__main__':unittest.main()
