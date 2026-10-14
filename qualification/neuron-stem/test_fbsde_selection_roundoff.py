"""Confidence ranking preserves raw complements; learned probabilities stay strict."""
import math
import unittest
from fbsde_outcome_policy import select


class SelectionRoundoffTests(unittest.TestCase):
    def rows(self, p):
        return [{'source_id':f'selection:{i}', 'features':[q,0.,0.]+[0.]*12,
                 'outcome_gain':g} for i,(q,g) in enumerate(zip(p,(.7,-.4,.2))) ]

    def test_hosted_boundary_is_ranked_without_clipping(self):
        r=self.rows([math.nextafter(1.,math.inf),1.,1.])
        s=[1-v['features'][0] for v in r]
        got=select(r,s,'outcome',score_kind='confidence_complement')
        self.assertEqual(got['grid'][0]['threshold'],s[0])
        self.assertEqual(got['grid'][0]['deep'],3)
        self.assertEqual(got['grid'][1]['deep'],2)
        self.assertEqual(s[0],-2.220446049250313e-16)
        with self.assertRaisesRegex(ValueError,'finite scores'):select(r,s,'outcome')

    def test_valid_probability_path_is_bit_identical(self):
        r=self.rows([1.,1.,1.]);s=[0.]*3
        self.assertEqual(select(r,s,'outcome'),select(r,s,'outcome',score_kind='confidence_complement'))

    def test_unbound_or_badly_normalized_confidence_rejects(self):
        for q,s in [(1.01,-.01),(1.,.1),(float('nan'),0.),(True,0.)]:
            with self.subTest(q=q):
                with self.assertRaises(ValueError):
                    select(self.rows([q]),[s],'outcome',score_kind='confidence_complement')

    def test_wrong_kind_and_partition_reject(self):
        r=self.rows([1.]);r[0]['source_id']='test:0'
        with self.assertRaises(ValueError):select(r,[0.],'outcome',score_kind='confidence_complement')
        with self.assertRaises(ValueError):select(self.rows([1.]),[0.],'outcome',score_kind='anything')

    def test_nonfinite_or_boolean_scores_reject(self):
        for s in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):
                select(self.rows([1.]),[s],'outcome',score_kind='confidence_complement')


if __name__=='__main__':unittest.main()
