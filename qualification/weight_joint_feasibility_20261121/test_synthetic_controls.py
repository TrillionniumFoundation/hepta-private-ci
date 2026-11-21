"""Offline controls: no private checkpoints, label files or network access."""
import unittest
import numpy as np
import joint_solver as s
import verify_records as r


class SyntheticControls(unittest.TestCase):
    def terminals(self,target,mask=None):
        scores=np.array([[0.,0.,0.,0.,1.,1.]])
        legal=np.array([[True,False,False,False,True,True]]) if mask is None else mask
        return s.immutable_obstructions(scores,legal,np.array([target]))

    def test_lower_index_immutable_tie_blocks(self):
        blocked,witness=self.terminals(5)
        self.assertTrue(blocked[0]);self.assertEqual(witness[0],4)

    def test_higher_index_immutable_tie_allowed(self):
        blocked,_=self.terminals(4);self.assertFalse(blocked[0])

    def test_illegal_fixed_competitor_ignored(self):
        blocked,_=self.terminals(5,np.array([[True,False,False,False,False,True]]))
        self.assertFalse(blocked[0])

    def test_lex_margin_only_lower_index(self):
        score=np.zeros((1,6));mask=np.ones((1,6),bool);target=np.array([2])
        m=s.constraint_metadata(score,mask,target,np.array([True]),'lex')
        for j,margin in zip(m['competitors'],m['margin']):self.assertEqual(margin,1e-6 if j<2 else 0.)

    def test_robust_margin_all_editable_comparisons(self):
        m=s.constraint_metadata(np.zeros((1,6)),np.ones((1,6),bool),np.array([2]),np.array([True]),'margin')
        np.testing.assert_array_equal(m['margin'],np.full(5,1e-3))

    def test_affine_constraint_sign(self):
        H=np.zeros((1,49));H[0,0]=2.;H[0,48]=1.
        masks=np.array([[False,True,True,False,False,False]]);t=np.array([1])
        m=s.constraint_metadata(np.zeros((1,6)),masks,t,np.array([True]),'lex')
        A=s.materialize(H,t,m,np.array([0]));d=np.zeros(147);d[0]=3.;d[49]=1.
        self.assertEqual(float((A@d)[0]),4.)

    def test_full_support_scan_retains_unselected_violation(self):
        H=np.zeros((2,49));H[:,48]=1.;t=np.array([1,2]);scores=np.zeros((2,6))
        masks=np.array([[False,True,True,False,False,False]]*2)
        m=s.constraint_metadata(scores,masks,t,np.ones(2,bool),'lex')
        d=np.zeros(147);d[48]=1.
        violation=m['b']-s.full_lhs(H,t,m,d)
        self.assertLess(violation[0],0.);self.assertGreater(violation[1],1.)

    def test_known_minimum_and_dual(self):
        A=np.eye(2);b=np.array([1.,2.]);x,z,info=s.invoke(A,b,2.)
        self.assertEqual(info['status'],'Solved')
        np.testing.assert_allclose(x,b,atol=1e-6,rtol=0.)
        np.testing.assert_allclose(z,b,atol=1e-6,rtol=0.)
        k=r.kkt(A,b,b,x,z,float(max(0.,np.max(b-A@x))),True)
        self.assertTrue(k['minimum_resolved'])

    def test_numerical_farkas_known_inconsistent_system(self):
        A=np.array([[1.],[-1.]]);b=np.array([1.,0.]);_,z,info=s.invoke(A,b,2.)
        self.assertEqual(info['status'],'PrimalInfeasible')
        self.assertTrue(s.infeasibility_indication(A,b,z)['checked_numeric_indication'])

    def test_epsilon_separation_is_not_closed_separation(self):
        A=np.array([[1.],[-1.]]);lam=np.array([.5,.5]);b0=np.zeros(2);b=np.array([1e-6,0.])
        self.assertEqual(float(np.linalg.norm(A.T@lam)),0.)
        self.assertEqual(float(b0@lam),0.)
        self.assertGreater(float(b@lam),0.)

    def test_belief_gate_checks_actual_terminal_margin(self):
        H=np.zeros((2,49));H[:,0]=[-1.,1.];H[:,48]=1.
        report,_,_=s.solve_belief(H,np.zeros((4,49)),np.array([4,5]),np.ones(2,bool),lambda:2.)
        self.assertTrue(report['feasible_upper'])
        self.assertGreaterEqual(report['actual_minimum_target_terminal_score'],1e-4)

    def test_reader_rejects_corrupted_numeric_summary(self):
        with self.assertRaises(AssertionError):r.close(1.,1.01,'mutated objective')


if __name__=='__main__':unittest.main()
