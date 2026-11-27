"""Check audit rejects fabricated historical success, duplication and missing evidence."""
import unittest
from cross_rule_audit import analyze

def row(i):
    return dict(name=f'r{i}',width='64' if i<48 else '256',seed=str((11,23,47)[i%3]),
                schedule=('fixed_gl5','stage_gl3_gl5')[(i//24)%2],
                method=('adam','lbfgs','adjoint_ncg','ad_ncg')[i%4],
                monitor='terminal_only',qualified='False',
                terminal_cc5='.04860',terminal_cc9='.04849',cc17='.04849',gl9='.04849')

class AuditTests(unittest.TestCase):
    def test_full_census_and_corroborated_rejection(self):
        result=analyze([row(i) for i in range(96)])
        self.assertEqual(len(result),96)
        self.assertTrue(all(x['legacy_rejection_with_support'] for x in result))
    def test_missing(self):
        with self.assertRaises(ValueError): analyze([row(i) for i in range(95)])
    def test_duplicate(self):
        a=[row(i) for i in range(96)];a[1]=a[0]
        with self.assertRaises(ValueError): analyze(a)
    def test_rehashed_false_historical_status(self):
        a=[row(i) for i in range(96)];a[0]['qualified']='True'
        with self.assertRaises(ValueError): analyze(a)
    def test_nonfinite(self):
        a=[row(i) for i in range(96)];a[0]['gl9']='nan'
        with self.assertRaises(ValueError): analyze(a)
if __name__=='__main__':unittest.main()
