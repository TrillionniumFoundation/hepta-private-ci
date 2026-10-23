import unittest
import numpy as np
import run

class OracleModel:
    coef_ = np.eye(8)
    def predict_proba(self, x):
        return x

class MechanismTests(unittest.TestCase):
    def test_permutation_and_corruption(self):
        pairs = np.array([[a,b] for a in range(8) for b in range(8)])
        self.assertTrue(np.array_equal(run.features(pairs, True),run.features(pairs[:,::-1],True)))
        corrupt = pairs.copy(); corrupt[:,1] = 0
        self.assertLess(np.mean(run.features(corrupt,True).argmax(1)==pairs.sum(1)%8),.2)

    def test_information_gate_and_charged_dead_branch(self):
        world=run.World(999,0,2)
        root=world.retrieve(())
        self.assertNotIn('answer', root)
        wrong=(sum(root['members'])+1)%8
        self.assertEqual(world.retrieve((wrong,)), {'kind':'dead'})
        found=False
        for episode in range(32):
            r=run.solve(999,episode,16,'bounded','member_corrupt',{'relation':OracleModel()},0)
            self.assertEqual(r['calls'],len(r['events']))
            self.assertEqual(r['calls'],r['retrieval_calls']+r['verifier_calls']+r['backtrack_calls'])
            self.assertLessEqual(r['calls'],16)
            self.assertEqual(r['candidate_evaluations'],8*r['verifier_calls'])
            found |= r['backtrack_calls']>0
        self.assertTrue(found)

    def test_success_requires_continued_reads(self):
        for budget in (8,16):
            r=run.solve(999,0,budget,'bounded','zero_noise',{'relation':OracleModel()},0)
            self.assertTrue(r['correct'])
            self.assertEqual(r['calls'],2*(budget//4)+1)
            self.assertEqual(r['events'][-1]['observation']['kind'],'terminal')
            self.assertEqual(r['retrieval_calls'],budget//4+1)

    def test_split_draws_differ_and_are_reproducible(self):
        # Different draws do not imply disjoint input support or source families.
        a=run.dataset(999,'train',20)[0]
        b=run.dataset(999,'holdout',20)[0]
        self.assertFalse(np.array_equal(a,b))
        self.assertTrue(np.array_equal(a,run.dataset(999,'train',20)[0]))

if __name__=='__main__': unittest.main()
