"""Signed costs, support, and predeclared source boundaries; no timing claims."""
from fractions import Fraction as F
import copy
import itertools
import unittest
from four_gate_common import digest
from fbsde_gain_policy import targets, counterexample
from fbsde_gain_data import generate, operation, target, FRAMES
from fbsde_outcome_data import generate as old_generate


class GainTests(unittest.TestCase):
    def row(self,g):return dict(source_id='train:one',outcome_gain=g,features=[0.]*15)

    def test_weights_retain_large_and_small_losses(self):
        a=[self.row(v) for v in (.012,-.988,.992,-.008)]
        for i,r in enumerate(a):r['source_id']=f'train:{i}'
        y,w=targets(a,'signed_gain_v2')
        self.assertEqual(y,[1.,0.,1.,0.]);self.assertEqual([round(v,8) for v in w],[.01,.99,.99,.01])
        self.assertEqual(targets(a,'frequency_v1')[1],[1.]*4)

    def test_equal_net_gain_has_no_weight(self):
        self.assertEqual(targets([self.row(.002)],'signed_gain_v2'),([0.],[0.]))

    def test_nonfinite_unbounded_boolean_and_wrong_partition_reject(self):
        for value in (float('nan'),float('inf'),True,3.,-3.):
            with self.assertRaises(ValueError):targets([self.row(value)],'signed_gain_v2')
        a=self.row(1.);a['source_id']='test:one'
        with self.assertRaisesRegex(ValueError,'training-only'):targets([a],'signed_gain_v2')

    def test_duplicate_and_unknown_objective_reject(self):
        with self.assertRaises(ValueError):targets([self.row(1.)]*2,'signed_gain_v2')
        with self.assertRaises(ValueError):targets([self.row(1.)],'unknown')

    def test_frequency_threshold_cannot_select_lower_frequency_only(self):
        report=counterexample();rows=report['contexts']
        f=[F(r['positive_frequency']) for r in rows];w=[F(r['weighted_score']) for r in rows]
        gains=[F(r['expected_net_gain']) for r in rows]
        values=[sum(g*(q>=t) for q,g in zip(f,gains))/2 for t in (F(0),*f,F(2))]
        weighted=sum(g*(q>=F(1,2)) for q,g in zip(w,gains))/2
        self.assertEqual(max(values),F(report['best_frequency_threshold_mean_gain']))
        self.assertEqual(weighted,F(report['weighted_half_mean_gain']))
        self.assertGreater(weighted,max(values))

    def test_new_frames_do_not_use_prior_source_text(self):
        old=old_generate();new=generate(old); a={t for r in old for t in r['events']}
        test=[r for r in new if r['split']=='test'];b={t for r in test for t in r['events']}
        self.assertFalse(a&b);self.assertEqual(len(test),192);self.assertEqual(generate(old),new)

    def test_source_rule_all_role_permutations_and_double_swap(self):
        names=['Gina','Hugo','Iris']
        for frame in FRAMES:
            for a,b,c in itertools.permutations(range(3)):
                text=frame.format(a=names[a],b=names[b],c=names[c])
                self.assertEqual(operation(text,names),tuple(sorted((a,b))))
                for query in range(3):
                    self.assertEqual(target(dict(names=names,events=[text,text],query=query)),query)

    def test_no_unknown_text_is_silently_scored(self):
        with self.assertRaises(ValueError):operation('The parser should just guess.', ['Gina','Hugo','Iris'])


if __name__=='__main__':unittest.main()
