"""Learned corner composition and original f=0-law guard, without Torch dependency."""
import itertools
import random
import unittest
from fbsde_composition import compile_formula, evaluate
from fbsde_tree import joint_probability


class CompositionTests(unittest.TestCase):
    def test_exact_corners_recover_same_full_world_law(self):
        table = [[0.,0.,0.,1.],[0.,1.,1.,1.]]
        for formula in [('and',('or',0,1),('or',2,3)), ('or',('and',0,1),('and',2,3))]:
            for p in ([.2,.3,.7,.9], [.99,.9,.98,.97], [.01,.02,.03,.04]):
                out = evaluate(formula,p,table,correct=True)
                self.assertAlmostEqual(out['probability'],joint_probability(formula,p))
                self.assertLess(out['root_error_bound_exact_arithmetic'],1e-12)
                self.assertEqual(out['learned_operator_depth'],2)
                self.assertEqual(out['learned_operator_calls'],3)

    def test_uninformative_cells_do_not_pass_as_original_solution(self):
        out=evaluate(('and',0,1),[.9,.9],[[.5]*4,[.5]*4],correct=True)
        self.assertTrue(out['exact_fallback'])
        self.assertFalse(out['decision_stable_under_model'])
        self.assertAlmostEqual(out['probability'],.81)
        self.assertEqual(out['fallback_operator_calls'],1)

    def test_guard_bound_contains_original_probability_random_cells(self):
        rng=random.Random(4523);f=('or',('and',0,1),('and',2,3))
        for _ in range(200):
            p=[rng.random() for _ in range(4)];tables=[[rng.random() for _ in range(4)] for _ in range(2)]
            out=evaluate(f,p,tables,correct=True);exact=joint_probability(f,p)
            self.assertLessEqual(abs(out['proposal_probability']-exact),out['root_error_bound_exact_arithmetic']+1e-12)
            self.assertEqual(out['probability']>=.5,exact>=.5)

    def test_unguarded_output_does_not_claim_certification(self):
        out=evaluate(('or',0,1),[.2,.8],[[.4]*4,[.6]*4])
        self.assertIsNone(out['root_error_bound_exact_arithmetic'])
        self.assertFalse(out['semantic_truth_certified'])
        self.assertEqual(out['guard_operator_calls'],0)

    def test_repeated_leaf_or_unknown_grammar_rejected(self):
        for f in [('and',0,0),('xor',0,1),True,-1,('or',0,4),('and',0)]:
            with self.subTest(f=f),self.assertRaises(ValueError):compile_formula(f)

    def test_corrupted_corner_table_or_belief_rejected(self):
        for value in [float('nan'),float('inf'),-.1,1.1,True]:
            table=[[.5]*4,[.5]*4];table[0][0]=value
            with self.assertRaises(ValueError):evaluate(('and',0,1),[.1,.9],table)
            with self.assertRaises(ValueError):evaluate(('and',0,1),[value,.9],[[.5]*4,[.5]*4])

    def test_no_silent_missing_leaf(self):
        with self.assertRaisesRegex(ValueError,'missing'):evaluate(('and',0,2),[.1,.9],[[.5]*4,[.5]*4])

    def test_exact_tie_forces_original_law(self):
        out=evaluate(('or',0,1),[.5,0.],[[0.,0.,0.,1.],[0.,1.,1.,1.]],correct=True)
        self.assertTrue(out['exact_fallback']);self.assertEqual(out['probability'],.5)

    def test_nontrivial_depth_not_parallel_width(self):
        out=evaluate(('and',('or',('and',0,1),2),3),[.1,.2,.3,.4],[[.5]*4,[.5]*4])
        self.assertEqual(out['learned_operator_depth'],3)
        self.assertEqual(out['learned_operator_calls'],3)

if __name__=='__main__':unittest.main()
